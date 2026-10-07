# Signyales — Hardware Testing: Step by Step with Commands

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
Enter. Flex and relax all 5 fingers for 8 seconds. Confirm you see 5 lines
like `Finger 0: min=800 max=3200` with a real spread between min and max
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

## Part 6 — Wire the receiver to the Raspberry Pi

Connect the 3 UART wires (crossed TX/RX + shared GND) per the wiring
diagram. Then, **on the Pi itself** (not your laptop), confirm the serial
port exists:

```bash
ls /dev/serial0
```

**If that says "No such file or directory"**, run this one-time setup:
```bash
sudo raspi-config
```
→ Interface Options → Serial Port → "login shell over serial": **No** →
"enable serial port hardware": **Yes** → Finish.

Then:
```bash
sudo nano /boot/firmware/config.txt
```
Add this line at the end, save (Ctrl+O, Enter, Ctrl+X):
```
dtoverlay=disable-bt
```
```bash
sudo systemctl disable hciuart
sudo systemctl disable bluetooth
sudo reboot
```
After it reboots, run `ls /dev/serial0` again to confirm it now exists.
This whole step is only ever needed once per Pi.

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

```bash
python -m signyales_hub.main --port /dev/serial0 --baud 460800 -v
```

**Expected:** continuous log output with no errors, no long silences, and
no crashes. You'll see a warning that no model is loaded — that's correct
and expected at this stage, since you haven't trained one yet.

**If it hangs with zero output:** almost always the UART wiring — double
check TX/RX are actually crossed (receiver TX → Pi RX, receiver RX → Pi
TX), not wired straight-through.

Press `Ctrl+C` to stop.

---

## Part 10 — Once a trained model exists (later milestone)

This part only applies after you've collected real gesture data and
trained a model — not yet, but documented here so you have it when ready.

```bash
python -m signyales_hub.main --port /dev/serial0 --model-dir model -v
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
| 4 | Calibration (`c`) | 5 finger lines, real min/max spread |
| 5 | Receiver flash + both gloves on | `[stats]` line, ratios near 100% |
| 6 | `ls /dev/serial0` on the Pi | File exists, no error |
| 8 | `test_frame_roundtrip.py` | `PASS` |
| 9 | `main.py -v` with real hardware | Continuous clean log output |
