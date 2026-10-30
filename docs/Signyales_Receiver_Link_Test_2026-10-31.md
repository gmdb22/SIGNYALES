# Receiver link test (USB cable vs UART wires) and glove hardware checks

Date: 31 October 2026 (Asia/Manila), about 01:00 to 03:20. Run by the project owner on the real
hardware; the output was pasted and read the same night. Code: branch `code-tasks`, commit
`51b690f` (tree `06ae540f`), on the laptop and on the Pi. The `live_view.py` summary fix and this
record were added afterwards.

Labels: **VERIFIED** = run on the real hardware and the output seen. **REASONED** = worked out
from the output, not confirmed. **NOT RUN** = not done yet.

## 1. Setup

| Part | Details |
|---|---|
| Receiver | 30-pin ESP32-WROOM-32 DevKit, CH340C USB chip, MAC 68:09:47:E0:ED:90, mounted on an ESP32 expansion board (G/V/S pin rows). Firmware from `51b690f`, flashed from the laptop the same night (VERIFIED: boot `rst:0x1 (POWERON_RESET), boot:0x13`, new firmware line "Frames go to the UART pins always, and to USB while the Pi asks for them.", `[stats]` advancing 50 frames per second). |
| Raspberry Pi 5 | Raspberry Pi OS (Debian 13), Python 3.13.5, code at `51b690f`. Software checks on the Pi passed before the test (frame round-trip, Pi-side unit tests, GUI core tests: VERIFIED). |
| Laptop | Windows, receiver on COM10. |
| USB link | USB-A to USB-C data cable, receiver's own USB-C to a Pi USB port (`/dev/ttyUSB0`). |
| UART link | Female-female jumpers: expansion board D17 row, S pin → Pi pin 10 (GPIO15 RX); D18 row, S pin → Pi pin 8 (GPIO14 TX); GND block → Pi pin 6. Receiver powered by the USB cable to the Pi at the same time (the receiver sends on both). |
| Gloves | **Off** for all link tests (not ready, see section 4). So these runs test the receiver-to-Pi link only, not ESP-NOW. |

## 2. Commands

```bash
# Pi bash, ~/SIGNYALES/pi-side, venv active
python3 -c "import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); s.write(b'hello'); time.sleep(0.2); print(s.read(5))"   # loopback, jumper pin 8-10
python tools/live_view.py --link uart --duration 10
python tools/live_view.py --link usb --duration 10
```
```powershell
# Laptop PowerShell, SIGNYALES folder
pi-side\venv\Scripts\python.exe pi-side\tools\live_view.py --duration 10
```

## 3. Results: USB vs UART (gloves off)

| # | Time | Test | Link / port | Frames in 10 s | Average | Rate per 0.5 s line | Restart when the port opened | Receiver `[stats]` on the reading side | Label |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 01:02 | `live_view`, laptop | USB, COM10 | 500 | 49.9 Hz | 50.0–50.4 Hz | No (`frame_seq` started at 4099) | Yes, every second | VERIFIED |
| 2 | 01:42 | Loopback (pin 8 ↔ pin 10, receiver not connected) | UART, `/dev/ttyAMA0` | — | — | — | — | — | VERIFIED: `b'hello'` |
| 3 | 02:12 | `live_view`, Pi | UART, `/dev/ttyAMA0` | 500 | 49.9 Hz | 50.0–50.3 Hz | No (`frame_seq` started at 5146) | No (not carried on the UART wires) | VERIFIED |
| 4 | 02:13 | `live_view`, Pi | USB, `/dev/ttyUSB0` | 468 | 46.8 Hz (includes the restart) | 1.5 Hz in the first 0.7 s, then 49.9–50.4 Hz | **Yes** (`frame_seq` started at 0) | Yes, from 1.7 s | VERIFIED |

Worked out from the same output:

- **Steady rate, startup left out** (from the first to the last printed `frame_seq`):
  laptop USB 459 frames in 9.2 s = 49.9 Hz; Pi UART 451 frames in 9.0 s = 50.1 Hz;
  Pi USB 458 frames in 9.1 s = 50.3 Hz. All match the receiver's 50 Hz (20 ms) forwarding.
- **Missing frames:** in every run `frame_seq` advanced by 25 or 26 per 0.5 s line, the same as
  the number of frames counted, so no frame was lost between receiver and reader (REASONED from
  the printed lines; the tool does not count receiver-to-reader frame gaps separately).
- **Restart on the Pi's USB:** opening `/dev/ttyUSB0` on Linux toggles the USB chip's reset
  lines, so the receiver rebooted once (REASONED: `frame_seq` 0, about 0.7 s with almost no
  frames). The Pi's frame requests brought the frames back within about 1.2 s with no action
  needed. This happens once each time a program opens the port (kiosk start, `live_view`), not
  while it runs. Windows did not reset the board (run 1). The receiver's `[stats]` counters
  restart from zero at that moment.
- **Tool issue found:** at the end of run 4 the summary stopped with a `KeyboardInterrupt`
  traceback. Cause: `live_view.py`'s backup timer for `--duration` fired while the summary was
  printing. Fixed in the commit that adds this record (the timer now only acts when no frames are
  arriving); the frame data above is not affected.

| | UART wires | USB cable |
|---|---|---|
| Rate | 50 Hz steady | 50 Hz steady, after a ~1.2 s restart when the port opens (Pi only) |
| Receiver's own `[stats]` on the Pi | No | Yes |
| Cabling | 3 jumpers, plus the USB cable for power | 1 cable |
| Pi setup | raspi-config serial + `dtparam=uart0=on` (done), loopback test | None |

**Conclusion:** both links pass with the gloves off. USB is the default because it is one cable
with nothing to wire wrong and it brings the receiver's own statistics; UART stays as the option
(Active mode → Receiver link). The choice for the demo is the team's (still open).

**NOT RUN yet:** both links with gloves sending (received %, lost, fresh %), runs longer than
10 s, 2.4 GHz interference, latency.

## 4. Glove hardware checks (same night)

Done with `firmware/tools/glove_hw_check` and the glove firmware, from the laptop.

**Left glove** (COM3)

- Uploads and starts normally: `rst:0x1 (POWERON_RESET), boot:0x12` (VERIFIED). The fault seen
  on 27 Oct (not recognised by Windows, USB area hot) did not appear.
- Glove firmware (`left_glove`): `This unit: LEFT`, then `FATAL: MPU6050 not found` on
  SDA=GPIO21/SCL=GPIO22 (VERIFIED).
- Hardware check: `nothing found` on GPIO21/22 and on GPIO12/14 (VERIFIED). The MPU6050 board's
  LED is off (owner) → REASONED: the IMU has no power.
- J5 pinky (IO36) and J6 palm (IO39) drift down to about 25 and 0 (floating) → REASONED: the
  J5/J6 jumpers are not done.
- The old pins IO25/IO26/IO27 read steady values (about 600 / 1250 / 1090) with Wi-Fi off and
  0 with Wi-Fi on (`ADC2 is in use by Wi-Fi`) (VERIFIED) → the pinky, palm and 7th sensor are
  still on ADC2 pins, which can't be read while the glove transmits.
- Flex spreads 38–99 counts; the fingers were barely moved (owner), so the resistor value
  could not be judged.

**Right glove** (MAC 38:3e:51:d1:c6:08, the same board as on 27 Oct)

- Boot now `boot:0x13` (VERIFIED): the IO12 strapping problem of 27 Oct (`boot:0x33`) is not
  there.
- With the MPU6050 connected: continuous `Brownout detector was triggered` resets, 119 in the
  pasted output (VERIFIED). With the MPU6050 unplugged: starts normally (`Last reset: power on`)
  (VERIFIED) → REASONED: the IMU board or its wiring overloads the 3.3 V supply (for example
  VCC/GND swapped or shorted).
- Without the IMU, the flex pins drift (J1 stays 0); whether the sensors were plugged in is not
  confirmed.
- After that, an erase/upload stopped at `Connecting...` with "No serial data received", and the
  monitor showed nothing even after EN. NOT RESOLVED (power, the USB chip or the board).

**Conclusion:** neither glove has the planned rework yet. Sent to the hardware assembler: the 6
usable flex pins (IO32–IO36, IO39; any finger order, tell us which), pinky and palm off
IO25/IO26, the MPU6050's power and SDA/SCL on IO21/IO22 (not IO12, 0, 2, 5, 15 or 34–39),
47 kΩ resistors, and the right glove's brownout with the IMU connected.
