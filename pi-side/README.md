# Signyales — Raspberry Pi Application

Layer 3 of the pipeline: gloves → receiver dongle → **Pi hub** → text/speech.
Target hardware: **Raspberry Pi 5 (4GB)**, Raspberry Pi OS Bookworm (64-bit).

```
receiver UART -> parse frames -> extract features -> sliding window
    -> TinyML inference -> debounce -> print text + speak
```

## What's in this folder

| File | Purpose |
|---|---|
| `signyales_hub/config.py` | All tunables: serial settings, window size, thresholds. |
| `signyales_hub/serial_link.py` | Parses the receiver's UART frame format (mirrors `frame.h`). |
| `signyales_hub/windowing.py` | Turns a frame stream into fixed-size windows for the model. |
| `signyales_hub/model_runtime.py` | Loads a TFLite model, or degrades gracefully if none exists yet. |
| `signyales_hub/gesture_debounce.py` | Turns flickering raw predictions into stable gesture events. |
| `signyales_hub/tts_engine.py` | Offline text-to-speech, non-blocking. |
| `signyales_hub/status_led.py` | Optional GPIO status LED via gpiozero. |
| `signyales_hub/main.py` | Wires everything together. |
| `tools/benchmark_inference.py` | Measures real inference latency once a model exists. |
| `tools/output_check.py` | Shows a test subtitle and plays a test phrase, to check the screen and speaker (no model or gloves needed). |
| `tools/freeze_manifest.py` | Records the commit, model file hashes, config values and package versions before field testing. |
| `tests/test_frame_roundtrip.py` | Verifies the Python struct format matches the firmware's, with no hardware needed. |
| `tests/test_hub_units.py` | Unit checks for feature order, windowing, debouncing (incl. the rest label), recorder resampling and tool helpers. Needs only numpy. |
| `model/*.example.json` | Shows the exact format the training pipeline must export. |

## Setup on the Raspberry Pi 5

### 1. Enable the hardware UART

**Pi 5-specific — do not trust `/dev/serial0`.** On earlier Pi models,
`/dev/serial0` pointed to the GPIO header UART. On the **Pi 5**, it instead
points to a separate 3-pin debug connector, unrelated to the GPIO14/15
pins this project wires to. Checking that it exists will give a
misleading "yes" that has nothing to do with whether the receiver
connection actually works. Use `/dev/ttyAMA0` directly, and verify it with
a real loopback test rather than a file-existence check:

```
sudo raspi-config   # Interface Options -> Serial Port -> login shell: No, hardware: Yes
sudo nano /boot/firmware/config.txt
```

Add at the end, save, then reboot:
```
dtparam=uart0=on
```
```
sudo reboot
```

**Loopback test (receiver not connected yet):** jumper GPIO14 (pin 8)
directly to GPIO15 (pin 10), then:
```
python3 -c "import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); s.write(b'hello'); time.sleep(0.2); print(s.read(5))"
```
Expect `b'hello'`. Remove the jumper once confirmed.

If that printed `b''` or the device doesn't exist, `dtoverlay=disable-bt`
may also be needed (sources disagree on whether Pi 5 requires this the
same way Pi 3/4 did) — add it to the same config.txt, reboot, and repeat
the loopback test. See
`docs/testing_handoff/Signyales_Hardware_Testing_Handoff.md`, Stage 5, for
the full walkthrough.

Wire the receiver dongle's TX/RX to the Pi's RX/TX (crossed) plus a shared
ground, matching the pins set in the receiver's `config.h`.

### 2. Install dependencies

```
sudo apt install espeak-ng
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Verify the frame format before touching real hardware

```
python tests/test_frame_roundtrip.py
```

This should print `PASS`. If it doesn't, stop here — nothing downstream will
work correctly until this does, since it means the Python struct layout has
drifted from the firmware's `combined_frame_t`.

### 4. Run without hardware or a trained model

```
python -m signyales_hub.main --simulate --no-tts -v
```

This exercises serial parsing (via synthetic frames), windowing, and the
model-runtime's graceful "no model yet" path — useful during early sprints
before the receiver or a trained model exist, per the proposal's Agile Scrum
structure.

### 5. Run against real hardware

```
python -m signyales_hub.main --port /dev/ttyAMA0 --baud 460800 --model-dir model
```

Add `--subtitle` for large, fullscreen text output during a demo — this is
the proposal's "visible text output" requirement, deliberately kept to
plain large text with no GUI elements, buttons, or windows, matching the
proposal's "console or LED-based" scope language. (Since October 2026 there
is also a windowed app, `gui/signyales_gui.py`, with subtitles, speech,
recording and a laptop mirror; see `gui/README.md`. That is an approved scope
change; this console mode is unchanged.)

```
python -m signyales_hub.main --port /dev/ttyAMA0 --model-dir model --subtitle
```

When `--subtitle` is on, logging is redirected to `signyales.log` instead
of the terminal, since the fullscreen display and scrolling log text can't
both use the same screen space. Check that file, not the terminal, if you
need to debug a run started with this flag.

## The model artifact contract

Once the training pipeline produces a model, drop these three files into
`model/` (see the `.example.json` files here for the exact shape expected):

- **`model.tflite`** — the trained, quantized model
- **`labels.json`** — a JSON list of gesture strings, index-aligned to the
  model's output classes
- **`scaler.json`** — `{"mean": [...], "std": [...]}`, 22 values each, computed
  on the *same* training data the model was fit on

The 22-value feature order is a hard contract, documented in `config.py`:
`left_flex(5), right_flex(5), left_accel(3), left_gyro(3), right_accel(3), right_gyro(3)`.
If the training pipeline logs features in a different order, the model will
silently make predictions on a scrambled input vector — it won't error, it
will just be wrong in a way that's hard to notice by inspection.

## Design notes specific to the Pi 5 upgrade

- **GPIO library:** `status_led.py` uses `gpiozero` (with the `lgpio` backend)
  rather than `RPi.GPIO`, because `RPi.GPIO` does not reliably support the
  Pi 5's RP1 I/O chip.
- **TFLite runtime:** `model_runtime.py` tries `tflite-runtime` first, then
  falls back to full `tensorflow`. `requirements.txt` defaults to installing
  full `tensorflow`, since `tflite-runtime`'s aarch64 wheel support for
  current Python versions has been inconsistent, and the Pi 5's CPU has
  enough headroom that the extra interpreter overhead isn't a real cost.
- **Inference rate:** `stride_samples` defaults to 5 (~10 inferences/sec at
  50 Hz) rather than a more conservative value — the Pi 5's quad-core
  Cortex-A76 can likely sustain this comfortably, but run
  `tools/benchmark_inference.py` once a real model exists and adjust if p95
  latency is close to the time budget between strides.
- **UART setup did not get simpler on Pi 5, and changed in a new way:**
  `/dev/serial0` no longer points to the GPIO header UART at all (it's the
  separate debug connector instead) — use `/dev/ttyAMA0` and verify with a
  real loopback test, not a file-existence check. Whether `disable-bt` is
  also required is genuinely unclear from available sources; try
  `dtparam=uart0=on` first and only add `disable-bt` if the loopback test
  still fails.

## Known limitations

- No automatic reconnection if the serial port is unplugged mid-run —
  `SerialFrameReader` will simply stop yielding frames. Restarting the
  process is the current recovery path.
- The debouncer holds only one "currently held" gesture at a time — rapid
  alternation between two known gestures faster than
  `debounce_required_consecutive` inferences will be missed by design (this
  is what prevents chatter, but it's a real trade-off worth being able to
  explain to a panel).
