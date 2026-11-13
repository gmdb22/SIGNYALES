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

## 2026-10-31

- Commit `51b690f` (pre-flash fixes from a code review): accelerometer sent in g, a lock in the
  receiver so a frame can't mix two samples, at most one "send failed" line a second, smoothing
  filter reset after calibration, GUI MAC test accepts a real MAC.
- First receiver-to-Pi tests on real hardware, gloves off: details and numbers in
  `docs/Signyales_Receiver_Link_Test_2026-10-31.md`. Receiver re-flashed (new firmware boots, 50
  frames/s). UART loopback on the Pi: `b'hello'`. USB on the laptop: 49.9 Hz, no restart. UART on
  the Pi: 49.9 Hz. USB on the Pi: 50 Hz after a ~1.2 s receiver restart when the port opens
  (normal on Linux, recovers by itself). Both links pass; USB stays the default.
- Glove hardware checks: neither glove has the rework yet. Left glove: starts and flashes now,
  but the MPU6050 has no power and pinky/palm/7th sensor are still on IO25-IO27. Right glove: no
  IO12 boot problem any more, but brownout resets while the MPU6050 is connected (starts fine
  without it); later it stopped answering uploads (unresolved). Message with the usable pins and
  fixes sent to the hardware assembler.
- Found and fixed: `live_view.py` could cut off its own summary with a `KeyboardInterrupt` at the
  end of a `--duration` run.
- Not run yet: the links with gloves sending, longer runs, the kiosk on the Pi with real data.

## 2026-11-02 to 2026-11-03 (bare-board and MPU checks)

Code at `01fe742`. The owner ran the checks; results from the pasted serial output and meter
readings. The glove PCBs were not powered.

- Both ESP32 boards taken out of the glove PCBs and tested bare with `glove_hw_check`
  (laptop, GUI Hardware helper). Board L: uploads, `boot:0x13`, "starts normally", chip
  ESP32-D0WD-V3 rev 3, 4 MB flash, no restarts while watched. Board R (the one that stopped
  accepting uploads on 31 Oct): uploads normally without holding BOOT, starts normally. Both
  boards are fine; the gloves' faults are on the PCBs.
- One flex divider resistor measured: about 0.5 kΩ on the 200k range, bands yellow-violet-brown-gold,
  i.e. still **470 Ω**, not 47 kΩ (which glove and which R was not noted). The other resistors
  were not measured.
- Both MPU boards checked unpowered (diode mode): no short; about 1.86 V one way (power LED glows),
  about 0.61 V the other way, the same on both.
- Each MPU wired alone to a bare board (VCC 3V3, GND, SDA IO21, SCL IO22; wiring confirmed with the
  meter): both answer at 0x68 with **WHO_AM_I = 0x72**, a clone, not the genuine MPU6050 (0x68).
  The Adafruit library in the glove firmware refuses that ID, so the glove would have stopped at
  `MPU6050 not found` even with correct wiring.
- With an MPU attached, both boards often reset with `Brownout detector was triggered`, mostly
  while starting up; once started they usually kept running. Seen with both MPUs on board R and
  with the left MPU on board L. Not seen with nothing attached. REASONED: a weak supply (the USB
  cable or port is the first suspect); not yet tested with another cable.
- Glove firmware changed to read the MPU directly over I2C (same settings and units, no library)
  and to accept WHO_AM_I 0x68, 0x70, 0x71 and 0x72; `glove_hw_check` gained an `a` command that
  reads the sensor the same way. Checked in a sandbox against a simulated sensor only; not yet
  compiled with PlatformIO or run on hardware.
- Not run yet: the `a` command on the real MPUs, the cable test for the brownouts, the other five
  resistors and both PCBs' short and pin checks, the glove firmware with the new IMU code.

## 2026-11-03 to 2026-11-04 (glove firmware flashed, first glove radio test)

Code at `3b469bf` (glove firmware from `8945b62`, receiver MAC added locally, not committed). Boards
still out of the PCBs, one MPU each on jumpers, no flex sensors. Details and numbers in
`docs/Signyales_Glove_Radio_Test_2026-11-04.md`.

- `a` command on a real MPU (laptop): WHO_AM_I 0x72, both config registers 0x08, 0.98 g lying
  still. Glove firmware compiled and uploaded to both boards (`left_glove` on L, `right_glove`
  on R): PASS.
- The laptop showed a Windows stop screen twice while a board was plugged/unplugged with the GUI
  monitor open (REASONED: CP210x driver). Testing moved to the Pi over SSH.
- On the Pi, "IMU: nothing answers at 0x68" was SDA/SCL swapped on the jumpers. Wired correctly,
  both MPUs on board L reach `Setup complete. Streaming...`.
- Meter on board L: 3V3 pin 2.73 V (left MPU) / 3.02 V (right MPU) with the MPU attached, 3.27 /
  3.31 V without; 5V pin 4.48 / 4.82 V vs 5.02 / 5.08 V. MPU current on the 10A range: 0.00 A for
  both, so under about 10 mA. Correction to the 2–3 Nov entry (REASONED): the brownouts are not a
  faulty MPU; the radio starts once the MPU is found and the USB supply/cable looks weak. Not yet
  tried with a better cable.
- Radio test, receiver on the UART wires to the Pi, one glove at a time, 20 s each
  (`live_view.py --link uart`): left 100% fresh at 50.0 Hz, right 100% fresh at 50.0 Hz, receiver
  reports 0 dropped and 0 corrupt. Tilting the right MPU moved gravity between the axes (about 1 g
  total) and the gyro followed the motion. VERIFIED.
- Right glove, board still: 5 min over UART (99.9% fresh, no outage, receiver 0 dropped), 20 s and
  5 min over the USB cable (100% fresh; one receiver restart when the port opens, as on 31 Oct).
  VERIFIED.
- Both gloves at once (receiver powered from Pi pin 2 → the expansion board's 5V pin, its USB-C
  unplugged; board L on the data cable, board R on the charge-only cable): 20 s and 5 min over UART,
  50 Hz, left and right 100% fresh, no outages. VERIFIED. The Pi's `live_view.py` was found out of
  date (pre-31 Oct, cut off one summary) and was updated.
- Not run yet: range/interference runs, runs with the gloves worn, the gloves on their PCBs and batteries, real flex sensors and calibration. The PCB rework is
  still with the hardware assembler.

## 2026-11-04 (morning): glove firmware robustness, not yet on hardware

- Glove firmware: clears a stuck I2C bus before starting it, tries the IMU 5 times before halting,
  restarts I2C and the IMU if 25 reads in a row fail while streaming, and measures the gyro's
  resting offset for 1 s at start-up (subtracted from every sample, saved to flash; the saved one
  is kept if the glove moved; `g` measures it again). Packet format unchanged.
- Checked in an AI assistant's sandbox only: logic tests against a simulated MPU (offset measured
  and subtracted, moving glove keeps the saved offset, 5 tries, stuck-SDA recovery, restart after
  25 failed reads), the earlier IMU tests, and the frame round-trip test. The functions used were
  checked against the ESP32 Arduino core 2.0.17 headers. Not compiled with PlatformIO yet, not run
  on the boards.
- Later the same morning (owner, real hardware): compiled and uploaded from the laptop GUI to both
  boards, PASS (board L needed BOOT held). Resting offsets measured at start-up: left about
  -4.6, +2.7, -0.3 deg/s, right about -4.2, +1.1, -0.2 deg/s, the same on every boot (saved). The
  "glove moved" fallback triggered a few times on the laptop (spread up to 1.9 deg/s on one axis)
  and kept the saved offset as intended; the 1.5 deg/s stillness limit may be a little strict.
  On the laptop the boards still reset with `Brownout` right where the radio starts (weak laptop
  USB, as before). On the Pi (receiver on Pi pin 2 → expansion board 5V, both gloves powered by the
  Pi): both 100% fresh at 50 Hz, gyro at rest about 0 (within about ±1.6 deg/s noise, was about
  -4 / +2 / -0.3 before), and a tilt test moved accel (total about 1 g) and gyro (up to about
  157 deg/s) on both. VERIFIED. Right glove seq gaps: 67 in one 20 s run, 12 in the next
  (REASONED: forwarding overlap, varies between runs; receiver count not readable with its USB
  unplugged). The I2C recovery and restart paths were not triggered on hardware.

## 2026-11-14

- Decided D1 (window length): every recording is exactly the model window, raw, with no
  resampling, and the window is 2.5 s (`window_size_samples` = 125 at 50 Hz), long enough for
  a short phrase. The GUI Record tab and `collect_gesture.py` now start a repetition at START
  and save it by themselves when the window is full; stopping early discards it.
  `collect_gesture.py` reads frames in the background, so a repetition no longer starts with
  frames that piled up while waiting (F2). The old START/STOP mode is kept only behind
  `--variable` / `fixed_length=False`. Recordings and models made with the old 50-sample window
  are flagged by `train.py` and refused by the recogniser.
- Verified in an AI assistant's Linux sandbox with fake or synthetic data only: frame
  round-trip, Pi-side unit tests (with new capture checks), GUI core tests, training smoke test
  (TensorFlow 2.21.0, 125x24 data), the GUI Record tab on a virtual screen and
  `collect_gesture.py --simulate`. Not yet run on the Windows laptop, the Pi or a real glove.
- One-glove demo planned (right glove, board R), signed with the right hand: words hello, deaf,
  hard of hearing, hearing, yes, no; phrases "sorry, I don't understand" and "I'm fine", each
  learned as one class; plus a rest class.
- Glove firmware: the board R glove stopped streaming after re-wiring. Its boot log showed
  "FATAL: MPU6050 not found" at 0x68 and "I2C device found at 0x69, WHO_AM_I=0x72": the MPU's
  AD0 pin is high or floating on the new wiring. `setupImu()` now tries 0x68, then 0x69, and
  uses whichever answers (the same check runs again on every IMU restart). Not compiled in the
  sandbox (PlatformIO download blocked); compile and upload on the laptop.

