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

The firmware was first written for an ESP32-S3. The gloves that were
actually built (October 2026) use different parts, so these are now:

- **MCU:** original ESP32, on an ESP32-DevKitC-32E clone (CP210x USB
  chip). PlatformIO board `esp32dev`.
- **Flex sensors:** the glove PCB's schematic has **7** connectors (J1–J7,
  F1–F7) on IO34, IO35, IO32, IO33, IO25, IO26 and IO27, each through a
  divider to 3.3 V. The firmware and the frame still carry **5** values;
  whether to use all 7 is not decided yet. `config.h` currently reads
  F1–F5 in the five finger slots. Which connector is which finger is not
  confirmed yet.
- **IMU:** MPU6050 board marked "ITG/MPU" (GY-521 type) over I2C,
  SDA = IO12, SCL = IO14 (from the schematic).

**Known wiring problems in the schematic (not yet fixed on the boards):**

- IO25, IO26 and IO27 are ADC2 pins. On the original ESP32 they can't be
  read while Wi-Fi/ESP-NOW is on, so F5–F7 are expected to read 0 in the
  real firmware (from the ESP32 documentation; not yet seen on the gloves).
  The fix is to move those sensors to free ADC1 pins (IO36/SENSOR_VP,
  IO39/SENSOR_VN). The firmware prints a warning at startup for each one.
- IO12 is a boot strapping pin. If the IMU's pull-up holds it high at
  power-on, the board may not start. The fix is to move SDA/SCL to IO21
  and IO22 and change `IMU_SDA_PIN`/`IMU_SCL_PIN`.
- The divider resistors fitted are 470 Ω, not the schematic's 47 kΩ. With
  470 Ω the readings hardly change when a finger bends.

Adjust the pin numbers in `config.h` if your wiring differs — nothing else
in the firmware needs to change while there are 5 sensors.

## Hardware check (before the first real flash)

`firmware/tools/glove_hw_check` is a temporary test program for one
glove. It sends nothing wirelessly and doesn't touch the saved
calibration. It prints the chip and why it last reset, scans for the
motion sensor on IO12/IO14 and on IO21/IO22 (and reports its WHO_AM_I
value), then shows all 7 flex readings four times a second.

```
# PowerShell, PlatformIO terminal, folder: firmware\tools\glove_hw_check
pio run -t upload
pio device monitor
```

In the monitor, type a letter and press Enter:

| Key | What it does |
|---|---|
| `r` then bend each finger fully a few times, then `s` | Shows each sensor's low, high and spread: tells you whether the resistors give a usable range |
| bend one finger at a time | Shows which F (J1–J7) is which finger |
| `w` | Turns Wi-Fi on or off. With it on, F5–F7 (ADC2) should stop changing, as in the real firmware. Press `r` after switching. |
| `i` | Scans for the motion sensor again |
| `p` | Pauses or resumes the readings |

If nothing at all appears after pressing the board's EN button, or it
keeps restarting, the board is not starting (see the IO12 problem above).
Flash the glove firmware back on afterwards. This program has not been
run on the real gloves yet.

## Build steps

1. In Arduino IDE, install board support for **esp32 by Espressif Systems**
   (Boards Manager) and select **ESP32 Dev Module**. (With PlatformIO,
   `platformio.ini` already selects it.)
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
