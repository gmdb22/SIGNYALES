/*
  Signyales — Glove Hardware Check (original ESP32)
  =================================================
  A temporary test program for one glove. It does NOT send anything
  wirelessly and does not change the glove's saved calibration.

  At startup it prints the chip, why it last reset, and every device on
  the I2C bus (the motion sensor). Then it prints the 7 flex readings
  (F1-F7 from the glove PCB schematic) four times a second.

  Serial commands (115200 baud; type the letter and press Enter):
    s   summary: lowest, highest and spread of each sensor since the last 'r'
    r   reset the lowest/highest values
    w   turn Wi-Fi on or off (shows which pins stop working while the
        glove transmits; the real firmware always has Wi-Fi on)
    i   scan the I2C bus again
    p   pause or resume the readings

  Pins are from the KiCad schematic of the glove PCB (22 Oct 2026).
*/

#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_system.h>

struct FlexChannel { const char* name; int pin; };

// F1-F7 as in the glove PCB schematic (connectors J1-J7).
const FlexChannel FLEX[] = {
  {"F1", 34}, {"F2", 35}, {"F3", 32}, {"F4", 33},
  {"F5", 25}, {"F6", 26}, {"F7", 27},
};
const int N = sizeof(FLEX) / sizeof(FLEX[0]);

// I2C pin pairs to scan: the schematic's pins, then the ESP32's usual
// I2C pins in case the IMU was wired there instead.
const int I2C_PAIRS[][2] = { {12, 14}, {21, 22} };

uint16_t lo[N], hi[N];
bool wifiOn = false;
bool paused = false;

bool isAdc2(int pin) {
  return pin == 0 || pin == 2 || pin == 4 || (pin >= 12 && pin <= 15) ||
         (pin >= 25 && pin <= 27);
}

const char* resetReason() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "power on";
    case ESP_RST_SW:       return "software restart";
    case ESP_RST_PANIC:    return "crash (panic)";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:      return "watchdog";
    case ESP_RST_BROWNOUT: return "BROWNOUT (power dipped too low)";
    case ESP_RST_EXT:      return "reset pin";
    case ESP_RST_DEEPSLEEP: return "wake from deep sleep";
    default:               return "other";
  }
}

void resetRange() {
  for (int i = 0; i < N; i++) { lo[i] = 4095; hi[i] = 0; }
}

void scanI2c() {
  Serial.println("--- I2C scan (motion sensor) ---");
  for (auto& pair : I2C_PAIRS) {
    int sda = pair[0], scl = pair[1];
    Wire.end();
    Wire.begin(sda, scl);
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
      Wire.beginTransmission(addr);
      if (Wire.endTransmission() != 0) continue;
      found++;
      Serial.printf("SDA=GPIO%d SCL=GPIO%d: device at 0x%02X", sda, scl, addr);
      if (addr == 0x68 || addr == 0x69) {
        Wire.beginTransmission(addr);
        Wire.write(0x75);  // WHO_AM_I register
        if (Wire.endTransmission(false) == 0 && Wire.requestFrom(addr, (uint8_t)1) == 1) {
          uint8_t who = Wire.read();
          const char* kind = who == 0x68 ? "MPU6050 (what the glove firmware expects)"
                           : who == 0x70 ? "MPU6500 (NOT accepted by the glove firmware's library)"
                           : who == 0x71 ? "MPU9250 (NOT accepted by the glove firmware's library)"
                           : "unknown chip (NOT accepted by the glove firmware's library)";
          Serial.printf(", WHO_AM_I=0x%02X = %s", who, kind);
        }
      }
      Serial.println();
    }
    if (!found) Serial.printf("SDA=GPIO%d SCL=GPIO%d: nothing found\n", sda, scl);
  }
  Wire.end();
}

void setWifi(bool on) {
  if (on) {
    WiFi.mode(WIFI_STA);   // radio on, as when the glove firmware transmits
    WiFi.disconnect();
  } else {
    WiFi.mode(WIFI_OFF);
  }
  wifiOn = on;
  Serial.printf("--- Wi-Fi is now %s ---\n", on ? "ON: ADC2 pins (F5, F6, F7) should stop changing"
                                                 : "OFF: all 7 pins can be read");
}

void printSummary() {
  Serial.printf("--- Summary since last 'r' (Wi-Fi %s) ---\n", wifiOn ? "ON" : "OFF");
  for (int i = 0; i < N; i++) {
    int spread = (int)hi[i] - (int)lo[i];
    if (spread < 0) spread = 0;
    const char* note = spread >= 800 ? "good range"
                     : spread >= 200 ? "small range"
                     : "barely moves (check the sensor, its resistor, or this pin)";
    Serial.printf("%s (GPIO%d%s): low=%4u high=%4u spread=%4d  %s\n", FLEX[i].name, FLEX[i].pin,
                  isAdc2(FLEX[i].pin) ? ", ADC2" : "", lo[i], hi[i], spread, note);
  }
  Serial.println("(Bend each finger fully a few times between 'r' and 's'. The 200/800 limits "
                 "are rough guides for this check only.)");
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("=== Signyales glove hardware check ===");
  Serial.printf("Chip: %s rev %d, %d core(s), flash %u MB\n", ESP.getChipModel(),
                ESP.getChipRevision(), ESP.getChipCores(), ESP.getFlashChipSize() / (1024 * 1024));
  Serial.printf("Last reset: %s\n", resetReason());
  Serial.println("If you can read this, the board starts normally.");

  analogReadResolution(12);
  resetRange();
  setWifi(false);
  scanI2c();
  Serial.println("--- Flex readings, 0-4095 (Wi-Fi OFF). Bend one finger at a time to see "
                 "which F it is. Commands: s r w i p ---");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 's') printSummary();
    else if (c == 'r') { resetRange(); Serial.println("--- low/high reset ---"); }
    else if (c == 'w') setWifi(!wifiOn);
    else if (c == 'i') scanI2c();
    else if (c == 'p') { paused = !paused; Serial.println(paused ? "--- paused ---" : "--- resumed ---"); }
  }

  static uint32_t last = 0;
  if (millis() - last < 250) return;
  last = millis();

  uint16_t v[N];
  for (int i = 0; i < N; i++) {
    v[i] = analogRead(FLEX[i].pin);
    if (v[i] < lo[i]) lo[i] = v[i];
    if (v[i] > hi[i]) hi[i] = v[i];
  }
  if (paused) return;
  for (int i = 0; i < N; i++) Serial.printf("%s=%4u  ", FLEX[i].name, v[i]);
  Serial.println(wifiOn ? " [Wi-Fi ON]" : "");
}
