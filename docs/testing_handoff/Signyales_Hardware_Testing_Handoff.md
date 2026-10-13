# Signyales — Hardware Testing Guide

You're being asked to test physical hardware for a Filipino Sign Language
translation glove system — two sensor gloves talk wirelessly to a receiver,
which forwards data to a Raspberry Pi that recognizes the gesture and speaks
it aloud. The software side has already been built and tested in
simulation; **what's needed from you is testing it on the real, physical
parts**, since that's the one thing that can't be verified remotely.

This guide is self-contained — you shouldn't need to ask the project owner
anything to get through it, except where it explicitly says to stop and
report back.

---

## What you'll need before starting

- [ ] The project repository (ask for the GitHub link or a zip file)
- [ ] [VSCode](https://code.visualstudio.com/) installed, plus its **PlatformIO IDE** extension (search for it in VSCode's Extensions panel)
- [ ] The assembled hardware: 2 gloves, 1 receiver dongle, 1 Raspberry Pi 5 — see `docs/Signyales_Hardware_Assembly_Guide.docx` in the repo for wiring diagrams if anything isn't assembled yet
- [ ] A USB cable for each ESP32 board (gloves + receiver) to connect to your computer
- [ ] Write down, before starting: which Raspberry Pi model you have (this project uses a Raspberry Pi 5; tell us if yours is different) and your PlatformIO version (`pio --version`)
- [ ] Basic comfort with a terminal — every step below has an exact command to type, so you don't need prior experience with this specific project

---

## Before you start, and what to watch for

**Safety first: do these before powering anything.**

- [ ] **Voltage dividers:** with a multimeter, check each flex sensor's divider output while relaxed and fully bent. It must stay within 0 to 3.3 V. The ESP32 pins are not 5 V tolerant, and one wiring mistake can damage a board.
- [ ] **Battery polarity:** confirm the LiPo's polarity matches your board's battery connector before plugging it in. A reversed battery can destroy the board.
- [ ] **UART wiring:** receiver TX goes to Pi RX and receiver RX to Pi TX (crossed), plus a shared ground, on the Pi's 3.3 V logic pins only: Pi pins 8 and 10, ground on pin 6. Straight-through wiring gives silence, not an error.
- [ ] **Pi 5 power and cooling:** use the 27 W USB-C supply and the active cooler. A throttling Pi can look like a software fault.
- [ ] **Battery safety:** if a battery swells, gets hot or smells, unplug it and stop testing. Report it.

**While testing, watch for:**

*Gloves*
- Calibration: each finger's printed min/max should span several hundred counts or more. A tiny spread means a dead or floating sensor. After calibration, that sensor shows up as wild noise rather than flat, so check the min/max at calibration time (Stage 2), not the live values later.
- A glove that was never calibrated uses placeholder bounds, so its values aren't trustworthy. Don't recalibrate in the middle of a recording session: it changes the value scale, and older recordings won't match newer ones.
- `MPU6050 not found` means the glove halts at startup. Check the IMU wiring and that AD0 is tied to ground.
- IMU values stuck flat at a maximum during fast movement mean the sensor range is saturating (accelerometer set to 4 g, gyro to 500 degrees per second). Report it.

*Wireless link*
- `ratio=0.0%` means that glove has never been heard. The most likely cause is a wrong `RECEIVER_MAC` (Stage 1b).
- Test with the gloves worn and the hands moving, not still on a bench: motion and the body can expose problems a bench test hides.
- The receiver's `[stats]` ratio is cumulative since boot and freezes when a glove goes silent. Use `live_view.py` for cutoff times, and power-cycle between range trials.
- Keep the receiver and Pi in one fixed spot, and note where you tested. Other 2.4 GHz devices (Wi-Fi, Bluetooth) can change range results.

*Raspberry Pi*
- Use `/dev/ttyAMA0`, not `/dev/serial0`, and confirm it with the loopback test (Stage 5) first.
- Baud must be 460800 on both ends. Only one program can read the UART at a time.
- With no model loaded, the main app prints nothing per frame. Use `live_view.py` to see data. A frame rate far below about 50 Hz means drops or stalls.

*Data quality (matters before training)*
- Move only one hand and confirm only that side's values change.
- Repeats of the same gesture should cluster closely (Stage 7b and 7c).
- Calibration should survive a power cycle (Stage 7c).

**How to record what you see**

- Copy raw numbers and pasted output into the log form, not summaries.
- Record the repo version (`git rev-parse --short HEAD`), the Pi model, and the PlatformIO version.
- If anything looks wrong, stop and report the exact output instead of editing firmware yourself.

---

## Testing proceeds in these stages (1 to 9, including 1b, 7b and 7c), in this exact order

Do not skip ahead — each stage assumes the previous one already works. If a
later stage fails, the most likely cause is something in an earlier stage
that looked fine but wasn't.

### Stage 1 — Confirm the code compiles (no hardware needed yet)

Open the repo folder in VSCode. In a PlatformIO terminal:

(ctrl + shit + P : search PlatformIO)

```bash
cd firmware/glove
pio run -e left_glove
pio run -e right_glove
cd ../receiver
pio run
```

**Expected result:** Each command ends with `[SUCCESS]`. If you see a
compile error instead, **stop here and report the exact error text back** —
don't try to fix firmware code yourself unless asked to.

---

### Stage 1b — Set the receiver's MAC address (REQUIRED before Stage 2)

`firmware/glove/src/config.h` ships with a placeholder
(`RECEIVER_MAC = AA:BB:CC:DD:EE:FF`). Until it is replaced with your real
receiver's address, the gloves transmit to nowhere and every glove will
show `ratio=0.0%` in Stage 4. Do this first:

1. Plug in **only the receiver ESP32** and flash the utility:
   ```bash
   cd firmware/tools/get_mac_address
   pio run -t upload
   pio device monitor
   ```
2. It prints a line like `MAC Address: AA:BB:CC:DD:EE:FF` (yours will differ). Copy it.
3. Open `firmware/glove/src/config.h` and change the `RECEIVER_MAC` line,
   one `0x..` per byte, for example `AA:BB:CC:11:22:33` becomes:
   ```
   static uint8_t RECEIVER_MAC[6] = {0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33};
   ```
4. Save, then continue to Stage 2 (both gloves will be flashed with the new
   address). The real receiver firmware replaces this utility in Stage 4.

**Report back:** the MAC address you read.

---

### Stage 2 — Flash and test one glove in isolation

```bash
cd firmware/glove
pio run -e left_glove -t upload
pio device monitor
```

(If `upload` fails asking you to specify a port, connect only one board at
a time to avoid ambiguity, or add `--upload-port` — VSCode's PlatformIO
sidebar also lets you pick the port visually if the command line is
fiddly.)

**Expected result in the serial monitor:**
```
Signyales glove firmware starting. This unit: LEFT
Setup complete. Streaming...
```

**If instead you see `FATAL: MPU6050 not found`:** this means the IMU
sensor isn't wired correctly — check its connections against the wiring
diagram in the Hardware Assembly Guide before assuming it's a software
problem.

**Now calibrate it.** With the serial monitor still open, type `c` and
press Enter. Flex and relax all 5 fingers repeatedly for 8 seconds. You'll
see output like:

```
Finger 0: min=800 max=3200
Finger 1: min=750 max=3100
...
```

**Report back:** the full min/max line for all 5 fingers. A healthy
reading has a spread of at least several hundred between min and max. If
any finger shows numbers very close together (e.g., `min=2040 max=2055`),
note which finger — that sensor likely isn't wired correctly.

---

### Stage 3 — Repeat for the second glove

Same as Stage 2, but:
```bash
pio run -e right_glove -t upload
```
and confirm it prints `This unit: RIGHT` instead of `LEFT`.

---

### Stage 4 — Flash the receiver and confirm it sees both gloves

```bash
cd ../receiver
pio run -t upload
pio device monitor
```

Power on both gloves (they don't need to stay connected to a computer —
just powered, via battery or USB). Within a few seconds, you should see a
line like this print once per second:

```
[stats] frames=150 | left: ratio=98.7% dropped=2 corrupt=0 | right: ratio=99.3% dropped=1 corrupt=0
```

**Report back:** a few of these stats lines, copy-pasted exactly.

**If one side stays at `ratio=0.0%`:** that glove is not reaching the
receiver. First re-check Stage 1b: the address in `config.h` must exactly
match the receiver's, and **both** gloves must have been flashed *after*
it was changed. If you edit `config.h` now, re-flash both gloves and then
re-flash the real receiver firmware (`cd firmware/receiver`, `pio run -t upload`).
If it still stays at 0%, report the stats lines and the MAC you used.

---

### Stage 5 — Connect the receiver to the Raspberry Pi

This requires physically wiring 3 wires between the receiver and the Pi's
GPIO header (TX, RX — crossed — and GND). See the wiring diagram in the
Hardware Assembly Guide for exact pins.

**Important, Pi 5-specific: do not trust `/dev/serial0` here.** On earlier
Raspberry Pi models, `/dev/serial0` pointed to the GPIO header UART. On the
**Pi 5 specifically**, `/dev/serial0` instead points to a separate 3-pin
debug connector that isn't what we've wired — checking for it will give a
misleading "it exists" result that has nothing to do with the receiver
connection. Use the loopback test below instead of trusting any file
existence check.

**Step 1 — see what's actually there:**
```bash
ls -l /dev/serial* /dev/ttyAMA*
```
Report this output exactly, whatever it shows.

**Step 2 — enable the header UART:**
```bash
sudo raspi-config
```
Interface Options → Serial Port → **No** to login shell over serial,
**Yes** to serial hardware → Finish. Then:
```bash
sudo nano /boot/firmware/config.txt
```
Add this line at the end, save (Ctrl+O, Enter, Ctrl+X):
```
dtparam=uart0=on
```
```bash
sudo reboot
```

**Step 3 — loopback test (receiver NOT connected yet).** Use a single
jumper wire to connect GPIO14 (pin 8) directly to GPIO15 (pin 10) — this
makes the Pi talk to itself so we can test the port in isolation, before
any receiver wiring could confuse the result. In the `pi-side` venv (if it doesn't exist yet, create it first with the
four commands at the start of Stage 6, then come back here):
```bash
python3 -c "import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); s.write(b'hello'); time.sleep(0.2); print(s.read(5))"
```
**Expected output:** `b'hello'`. Then **remove the jumper wire**.

- **If you got `b'hello'`:** `/dev/ttyAMA0` is the correct port. Wire the
  receiver as shown in the Hardware Assembly Guide (receiver TX → Pi RX,
  receiver RX → Pi TX, GND → GND), and use `--port /dev/ttyAMA0` (not
  `/dev/serial0`) in every command for the rest of this guide.
- **If the device doesn't exist, or it printed `b''`:** stop and report
  the Step 1 output plus the exact error. As a fallback ONLY after
  reporting that, you can try adding `dtoverlay=disable-bt` to the same
  config.txt and rebooting, then repeat the loopback test.

---

### Stage 6 — Run the Pi-side software

On the Raspberry Pi itself (not your laptop):

```bash
cd pi-side
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
sudo apt install espeak-ng
```

`espeak-ng` is what makes spoken output work (needed in Stage 7).
`requirements.txt` installs full `tensorflow`, which is large and may fail
on the Pi. No model exists yet, so it is not needed for Stages 5 to 7b: if
the install fails, report the error and run this instead:
```bash
pip install pyserial numpy pyttsx3 pyfiglet gpiozero lgpio
```
(The fallback is untested; the project's CI notes say the hub runs without
TensorFlow when no model is present.)

First, a test that needs no hardware at all, to confirm the software
itself is intact:
```bash
python tests/test_frame_roundtrip.py
```
**Expected:** `PASS: frame format round-trips correctly...`. If this fails,
report it immediately — it means something about the files you received is
different from what was tested, not a hardware problem.

Then, with the receiver wired up and both gloves powered on, **from `pi-side/`
with the venv active**, watch the live data for 30 seconds while you open and
close the fingers of both hands:
```bash
python tools/live_view.py --port /dev/ttyAMA0 --duration 30
```
It prints each hand's flex/accel/gyro values twice a second, then a summary
(frame rate, how often each hand's data was fresh, sequence gaps, and each
finger's min/max). If it prints `No frames for ...s`, the Pi is receiving
nothing: re-check Stage 5 (TX/RX crossed, port, baud).

**Report back:** the full summary printed at the end.

Then confirm the main app also starts:
```bash
python -m signyales_hub.main --port /dev/ttyAMA0 -v
```
With no model, this app prints **no per-frame output**. Seeing only the
"Opened serial link" line and a "No model loaded" warning is normal, and
silence does not mean the link is dead (that's why `live_view.py` exists).
Stop it with Ctrl+C. Report any error lines, in particular `Dropped a
corrupt/misframed payload`.

---

### Stage 7 — Full end-to-end test

This stage only works if a trained model file already exists in
`pi-side/model/model.tflite`. If that file isn't there, **stop and report
back** — this stage isn't testable yet and that's expected, not a failure
on your part.

If it is there:
```bash
python -m signyales_hub.main --port /dev/ttyAMA0 --model-dir model -v
```

Wear both gloves and perform a gesture. You should see `[gesture] <name>`
printed, and hear it spoken aloud through a connected speaker.

**Report back:** does it recognize anything at all, and does the spoken
output sound right?

---

### Stage 7b — Real-data sanity check

No trained model exists yet, so Stage 7 can't be fully tested. This
instead checks that real sensor data flows correctly into the data
collection tool, which the next phase of this project depends on — not
gesture accuracy, just that the data pipeline works with real hands
instead of synthetic data.

**Step 1.** On the Pi, from `pi-side/` with the venv active, run
`python tools/collect_gesture.py --help` and report the output.

**Step 2.** Record about 5 repetitions each of two very different hand
positions, plus a few seconds with the hands idle. Use `--out ../training/data`
(the tool's built-in default points to a folder that doesn't exist in this repo):
```bash
python tools/collect_gesture.py --label fist --reps 5 --port /dev/ttyAMA0 --out ../training/data
python tools/collect_gesture.py --label open --reps 5 --port /dev/ttyAMA0 --out ../training/data
python tools/collect_gesture.py --label idle --reps 3 --port /dev/ttyAMA0 --out ../training/data
```
Files are saved as `training/data/<label>/rep_0000.npz`, and so on. Don't
commit them to git: zip the `training/data` folder and send it instead.

**Step 3. Report:**
- Where the recorded files were saved
- Any errors encountered
- Whether both hands' data appears in the output
- Whether finger values clearly differ between the fist and open-hand
  positions. Run this from `pi-side/` and paste its full output:
  ```bash
  python tools/inspect_recordings.py --root ../training/data
  ```
  It lists per-finger averages for each gesture, how much repetitions of the
  same gesture vary, and flags a hand that never moved or channels that
  can't tell two gestures apart. It checks data consistency only.

---

### Stage 7c — Training-readiness checks (no model needed)

These confirm the hardware gives data that is safe to train on. Run from
`pi-side/` with the venv active, gloves and receiver powered and worn.

1. **Left/right alignment.** Run `python tools/live_view.py --port /dev/ttyAMA0 --duration 15`
   twice: once moving **only the left hand's** fingers, once moving **only
   the right hand's**. In each summary, only the moved hand should show a
   large spread. If the other hand also changes, or the wrong one does,
   the sides are swapped or crosstalking: stop and report.
2. **Repeatability.** In the `inspect_recordings.py` output from Stage 7b,
   the `std/reps` row (how much repetitions of one gesture differ) should
   be small compared with the difference between fist and open. Report the output.
3. **Calibration survives a power cycle.** Unplug and replug one glove
   (don't press `c`), run `python tools/live_view.py --port /dev/ttyAMA0 --duration 15`
   while flexing its fingers, and report whether the min/max are similar to
   Stage 2's. (The firmware says it saves calibration to flash; this checks it.)
4. **Longer run.** Run
   `python tools/live_view.py --port /dev/ttyAMA0 --duration 1800 --interval 60`
   (30 minutes, one line per minute). Report the final summary, especially
   the fresh-data percentages and sequence gaps, and anything that stalled.

---

### Stage 8 — Battery test

1. Fully charge both gloves. Note the battery type and capacity printed
   on it.
2. Start the receiver and both gloves. On the Pi, from `pi-side/` with the
   venv active, start the live viewer for up to 3 hours, one status line
   every 5 minutes:
   ```bash
   python tools/live_view.py --port /dev/ttyAMA0 --duration 10800 --interval 300
   ```
   Leave the gloves worn or held still. Don't run `main.py` at the same
   time: two programs can't both reliably read the same serial port.
3. Note the start time (the viewer prints `Started at HH:MM:SS`).
4. When a glove stops sending, the viewer prints a line such as
   `[14:05:22] LEFT glove: no fresh data since 14:05:20`. Record that time
   for each glove. **Don't use the receiver's `[stats]` ratio for this:** it
   freezes at its last value when a glove goes silent, it does not drop to 0%.
5. The run ends by itself after 3 hours. If a glove is still running then,
   report that rather than continuing indefinitely.

**Report:** battery details, start time, the cutoff time for each glove (the
`no fresh data` lines), and the viewer's final summary.

---

### Stage 9 — Range test

Keep the receiver and Pi in one fixed location. Use a tape measure.

**Important:** the `[stats]` ratio is cumulative since the glove and receiver
started (it is computed from sequence numbers), so lines taken in a row
during one hold are *not* independent trials, and anything transmitted
before you reached the spot is included. The proposal averages repeated
trials, so use this procedure:

1. Stand at the position, **then** power on both gloves and the receiver there.
2. Hold still for 30 seconds, then copy the latest `[stats]` line. That is one trial.
3. Power-cycle everything and repeat for **3 trials** per position.
4. Positions: 1 m, 3 m, 5 m, 10 m in clear line of sight. Then 5 m with a wall
   or door between you and the receiver, and 5 m with the receiver behind
   your own body.

(Power-cycling restarts the counters. This reasoning comes from reading the
receiver code, not from running it on hardware.)

**Optional, if a second USB cable is available:**
`python tools/receiver_link_logger.py --port <receiver USB port> --duration 60 --out results/range_<distance>m_run<n>.csv`
(run from `pi-side/`) logs the stats line to a CSV for later averaging. This
tool has not been tested against real hardware.

**Limitation:** the `[stats]` ratio only counts a packet as dropped when a
*later* packet arrives and reveals the gap. Packets lost at the very end of
a hold (for instance a glove sliding out of range) are never counted, so at
the edge of range the ratio can overstate delivery. If the Pi is reachable
at the same time, you can also run
`python tools/live_view.py --port /dev/ttyAMA0 --duration 40` during each
trial (receiver USB on the laptop, UART on the Pi, so both work together).
Its `fresh in X%` means a packet arrived within the receiver's 30 ms window,
which is a different measure from `[stats]`, so report both and label each.
Start it first, then power on the gloves: the seconds before they connect
count as not fresh.

**Report:** the `[stats]` line for every trial (3 per position), plus the
viewer's `fresh in` percentages if you ran it.

---

## Quick summary to send back when you're done

Copy this and fill it in:

```
Stage 1 (compiles):          PASS / FAIL — [notes]
Stage 1b (MAC address):      DONE — [address read]
Stage 2 (left glove):        PASS / FAIL — [calibration numbers]
Stage 3 (right glove):       PASS / FAIL — [calibration numbers]
Stage 4 (receiver sees both): PASS / FAIL — [stats line]
Stage 5 (Pi UART wiring):    PASS / FAIL — [ls output / loopback result / port used]
Stage 6 (hub app runs):      PASS / FAIL — [notes]
Stage 7 (full recognition):  PASS / FAIL / NOT APPLICABLE (no model yet)
Stage 7b (real data):        PASS / FAIL — [notes]
Stage 7c (readiness checks): alignment OK/NOT OK | repeatability notes | calibration kept after power cycle Y/N | 30-min run summary
Stage 8 (battery):           left ___ min, right ___ min (or still running at 3h)
Stage 9 (range, 3 trials each): 1m ___ | 3m ___ | 5m ___ | 10m ___ | wall ___ | body ___
Pi model / PlatformIO version / repo commit: ___ / ___ / ___
```

## One general rule while testing

**Test one new thing at a time, in order.** If Stage 4 works but Stage 5
doesn't, the problem is specifically in the receiver-to-Pi wiring or Pi
configuration — the gloves and wireless link are already proven fine, so
there's no need to re-check those.
