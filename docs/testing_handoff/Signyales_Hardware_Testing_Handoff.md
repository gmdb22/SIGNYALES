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

The guide has two halves, done in order:

1. **Parts A to C: setup and software checks (no gloves needed).**
   Part A sets up the Raspberry Pi 5, Part B sets up VS Code on your laptop,
   and Part C checks that the software runs on both.
2. **Stages 1 to 9: hardware tests**, from compiling the firmware to the range test.

Every command says where to type it:
- **LAPTOP**: Windows PowerShell, in VS Code's terminal.
- **PI**: the Raspberry Pi's terminal (bash).

It also says which folder to be in.

---

## What you'll need before starting

**For the Raspberry Pi (Part A)**
- [ ] A Raspberry Pi 5, its official 27 W USB-C power supply, and the active cooler. An underpowered or overheating Pi slows itself down, which can look like a software fault.
- [ ] A microSD card (32 GB or larger), and a card reader for your laptop if it has no SD slot
- [ ] A monitor, a micro-HDMI to HDMI cable (the Pi 5 only has micro-HDMI ports), and a USB keyboard and mouse
- [ ] Internet for the Pi during setup (Wi-Fi, or an Ethernet cable). It's only needed for the downloads in Part A.
- [ ] A speaker for the Pi, for Stage 6b. A USB speaker is easiest: the Raspberry Pi 5 has **no 3.5 mm audio jack**, so a plug-in speaker needs a USB sound adapter, or use a monitor with speakers over HDMI

**For the laptop (Part B)**
- [ ] A Windows laptop with internet, where you're allowed to install programs
- [ ] A USB **data** cable for each ESP32 board (2 gloves and the receiver). Some cables only charge and won't work.

**Hardware and access**
- [ ] The assembled hardware: 2 gloves, 1 receiver dongle — see `docs/Signyales_Hardware_Assembly_Guide.docx` in the repo for wiring diagrams if anything isn't assembled yet
- [ ] Access to the repository `https://github.com/gmdb22/SIGNYALES`, and the tester addendum with the commit hash to expect. If `git clone` asks you to log in, ask the project owner for access.
- [ ] Basic comfort with a terminal — every step below has an exact command to type, so you don't need prior experience with this specific project

---

## Part A — Set up the Raspberry Pi 5

These are the standard Raspberry Pi setup steps. They haven't been done on
this project's Pi yet, so if a screen or menu looks different, pick the
closest choice and write down what you saw.

**A1. Put Raspberry Pi OS on the microSD card (LAPTOP).**
1. Install **Raspberry Pi Imager** from https://www.raspberrypi.com/software/
   and open it. Put the microSD card in the laptop.
2. Choose the device **Raspberry Pi 5**, the operating system
   **Raspberry Pi OS (64-bit)** (the recommended one, with the desktop), and
   your microSD card as the storage. Double-check the storage choice:
   everything on that card is erased.
3. When Imager offers to customise the settings, set:
   - hostname: `signyales`
   - a username and password (write them down)
   - your Wi-Fi name, password and country (skip this if you'll use Ethernet)
   - your time zone and keyboard layout
   - optional: turn on **SSH** with password login, so you can type Pi
     commands from your laptop (see A8)
4. Write the card, wait until it has finished verifying, then take it out.

**A2. First start.**
1. Put the card in the Pi. Connect the monitor (either micro-HDMI port),
   keyboard, mouse, the speaker, and Ethernet if you use it. Plug in the
   27 W power supply last.
2. The first start takes a few minutes and may restart once by itself. Log
   in with the username you set.
3. Open a terminal (the terminal icon in the top bar, or Ctrl+Alt+T).

To turn the Pi off at any point, run `sudo shutdown now` and wait for the
green light to stop flashing before unplugging. Pulling the power while it
runs can damage the card.

**A3. Install git, venv, Tk and espeak-ng on the Pi (PI, any folder).**

These are installed **on the Pi itself**: type the commands into the Pi's
terminal, not the laptop's. The Pi needs internet for this step.

1. Check the Pi is online:
   ```bash
   ping -c 3 raspberrypi.com
   ```
   You should see three lines containing `time=`. If it says
   `Temporary failure in name resolution` or `Network is unreachable`,
   connect to Wi-Fi (the network icon in the top bar) or plug in Ethernet,
   then try again.
2. Update the Pi. This takes a few minutes. `sudo` asks for the Pi's
   password; nothing appears while you type it, which is normal.
   ```bash
   sudo apt update
   sudo apt full-upgrade -y
   ```
3. Install the four packages with one command:
   ```bash
   sudo apt install -y git python3-venv python3-tk espeak-ng
   ```

   | Package | What it's for |
   |---|---|
   | `git` | Downloads the project code (A5) |
   | `python3-venv` | Makes the Python environment (A6) |
   | `python3-tk` | Windows for the optional Signyales app (GUI) |
   | `espeak-ng` | The voice for spoken output (Stages 6b and 7) |

   Some may already be on the Pi. `is already the newest version` is fine.
4. Restart, then open a terminal again:
   ```bash
   sudo reboot
   ```
5. Check all four are installed:
   ```bash
   git --version
   python3 -m venv --help | head -n 1
   python3 -c "import tkinter; print('Tk', tkinter.TkVersion)"
   espeak-ng --version
   ```
   Expect, in order: `git version ...`, `usage: venv ...`, `Tk 8.6` (or
   another number), and `eSpeak NG text-to-speech: ...`. A
   `command not found` or `ModuleNotFoundError` means that package didn't
   install: run step 3 again and report the error if it repeats.

If any `apt` command fails, copy the full error into your report.

**A4. Write down the Pi's versions (PI, any folder).**
```bash
cat /proc/device-tree/model; echo
grep PRETTY_NAME /etc/os-release
python3 --version
```
The first line should say `Raspberry Pi 5`. If it says something else, tell
the project owner. The Pi's Python packages were written for Raspberry Pi
OS "Bookworm" with Python 3.11 and have never been installed on a real Pi,
so these versions matter if anything fails later.

**A5. Get the code (PI, home folder).**
```bash
cd ~
git clone https://github.com/gmdb22/SIGNYALES.git
cd SIGNYALES
git checkout handoff-4
git --no-pager log -1 --oneline
```
A "detached HEAD" message is normal. The last line must start with the
commit hash in the tester addendum. If it doesn't, stop and report. Put that
line in every report. From now on, `~/SIGNYALES` is the repo on the Pi.

Already have a copy from an earlier handoff? Run `cd ~/SIGNYALES`, then
`git fetch --tags --force`, then `git checkout handoff-4`, then the `log`
line above.

**A6. Make the Python environment and install the packages (PI, folder `~/SIGNYALES/pi-side`).**
```bash
cd ~/SIGNYALES/pi-side
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```
The prompt now starts with `(venv)`. Whenever this guide says **"venv
active"**, it means: open a terminal, then run
```bash
cd ~/SIGNYALES/pi-side
source venv/bin/activate
```

`requirements.txt` installs full `tensorflow`, which is large and may fail
on the Pi. No model exists yet, so it isn't needed before Stage 7. If the
install fails, copy the error into your report, then run this instead:
```bash
pip install pyserial numpy pyttsx3 pyfiglet gpiozero lgpio
```
(The fallback is untested; the project's CI notes say the hub runs without
TensorFlow when no model is present.)

**A7. Choose the speaker and test it (PI, any folder).** Plug the speaker
into the Pi, then use either method:

- **On the desktop:** right-click the speaker (volume) icon in the top bar
  and pick your speaker as the audio output, then left-click it and set the
  volume to about three-quarters.
- **With commands** (in the Pi's own terminal, not over SSH):
  ```bash
  wpctl status
  ```
  Under **Audio**, the **Sinks** list shows each output with a number; the
  current one has a `*`. Make your speaker the default and set the volume,
  replacing `47` with your speaker's number:
  ```bash
  wpctl set-default 47
  wpctl set-volume @DEFAULT_AUDIO_SINK@ 75%
  ```
  If `wpctl` is not found, use the desktop method.

Then test it:
```bash
espeak-ng "Signyales speaker test"
```
If you hear nothing, report the `wpctl status` output. Stage 6b checks the
speaker and subtitles fully.

**A8. Optional: type Pi commands from your laptop (SSH).** Only if you
turned on SSH in A1. In PowerShell on the laptop:
```powershell
ssh <your Pi username>@signyales.local
```
If `signyales.local` isn't found, run `hostname -I` on the Pi and use the
first address it prints instead. Commands typed in that window run on the
Pi. Two things still need the Pi's own monitor: the subtitles in Stage 6b
(over SSH they appear in the SSH window instead) and the optional GUI.

**Report (Part A):** the three lines from A4, the `log` line from A5, and
whether `pip install -r requirements.txt` worked. If it didn't, include the
error and whether the fallback worked.

---

## Part B — Set up VS Code on your laptop

These steps match the project owner's Windows laptop, where the software
was tested with Python 3.13. Other setups haven't been tried.

**B1. Install Git, Python 3.13 and VS Code (LAPTOP).** Use either method.

*With commands* (PowerShell; `winget` is built into Windows 10 and 11):
```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.13
winget install -e --id Microsoft.VisualStudioCode
```

*From the websites* (the default options are fine unless noted):
1. **Git for Windows**: https://git-scm.com/download/win
2. **Python 3.13**, 64-bit, from https://www.python.org/downloads/windows/.
   On the first installer screen, tick **"Add python.exe to PATH"**.
3. **VS Code**: https://code.visualstudio.com/

Use Python 3.13 even if a newer version is offered: TensorFlow may not
support the newest Python yet.

Then restart the laptop (or at least close every PowerShell and VS Code
window), open PowerShell again and check:
```powershell
git --version
py -3.13 --version
code --version
```
Each should print a version number. (`py` is the Python launcher that comes
with Python.)

**B2. Add the VS Code extensions (LAPTOP, PowerShell).**
```powershell
code --install-extension platformio.platformio-ide
code --install-extension ms-python.python
```
Or, in VS Code, open the Extensions panel (Ctrl+Shift+X) and install
**PlatformIO IDE** (publisher: PlatformIO) and **Python** (publisher:
Microsoft).

Then open VS Code. The first time, PlatformIO finishes installing itself in
the background; watch the bottom-right corner, and restart VS Code when it
asks.

**B3. Get the code (LAPTOP, VS Code terminal).** Open a terminal with
Terminal → New Terminal (it's PowerShell). This example keeps the repo in
Documents:
```powershell
cd $HOME\Documents
git clone https://github.com/gmdb22/SIGNYALES.git
cd SIGNYALES
git checkout handoff-4
git --no-pager log -1 --oneline
```
The last line must match the Pi's (A5). Already have a copy? Use the same
`fetch` and `checkout` steps as in A5.

Then choose File → Open Folder and pick the `SIGNYALES` folder. If VS Code
asks whether you trust the authors, choose **Yes**. From now on,
**"repo root"** on the laptop means this folder.

**B4. Make the laptop's Python environment (LAPTOP, VS Code terminal, folder: repo root).**
```powershell
py -3.13 -m venv pi-side\venv
pi-side\venv\Scripts\python.exe -m pip install --upgrade pip
pi-side\venv\Scripts\python.exe -m pip install -r pi-side\requirements.txt scikit-learn
pi-side\venv\Scripts\python.exe --version
```
This downloads TensorFlow and can take several minutes. The commands call
the environment's Python directly, so there's no "activate" step (which
PowerShell sometimes blocks). If VS Code asks which Python interpreter to
use, choose the one in `pi-side\venv`.

**B5. Open a PlatformIO terminal.** Press Ctrl+Shift+P, type
`PlatformIO: New Terminal` and press Enter. All firmware commands (Stages 1
to 4, and 9) go in this terminal: a plain terminal may not find `pio`.
```powershell
pio --version
```

**Report (Part B):** the `log` line from B3, the Python version from B4, and
the PlatformIO version from B5.

---

## Part C — Test the software (no gloves needed)

These checks run on fake (synthetic) data. Passing them means the files and
installs are fine; it says nothing about the hardware. If any check fails,
**stop and report the output**: it means a problem with the files or the
install, not the hardware. Some checks print warnings along the way (for
example about a missing model or speech); that's normal, so judge each one
by its last line.

**C1. Laptop (LAPTOP, VS Code terminal, folder: repo root).**
```powershell
pi-side\venv\Scripts\python.exe gui\tests\test_gui_core.py
pi-side\venv\Scripts\python.exe gui\core\run_native_tests.py
pi-side\venv\Scripts\python.exe training\tests\test_train_smoke.py
cd pi-side
venv\Scripts\python.exe tests\test_frame_roundtrip.py
venv\Scripts\python.exe tests\test_hub_units.py
venv\Scripts\python.exe -m signyales_hub.main --simulate --no-tts -v
cd ..
```

| Command | Pass looks like |
|---|---|
| `test_gui_core.py` | Ends with `All GUI core checks passed` |
| `run_native_tests.py` | Ends with `ALL NATIVE LOGIC TESTS PASSED`. If it says `SKIPPED: g++ not found`, that's fine: write "skipped" (the project's automatic checks on GitHub run it). |
| `test_train_smoke.py` (1 to 3 minutes) | Ends with `All training smoke checks passed` |
| `test_frame_roundtrip.py` | `PASS: frame format round-trips correctly...` |
| `test_hub_units.py` | Ends with `All Pi-side unit checks passed` |
| `signyales_hub.main --simulate` | Keeps running. It logs `Running in --simulate mode` and a `No model loaded` warning, both normal. After about 10 seconds press Ctrl+C. A `Traceback` or `ERROR` line is a fail. |

**Optional, the same checks as buttons.** From the repo root, run
`pi-side\venv\Scripts\python.exe gui\signyales_gui.py`. In **Testing** mode,
press **Run all software checks**; **Subtitle and speaker check** also
tests the laptop's own screen and speaker. Each button shows its command and
output in the log.

**C2. Pi (PI, venv active).**
```bash
python tests/test_frame_roundtrip.py
python tests/test_hub_units.py
python ../gui/tests/test_gui_core.py
python tools/live_view.py --simulate --duration 3
python -m signyales_hub.main --simulate --no-tts -v
```
Pass looks the same as on the laptop. `live_view.py` prints fake values for
3 seconds, then a summary with each finger's min/max. Stop `main` with
Ctrl+C after about 10 seconds. The training smoke test isn't run on the Pi:
training happens on the laptop.

**Report (Part C):** the last line of each command, on each machine, and any
`Traceback` or `ERROR` line in full.

---

## Before the hardware stages, and what to watch for

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
- Record the versions from Parts A and B: the `git --no-pager log -1 --oneline` line from both machines, the Pi model, OS and Python version, and the laptop's Python and PlatformIO versions.
- If anything looks wrong, stop and report the exact output instead of editing firmware yourself.

---

## Hardware stages (1 to 9, including 1b, 6b, 7b and 7c), in this exact order

Finish Parts A to C first. Do not skip ahead — each stage assumes the previous one already works. If a
later stage fails, the most likely cause is something in an earlier stage
that looked fine but wasn't.

### Stage 1 — Confirm the code compiles (no hardware needed yet)

LAPTOP, in the PlatformIO terminal (Part B5), starting from the repo root:

```powershell
cd firmware/glove
pio run -e left_glove
pio run -e right_glove
cd ../receiver
pio run
cd ../..
```
The last line goes back to the repo root for Stage 1b.

**Expected result:** Each command ends with `[SUCCESS]`. If you see a
compile error instead, **stop here and report the exact error text back** —
don't try to fix firmware code yourself unless asked to.

---

### Stage 1b — Set the receiver's MAC address (REQUIRED before Stage 2)

`firmware/glove/src/config.h` ships with a placeholder
(`RECEIVER_MAC = AA:BB:CC:DD:EE:FF`). Until it is replaced with your real
receiver's address, the gloves transmit to nowhere and every glove will
show `ratio=0.0%` in Stage 4. Do this first:

1. Plug in **only the receiver ESP32** and flash the utility (LAPTOP,
   PlatformIO terminal, starting from the repo root):
   ```powershell
   cd firmware/tools/get_mac_address
   pio run -t upload
   pio device monitor
   ```
2. It prints a line like `MAC Address: AA:BB:CC:DD:EE:FF` (yours will
   differ). Copy it, then close the monitor with Ctrl+C and go back to the
   repo root:
   ```powershell
   cd ../../..
   ```
3. Open the glove's settings file in VS Code:
   ```powershell
   code firmware\glove\src\config.h
   ```
   Change the `RECEIVER_MAC` line, one `0x..` per byte. For example,
   `AA:BB:CC:11:22:33` becomes:
   ```
   static uint8_t RECEIVER_MAC[6] = {0xAA, 0xBB, 0xCC, 0x11, 0x22, 0x33};
   ```
   Save (Ctrl+S), then check the line now shows your address:
   ```powershell
   Select-String -Path firmware\glove\src\config.h -Pattern RECEIVER_MAC
   ```
4. Continue to Stage 2 (both gloves will be flashed with the new
   address). The real receiver firmware replaces this utility in Stage 4.

**Report back:** the MAC address you read.

---

### Stage 2 — Flash and test one glove in isolation

LAPTOP, PlatformIO terminal, starting from the repo root, with only the
left glove plugged in:
```powershell
cd firmware/glove
pio run -e left_glove -t upload
pio device monitor
```
Close the monitor with Ctrl+C before uploading to another board.

If `upload` fails because it can't find or choose the port, connect only one
board at a time. If it still fails, list the ports and name the right one
(replace `COM5` with the port shown for your board):
```powershell
pio device list
pio run -e left_glove -t upload --upload-port COM5
pio device monitor --port COM5
```

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
press Enter. Flex and relax all 5 fingers and the palm repeatedly for 8
seconds. You'll see output like:

```
Sensor 0 (thumb): min=800 max=3200
Sensor 1 (index): min=750 max=3100
...
Sensor 5 (palm): min=900 max=2600
```

**Report back:** the full min/max lines for all 6 sensors. A healthy
reading has a spread of at least several hundred between min and max. If
any sensor shows numbers very close together (e.g., `min=2040 max=2055`),
note which one — that sensor likely isn't wired correctly, or the glove
still has the old 470 Ω resistors.

---

### Stage 3 — Repeat for the second glove

Same as Stage 2, with only the right glove plugged in (LAPTOP, PlatformIO
terminal, folder `firmware/glove`):
```powershell
pio run -e right_glove -t upload
pio device monitor
```
Calibrate it the same way (`c`, then Enter), and confirm it prints `This unit: RIGHT` instead of `LEFT`.

---

### Stage 4 — Flash the receiver and confirm it sees both gloves

LAPTOP, PlatformIO terminal, from `firmware/glove`, with only the receiver
plugged in:
```powershell
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
It opens a menu (use the arrow keys, Enter and Tab): Interface Options →
Serial Port → **No** to login shell over serial, **Yes** to serial
hardware → Finish. Then add `dtparam=uart0=on` to the end of
`/boot/firmware/config.txt` (the first command only adds it if it isn't
there yet), check it, and restart:
```bash
grep -q '^dtparam=uart0=on' /boot/firmware/config.txt || echo 'dtparam=uart0=on' | sudo tee -a /boot/firmware/config.txt
tail -n 3 /boot/firmware/config.txt
sudo reboot
```
The `tail` output should end with `dtparam=uart0=on`. (To edit the file by
hand instead: `sudo nano /boot/firmware/config.txt`, add the line at the
end, then Ctrl+O, Enter, Ctrl+X.)

**Step 3 — loopback test (receiver NOT connected yet).** Use a single
jumper wire to connect GPIO14 (pin 8) directly to GPIO15 (pin 10) — this
makes the Pi talk to itself so we can test the port in isolation, before
any receiver wiring could confuse the result. PI, venv active (Part A6):
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
  reporting that, you can add `dtoverlay=disable-bt` to the same file,
  restart, and repeat the loopback test:
  ```bash
  grep -q '^dtoverlay=disable-bt' /boot/firmware/config.txt || echo 'dtoverlay=disable-bt' | sudo tee -a /boot/firmware/config.txt
  sudo reboot
  ```

---

### Stage 6 — Run the Pi-side software

On the Raspberry Pi itself (not your laptop), venv active. The software was
installed in Part A6 and checked without hardware in Part C2.

With the receiver wired up and both gloves powered on, watch the live data
for 30 seconds while you open and close the fingers of both hands:
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

### Stage 6b — Subtitle and speaker check (no model or gloves needed)

This checks the two things a user actually sees and hears: the large
subtitle text and the spoken output. The speaker should be connected and
chosen as the output (Part A7). PI, venv active:
```bash
python tools/output_check.py
```
The terminal clears and shows "Listening..." in large letters, then the word
**salamat** for 5 seconds. After that the speaker says *"Signyales speaker
test. Salamat. Kumusta."* and a short summary is printed.

The subtitle appears in the terminal window you ran the command in. If you
are connected over SSH from a laptop, that is the SSH window on the laptop;
on a monitor plugged into the Pi, it is that monitor. The sound always plays
on the Pi's speaker.

- No sound, and the summary says `FAILED`: read the error line above the
  summary. `espeak-ng is not installed` means the `sudo apt install` step in
  Part A3 was skipped or failed.
- No sound, but the summary says `reported no error`: the software ran, but the
  audio is going to a different output. Choose the speaker again and check
  the volume as in Part A7 (desktop icon or `wpctl`; without a desktop,
  `sudo raspi-config`, then System Options, then Audio). Then run `python tools/output_check.py --no-subtitle` again.
- Letters look broken or very wide: make the terminal window wider, or note it.

**Report back:**
- Was the subtitle readable from about 2 m away? Was it centered? Was this on
  a monitor or over SSH?
- Did you hear the whole phrase? Which speaker (USB, HDMI or other)? Were
  "Salamat" and "Kumusta" understandable?
- The summary printed at the end.

**Optional: the Signyales app (GUI).** The repo also has a windowed app that
runs these checks as buttons and shows large subtitles. It is **not needed**
for this guide, and it has not been run on a Raspberry Pi yet, so anything
you notice is useful. Only if you have time, on the Pi's desktop (not over
plain SSH), from the repo root (`~/SIGNYALES`):
```bash
pi-side/venv/bin/python gui/signyales_gui.py
```
(`python3-tk`, which it needs, was installed in Part A3.)
Try Testing mode's **Run all software checks** and **Subtitle and speaker
check**. Report whether it opened, and any error shown. Close it before
continuing: it and the other tools can't share the serial port.

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
(run from `pi-side/`) logs the stats line to a CSV for later averaging.
To find the receiver's USB port, run `ls /dev/ttyACM* /dev/ttyUSB*` on the
Pi, or `pio device list` on the laptop. This
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
Part A (Pi setup):           DONE / PROBLEM — [model, OS, Python | pip install OK or fallback used]
Part B (laptop setup):       DONE / PROBLEM — [Python version, PlatformIO version]
Part C (software checks):    laptop PASS / FAIL | Pi PASS / FAIL — [native tests run or skipped]
Stage 1 (compiles):          PASS / FAIL — [notes]
Stage 1b (MAC address):      DONE — [address read]
Stage 2 (left glove):        PASS / FAIL — [calibration numbers]
Stage 3 (right glove):       PASS / FAIL — [calibration numbers]
Stage 4 (receiver sees both): PASS / FAIL — [stats line]
Stage 5 (Pi UART wiring):    PASS / FAIL — [ls output / loopback result / port used]
Stage 6 (hub app runs):      PASS / FAIL — [notes]
Stage 6b (subtitle+speaker): PASS / FAIL — [readable Y/N, monitor or SSH | heard Y/N, speaker type]
Stage 7 (full recognition):  PASS / FAIL / NOT APPLICABLE (no model yet)
Stage 7b (real data):        PASS / FAIL — [notes]
Stage 7c (readiness checks): alignment OK/NOT OK | repeatability notes | calibration kept after power cycle Y/N | 30-min run summary
Stage 8 (battery):           left ___ min, right ___ min (or still running at 3h)
Stage 9 (range, 3 trials each): 1m ___ | 3m ___ | 5m ___ | 10m ___ | wall ___ | body ___
Repo log line, laptop / Pi: ___ / ___
```

## One general rule while testing

**Test one new thing at a time, in order.** If Stage 4 works but Stage 5
doesn't, the problem is specifically in the receiver-to-Pi wiring or Pi
configuration — the gloves and wireless link are already proven fine, so
there's no need to re-check those.
