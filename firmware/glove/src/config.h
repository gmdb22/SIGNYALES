/*
  Signyales — Glove Build Configuration
  --------------------------------------
  Everything you're likely to need to change per-device or per-build
  lives here, so glove_firmware.ino itself never needs editing.
*/

#pragma once

// ---------------------------------------------------------------
// Glove identity — set via PlatformIO build_flags (see platformio.ini),
// falling back to these defaults if built outside PlatformIO (e.g.
// directly from the Arduino IDE, where you'd edit the values below).
// ---------------------------------------------------------------
#ifndef IS_LEFT_GLOVE
#define IS_LEFT_GLOVE   1
#endif
#ifndef IS_RIGHT_GLOVE
#define IS_RIGHT_GLOVE  0
#endif

#if (IS_LEFT_GLOVE + IS_RIGHT_GLOVE) != 1
#error "Exactly one of IS_LEFT_GLOVE / IS_RIGHT_GLOVE must be set to 1"
#endif

// ---------------------------------------------------------------
// Flex sensor pins. Board: original ESP32 (ESP32-DevKitC-32E clone).
//
// PROVISIONAL (22 Oct 2026): taken from the glove PCB's KiCad schematic,
// which has 7 flex connectors J1-J7 (F1-F7) on IO34, IO35, IO32, IO33,
// IO25, IO26 and IO27. Which connector goes to which finger is not known
// yet, and whether all 7 sensors will be used is not decided, so this
// build reads F1-F5 in the finger slots below and ignores F6/F7. Use
// firmware/tools/glove_hw_check to find out which F is which finger,
// then set these five lines to match.
//
// ADC2 WARNING: on the original ESP32, ADC2 pins (GPIO 0, 2, 4, 12-15,
// 25-27) cannot be read while Wi-Fi/ESP-NOW is on, and this firmware
// transmits all the time. Only ADC1 pins (GPIO 32-39) work here. IO25
// (F5) is ADC2, so FLEX_PIN_PINKY reads nothing until that sensor is
// rewired to a free ADC1 pin (IO36 = SENSOR_VP or IO39 = SENSOR_VN).
// The firmware prints a warning at startup for every ADC2 pin below.
// ---------------------------------------------------------------
#define FLEX_PIN_THUMB   34   // F1 / J1 (finger not confirmed)
#define FLEX_PIN_INDEX   35   // F2 / J2 (finger not confirmed)
#define FLEX_PIN_MIDDLE  32   // F3 / J3 (finger not confirmed)
#define FLEX_PIN_RING    33   // F4 / J4 (finger not confirmed)
#define FLEX_PIN_PINKY   25   // F5 / J5 (ADC2: unreadable while transmitting)
#define FLEX_SENSOR_COUNT 5

// ---------------------------------------------------------------
// IMU (I2C): MPU6050 board ("ITG/MPU", GY-521 type).
// From the glove PCB schematic: SDA = IO12, SCL = IO14.
//
// IO12 WARNING: IO12 is a boot strapping pin on the original ESP32. If
// it is high at power-on (the IMU board's pull-up resistors do that),
// the ESP32 sets its flash to 1.8 V and a 3.3 V-flash module such as
// the WROOM-32E may not start (reset loop or "flash read err"). If that
// happens, move SDA/SCL to the ESP32's usual I2C pins, IO21 and IO22,
// and change these two lines to 21 and 22.
// ---------------------------------------------------------------
#define IMU_SDA_PIN   12
#define IMU_SCL_PIN   14
#define IMU_I2C_ADDR  0x68   // MPU6050 default (0x69 if AD0 is pulled high)

// ---------------------------------------------------------------
// Receiver dongle MAC address.
// Flash get_mac_address.ino onto the receiver ESP32 first, read the
// printed address over Serial, and paste it here. This must be kept
// in sync if the receiver is ever re-flashed onto different hardware.
// ---------------------------------------------------------------
static uint8_t RECEIVER_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};

// ---------------------------------------------------------------
// Sampling rate. This directly determines the time resolution of
// every gesture the TinyML model will ever see — if you change this,
// the training data collection script must sample at the same rate,
// or the model's input window will no longer correspond to real time.
// ---------------------------------------------------------------
#define SAMPLE_RATE_HZ    50
#define SAMPLE_PERIOD_MS  (1000 / SAMPLE_RATE_HZ)

// ---------------------------------------------------------------
// Exponential moving average smoothing for flex readings.
// Closer to 1.0 = more responsive/less smoothing.
// Closer to 0.0 = smoother/more lag.
// ---------------------------------------------------------------
#define EMA_ALPHA 0.3f

// ---------------------------------------------------------------
// Flash storage namespace for per-glove flex calibration.
// ---------------------------------------------------------------
#define CALIBRATION_NAMESPACE "signyales"
