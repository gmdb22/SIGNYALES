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
