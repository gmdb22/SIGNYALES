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
// Flex sensor pins: 6 per glove (5 fingers + 1 palm), decided 24-25 Oct
// 2026. Board: original ESP32 (ESP32-DevKitC-32E clone).
//
// The connectors are swappable; the agreed plug-in order is
// J1 thumb, J2 index, J3 middle, J4 ring, J5 pinky, J6 palm (J7 unused).
//
// These pins assume the planned rework of the glove PCB:
//   - J5's signal point jumpered to IO36 (SENSOR_VP)
//   - J6's signal point jumpered to IO39 (SENSOR_VN)
//   - all divider resistors (R1-R6) changed from 470 ohm to 47 kOhm
// Before that rework, pinky and palm read an unconnected pin (noise) and
// every finger's reading barely moves.
//
// ADC2 WARNING: on the original ESP32, ADC2 pins (GPIO 0, 2, 4, 12-15,
// 25-27) cannot be read while Wi-Fi/ESP-NOW is on, and this firmware
// transmits all the time. That is why J5 and J6 (on IO25/IO26 in the
// PCB schematic) are moved to IO36/IO39. Only ADC1 pins (GPIO 32-39)
// work here. The firmware prints a warning at startup for any ADC2 pin.
// ---------------------------------------------------------------
#define FLEX_PIN_THUMB   34   // J1
#define FLEX_PIN_INDEX   35   // J2
#define FLEX_PIN_MIDDLE  32   // J3
#define FLEX_PIN_RING    33   // J4
#define FLEX_PIN_PINKY   36   // J5, via jumper to IO36 (SENSOR_VP)
#define FLEX_PIN_PALM    39   // J6, via jumper to IO39 (SENSOR_VN)
#define FLEX_SENSOR_COUNT 6

// ---------------------------------------------------------------
// IMU (I2C): MPU6050 board ("ITG/MPU", GY-521 type).
// SDA = IO21, SCL = IO22 (the ESP32's usual I2C pins), per the rework
// decided on 27 Oct 2026. The PCB schematic had SDA = IO12, SCL = IO14.
// IO12 is a boot strapping pin on the original ESP32: the IMU board's
// pull-up resistors hold it high at power-on, the ESP32 then sets its
// flash to 1.8 V and the 3.3 V flash fails to start (the right glove's
// boot loop on 27 Oct: "Probe failed", boot:0x33). IO12 must stay
// unconnected. Only flash this after the gloves are rewired: with the
// IMU still on IO12/IO14 the firmware stops at "MPU6050 not found".
// ---------------------------------------------------------------
#define IMU_SDA_PIN   21
#define IMU_SCL_PIN   22
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
// Changed from "signyales" when the sensors went from 5 to 6 (Oct 2026)
// so an old 5-sensor calibration is never loaded for the new pins.
// ---------------------------------------------------------------
#define CALIBRATION_NAMESPACE "signyales6"
