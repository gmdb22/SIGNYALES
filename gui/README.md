# Signyales GUI

One app for the laptop and the Raspberry Pi, with two modes:

| | **Testing** (every check is a button) | **Active** (plug and play) |
|---|---|---|
| **Laptop** | Software checks, native firmware tests, training smoke test, firmware compile, subtitle and speaker check, simulated pipeline, inspect recordings, train a model, benchmark | **Mirror the Pi**: the Pi recognizes, the laptop shows the subtitles and plays the sound. **Hardware helper**: compile and upload firmware, serial monitor (with "send c" for calibration), RECEIVER_MAC check |
| **Raspberry Pi** | Software checks, UART loopback, 30 s live data check, freeze manifest, subtitle and speaker check, simulated pipeline, inspect, benchmark | **Recognize**: live subtitles and speech, optional sharing to a laptop. **Record (teach the model)**: one big Start/Stop button per repetition |

The app detects whether it runs on a Raspberry Pi. The **This machine** menu
overrides that, e.g. to try the Pi screens on the laptop with fake glove data.

## Start it

Windows (PowerShell, folder: repo root):
```powershell
pi-side\venv\Scripts\python.exe gui\signyales_gui.py
```

Raspberry Pi (bash, folder: repo root, on the Pi's desktop, not over plain SSH):
```bash
sudo apt install python3-tk      # once
pi-side/venv/bin/python gui/signyales_gui.py
```

Every button runs the same command the guides use; the full command and its
output appear in the log, so a result can always be repeated by hand.

## Mirror: Pi recognizes, laptop shows and speaks

1. Connect the laptop and the Pi with an Ethernet cable, or put both on the
   same private Wi-Fi or phone hotspot. No internet is needed; a direct cable
   works on its own.
2. On the Pi: **Active → Recognize**, tick **Share with a laptop**, then
   **Start recognition**. The Pi shows its address(es).
3. On the laptop: **Active → Mirror the Pi**, type that address, **Connect**.

To check the link without a model or gloves, press **Send test word** on the Pi: the
laptop shows and speaks "salamat" exactly as for a recognized sign.

Only recognized words and a twice-a-second glove status are sent (TCP port
50555), never sensor recordings. There is no password, so only share on a
cable or a network you control. Untick **Speak words on this Pi** if the
laptop should be the only speaker.

## Recording ("teach the model")

Files go to `<Save under>/<signer>_<session>/<word>/rep_NNNN.npz`, in exactly
the format `pi-side/tools/collect_gesture.py` writes, so training works the same
way. Use codes such as `W01` and `S01`, never names. Press **Space** (or click
the big button) to start/stop a repetition, **Esc** to cancel one. The button
shows a live frame count while recording. On a machine that isn't a Raspberry
Pi, **Fake glove data** is ticked by default; fake recordings only test the
tool, they are not training data.

Record **at least 10 repetitions per word** (20 or more recommended), and at
least 2 words: training splits each word's recordings into training,
validation and test parts and stops with a message if there are fewer.

## Training from the GUI

Testing mode → **Train a model…**. The first dialog opens in
`~/signyales_data`: pick a session folder such as `W01_S01` (the one with one
folder per word); the GUI checks it and lists the words before training. The
second dialog opens in `~/signyales_models`: make a new folder (e.g. `test1`)
and pick it. The log ends with a summary of `train_report.json`. To use the
model, choose that folder as **Model folder** on the Recognize tab, or copy
`model.tflite`, `labels.json` and `scaler.json` into the Pi's `pi-side/model/`.

Known limits, until the F1–F5 recorder work is done: each repetition is still
resampled to the window length (F1), and frames where a glove dropped out are
still kept (F3). Unlike the command-line recorder, the GUI reads the serial
port continuously, so a repetition never starts with stale frames (F2).

## Files

| File | What it is |
|---|---|
| `signyales_gui.py` | The app window, machine and mode switch |
| `testing_view.py` | Testing mode |
| `active_view.py` | Active mode (Pi: Recognize, Record; laptop: Mirror, Hardware helper) |
| `widgets.py` | Log box, subtitle panel (and fullscreen), glove status, speaker |
| `core/speech_worker.py` | Speaks for the GUI in a separate process (Windows' speech was silent from a GUI background thread) |
| `core/` | Logic without any window code: tasks, process runner, live pipeline, recorder, mirror link, serial helpers |
| `tests/test_gui_core.py` | Tests for `core/` (runs in CI) |

`core/live.py` repeats the steps of `pi-side/signyales_hub/main.py`. If the
main loop changes, change both; `tests/test_gui_core.py` checks they agree.

## Speech

The GUI speaks through a separate helper process (`core/speech_worker.py`). On
Windows it uses the built-in SAPI voice directly; through `pyttsx3` only the
first phrase played on the Windows dev laptop, and nothing played from a
background thread. On Linux and the Pi it uses the hub's `TTSEngine`
(`pyttsx3`, falling back to `espeak-ng`). The console app `signyales_hub.main`
still uses `TTSEngine` directly; whether it speaks on Windows has not been
checked.

## Status

Checked on the Windows dev laptop (17 October 2026, fake glove data): every
Testing-mode check, the subtitle and speaker check, Record, Train, Recognize
and the mirror between two windows on one laptop. **Not yet run:** the GUI on
a Raspberry Pi, real gloves, firmware uploads from the Hardware helper, and
the mirror over a real cable or Wi-Fi.

`tools/test_dashboard.py` (the old dashboard) still works; the GUI's Testing
mode covers everything it does.
