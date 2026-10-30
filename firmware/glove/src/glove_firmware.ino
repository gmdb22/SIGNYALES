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

  Dependencies (install via Arduino Library Manager):
    - Adafruit MPU6050
    - Adafruit Unified Sensor

  Board: ESP32 Dev Module (esp32dev; the glove PCB uses an
  ESP32-DevKitC-32E clone). Installed via Boards Manager: esp32 by
  Espressif Systems.

  Serial commands (115200 baud):
    'c'  -> run an 8-second flex calibration routine and save to flash
*/

#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <Preferences.h>

#include "config.h"
#include "packet.h"

Adafruit_MPU6050 mpu;
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

// Standard gravity: Adafruit's acceleration (m/s²) divided by this = g.
const float MS2_PER_G = 9.80665f;

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

// Called when mpu.begin() fails: reports what, if anything, answers on
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
          Serial.printf(", WHO_AM_I=0x%02X (a genuine MPU6050 reports 0x68)", Wire.read());
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
  Serial.println("Send 'c' over Serial at any time to (re)run flex calibration.");

  analogReadResolution(12); // 0-4095, matches packet.h's assumed range
  warnAboutAdc2Pins();

  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  if (!mpu.begin(IMU_I2C_ADDR)) {
    Serial.println("FATAL: MPU6050 not found. Check wiring/I2C address. Halting.");
    reportImuProblem();
    while (true) delay(1000);
  }
  mpu.setAccelerometerRange(MPU6050_RANGE_4_G);
  mpu.setGyroRange(MPU6050_RANGE_500_DEG);
  mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);

  loadCalibration();
  setupEspNow();

  Serial.println("Setup complete. Streaming...");
}

void loop() {
  static uint32_t lastSample = 0;

  // Non-blocking calibration trigger — checked every loop iteration
  // so it never has to compete with a blocking delay().
  if (Serial.available() && Serial.read() == 'c') {
    runCalibrationRoutine();
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

  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);
  // Adafruit's getEvent() gives m/s²; the packet carries g (packet.h,
  // windowing.py and the training scaler all assume g: about 1.0 at rest).
  pkt.accel[0] = a.acceleration.x / MS2_PER_G;
  pkt.accel[1] = a.acceleration.y / MS2_PER_G;
  pkt.accel[2] = a.acceleration.z / MS2_PER_G;
  pkt.gyro[0]  = g.gyro.x * 180.0f / PI; // rad/s -> deg/s
  pkt.gyro[1]  = g.gyro.y * 180.0f / PI;
  pkt.gyro[2]  = g.gyro.z * 180.0f / PI;

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
