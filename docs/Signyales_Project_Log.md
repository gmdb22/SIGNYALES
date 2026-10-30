# Signyales Project Log

Dated team notes, moved verbatim from the root README (entries are unedited).
Add new entries at the bottom.

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

FAH use /compact when vibing, i am going nowhere dawg brah

## 2026-10-16

- Created branch `code-tasks` from `fixes-f6-f7-f8-f15` (8 commits): sample (n-1) standard
  deviation in the loggers, model compatibility check on load, silent `rest` label in the
  debouncer, stage timing in performance_logger, train.py report/seed/required --out-dir,
  tools/freeze_manifest.py, unit tests and a training smoke test, faster start with no model.
- Verified: GitHub Actions run #23 on `e49ce6d`, all 8 jobs passed. On the Windows laptop:
  test_hub_units.py 33/33, test_train_smoke.py 15/15, main --simulate ran cleanly.
  Synthetic data only; nothing tested on the gloves, receiver or Pi.
- Tagged the hardware-handoff commit `f4f7ad8` as `handoff-1`. Updated the tester addendum hash.
- Hardware handoff not started yet: PCBs still being manufactured.
- Open: decisions D1–D5 (window length, one/two hands, rest, test split, serial_link), latency
  definition vs the 300 ms target, word list to confirm with Blessed Ville.

oct. 16, 2026 - FAH
1. PCBs finished → hardware handoff tests pass.
2. Recorder fixes F1–F5, consent forms ready, word list confirmed by Ma’am Joanne.
3. At home: record yourself → train → check that recognition and speech work live (development only).
4. Blessed Ville visits: record students (no speech yet).
5. At home: train on the student recordings.
6. Blessed Ville visits: live testing with speech and subtitles, plus the survey.

## 2026-10-17

- Since the 16 Oct entry: tagged `handoff-2` (16 Oct), then added the Signyales app (`gui/`,
  Testing and Active modes, laptop and Pi), `pi-side/tools/output_check.py` and handoff
  Stage 6b (subtitle and speaker check, no model needed).
- Fixed what Windows testing found (17 Oct): GUI speech now uses the Windows SAPI voice in a
  separate helper, recording Start/Stop works with one press or Space, training needs at
  least 10 recordings per word. Also added a "Send test word" button on the Pi's Recognize tab.
- Verified on the Windows laptop, fake glove data only: all GUI Testing-mode checks passed,
  the 4 firmware compiles passed, and the subtitle and speaker check was seen and heard.
  Record, train, recognize and the mirror between two windows worked.
- Updated the docs to match (commit `0f31777`). `code-tasks` and `hardware-handoff` are both
  at `0f31777`, tagged `handoff-3` (the tag was moved from `a4c30c5`). Updated the tester
  addendum and command cheat sheet to `handoff-3`.
- Not run anywhere yet: the Pi, real gloves and receiver, firmware upload, the GUI on a Pi,
  the mirror over a real network, and console app speech on Windows.
- Open: decisions D1–D5 and latency, word list with Ma'am Joanne, consent forms, F1–F5 and F16.

## 2026-10-22 to 2026-10-25

- The gloves as built differ from the design: original ESP32 (ESP32-DevKitC-32E clone,
  CP210x) instead of the ESP32-S3, MPU6050 board ("ITG/MPU"), 7 flex sensors fitted with
  470 Ω divider resistors instead of 47 kΩ. Decided: 6 flex sensors per glove (5 fingers +
  palm), because only 6 ADC1 pins can be read while ESP-NOW transmits. The adviser confirmed
  the changes (6 sensors, original ESP32, Pi 5, GUI + mirror).
- Commits on `code-tasks`: `2ed8bc8` handoff guide Parts A–C; `44d76f7` glove firmware for
  the original ESP32 and the schematic pins, plus `firmware/tools/glove_hw_check`; `120bc04`
  6 flex sensors (packet 46 B, frame 103 B, 24 features); `be7fa90` kiosk mode and Pi
  autostart.
- Rework plan agreed with the hardware assembler: R1–R6 → 47 kΩ, J5 → IO36, J6 → IO39, J7 unused.

## 2026-10-26 to 2026-10-27 (first session with real hardware)

Commit `be7fa90`. Results from the terminal output seen during the session.

- Raspberry Pi 5 (Raspberry Pi OS 64-bit, Debian 13, Python 3.13.5): `setup_pi.sh` finished on
  the third run. Run 1 stopped when the Pi lost Wi-Fi during the TensorFlow download. Run 2
  failed building `lgpio` (`swig` missing), fixed by hand with
  `sudo apt install -y swig liblgpio-dev` (`setup_pi.sh` does not install these yet). Run 3:
  full install OK (TensorFlow 2.21.0) and `dtparam=uart0=on` added.
- On the Pi, fake data only: frame round-trip, Pi-side unit tests and GUI core tests passed;
  `live_view.py --simulate` ran at about 49.4 Hz with both hands and 6 sensors;
  `signyales_hub.main --simulate --no-tts` ran (no model, as expected); `output_check.py`
  subtitles seen and speech heard. Serial port enabled in raspi-config (login shell off,
  hardware on). SSH from the laptop works by IP (password login; `pi5.local` is unreliable
  from Windows). The laptop hotspot gave the Pi no IP address (unresolved).
- Receiver (ESP32-WROOM-32, CH340): uploaded from the GUI Hardware helper, boots, prints its
  MAC and `[stats]` every second, 0% from both gloves (none were on). Not wired to the Pi yet.
- Right glove: firmware upload OK, but the board boot-loops (`spi_flash ... Probe failed`,
  `boot:0x33`). Reasoned cause, not yet confirmed: the IMU's SDA is on IO12, a boot strapping
  pin; the IMU board's pull-up holds it high at power-on, so the ESP32 sets its flash to 1.8 V.
  The receiver boots with `boot:0x13`; the difference is the GPIO12 bit. Decided: move the IMU
  to SDA IO21 / SCL IO22 on both gloves and leave IO12 unconnected. The eFuse alternative
  (irreversible) was not used.
- Left glove: Windows reports "Device Descriptor Request Failed", and the area around the
  ESP32's USB port gets very hot on USB power alone (battery unplugged). Reasoned: a short or
  overcurrent. Not to be powered until checked.
- Both gloves handed back to the hardware assembler with a written handoff (short checks,
  IO12 explanation, rework list, pin map).
- Not run yet: the IO12 confirm test (IMU unplugged), glove hardware check, calibration, Pi
  UART loopback, receiver wired to the Pi, real glove data on the Pi, kiosk mode and autostart
  on the Pi.
- Open: the assembler's rework and left-glove result; D1–D5 and latency; power plan (LCD,
  session length, power bank); word list and consent forms; palm sensor orientation.

## 2026-10-28 to 2026-10-29

- Decided: the Pi runs on its wall supply (27 W) with an HDMI monitor; sound goes through a
  USB sound card and AUX cable to a speaker with its own power (wired, so nothing to pair or
  reconnect; the Pi 5 has no headphone jack). The receiver connects to the Pi with one USB
  data cable by default; the UART wires stay as an option chosen in the GUI. Still to tell the
  adviser and the paper writer: wall power instead of the proposal's 5000 mAh power system
  (battery life is then measured on the gloves only), the wired speaker, the USB link.
- Commits on `code-tasks`: `4ba2220` docs for the 26-27 Oct session; `c683229` IMU moved to
  IO21/IO22 in the glove firmware and hardware check; `6406d2a` receiver link over USB by
  default (receiver sends frames on USB while the Pi asks, Pi finds it by its CH340 chip, GUI
  setting USB/UART saved for the kiosk, link numbers in Active mode and the kiosk with F3);
  `9adf2b0` flashing kit in the repo (`flashing_kit/`), `setup_pi.sh` in `pi-side/deploy/` and
  now installing `swig` and `liblgpio-dev` itself. Then the docs update (this entry): the
  Hardware Assembly Guide (new wiring figures), Software Requirements, System Implementation,
  the handoff guide, the cheat sheet, the build walkthrough and the root README now describe
  the hardware as built. (Commit IDs as they are after 29 Oct, when the co-author lines were
  removed from the messages; the code didn't change.)
- Verified in an AI assistant's Linux sandbox, synthetic data only: frame round-trip (incl. the
  USB requests and the receiver's text between frames), Pi-side unit tests, GUI core tests, and
  `live_view.py` and the kiosk reading a simulated receiver on a virtual serial port at about
  50 Hz. The receiver firmware was only syntax-checked there (the ESP32 toolchain download is
  blocked). The owner ran the GUI checks and compiles on the laptop and checked CI after the
  push (reported done).
- Not run yet: the receiver with the new firmware, the USB link on real hardware (CH340 on the
  Pi or Windows), the gloves after the rework. The hardware is with the assembler.
