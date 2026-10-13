# Signyales

A bimanual smart glove system for Filipino Sign Language (FSL) translation:
two sensor gloves → a wireless receiver → a Raspberry Pi 5 running on-device
gesture recognition → spoken/text output.

```
signyales/
├── firmware/
│   ├── glove/                PlatformIO project — flash onto each glove (ESP32-S3)
│   ├── receiver/             PlatformIO project — flash onto the receiver (ESP32)
│   ├── tools/get_mac_address/  One-off utility to read the receiver's MAC address
│   └── tests/native/         Plain-g++ tests of packet.h / frame.h (no hardware)
├── pi-side/                  Python application that runs on the Raspberry Pi 5
│                             (tests/, tools/, deploy/, model/ live inside it)
├── training/                 Offline TinyML training pipeline (Jupyter + scripts)
├── tools/                    Laptop-side helpers: test_dashboard.py (one-click
│                             no-hardware tests), results_visualizer.py
├── .github/workflows/        CI: runs the no-hardware tests on every push/PR
└── docs/                     Software requirements, system design, hardware
                              assembly guide, research/testing instruments,
                              a build walkthrough, a verification status
                              snapshot, and Signyales_Project_Log.md (dated
                              team notes)
    └── testing_handoff/      Guide + fillable form for whoever is testing the
                              physical hardware (not the project author)
```

## Test Dashboard

```
python tools/test_dashboard.py
```

A local GUI for running every no-hardware test with one click each —
no commands, folders, or venv activation to remember. Shows live
pass/fail status and full output for the frame format test, the native
firmware logic tests, the Pi-side pipeline smoke test, and (slower, needs
PlatformIO + internet) a full firmware compile check. If a required tool
(like `g++` or `pio`) isn't installed, that test shows as "Skipped" with
an explanation rather than crashing the dashboard.

## Continuous Integration

Every push and pull request automatically runs everything in this repo
that's testable without physical hardware — the frame format contract
test, the native firmware logic tests, a Pi-side pipeline smoke test, and
a full compile check of all 4 firmware targets (left glove, right glove,
receiver, MAC utility). See `.github/workflows/test.yml`. Check the
Actions tab on GitHub after pushing to see results.

Open `signyales.code-workspace` in VSCode to load all sub-projects at once,
each with the right tooling active (PlatformIO for firmware, Python for the
rest).

## Testing guide

Three levels, cheapest first. Don't move up until the level below passes.
Anything run with `--simulate` uses synthetic data and is **never** a
hardware result. For hardware testing by someone other than the project
author, use `docs/testing_handoff/Signyales_Hardware_Testing_Handoff.md`
(step-by-step, with pass criteria) and fill in
`docs/testing_handoff/signyales_test_log.html`.

Commands show the terminal and the folder to run them from. PowerShell is
the Windows dev machine; bash is the Raspberry Pi (or any Linux/macOS shell).

### Level 1 — No hardware needed

One-click version (PowerShell or bash, from the repo root; needs Python with
tkinter): `python tools/test_dashboard.py`. Or run each test by hand:

| Test | Folder | PowerShell | bash |
|---|---|---|---|
| Frame format round-trip, plus serial reader resync (Python standard library only) | `pi-side` | `python tests\test_frame_roundtrip.py` | `python3 tests/test_frame_roundtrip.py` |
| Whole Pi pipeline on synthetic data (runs until you press Ctrl+C; needs `numpy`) | `pi-side` | `python -m signyales_hub.main --simulate --no-tts -v` | `python3 -m signyales_hub.main --simulate --no-tts -v` |
| Live viewer self-test (needs `pyserial`, `numpy`) | `pi-side` | `python tools\live_view.py --simulate --duration 3` | `python3 tools/live_view.py --simulate --duration 3` |

Expected: the first prints a line starting `PASS:`. The second logs
`Running in --simulate mode` and a "No model loaded" warning, which is normal
with no model. For the Python tests, use the `pi-side` venv:

```
# PowerShell, folder: pi-side
.\venv\Scripts\Activate.ps1
python -m pip install numpy pyserial

# bash, folder: pi-side
source venv/bin/activate
python3 -m pip install numpy pyserial
```

Don't use `pip install -r requirements.txt` for simulated runs: it also pulls in
TensorFlow, which is large and not needed for them. A snapshot of what one full
laptop install resolved to is in `pi-side/requirements-laptop-lock.txt`
(reference only, not verified on the Pi).

**Native firmware logic tests** (needs `g++`; checks `packet.h` is 44 bytes and
`frame.h` is 99 bytes, and the checksums):

```
# bash, folder: firmware
bash tests/native/run_all.sh

# PowerShell, folder: firmware\tests\native
g++ -Wall -Wextra -I..\..\glove\src -o test_packet_logic.exe test_packet_logic.cpp
g++ -Wall -Wextra -I..\..\receiver\src -o test_frame_logic.exe test_frame_logic.cpp
.\test_packet_logic.exe
.\test_frame_logic.exe
```

Expected: `ALL NATIVE LOGIC TESTS PASSED` (bash) or `0 check(s) failed` twice
(PowerShell).

**Firmware compile check** (needs PlatformIO and internet; no board attached):

```
# PowerShell, folder: firmware\glove
pio run -e left_glove
pio run -e right_glove

# PowerShell, folder: firmware\receiver
pio run

# PowerShell, folder: firmware\tools\get_mac_address
pio run
```

If you change `packet.h` or `frame.h`, or the Python frame layout in
`pi-side/signyales_hub/serial_link.py`, change the other side too and re-run
the frame round-trip test and both native tests.

### Level 2 — Hardware bring-up (gloves, receiver and Pi)

Full detail and pass criteria are in the handoff guide; this is the command
sequence. Stage numbers match that guide and the log form.

1. **Read the receiver's MAC (Stage 1b).** Receiver ESP32 plugged in.
   ```
   # PowerShell, folder: firmware\tools\get_mac_address
   pio run -t upload
   pio device monitor
   ```
   Copy the printed address into `RECEIVER_MAC` in `firmware/glove/src/config.h`
   as `{0xAA, 0xBB, ...}`. Do not commit that change: it's specific to your receiver.
2. **Flash and calibrate each glove (Stages 2 and 3).** One glove plugged in at a time.
   ```
   # PowerShell, folder: firmware\glove
   pio run -e left_glove -t upload      # right glove: -e right_glove
   pio device monitor
   ```
   In the monitor, type `c` and flex all fingers for 8 seconds to calibrate.
3. **Flash the receiver (Stage 4).**
   ```
   # PowerShell, folder: firmware\receiver
   pio run -t upload
   pio device monitor
   ```
   Expect a `[stats]` line each second. Both gloves should show a high `ratio`
   with `corrupt=0`. `ratio=0.0%` means that glove has never been heard
   (usually a wrong `RECEIVER_MAC`).
4. **Pi UART loopback (Stage 5).** Jumper Pi GPIO14 (pin 8) to GPIO15 (pin 10),
   receiver disconnected. Pi 5: use `/dev/ttyAMA0`, not `/dev/serial0`. See
   `pi-side/README.md` for the config.txt steps.
   ```
   # bash, any folder, with the pi-side venv active
   python3 -c "import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); s.write(b'hello'); time.sleep(0.2); print(s.read(5))"
   ```
   Expect `b'hello'`. Remove the jumper, then wire the receiver (TX/RX crossed, shared ground).
5. **Pi software (Stage 6).**
   ```
   # bash, folder: pi-side
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   sudo apt install espeak-ng
   python tests/test_frame_roundtrip.py
   python tools/live_view.py --port /dev/ttyAMA0 --duration 30
   ```
   `live_view.py` prints both hands' values, the frame rate and a summary. If it
   prints `No frames for ...s`, nothing is reaching the Pi: check wiring, port and baud.
   Then `python -m signyales_hub.main --port /dev/ttyAMA0 -v`: with no model it prints
   only startup lines and **nothing per frame**, so use `live_view.py` to see data.
6. **Record real data (Stage 7b).** Gloves worn.
   ```
   # bash, folder: pi-side, venv active
   python tools/collect_gesture.py --label fist --reps 5 --port /dev/ttyAMA0 --out ../training/data
   python tools/collect_gesture.py --label open --reps 5 --port /dev/ttyAMA0 --out ../training/data
   python tools/inspect_recordings.py --root ../training/data
   ```
   `inspect_recordings.py` checks data consistency (NaN, a hand that never moved,
   channels that can't tell two gestures apart). It says nothing about accuracy.

Only one program can read the receiver's UART at a time: don't run `live_view.py`,
`main.py` and a logger together.

### Level 3 — Measurement (feeds the proposal's performance checklist)

Run from `pi-side/` in bash, venv active. Details in `pi-side/TESTING.md`.

| Tool | Command | Needs |
|---|---|---|
| Pi-side packet delivery and latency over a session | `python tools/performance_logger.py --port /dev/ttyAMA0 --duration 300 --out results/perf_run1` | Gloves and receiver. Delivery figures work with no model. Recognition latency needs one. |
| Receiver-side delivery (ESP-NOW hop only) | `python tools/receiver_link_logger.py --port <receiver USB port> --duration 60 --out results/link_run1.csv` | A second USB cable from the receiver. |
| Recognition accuracy matrix | `python tools/accuracy_logger.py --gestures kumusta salamat --trials 10 --model-dir model --out results/accuracy_session1` | A trained model in `pi-side/model/`. |
| Inference time per window on the Pi | `python tools/benchmark_inference.py --model-dir model --runs 200` | A trained model in `pi-side/model/`. Measures `predict()` only, not the whole pipeline. |
| Battery life (when does each glove stop?) | `python tools/live_view.py --port /dev/ttyAMA0 --duration 10800 --interval 300` | Prints `no fresh data since HH:MM:SS` per glove. |

The receiver's `[stats]` ratio **freezes** when a glove goes silent, it does not
drop to 0%, so don't use it to find a battery cutoff. It is also cumulative
since boot, so power-cycle between range trials.

### What's been verified

The Python tests, the simulated pipeline and viewer, and the native
firmware tests in Level 1 were run on Linux against this repo, and passed.
The test dashboard, the firmware compile check, the Windows/PowerShell
variants above, and every Level 2 and 3 command on real gloves or a Pi 5
have **not** been run by the author of this section. Treat them as untested
until the log form says otherwise, and check the GitHub Actions tab for the
compile results.

## Build order

1. **`firmware/tools/get_mac_address`** — flash onto the receiver ESP32 once
   to read its MAC address.
2. **`firmware/glove`** — paste that MAC into `src/config.h`'s `RECEIVER_MAC`,
   then build/flash both `left_glove` and `right_glove` environments.
3. **`firmware/receiver`** — flash the real receiver firmware (overwriting the
   MAC utility from step 1).
4. **`pi-side`** — set up a Python virtual environment and run against the
   receiver's UART link. See `pi-side/README.md` and `pi-side/TESTING.md`.
5. **`training`** — collect gesture data via `pi-side/tools/collect_gesture.py`,
   then train and export a model with this pipeline. See `training/README.md`.

Each subfolder has its own README with full details — this file is just the
map.

Dated team notes live in [`docs/Signyales_Project_Log.md`](docs/Signyales_Project_Log.md).

**REMINDER** 
project updates go from lockin-start-here to main 
hardware testing handoff goes to the hardware-handoff branch 
ONLY SHARE THE hardware-handoff REPO 
