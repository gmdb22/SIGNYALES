# Glove radio test (glove → receiver → Pi) and glove firmware checks

Date: night of 3 to 4 November 2026 (Asia/Manila), ending about 04:45. Run by the project owner on
the real hardware; the output and meter readings were pasted and read the same night. Code: branch
`code-tasks` at `3b469bf`. Glove firmware from `8945b62` (MPU read directly, clone IDs accepted)
with the receiver's MAC put into `config.h` locally (not committed). Receiver firmware unchanged
since `51b690f` (flashed 31 Oct).

Labels: **VERIFIED** = run on the real hardware and the output seen. **REASONED** = worked out
from the output, not confirmed. **NOT RUN** = not done yet.

## 1. Setup

| Part | Details |
|---|---|
| Glove boards | Board L and board R (ESP32-DevKitC-32E clones, CP2102), **out of the glove PCBs**. Each tested with one MPU6050 clone board on jumpers: VCC → 3V3, GND → GND, SDA → IO21, SCL → IO22. **No flex sensors attached.** |
| MPU boards | Left and right MPU, both WHO_AM_I `0x72` (clone), address 0x68. |
| Receiver | 30-pin ESP32-WROOM-32 (CH340), MAC 68:09:47:E0:ED:90. UART wires to the Pi: D17 → pin 10, D18 → pin 8, GND → pin 6 (`/dev/ttyAMA0`). Its USB was also on the Pi (`/dev/ttyUSB0`): the `[stats]` lines were read there (REASONED from the output). |
| Raspberry Pi 5 | Reached over SSH from the laptop. Commands from `~/SIGNYALES/pi-side` with the venv active. |
| Cables | One USB data cable and one charge-only cable. The glove board under test only needed power once flashed. |

## 2. Commands

```bash
# Pi bash (SSH), ~/SIGNYALES/pi-side, venv active
python -m serial.tools.miniterm --exit-char 24 /dev/ttyUSB0 115200   # board or receiver text, Ctrl+X to quit
python tools/live_view.py --link uart --duration 20
```

## 3. Results: radio link, one glove at a time

| # | Time | Glove sending | Frames | Fresh | Outages > 2 s | Glove seq gaps (`live_view`) | Receiver `[stats]` | Label |
|---|---|---|---|---|---|---|---|---|
| 1 | 04:22 | Board L + left MPU | 1000 (50.0 Hz) | Left **100.0%** | 0 | 1 | left dropped 0, corrupt 0 (read after the run, frames 11735–12585) | VERIFIED |
| 2 | 04:39 | Board R + right MPU | 1000 (50.0 Hz) | Right **100.0%** | 0 | 3 | right dropped 0, corrupt 0 (read just before the run) | VERIFIED |
| 3 | 04:41 | Board R + right MPU, tilted and turned by hand | 999 (49.9 Hz) | Right **100.0%** | 0 | 0 | — | VERIFIED |
| 4 | before 04:59, **5 min** (UART) | Board R + right MPU, still | 15001 in 300 s (50.0 Hz) | Right **99.9%** | 0 | 25 | right dropped 0, corrupt 0 at about 124,000 frames since receiver boot (read at 05:01, covers the run) | VERIFIED |
| 5 | 05:03, **USB link** (`--link usb`, `/dev/ttyUSB0`), 20 s | Board R + right MPU | 967 (48.3 Hz incl. start-up; 50.0 Hz after) | Right **100.0%** | 0 | 0 | `receiver:` line on the Pi: right 100.0% received, 0 lost, 0 damaged | VERIFIED |
| 6 | before 05:09, **5 min**, USB link (REASONED from the 0.7 s start-up gap; command not pasted) | Board R + right MPU, still | 14968 in 300 s (49.9 Hz) | Right **100.0%** | 0 | 8 | — | VERIFIED |

The other hand showed `STALE` in every run, as expected (that glove was off).

Motion sensor values over the radio:

| | Accel at rest (g) | Total | Gyro at rest (deg/s) |
|---|---|---|---|
| Left MPU (run 1) | +0.70, +0.33, −0.62 | ≈ 0.99 g | about −4.4, +2.8, −0.3 |
| Right MPU (run 2) | −0.98, +0.04, +0.17 | ≈ 1.00 g | about −4.2, +1.2, −0.2 |

- **Tilt test (run 3):** gravity moved between the axes as the board was turned, for example
  (−0.98, −0.01, +0.19) → (−0.06, −0.14, +1.02) → (−0.03, +0.88, +0.46), and the total stayed
  near 1 g. The gyro rose to about 90 deg/s while turning and went back to the resting values when
  still (VERIFIED). So accel and gyro are live, in the right units, and reach the Pi.
- **Gyro offset at rest:** a few deg/s on both MPUs (also seen with the `a` command on the laptop).
  REASONED: normal zero-rate offset for these sensors. Not corrected in the firmware. It may matter
  for recognition later; noted, no action yet.
- **Glove seq gaps vs radio loss:** the receiver counts lost radio packets itself (`dropped`) and
  reported 0. `live_view` counts gaps in the glove sequence numbers seen in the forwarded frames.
  The receiver forwards every 20 ms, and the glove also sends every 20 ms on its own clock, so now
  and then two glove packets arrive within one forwarding period and only the newer one is
  forwarded. REASONED: the 1 and 3 gaps are from that, not packets lost over the radio.
- **5-minute run (4):** about 15 frames of 15,001 were marked stale (no right-glove packet in the
  receiver's 30 ms freshness window); each was a single frame, never an outage. The receiver's own
  count shows 0 radio packets lost over the run, so the 25 gaps are all from the forwarding overlap
  above (VERIFIED by the receiver's count).
- **USB link (5, 6):** opening `/dev/ttyUSB0` restarted the receiver once (`frame_seq` 0, 1.5 Hz in
  the first 0.7 s), then 50 Hz, as on 31 Oct. With a glove sending, the Pi showed the receiver's
  statistics (`receiver:` line). So both links now work with a glove sending.
- **Flex values:** meaningless here (no sensors). Board L reads about 0 because `c` was run on it
  earlier with nothing attached and that calibration is saved; board R drifts because it has the
  default calibration. Both need `c` again once the flex sensors are connected.
- **LED:** board R's power LED stayed off although the board ran normally (owner). Cosmetic.

**Conclusion:** each glove board, with its MPU and the new firmware, reaches the receiver over
ESP-NOW and the Pi at 50 Hz with no radio packets lost, over the UART wires and over the USB
cable. VERIFIED for one glove at a time: 20 s runs for each glove, and 5 minutes for the right
glove on each link, with the board still and close to the receiver.

**NOT RUN yet:** both gloves sending at once (needs a third USB cable or the batteries), the left
glove for 5 minutes, runs with the glove moving or worn, range and 2.4 GHz interference, the gloves
on their PCBs and batteries, real flex sensors.

## 4. Earlier the same night

**On the laptop (Windows, GUI Hardware helper / PlatformIO)**

- Hardware check with an MPU attached, `a` command (about 01:57): WHO_AM_I `0x72`, GYRO_CONFIG and
  ACCEL_CONFIG both `0x08`, accel total 0.98 g lying still, gyro a few deg/s (VERIFIED). First run
  of the direct-register code on a real sensor.
- Glove firmware (`8945b62` + local MAC) compiled and uploaded to both boards: `left_glove` on
  board L and `right_glove` on board R, both uploads PASS (VERIFIED).
- Brownout resets still appeared on the laptop when opening the monitor with an MPU attached
  (VERIFIED, as on 2–3 Nov).
- **The laptop showed a Windows stop screen ("Your device ran into a problem") twice** while the board
  was plugged and unplugged with the GUI and its serial monitor open (VERIFIED by the owner, photo).
  The stop code was not readable in the photo. REASONED: the CP210x USB driver; to avoid it, close
  the monitor before unplugging and update the Silicon Labs CP210x driver. Testing moved to the Pi.

**On the Pi (SSH, miniterm on `/dev/ttyUSB0`)**

- The first runs stopped with `IMU: nothing answers at 0x68 on SDA=GPIO21, SCL=GPIO22` (VERIFIED).
  Cause: SDA and SCL were swapped on the jumpers (owner found it). With SDA → IO21, SCL → IO22, both
  MPUs on board L gave `IMU: WHO_AM_I=0x72 ...` and `Setup complete. Streaming...` (VERIFIED). The
  log also showed `nvs_open failed: NOT_FOUND` (REASONED: no calibration saved yet on that board,
  harmless) and some restarts.
- Sometimes the board printed only garbage after being plugged in, until EN was pressed, the
  monitor closed (Ctrl+X) and reopened, and EN pressed again (VERIFIED, owner). REASONED: the same
  unstable start-up as the brownouts.
- Meter readings on board L (DCV 20, owner), powered from the Pi:

| MPU on board L | 3V3 pin, MPU VCC attached | 5V pin, attached | 3V3, VCC not attached | 5V, not attached |
|---|---|---|---|---|
| Left MPU | 2.73 V | 4.48 V | 3.27 V | 5.02 V |
| Right MPU | 3.02 V | 4.82 V | 3.31 V | 5.08 V |

- MPU supply current, meter on the 10A range in series with the MPU's VCC: **0.00 A** for both MPUs
  on board L (VERIFIED). REASONED: below 0.01 A (the range's resolution), so each MPU draws under
  about 10 mA and is not overloading the supply.

**What this changes (REASONED):** the 2–3 Nov brownouts are not caused by a faulty MPU. With the MPU
found, the firmware starts the radio, which draws far more current than the MPU, so the lower 3V3
readings with the MPU attached mix the two. The 5V pin also sags (4.48–4.82 V), which points at a
weak USB supply or cable. NOT RUN: the same test with a short, thick data cable.

## 5. Still to do

- Assembler rework of both PCBs: 47 kΩ for R1–R6, pinky → IO36, palm → IO39, MPU on IO21 (SDA) /
  IO22 (SCL), the PCB power path (J8). Then the boards back in, `c` calibration on each glove.
- Measure the other five divider resistors and do the PCB short and pin checks.
- Both gloves at once; range and interference runs; runs with the gloves worn.
- Brownouts with a better cable; the CP210x driver update on the laptop.
