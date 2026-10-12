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
- [ ] Basic comfort with a terminal — every step below has an exact command to type, so you don't need prior experience with this specific project

---

## Testing proceeds in 7 stages, in this exact order

Do not skip ahead — each stage assumes the previous one already works. If a
later stage fails, the most likely cause is something in an earlier stage
that looked fine but wasn't.

### Stage 1 — Confirm the code compiles (no hardware needed yet)

Open the repo folder in VSCode. In the terminal:

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

**If one side stays at `ratio=0.0%`:** that glove doesn't know the
receiver's address yet. You'll need to:
1. Temporarily flash `firmware/tools/get_mac_address` onto the receiver instead
2. Open its serial monitor — it prints a MAC address like `AA:BB:CC:DD:EE:FF`
3. Report that address back, or if you're comfortable editing code: open `firmware/glove/src/config.h`, find `RECEIVER_MAC`, update it to match, and re-flash **both** gloves
4. Re-flash the real receiver firmware back on afterward (Stage 4's first command)

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
any receiver wiring could confuse the result. In the `pi-side` venv:
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
```

First, a test that needs no hardware at all, to confirm the software
itself is intact:
```bash
python tests/test_frame_roundtrip.py
```
**Expected:** `PASS: frame format round-trips correctly...`. If this fails,
report it immediately — it means something about the files you received is
different from what was tested, not a hardware problem.

Then, with the receiver wired up and both gloves powered on:
```bash
python -m signyales_hub.main -v
```

**Report back:** whether you see continuous activity with no errors, or if
it hangs with no output at all (which usually means the wiring in Stage 5
isn't right — double check it's crossed correctly, not straight-through).

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

**Step 1.** Run this and report the output:
```bash
python tools/collect_gesture.py --help
```

**Step 2.** Using those options, record about 5 repetitions each of two
very different hand positions (for example, a closed fist and an open
hand), plus a few seconds with the hands idle.

**Step 3. Report:**
- Where the recorded files were saved
- Any errors encountered
- Whether both hands' data appears in the output
- Whether finger values clearly differ between the fist and open-hand
  positions (a sanity check that the sensors are actually responding to
  real hand movement, not just producing noise)

---

### Stage 8 — Battery test

1. Fully charge both gloves. Note the battery type and capacity printed
   on it.
2. Start both gloves, the receiver, and the Pi hub together, and leave
   them running continuously with the gloves worn or held still.
3. Note the start time. Check the receiver's `[stats]` line every 15
   minutes.
4. Record the time each glove stops transmitting (its delivery ratio
   drops to 0%).
5. If a glove is still running after 3 hours, stop there and report that
   rather than continuing indefinitely.

**Report:** battery details, start time, and the cutoff time for each
glove.

---

### Stage 9 — Range test

Keep the receiver and Pi in one fixed location. Use a tape measure.

1. With both gloves powered on, stand at 1 m, 3 m, 5 m, and 10 m in clear
   line of sight of the receiver.
2. At each distance, hold position for about 30 seconds and copy down the
   `[stats]` line.
3. Repeat once at 5 m with a wall or door between you and the receiver,
   and once more with the receiver positioned behind your own body.

**Report:** the `[stats]` line for each of the positions above.

---

## Quick summary to send back when you're done

Copy this and fill it in:

```
Stage 1 (compiles):          PASS / FAIL — [notes]
Stage 2 (left glove):        PASS / FAIL — [calibration numbers]
Stage 3 (right glove):       PASS / FAIL — [calibration numbers]
Stage 4 (receiver sees both): PASS / FAIL — [stats line]
Stage 5 (Pi UART wiring):    PASS / FAIL — [ls output / loopback result / port used]
Stage 6 (hub app runs):      PASS / FAIL — [notes]
Stage 7 (full recognition):  PASS / FAIL / NOT APPLICABLE (no model yet)
Stage 7b (real data):        PASS / FAIL — [notes]
Stage 8 (battery):           left ___ min, right ___ min (or still running at 3h)
Stage 9 (range):             1m ___ | 3m ___ | 5m ___ | 10m ___ | obstructed ___
```

## One general rule while testing

**Test one new thing at a time, in order.** If Stage 4 works but Stage 5
doesn't, the problem is specifically in the receiver-to-Pi wiring or Pi
configuration — the gloves and wireless link are already proven fine, so
there's no need to re-check those.
