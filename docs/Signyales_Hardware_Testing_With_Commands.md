# Signyales — Hardware Testing: Step by Step with Commands

> **Older guide (13 Oct 2026), kept for reference.** For hardware testing, use
> `docs/testing_handoff/Signyales_Hardware_Testing_Handoff.md` at tag `handoff-4`.
> This page has no Stage 6b (subtitle and speaker check) and no GUI, and may be
> out of date in other places. Changes since it was written (29 Oct 2026):
> gloves use the original ESP32 with **6 flex sensors** (5 fingers + palm) and
> the IMU on IO21/IO22; the receiver connects to the Pi with **one USB data
> cable** by default (UART wires are an option, chosen in the app's Active
> mode), so the Pi commands below no longer need `--port`.

This is the complete process for connecting the real hardware to the real
code and verifying each stage works, in order. Every command is exact —
copy-paste ready for a Windows PowerShell terminal inside VSCode. If
you're on Mac/Linux, swap backslashes for forward slashes in paths and use
`source venv/bin/activate` instead of the `.ps1` activation line.

**Before starting:** the firmware you have already includes the ESP-NOW
callback fix from earlier testing — you should not hit that specific
compile error again. If you do, something about your files has reverted;
stop and flag it rather than re-debugging from scratch.

---

## Part 1 — Wiring

Wire both gloves and the receiver-to-Pi connection exactly as shown in
`docs/Signyales_Hardware_Assembly_Guide.docx` (two diagrams: glove wiring,
receiver↔Pi wiring). Do not power anything on yet — finish wiring first.

---

## Part 2 — Get the receiver's real MAC address

The gloves need to know the receiver's hardware address before they can
talk to it. This is the one file edit that's mandatory before anything
else will work.

**1. Flash the MAC address utility onto the receiver board:**
```powershell
cd firmware\tools\get_mac_address
pio run -t upload
pio device monitor
```

**Expected output:**
```
MAC Address: AA:BB:CC:DD:EE:FF
```

**2. Copy that address.** Press `Ctrl+C` to close the serial monitor once you have it.

---

## Part 3 — Put the real MAC address into the glove firmware

Open `firmware\glove\src\config.h` in VSCode. Find this line:
```c
static uint8_t RECEIVER_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};
```
Replace the placeholder bytes with your receiver's real address (keep the
`0x` prefix on each byte, comma-separated, exactly like the format shown).
Save the file.

---

## Part 4 — Flash both gloves

```powershell
cd ..\..\glove
pio run -e left_glove -t upload
pio device monitor
```

**Expected output:**
```
Signyales glove firmware starting. This unit: LEFT
Setup complete. Streaming...
```

**Calibrate it** — with the serial monitor still open, type `c` and press
Enter. Flex and relax all 5 fingers and the palm for 8 seconds. Confirm you
see 6 lines like `Sensor 0 (thumb): min=800 max=3200` with a real spread between min and max
(not numbers close together). Press `Ctrl+C` to close the monitor.

**Repeat for the right glove:**
```powershell
pio run -e right_glove -t upload
pio device monitor
```
Confirm it prints `This unit: RIGHT`, then calibrate the same way.

---

## Part 5 — Flash the real receiver firmware

This overwrites the MAC-address utility from Part 2 — same physical board,
different program now.

```powershell
cd ..\receiver
pio run -t upload
pio device monitor
```

**Expected output** — power both gloves on (battery or USB) and watch for
a line printing once per second:
```
[stats] frames=150 | left: ratio=98.7% dropped=2 corrupt=0 | right: ratio=99.3% dropped=1 corrupt=0
```

**This confirms the wireless link genuinely works.** Both ratios should
climb toward 100%. If one stays at `0.0%`, the MAC address in that glove's
`config.h` doesn't match — go back to Part 3 for that glove specifically.

Leave this monitor open or press `Ctrl+C` — either is fine, the receiver
keeps running on its own either way.

---

## Part 6 — Connect the receiver to the Raspberry Pi

**Default (since 29 Oct 2026): one USB data cable** from the receiver to a
Pi USB port. Nothing else to set up; skip to Part 7 and the live check
(`python tools/live_view.py --duration 10`, about 50 Hz).

**Option: UART wires.** Connect the 3 UART wires (crossed TX/RX + shared
GND) per the wiring diagram, choose "UART wires" in the app (Active mode),
and do the rest of this part.

**Pi 5-specific — do not trust `/dev/serial0`.** Unlike earlier Pi models,
the Pi 5's `/dev/serial0` points to a separate 3-pin debug connector, not
the GPIO14/15 pins we're wiring to. A file-existence check here gives a
misleading result. Use a real loopback test instead.

**On the Pi itself** (not your laptop), see what's actually there first:
```bash
ls -l /dev/serial* /dev/ttyAMA*
```

**One-time setup:**
```bash
sudo raspi-config
```
→ Interface Options → Serial Port → "login shell over serial": **No** →
"enable serial port hardware": **Yes** → Finish.
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

**Loopback test (receiver NOT wired in yet)** — jumper GPIO14 (pin 8)
directly to GPIO15 (pin 10), then in the `pi-side` venv:
```bash
python3 -c "import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); s.write(b'hello'); time.sleep(0.2); print(s.read(5))"
```
Expect `b'hello'`. **Remove the jumper** once confirmed, then wire the
receiver for real. The UART option uses `/dev/ttyAMA0` (not `/dev/serial0`);
add `--link uart` to a command to force it.

If the test printed `b''` or the device didn't exist: try adding
`dtoverlay=disable-bt` to the same config.txt and reboot, then repeat the
loopback test — sources disagree on whether Pi 5 needs this the same way
Pi 3/4 did, so treat it as a fallback to try, not an assumed requirement.

---

## Part 7 — Set up the Pi-side Python environment

**On the Pi:**
```bash
cd pi-side
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Part 8 — Sanity check before trusting real hardware

Run this first — it needs zero hardware and confirms the Python code
itself is intact before you try to debug anything live:
```bash
python tests/test_frame_roundtrip.py
```
**Expected:**
```
PASS: frame format round-trips correctly and checksum validation works.
```
If this fails, stop — something about the files is wrong, and no amount
of hardware troubleshooting will fix a software problem.

---

## Part 9 — Run against the real, wired-up hardware

First, confirm data is actually arriving. From `pi-side/`, with the venv
active and both gloves and the receiver powered:

```bash
python tools/live_view.py --duration 30
```

**Expected:** a line of values for each hand twice a second, a frame rate
near 50 Hz, and a summary at the end. Move your fingers and the numbers
should change.

**If it prints `No frames for ...s` or `No receiver found on USB`:** nothing
is reaching the Pi. On USB: a charge-only cable, or old receiver firmware
(re-flash it). On UART: almost always the wiring — double check TX/RX are
actually crossed (receiver TX → Pi RX, receiver RX → Pi TX), not wired
straight-through.

Then confirm the main app starts:

```bash
python -m signyales_hub.main -v
```

**Expected:** a couple of startup lines ("Opened serial link…") and a
warning that no model is loaded — that is correct at this stage. With no
model the app prints **nothing per frame**, so silence after those lines
does not mean the link is dead (that is what `live_view.py` is for). Any
`Dropped a corrupt/misframed payload` lines are worth reporting.

Press `Ctrl+C` to stop.

---

## Part 10 — Once a trained model exists (later milestone)

This part only applies after you've collected real gesture data and
trained a model — not yet, but documented here so you have it when ready.

```bash
python -m signyales_hub.main --model-dir model -v
```
Wear both gloves, perform a known gesture, confirm `[gesture] <name>`
prints and is spoken aloud.

For formal accuracy testing across many gestures at once, instead of
checking one at a time by hand:
```bash
python tools/accuracy_logger.py --gestures kumusta salamat oo --trials 10 --model-dir model --out results/run1
```

---

## Quick reference: what "success" looks like at each stage

| Part | Command | Success looks like |
|---|---|---|
| 2 | `pio run -t upload` + monitor | A MAC address prints |
| 4 | `pio run -e left_glove -t upload` | `Setup complete. Streaming...` |
| 4 | Calibration (`c`) | 6 sensor lines (5 fingers + palm), real min/max spread |
| 5 | Receiver flash + both gloves on | `[stats]` line, ratios near 100% |
| 6 | USB: `live_view.py --duration 10` (UART option: loopback on `/dev/ttyAMA0`) | About 50 Hz (loopback: prints `b'hello'`) |
| 8 | `test_frame_roundtrip.py` | `PASS` |
| 9 | `main.py -v` with real hardware | Continuous clean log output |
