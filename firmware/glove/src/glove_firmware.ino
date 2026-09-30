/*
  Signyales — Glove Node Firmware (ESP32-S3)
  ============================================
  Layer 1 of the Signyales pipeline. Reads 5 flex sensors and a 6-axis
  IMU, filters and calibrates the readings, packs them into a
  glove_packet_t (see packet.h), and transmits over ESP-NOW to the
  receiver dongle at SAMPLE_RATE_HZ.

  Flash this same sketch onto both gloves — only config.h's
  IS_LEFT_GLOVE/IS_RIGHT_GLOVE flag changes between the two builds.

  Dependencies (install via Arduino Library Manager):
    - Adafruit MPU6050
    - Adafruit Unified Sensor

  Board: ESP32S3 Dev Module (installed via Boards Manager: esp32 by
  Espressif Systems)

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

const int flexPins[FLEX_SENSOR_COUNT] = {
  FLEX_PIN_THUMB, FLEX_PIN_INDEX, FLEX_PIN_MIDDLE, FLEX_PIN_RING, FLEX_PIN_PINKY
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
  Serial.println("=== Calibration: flex and relax ALL fingers repeatedly for 8 seconds ===");
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
  Serial.println("Calibration saved:");
  for (int i = 0; i < FLEX_SENSOR_COUNT; i++) {
    Serial.printf("  Finger %d: min=%u max=%u\n", i, flexMin[i], flexMax[i]);
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

  Wire.begin(IMU_SDA_PIN, IMU_SCL_PIN);
  if (!mpu.begin(IMU_I2C_ADDR)) {
    Serial.println("FATAL: MPU6050 not found. Check wiring/I2C address. Halting.");
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
  pkt.accel[0] = a.acceleration.x;
  pkt.accel[1] = a.acceleration.y;
  pkt.accel[2] = a.acceleration.z;
  pkt.gyro[0]  = g.gyro.x * 180.0f / PI; // rad/s -> deg/s
  pkt.gyro[1]  = g.gyro.y * 180.0f / PI;
  pkt.gyro[2]  = g.gyro.z * 180.0f / PI;

  pkt.checksum = compute_checksum(&pkt);

  esp_err_t result = esp_now_send(RECEIVER_MAC, (uint8_t*)&pkt, sizeof(pkt));
  if (result != ESP_OK) {
    Serial.println("esp_now_send failed for this sample.");
  }
}
