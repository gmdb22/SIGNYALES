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
- **Flex sensors: 6 per glove** (5 fingers + 1 palm), decided 24–25 Oct
  2026. The PCB has 7 connectors (J1–J7); J7 is not used. Plug-in order:
  J1 thumb, J2 index, J3 middle, J4 ring, J5 pinky, J6 palm. The palm
  sensor's orientation (horizontal or diagonal) is still open. Pins after
  the planned rework: thumb IO34, index IO35, middle IO32, ring IO33,
  pinky IO36 (jumper from J5), palm IO39 (jumper from J6).
- **IMU:** MPU6050 board marked "ITG/MPU" (GY-521 type) over I2C,
  SDA = IO12, SCL = IO14 (from the schematic).

**Planned rework of each glove PCB (not done yet):**

- Replace R1–R6 (470 Ω fitted) with **47 kΩ**, as in the schematic. With
  470 Ω the readings hardly change when a finger bends. R7 is not needed.
- Jumper **J5's signal point → IO36** (SENSOR_VP) and **J6's signal point →
  IO39** (SENSOR_VN). In the schematic J5–J7 are on IO25–IO27, which are
  ADC2 pins: on the original ESP32 they can't be read while Wi-Fi/ESP-NOW
  is on (ESP-IDF documentation). The old tracks can stay; the firmware
  leaves IO25–IO27 as plain inputs. The ESP32 board has only 6 pins that
  work while transmitting (IO32–IO36, IO39), which is why there are 6
  sensors.
- IO12 (the IMU's SDA) is a boot strapping pin and can stop the board from
  starting. On 27 Oct 2026 the right glove went into a boot loop
  (`spi_flash ... Probe failed`, `boot:0x33`), most likely for this reason
  (reasoned, not yet confirmed). Decided: move the IMU to **SDA IO21, SCL
  IO22** on both gloves and leave IO12 unconnected. The matching firmware
  change (`IMU_SDA_PIN`/`IMU_SCL_PIN` in `config.h`) is a separate patch,
  applied once the assembler confirms the rewiring.

Before the rework, the pinky and palm slots read unconnected pins (noise).

Adjust the pin numbers in `config.h` if your wiring differs. The number
of sensors (`FLEX_PER_GLOVE` in `packet.h`) is part of the data format:
changing it also means changing the Pi side and retraining.

## Hardware check (before the first real flash)

`firmware/tools/glove_hw_check` is a temporary test program for one
glove. It sends nothing wirelessly and doesn't touch the saved
calibration. It prints the chip and why it last reset, scans for the
motion sensor on IO12/IO14 and on IO21/IO22 (and reports its WHO_AM_I
value), then shows the flex readings four times a second: the 6 pins the
glove firmware uses (J1 thumb … J6 palm) and, for comparison, the
schematic's original J5–J7 pins (IO25–IO27).

```
# PowerShell, PlatformIO terminal, folder: firmware\tools\glove_hw_check
pio run -t upload
pio device monitor
```

In the monitor, type a letter and press Enter:

| Key | What it does |
|---|---|
| `r` then bend each finger fully a few times, then `s` | Shows each sensor's low, high and spread: tells you whether the resistors give a usable range |
| bend one finger (or the palm) at a time | Checks each J is plugged into the right sensor |
| `w` | Turns Wi-Fi on or off. With it on, the old J5–J7 pins (ADC2) should stop changing, as in the real firmware; IO36/IO39 keep working. Press `r` after switching. |
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
time to run an 8-second calibration: flex and relax every finger and the
palm fully during that window. The captured min/max per sensor is saved to flash
(NVS) and survives reboots — you only need to redo it if the sensors are
replaced or a different wearer's flex range differs substantially.

## How this connects to the rest of the system

- **Packet format (`packet.h`) must be copied verbatim into the receiver
  dongle's firmware.** If the two drift out of sync, ESP-NOW still
  delivers bytes, but the receiver will misread the struct with no error
  surfaced anywhere — this is the most common silent-failure point in
  this kind of pipeline.
- **Field order matters for the TinyML model.** `flex_raw` is fixed as
  thumb/index/middle/ring/pinky/palm, followed by accel then gyro. Whatever
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
