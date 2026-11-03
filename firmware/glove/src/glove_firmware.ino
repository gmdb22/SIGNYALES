/*
  Signyales — Glove Node Firmware (original ESP32)
  ============================================
  Layer 1 of the Signyales pipeline. Reads 6 flex sensors (5 fingers +
  1 palm) and a 6-axis
  IMU, filters and calibrates the readings, packs them into a
  glove_packet_t (see packet.h), and transmits over ESP-NOW to the
  receiver dongle at SAMPLE_RATE_HZ.

  Flash this same sketch onto both gloves — only config.h's
  IS_LEFT_GLOVE/IS_RIGHT_GLOVE flag changes between the two builds.

  No extra libraries: the IMU is read directly over I2C (see the IMU
  section below), so MPU6050-compatible clone chips work too.

  Board: ESP32 Dev Module (esp32dev; the glove PCB uses an
  ESP32-DevKitC-32E clone). Installed via Boards Manager: esp32 by
  Espressif Systems.

  Serial commands (115200 baud):
    'c'  -> run an 8-second flex calibration routine and save to flash
    'g'  -> measure the gyro's resting offset again (keep the glove still
            for 1 second) and save it to flash
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Preferences.h>

#include "config.h"
#include "packet.h"

Preferences prefs;

static_assert(FLEX_SENSOR_COUNT == FLEX_PER_GLOVE,
              "config.h FLEX_SENSOR_COUNT must match packet.h FLEX_PER_GLOVE");

const int flexPins[FLEX_SENSOR_COUNT] = {
  FLEX_PIN_THUMB, FLEX_PIN_INDEX, FLEX_PIN_MIDDLE, FLEX_PIN_RING, FLEX_PIN_PINKY,
  FLEX_PIN_PALM
};
const char* const flexNames[FLEX_SENSOR_COUNT] = {
  "thumb", "index", "middle", "ring", "pinky", "palm"
};

// Per-finger calibration bounds, persisted in flash (NVS) so they
// survive reboots/re-flashes without needing recalibration every time.
uint16_t flexMin[FLEX_SENSOR_COUNT];
uint16_t flexMax[FLEX_SENSOR_COUNT];

// EMA filter state, carried between samples.
float flexFiltered[FLEX_SENSOR_COUNT];
bool filterInitialized = false;

uint32_t seqCounter = 0;
esp_now_peer_info_t peerInfo;

// Failed esp_now_send() calls since the last report (printed once a second).
uint32_t sendFailures = 0;
uint32_t lastFailureReport = 0;

// ------------------------------------------------------------------
// Calibration
// ------------------------------------------------------------------

void loadCalibration() {
  prefs.begin(CALIBRATION_NAMESPACE, true); // read-only
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    char keyMin[8], keyMax[8];
    snprintf(keyMin, sizeof(keyMin), "min%d", i);
    snprintf(keyMax, sizeof(keyMax), "max%d", i);
    // Defaults are placeholders until the first real calibration runs —
    // they won't be accurate, but they keep normalizeFlex() well-behaved.
    flexMin[i] = prefs.getUShort(keyMin, 500);
    flexMax[i] = prefs.getUShort(keyMax, 3500);
  }
  prefs.end();
}

void saveCalibration() {
  prefs.begin(CALIBRATION_NAMESPACE, false); // read-write
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    char keyMin[8], keyMax[8];
    snprintf(keyMin, sizeof(keyMin), "min%d", i);
    snprintf(keyMax, sizeof(keyMax), "max%d", i);
    prefs.putUShort(keyMin, flexMin[i]);
    prefs.putUShort(keyMax, flexMax[i]);
  }
  prefs.end();
}

// Have the wearer fully flex and relax every finger during this
// window; captures each sensor's real min/max range so normalizeFlex()
// can map raw ADC counts to a consistent 0-4095 scale regardless of
// sensor-to-sensor manufacturing variance.
void runCalibrationRoutine() {
  Serial.println("=== Calibration: flex and relax ALL fingers and the palm repeatedly for 8 seconds ===");
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    flexMin[i] = 4095;
    flexMax[i] = 0;
  }
  uint32_t start = millis();
  while (millis() - start < 8000) {
    for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
      uint16_t v = analogRead(flexPins[i]);
      if (v < flexMin[i]) flexMin[i] = v;
      if (v > flexMax[i]) flexMax[i] = v;
    }
    delay(10);
  }
  saveCalibration();
  // Start the smoothing filter fresh on the new scale, so the first
  // readings after calibration don't ramp over from the old one.
  filterInitialized = false;
  Serial.println("Calibration saved:");
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    Serial.printf("  Sensor %d (%s): min=%u max=%u\n", i, flexNames[i], flexMin[i], flexMax[i]);
  }
}

// ------------------------------------------------------------------
// Startup checks (original ESP32 only)
// ------------------------------------------------------------------

// ADC2 pins on the original ESP32. They return no reading while Wi-Fi
// (and so ESP-NOW) is on. See the ADC2 WARNING in config.h.
bool isAdc2Pin(int pin) {
#if CONFIG_IDF_TARGET_ESP32
  switch (pin) {
    case 0: case 2: case 4: case 12: case 13: case 14: case 15:
    case 25: case 26: case 27:
      return true;
  }
#endif
  (void)pin;
  return false;
}

void warnAboutAdc2Pins() {
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    if (isAdc2Pin(flexPins[i])) {
      Serial.printf("WARNING: flex slot %d is on GPIO%d, an ADC2 pin. It cannot be read "
                    "while ESP-NOW is on, so it will read 0. Rewire it to an ADC1 pin "
                    "(GPIO32-39), see config.h.\n", i, flexPins[i]);
    }
  }
}

// Called when setupImu() fails: reports what, if anything, answers on
// the I2C bus, so "not found" can be told apart from "a different chip".
void reportImuProblem() {
  bool any = false;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      any = true;
      Serial.printf("  I2C device found at 0x%02X", addr);
      if (addr == 0x68 || addr == 0x69) {
        Wire.beginTransmission(addr);
        Wire.write(0x75); // WHO_AM_I
        if (Wire.endTransmission(false) == 0 && Wire.requestFrom(addr, (uint8_t)1) == 1) {
          Serial.printf(", WHO_AM_I=0x%02X (accepted: see IMU_ACCEPTED_IDS in config.h)", Wire.read());
        }
      }
      Serial.println();
    }
  }
  if (!any) {
    Serial.printf("  No I2C device answered on SDA=GPIO%d, SCL=GPIO%d. Check the IMU wiring "
                  "and power.\n", IMU_SDA_PIN, IMU_SCL_PIN);
  }
}

// ------------------------------------------------------------------
// IMU (MPU6050 or a register-compatible clone), read directly over I2C
// ------------------------------------------------------------------
// Until 3 Nov 2026 this used the Adafruit MPU6050 library, which refuses
// any chip whose WHO_AM_I is not 0x68. Both MPU boards on hand report
// 0x72 (a clone; seen with glove_hw_check on 3 Nov 2026), so the library
// would stop at "MPU6050 not found" even with correct wiring. The
// registers below are the same on the MPU6050 and the MPU65xx family.
// Settings and units match what the library gave before: +-4 g,
// +-500 deg/s, ~21 Hz low-pass; accel in g, gyro in deg/s.

const uint8_t IMU_REG_SMPLRT_DIV    = 0x19;
const uint8_t IMU_REG_CONFIG        = 0x1A;  // digital low-pass filter (gyro; accel too on MPU6050)
const uint8_t IMU_REG_GYRO_CONFIG   = 0x1B;
const uint8_t IMU_REG_ACCEL_CONFIG  = 0x1C;
const uint8_t IMU_REG_ACCEL_CONFIG2 = 0x1D;  // accel low-pass, MPU65xx family only
const uint8_t IMU_REG_ACCEL_XOUT_H  = 0x3B;  // 14 bytes: accel x,y,z, temp, gyro x,y,z
const uint8_t IMU_REG_PWR_MGMT_1    = 0x6B;
const uint8_t IMU_REG_WHO_AM_I      = 0x75;

const uint8_t IMU_DLPF_21HZ   = 0x04;
const uint8_t IMU_GYRO_500DPS = 0x08;    // FS_SEL = 1
const uint8_t IMU_ACCEL_4G    = 0x08;    // AFS_SEL = 1
const float IMU_ACCEL_LSB_PER_G   = 8192.0f;
const float IMU_GYRO_LSB_PER_DPS  = 65.5f;

const uint8_t imuAcceptedIds[] = IMU_ACCEPTED_IDS;

// Failed IMU reads since the last report (printed at most once a second).
uint32_t imuReadFailures = 0;
uint32_t lastImuFailureReport = 0;

// Start-up and recovery (added 4 Nov 2026). The MPU board keeps its power
// when only the ESP32 resets, so a reset in the middle of an I2C read can
// leave the MPU holding SDA low; then nothing answers until the bus is
// cleared. On 3-4 Nov the boards also reset often at power-up (brownouts
// on a weak USB supply). So: clear the bus before starting I2C, try the
// IMU a few times before halting, and re-start it if reads keep failing.
const int      IMU_SETUP_ATTEMPTS        = 5;     // tries at power-up before halting
const uint32_t IMU_SETUP_RETRY_MS        = 300;   // pause between tries
const uint32_t IMU_REINIT_AFTER_FAILS    = 25;    // consecutive failed reads (0.5 s at 50 Hz)
const uint32_t IMU_REINIT_MIN_GAP_MS     = 2000;  // at most one re-start every 2 s
uint32_t imuConsecutiveFailures = 0;
uint32_t lastImuReinit = 0;
bool wireStarted = false;

// Gyro resting offset (added 4 Nov 2026). Both clone MPUs read a few
// deg/s on some axes while lying still (e.g. about -4.4, +2.8, -0.3 deg/s
// on 4 Nov). At start-up the firmware averages 1 s of gyro readings and
// subtracts that from every sample, so a still glove reads about 0. If
// the glove moved during that second, the last saved offset is used.
// The thresholds are first guesses, not tuned on hardware yet.
const int   GYRO_CAL_SAMPLES        = 200;    // 200 x 5 ms = 1 s
const float GYRO_CAL_MAX_STD_DPS    = 1.5f;   // more spread than this = the glove moved
const float GYRO_CAL_MAX_OFFSET_DPS = 15.0f;  // larger than this = not a resting offset
float gyroOffset[3] = {0, 0, 0};

bool imuWrite(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;
}

bool imuRead(uint8_t reg, uint8_t* buf, uint8_t len) {
  Wire.beginTransmission(IMU_I2C_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)IMU_I2C_ADDR, len) != len) return false;
  for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
  return true;
}

bool imuIdAccepted(uint8_t id) {
  for (size_t i = 0; i < sizeof(imuAcceptedIds); i++) {
    if (imuAcceptedIds[i] == id) return true;
  }
  return false;
}

// Frees a stuck I2C bus: if a device holds SDA low, clock SCL up to 9
// times until it lets go, then send a STOP. Done with plain GPIO before
// the I2C driver takes the pins.
void i2cBusRecover() {
  pinMode(IMU_SDA_PIN, INPUT_PULLUP);
  pinMode(IMU_SCL_PIN, OUTPUT_OPEN_DRAIN);
  digitalWrite(IMU_SCL_PIN, HIGH);
  delayMicroseconds(10);
  bool wasStuck = digitalRead(IMU_SDA_PIN) == LOW;
  for (int i = 0; i < 9 && digitalRead(IMU_SDA_PIN) == LOW; i++) {
    digitalWrite(IMU_SCL_PIN, LOW);
    delayMicroseconds(10);
    digitalWrite(IMU_SCL_PIN, HIGH);
    delayMicroseconds(10);
  }
  // STOP: SDA goes low -> high while SCL is high.
  pinMode(IMU_SDA_PIN, OUTPUT_OPEN_DRAIN);
  digitalWrite(IMU_SDA_PIN, LOW);
  delayMicroseconds(10);
  digitalWrite(IMU_SCL_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(IMU_SDA_PIN, HIGH);
  delayMicroseconds(10);
  pinMode(IMU_SDA_PIN, INPUT);
  pinMode(IMU_SCL_PIN, INPUT);
  if (wasStuck) {
    Serial.printf("I2C: SDA was held low; bus cleared (SDA now %s).\n",
                  digitalRead(IMU_SDA_PIN) == HIGH ? "free" : "STILL LOW");
  }
}

// (Re)starts the I2C driver on a cleared bus.
void startI2c() {
  if (wireStarted) {
    Wire.end();
    wireStarted = false;
  }
  i2cBusRecover();
  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  wireStarted = true;
}

// Wakes and configures the IMU. Returns false (with the reason printed)
// if nothing answers, the chip ID isn't accepted, or a setting doesn't stick.
bool setupImu() {
  uint8_t id = 0;
  if (!imuRead(IMU_REG_WHO_AM_I, &id, 1)) {
    Serial.printf("IMU: nothing answers at 0x%02X on SDA=GPIO%d, SCL=GPIO%d.\n",
                  IMU_I2C_ADDR, IMU_SDA_PIN, IMU_SCL_PIN);
    return false;
  }
  if (!imuIdAccepted(id)) {
    Serial.printf("IMU: WHO_AM_I=0x%02X is not in IMU_ACCEPTED_IDS (config.h).\n", id);
    return false;
  }
  imuWrite(IMU_REG_PWR_MGMT_1, 0x80);  // reset
  delay(100);
  imuWrite(IMU_REG_PWR_MGMT_1, 0x01);  // wake, clock from the gyro PLL
  delay(10);
  imuWrite(IMU_REG_SMPLRT_DIV, 0x00);
  imuWrite(IMU_REG_CONFIG, IMU_DLPF_21HZ);
  imuWrite(IMU_REG_GYRO_CONFIG, IMU_GYRO_500DPS);
  imuWrite(IMU_REG_ACCEL_CONFIG, IMU_ACCEL_4G);
  if (id != 0x68) {
    imuWrite(IMU_REG_ACCEL_CONFIG2, IMU_DLPF_21HZ);  // not a register on a genuine MPU6050
  }

  uint8_t gyroCfg = 0, accelCfg = 0;
  if (!imuRead(IMU_REG_GYRO_CONFIG, &gyroCfg, 1) || !imuRead(IMU_REG_ACCEL_CONFIG, &accelCfg, 1) ||
      (gyroCfg & 0x18) != IMU_GYRO_500DPS || (accelCfg & 0x18) != IMU_ACCEL_4G) {
    Serial.printf("IMU: settings did not stick (GYRO_CONFIG=0x%02X, ACCEL_CONFIG=0x%02X).\n",
                  gyroCfg, accelCfg);
    return false;
  }
  Serial.printf("IMU: WHO_AM_I=0x%02X%s, +-4 g, +-500 deg/s.\n", id,
                id == 0x68 ? " (MPU6050)" : " (compatible chip)");
  return true;
}

// Reads one sample: accel in g, gyro in deg/s. Returns false if the
// I2C read failed (the caller keeps the previous values).
bool readImu(float* accel, float* gyro) {
  uint8_t b[14];
  if (!imuRead(IMU_REG_ACCEL_XOUT_H, b, sizeof(b))) return false;
  for (int i = 0; i < 3; i++) {
    int16_t a = (int16_t)((b[2 * i] << 8) | b[2 * i + 1]);
    int16_t g = (int16_t)((b[8 + 2 * i] << 8) | b[8 + 2 * i + 1]);
    accel[i] = a / IMU_ACCEL_LSB_PER_G;
    gyro[i] = g / IMU_GYRO_LSB_PER_DPS;
  }
  return true;
}

// Power-up: up to IMU_SETUP_ATTEMPTS tries, each on a freshly cleared bus.
bool setupImuWithRetries() {
  for (int attempt = 1; attempt <= IMU_SETUP_ATTEMPTS; attempt++) {
    startI2c();
    if (setupImu()) return true;
    if (attempt < IMU_SETUP_ATTEMPTS) {
      Serial.printf("IMU: try %d of %d failed, trying again.\n", attempt, IMU_SETUP_ATTEMPTS);
      delay(IMU_SETUP_RETRY_MS);
    }
  }
  return false;
}

// While streaming: called after every read. If reads keep failing,
// clears the bus and sets the IMU up again (at most every 2 s). The
// packets keep the last good values meanwhile.
void handleImuReadResult(bool ok, uint32_t now) {
  if (ok) {
    imuConsecutiveFailures = 0;
    return;
  }
  imuConsecutiveFailures++;
  if (imuConsecutiveFailures >= IMU_REINIT_AFTER_FAILS && now - lastImuReinit >= IMU_REINIT_MIN_GAP_MS) {
    lastImuReinit = now;
    Serial.printf("IMU: %lu reads in a row failed; restarting I2C and the IMU.\n",
                  (unsigned long)imuConsecutiveFailures);
    startI2c();
    if (setupImu()) {
      imuConsecutiveFailures = 0;
      Serial.println("IMU: back.");
    }
  }
}

void loadGyroOffset() {
  prefs.begin(CALIBRATION_NAMESPACE, true);
  gyroOffset[0] = prefs.getFloat("gofs0", 0.0f);
  gyroOffset[1] = prefs.getFloat("gofs1", 0.0f);
  gyroOffset[2] = prefs.getFloat("gofs2", 0.0f);
  prefs.end();
}

void saveGyroOffset() {
  prefs.begin(CALIBRATION_NAMESPACE, false);
  prefs.putFloat("gofs0", gyroOffset[0]);
  prefs.putFloat("gofs1", gyroOffset[1]);
  prefs.putFloat("gofs2", gyroOffset[2]);
  prefs.end();
}

// Averages 1 s of gyro readings. Returns false (offset unchanged) if the
// glove moved, too many reads failed, or the average is too large to be a
// resting offset; then the previously saved offset stays in use.
bool measureGyroOffset() {
  Serial.println("Gyro offset: keep the glove still for 1 second...");
  double sum[3] = {0, 0, 0}, sumSq[3] = {0, 0, 0};
  int n = 0, failed = 0;
  for (int k = 0; k < GYRO_CAL_SAMPLES; k++) {
    float a[3], g[3];
    if (readImu(a, g)) {
      for (int i = 0; i < 3; i++) {
        sum[i] += g[i];
        sumSq[i] += (double)g[i] * g[i];
      }
      n++;
    } else {
      failed++;
    }
    delay(5);
  }
  if (n < GYRO_CAL_SAMPLES / 2) {
    Serial.printf("Gyro offset: %d of %d reads failed; keeping the saved offset.\n", failed, GYRO_CAL_SAMPLES);
    return false;
  }
  float mean[3], sd[3];
  for (int i = 0; i < 3; i++) {
    mean[i] = (float)(sum[i] / n);
    double var = sumSq[i] / n - (double)mean[i] * mean[i];
    sd[i] = var > 0 ? (float)sqrt(var) : 0.0f;
  }
  for (int i = 0; i < 3; i++) {
    if (sd[i] > GYRO_CAL_MAX_STD_DPS || fabsf(mean[i]) > GYRO_CAL_MAX_OFFSET_DPS) {
      Serial.printf("Gyro offset: the glove moved (or the reading is odd: mean %.1f, %.1f, %.1f; "
                    "spread %.1f, %.1f, %.1f deg/s). Keeping the saved offset %.1f, %.1f, %.1f. "
                    "Send 'g' with the glove still to measure again.\n",
                    mean[0], mean[1], mean[2], sd[0], sd[1], sd[2],
                    gyroOffset[0], gyroOffset[1], gyroOffset[2]);
      return false;
    }
  }
  for (int i = 0; i < 3; i++) gyroOffset[i] = mean[i];
  saveGyroOffset();
  Serial.printf("Gyro offset: %.2f, %.2f, %.2f deg/s (saved; subtracted from every sample).\n",
                gyroOffset[0], gyroOffset[1], gyroOffset[2]);
  return true;
}

// ------------------------------------------------------------------
// ESP-NOW
// ------------------------------------------------------------------

void onDataSent(const uint8_t* mac, esp_now_send_status_t status) {
  // Intentionally lightweight — this runs in a callback context.
  // A single failed send is not fatal; the next sample tries again.
  // Persistent failures usually mean the receiver is powered off or
  // out of range, not a bug in this firmware.
  (void)mac;
  (void)status;
}

void setupEspNow() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(); // ESP-NOW doesn't need an AP connection; this just
                      // ensures the radio isn't mid-scan when we start.

  if (esp_now_init() != ESP_OK) {
    Serial.println("FATAL: esp_now_init failed. Halting.");
    while (true) delay(1000);
  }
  esp_now_register_send_cb(onDataSent);

  memcpy(peerInfo.peer_addr, RECEIVER_MAC, 6);
  peerInfo.channel = 0; // use whatever channel the radio is already on
  peerInfo.encrypt = false;

  if (esp_now_add_peer(&peerInfo) != ESP_OK) {
    Serial.println("FATAL: esp_now_add_peer failed. Check RECEIVER_MAC in config.h.");
    while (true) delay(1000);
  }
}

// ------------------------------------------------------------------
// Sensor reading
// ------------------------------------------------------------------

// Maps a raw ADC reading to a normalized 0-4095 range using this
// finger's stored calibration bounds, clamped at the edges.
uint16_t normalizeFlex(int fingerIndex, uint16_t raw) {
  uint16_t lo = flexMin[fingerIndex];
  uint16_t hi = flexMax[fingerIndex];
  if (hi <= lo) return raw; // calibration not run yet — fall back to raw value
  long normalized = (long)(raw - lo) * 4095L / (long)(hi - lo);
  if (normalized < 0) normalized = 0;
  if (normalized > 4095) normalized = 4095;
  return (uint16_t)normalized;
}

void readFlexSensors(uint16_t* out) {
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    uint16_t raw = analogRead(flexPins[i]);
    uint16_t norm = normalizeFlex(i, raw);

    if (!filterInitialized) {
      flexFiltered[i] = norm;
    } else {
      flexFiltered[i] = EMA_ALPHA * norm + (1.0f - EMA_ALPHA) * flexFiltered[i];
    }
    out[i] = (uint16_t)flexFiltered[i];
  }
  filterInitialized = true;
}

// ------------------------------------------------------------------
// Setup / loop
// ------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(200);

  Serial.printf("Signyales glove firmware starting. This unit: %s\n",
                IS_LEFT_GLOVE ? "LEFT" : "RIGHT");
  Serial.println("Send 'c' over Serial at any time to (re)run flex calibration,");
  Serial.println("or 'g' to measure the gyro's resting offset again (glove still).");

  analogReadResolution(12); // 0-4095, matches packet.h's assumed range
  warnAboutAdc2Pins();

  if (!setupImuWithRetries()) {
    Serial.println("FATAL: MPU6050 not found or not usable. Check wiring/I2C address. Halting.");
    reportImuProblem();
    while (true) delay(1000);
  }

  loadGyroOffset();
  measureGyroOffset();

  loadCalibration();
  setupEspNow();

  Serial.println("Setup complete. Streaming...");
}

void loop() {
  static uint32_t lastSample = 0;

  // Non-blocking command check — every loop iteration, so it never has
  // to compete with a blocking delay().
  if (Serial.available()) {
    int cmd = Serial.read();
    if (cmd == 'c') {
      runCalibrationRoutine();
    } else if (cmd == 'g') {
      measureGyroOffset();
    }
  }

  uint32_t now = millis();
  if (now - lastSample < SAMPLE_PERIOD_MS) {
    return; // not time for the next sample yet
  }
  lastSample = now;

  glove_packet_t pkt;
  pkt.glove_id = IS_LEFT_GLOVE ? GLOVE_ID_LEFT : GLOVE_ID_RIGHT;
  pkt.seq = seqCounter++;
  pkt.timestamp_ms = now;

  readFlexSensors(pkt.flex_raw);

  // The packet carries accel in g (about 1.0 at rest) and gyro in deg/s,
  // as packet.h, windowing.py and the training scaler assume. If a read
  // fails, the previous sample's values are sent again.
  static float lastAccel[3] = {0, 0, 0};
  static float lastGyro[3] = {0, 0, 0};
  bool imuOk = readImu(lastAccel, lastGyro);
  if (!imuOk) {
    imuReadFailures++;
  }
  handleImuReadResult(imuOk, now);
  if (imuReadFailures > 0 && now - lastImuFailureReport >= 1000) {
    Serial.printf("IMU read failed %lu time(s) in the last second.\n", (unsigned long)imuReadFailures);
    imuReadFailures = 0;
    lastImuFailureReport = now;
  }
  for (int i = 0; i < 3; i++) {
    pkt.accel[i] = lastAccel[i];
    pkt.gyro[i] = lastGyro[i] - gyroOffset[i];
  }

  pkt.checksum = compute_checksum(&pkt);

  esp_err_t result = esp_now_send(RECEIVER_MAC, (uint8_t*)&pkt, sizeof(pkt));
  if (result != ESP_OK) {
    sendFailures++;
  }
  // At most one line a second about failed sends (it used to be one per
  // sample, up to 50 a second).
  if (sendFailures > 0 && now - lastFailureReport >= 1000) {
    Serial.printf("esp_now_send failed %lu time(s) in the last second.\n", (unsigned long)sendFailures);
    sendFailures = 0;
    lastFailureReport = now;
  }
}
