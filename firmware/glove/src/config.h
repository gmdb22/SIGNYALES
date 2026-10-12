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
// Flex sensor pins — ESP32-S3 ADC1-capable GPIOs (safe to use even
// when Wi-Fi/ESP-NOW is active; ADC2 pins are not, on this chip).
// Adjust to match your actual wiring.
// ---------------------------------------------------------------
#define FLEX_PIN_THUMB   1
#define FLEX_PIN_INDEX   2
#define FLEX_PIN_MIDDLE  3
#define FLEX_PIN_RING    4
#define FLEX_PIN_PINKY   5
#define FLEX_SENSOR_COUNT 5

// ---------------------------------------------------------------
// IMU (I2C) — defaults assume an MPU6050 on ESP32-S3's default
// Wire pins. Adjust if your board/wiring differs.
// ---------------------------------------------------------------
#define IMU_SDA_PIN   8
#define IMU_SCL_PIN   9
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
