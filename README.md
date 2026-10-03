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
                               assembly guide, and research/testing instruments
```

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

update the readme everytime you push changes in this file with this format, this marks the first one. 

Oct.10, 2026 - rn just testing the firmware. everything seems to compile except the receiver firmware, needs to get checked out. 
   -so far i have jsut checked the firmware, we still need to build the other software stuff so i had gab start working on it while i try and understand the whole shabang wit da firmware. 
   -we also need to worry about the data set we need to collect with the sensors as the available data set was meant to be used for camera based systems. 
   -shibal saekkiya ok fuck we got this medyo malabo na makahabol tayo sa defense pero fuck it we ball lets just hope we can do it next sem. 