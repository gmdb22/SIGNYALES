# Signyales

A bimanual smart glove system for Filipino Sign Language (FSL) translation:
two sensor gloves → a wireless receiver → a Raspberry Pi 5 running on-device
gesture recognition → spoken/text output.

```
signyales/
├── firmware/
│   ├── glove/               PlatformIO project — flash onto each glove (ESP32-S3)
│   ├── receiver/             PlatformIO project — flash onto the receiver (ESP32)
│   └── tools/get_mac_address/  One-off utility to read the receiver's MAC address
├── pi-side/                   Python application that runs on the Raspberry Pi 5
├── training/                 Offline TinyML training pipeline (Jupyter + scripts)
└── docs/                     Software requirements, system design, hardware
                               assembly guide, research/testing instruments,
                               a build walkthrough, and a current verification
                               status snapshot
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


Oct.4, 2026 (3am) - rn just testing the firmware. everything seems to compile except the receiver firmware, needs to get checked out. 
   -so far i have jsut checked the firmware, we still need to build the other software stuff so i had gab start working on it while i try and understand the whole shabang wit da firmware. 
   -we also need to worry about the data set we need to collect with the sensors as the available data set was meant to be used for camera based systems. 
   -shibal saekkiya ok fuck we got this medyo malabo na makahabol tayo sa defense pero fuck it we ball lets just hope we can do it next sem. 

   Oct.4, 2026 (3:30pm)  -reciever firmware fixed
   -everything compiles and runs (albeit no data set yet)
   -suggestion: create user friendly UI for testing, just make buttons pressable to test
   -suggestion: maybe make a separate application to run all tests in sequence


   Oct.10, 2026 
update sa consult form -renzo 

client survey consent form -gab 

surveys according to iso x2 software and hardware -gab 

vibe coding the fuck outta the capstone -recce 

update on how the testing has been -andrei

FAH use /compact when vibing, i am going nowhere dawg