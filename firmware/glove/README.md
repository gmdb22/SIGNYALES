# Signyales — Glove Node Firmware

This is layer 1 of the Signyales pipeline (see the ranked software list):
glove firmware → receiver dongle → TinyML model → Pi hub app → TTS.
Everything downstream depends on this layer producing clean, consistently
formatted data, so a few design choices here are made specifically with
the rest of the pipeline in mind — flagged below.

## What's in this folder

| File | Purpose |
|---|---|
| `packet.h` | Wire format shared with the receiver dongle. Copy it there unchanged. |
| `config.h` | Pin mapping, glove identity (left/right), receiver MAC, sample rate. |
| `glove_firmware.ino` | The firmware itself. |
| `get_mac_address/get_mac_address.ino` | One-off utility to read the receiver's MAC address. |

## Hardware assumptions

- **MCU:** ESP32-S3 (Dev Module)
- **Flex sensors:** 5× analog flex sensors (one per finger), wired through
  a voltage divider into ADC1-capable GPIOs (GPIO1–5 by default)
- **IMU:** MPU6050 6-axis accelerometer/gyroscope over I2C (GPIO8/9 by default)

Adjust the pin numbers in `config.h` if your wiring differs — nothing else
in the firmware needs to change.

## Build steps

1. In Arduino IDE, install board support for **esp32 by Espressif Systems**
   (Boards Manager) and select **ESP32S3 Dev Module**.
2. Install libraries via Library Manager: **Adafruit MPU6050** and
   **Adafruit Unified Sensor** (installing the first will prompt for the
   second as a dependency).
3. Flash `get_mac_address/get_mac_address.ino` onto the **receiver** ESP32
   and copy the printed MAC address.
4. Open `glove_firmware.ino`. In `config.h`:
   - Paste the receiver's MAC into `RECEIVER_MAC`.
   - Set `IS_LEFT_GLOVE` / `IS_RIGHT_GLOVE` for the unit you're flashing.
5. Flash onto the left glove. Flip the flag, flash again onto the right glove.
6. Open Serial Monitor at 115200 baud. You should see `Setup complete. Streaming...`

## Calibration

Flex sensors vary from unit to unit, so raw ADC values alone aren't
comparable across fingers or across gloves. Send `c` over Serial at any
time to run an 8-second calibration: flex and relax every finger fully
during that window. The captured min/max per finger is saved to flash
(NVS) and survives reboots — you only need to redo it if the sensors are
replaced or a different wearer's flex range differs substantially.

## How this connects to the rest of the system

- **Packet format (`packet.h`) must be copied verbatim into the receiver
  dongle's firmware.** If the two drift out of sync, ESP-NOW still
  delivers bytes, but the receiver will misread the struct with no error
  surfaced anywhere — this is the most common silent-failure point in
  this kind of pipeline.
- **Field order matters for the TinyML model.** `flex_raw` is fixed as
  thumb/index/middle/ring/pinky, followed by accel then gyro. Whatever
  order the training data collection script logs features in on the Pi
  side must match this exactly, or the model will train on a feature
  vector that doesn't correspond to what it receives at inference time.
- **Sample rate (50 Hz by default) sets the model's time resolution.**
  If you change `SAMPLE_RATE_HZ`, the training data collection script
  must sample at the same rate — otherwise a gesture that took, say,
  40 samples during training will take a different number of samples
  at runtime, and the model's input window size will no longer line up.
- **`seq` and `timestamp_ms`** exist so the receiver can detect dropped
  or reordered packets and so the Pi can align left/right glove streams
  by time rather than assuming they arrive in lockstep.
- **`checksum`** is a cheap integrity check the receiver should verify
  before forwarding a packet onward — silently forwarding corrupted
  sensor data into the model is worse than dropping the sample.

## Known limitations (carried over from the proposal)

- No AES encryption on the ESP-NOW link (`peerInfo.encrypt = false`) —
  fine for a point-to-point classroom deployment, but worth noting if
  asked about security.
- No deep-sleep power saving: ESP-NOW requires the radio to stay
  active, so this firmware trades battery life for responsiveness.
  If battery life becomes a bottleneck, look at modem-sleep
  (`esp_wifi_set_ps()`) rather than deep sleep, which would drop the
  ESP-NOW connection entirely.
