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

**Before anything else, on the Pi itself**, confirm the serial port is set
up correctly (this is a one-time Pi configuration step, unrelated to our
code):
```bash
ls /dev/serial0
```

**If this says "No such file or directory," do this one-time fix:**
```bash
sudo raspi-config
```
Navigate to **Interface Options → Serial Port** → answer **No** to "login
shell over serial", **Yes** to "enable serial port hardware" → Finish.

Then edit the boot config:
```bash
sudo nano /boot/firmware/config.txt
```
Add this line at the end:
```
dtoverlay=disable-bt
```
Save (Ctrl+O, Enter, Ctrl+X), then disable two services and reboot:
```bash
sudo systemctl disable hciuart
sudo systemctl disable bluetooth
sudo reboot
```

After it reboots, run `ls /dev/serial0` again to confirm it now exists.
This step is only ever needed once per Pi — **why it's needed:** by
default, Bluetooth claims the Pi's good UART hardware, leaving only a
low-quality fallback on the GPIO pins that isn't reliable at the speed this
project needs. Disabling Bluetooth frees up the good one. If it still
doesn't appear after this, that's worth reporting back, since it would be
unusual.

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
python -m signyales_hub.main --port /dev/serial0 --model-dir model -v
```

Wear both gloves and perform a gesture. You should see `[gesture] <name>`
printed, and hear it spoken aloud through a connected speaker.

**Report back:** does it recognize anything at all, and does the spoken
output sound right?

---

## Quick summary to send back when you're done

Copy this and fill it in:

```
Stage 1 (compiles):          PASS / FAIL — [notes]
Stage 2 (left glove):        PASS / FAIL — [calibration numbers]
Stage 3 (right glove):       PASS / FAIL — [calibration numbers]
Stage 4 (receiver sees both): PASS / FAIL — [stats line]
Stage 5 (Pi UART wiring):    PASS / FAIL — [notes]
Stage 6 (hub app runs):      PASS / FAIL — [notes]
Stage 7 (full recognition):  PASS / FAIL / NOT APPLICABLE (no model yet)
```

## One general rule while testing

**Test one new thing at a time, in order.** If Stage 4 works but Stage 5
doesn't, the problem is specifically in the receiver-to-Pi wiring or Pi
configuration — the gloves and wireless link are already proven fine, so
there's no need to re-check those.
