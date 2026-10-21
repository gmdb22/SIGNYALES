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
├── gui/                      The Signyales app (laptop and Pi): Testing mode
│                             (every check is a button) and Active mode
│                             (recognize, record, mirror, hardware helper)
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

## Signyales app (GUI)

```
# PowerShell, folder: repo root
pi-side\venv\Scripts\python.exe gui\signyales_gui.py

# bash on the Pi (desktop, not plain SSH; once: sudo apt install python3-tk)
pi-side/venv/bin/python gui/signyales_gui.py
```

One app for the laptop and the Pi, with two modes:

- **Testing:** every check is a button with PASS/FAIL and full output: the
  software tests, native firmware tests, training smoke test, firmware
  compile, Pi hardware checks (UART loopback, live data, freeze manifest),
  the subtitle and speaker check, a simulated pipeline, and inspect / train /
  benchmark.
- **Active:** on the Pi, *Recognize* (large subtitles and speech, optional
  sharing to a laptop) and *Record* (teach the model with a Start/Stop
  button); on the laptop, *Mirror the Pi* (the laptop shows and speaks what
  the Pi recognizes) and a *Hardware helper* (compile/upload firmware,
  serial monitor, RECEIVER_MAC check).

Details, setup and the mirror link: `gui/README.md`. The GUI subtitles and
the laptop mirror are a scope change from the proposal's console-only output
(approved by the adviser, as reported by the team in October 2026); the
console app `signyales_hub.main` still works as before.

The older one-click runner, `python tools/test_dashboard.py`, still works for
the four basic no-hardware tests.

## Continuous Integration

Every push and pull request automatically runs everything in this repo
that's testable without physical hardware: the frame format contract
test, the native firmware logic tests, the Pi-side pipeline smoke test with
the Pi-side unit tests and the GUI core tests, a training smoke test on
synthetic data, and a full compile check of all 4 firmware targets (left
glove, right glove, receiver, MAC utility). See `.github/workflows/test.yml`. Check the
Actions tab on GitHub after pushing to see results.

Open `signyales.code-workspace` in VSCode to load all sub-projects at once,
each with the right tooling active (PlatformIO for firmware, Python for the
rest).

## Testing guide

Three levels, cheapest first. Don't move up until the level below passes.
Anything run with `--simulate` uses synthetic data and is **never** a
hardware result. For hardware testing by someone other than the project
author, use `docs/testing_handoff/Signyales_Hardware_Testing_Handoff.md`
(step-by-step, with pass criteria: Parts A to C set up the Pi 5 and VS Code
and run the software checks, then Stages 1 to 9 test the hardware) and fill in
`docs/testing_handoff/signyales_test_log.html`.

Commands show the terminal and the folder to run them from. PowerShell is
the Windows dev machine; bash is the Raspberry Pi (or any Linux/macOS shell).

### Level 1 — No hardware needed

One-click version: the GUI's **Testing** mode (see "Signyales app" above),
or the older `python tools/test_dashboard.py`. Or run each test by hand:

| Test | Folder | PowerShell | bash |
|---|---|---|---|
| Frame format round-trip, plus serial reader resync (Python standard library only) | `pi-side` | `python tests\test_frame_roundtrip.py` | `python3 tests/test_frame_roundtrip.py` |
| Whole Pi pipeline on synthetic data (runs until you press Ctrl+C; needs `numpy`) | `pi-side` | `python -m signyales_hub.main --simulate --no-tts -v` | `python3 -m signyales_hub.main --simulate --no-tts -v` |
| Live viewer self-test (needs `pyserial`, `numpy`) | `pi-side` | `python tools\live_view.py --simulate --duration 3` | `python3 tools/live_view.py --simulate --duration 3` |
| Pi-side unit tests (needs `numpy`) | `pi-side` | `python tests\test_hub_units.py` | `python3 tests/test_hub_units.py` |
| GUI core tests, no window (needs `numpy`) | repo root | `python gui\tests\test_gui_core.py` | `python3 gui/tests/test_gui_core.py` |
| Training smoke test, about 1-3 min (needs TensorFlow, scikit-learn) | repo root | `python training\tests\test_train_smoke.py` | `python3 training/tests/test_train_smoke.py` |
| Subtitle and speaker check (listen and look) | `pi-side` | `python tools\output_check.py` | `python3 tools/output_check.py` |

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

# PowerShell, folder: repo root (same tests, build files go to a temp folder)
python gui\core\run_native_tests.py

# PowerShell, folder: firmware\tests\native (by hand)
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
5. **Pi software (Stage 6).** The venv, packages and `espeak-ng` are installed
   in the handoff guide's Part A.
   ```
   # bash, folder: pi-side, venv active
   python tests/test_frame_roundtrip.py
   python tools/live_view.py --port /dev/ttyAMA0 --duration 30
   ```
   `live_view.py` prints both hands' values, the frame rate and a summary. If it
   prints `No frames for ...s`, nothing is reaching the Pi: check wiring, port and baud.
   Then `python -m signyales_hub.main --port /dev/ttyAMA0 -v`: with no model it prints
   only startup lines and **nothing per frame**, so use `live_view.py` to see data.
6. **Subtitle and speaker (Stage 6b).** Speaker connected to the Pi (the Pi 5 has
   no 3.5 mm jack: use USB or HDMI audio).
   ```
   # bash, folder: pi-side, venv active
   python tools/output_check.py
   ```
   Large "salamat" on screen, then a spoken test phrase. Listen and look; there is
   no automatic pass.
7. **Record real data (Stage 7b).** Gloves worn.
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

As of 17 October 2026, on branch `code-tasks`, synthetic data only:

- **Linux and CI:** all Level 1 tests pass. GitHub Actions run #23 on
  `e49ce6d` passed all 8 jobs, including the 4 firmware compiles; check the
  Actions tab for later pushes.
- **Windows dev laptop (Python 3.13):** in the GUI's Testing mode, all
  software checks, the native firmware tests and all 4 firmware compiles
  passed; the subtitle and speaker check played each word in step with the
  screen; recording with fake glove data, training on it, recognition and the
  Pi-to-laptop mirror (two windows on one laptop) worked.

**Not run anywhere yet:** every Level 2 and 3 command on real gloves,
receiver or a Pi 5; firmware uploads; the GUI on a Pi; the mirror over a
real cable or Wi-Fi; recognition accuracy on real signing. Treat these as
untested until the hardware test log says otherwise.

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
can do changes on lockin-start-here but any changes during testing should be done in branch hardware-handoff

## Hardware handoff: which version to test

- The version for hardware testing is the tag **`handoff-4`** (adds Parts A
  to C to the guide: Pi 5 setup, VS Code setup and the software checks). The
  exact commit hash is in the tester addendum. `handoff-1` to `handoff-3` are
  older versions; don't use them.
- Testers: clone the repo and check out the tag, on both the laptop and the Pi:
  ```
  git clone https://github.com/gmdb22/SIGNYALES.git
  cd SIGNYALES
  git checkout handoff-4
  git --no-pager log -1 --oneline
  ```
  The last line must start with the hash given in the addendum. A "detached
  HEAD" message is normal. Include that line in every test report, from both
  machines.
- `RECEIVER_MAC` in `firmware/glove/src/config.h` is edited locally in Stage 1b
  and **never committed**: every receiver has its own MAC.
- If a code fix is pushed to `hardware-handoff` during testing, tag that commit
  with the next number (`handoff-4`, `handoff-5`, ...) and tell the tester which
  tag to use. Commits that only change documentation don't need a new tag,
  unless they change the testing guide itself (as `handoff-4` did).
- `hardware-handoff` is not locked on GitHub. The tags are the record of exactly
  what was tested.
