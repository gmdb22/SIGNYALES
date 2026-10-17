# Signyales — Build Walkthrough

How the codebase was built, phase by phase, and how each piece actually
works. This follows the real order of construction, not a reverse-engineered
narrative — each phase exists because the one before it created a need for it.

---

## Phase 0 — Reading the project proposal

Before any code, the existing capstone proposal PDF was read in full to
extract: the system architecture (two gloves → receiver → Pi), the named
hardware (ESP32-S3, ESP32, Raspberry Pi, TinyML), and the methodology's
evaluation instruments (Recognition Accuracy Matrix, statistical treatment
via mean/weighted mean/SD). This is why the code that follows uses specific
terms like "Recognition Accuracy Matrix" rather than generic ones — it's
matching vocabulary already committed to in the proposal, not introducing
new concepts.

From this, a ranked list of required software was produced (glove firmware
→ receiver firmware → TinyML pipeline → Pi hub app → TTS → data collection
→ testing tools → research instruments), ordered by "how much the system
breaks without it." That ranking became the build order for everything after.

---

## Phase 1 — Glove Firmware

**Files:** `firmware/glove/src/{glove_firmware.ino, config.h, packet.h}`

Built first because every other layer depends on *something* coming off
the glove — there's no point designing a receiver for data that doesn't
exist yet.

**`packet.h`** was written first, before any logic, because it defines the
one thing every other layer needs to agree on: the exact byte layout of a
sensor reading (`glove_id`, `seq`, `timestamp_ms`, 5 flex values, 3-axis
accel, 3-axis gyro, a checksum). `#pragma pack(push, 1)` forces no padding
between fields, which matters because the receiver and the Pi's Python code
both need to read these exact same bytes back out later — any compiler-
inserted padding would silently break that agreement.

**`config.h`** holds everything that changes per-build (which hand, which
pins, the receiver's address, sample rate) specifically so the actual logic
file never needs editing per-glove — only this file does.

**`glove_firmware.ino`** does four things in sequence each loop iteration:
read the 5 flex sensors and IMU, smooth the flex readings (exponential
moving average, so a jittery ADC reading doesn't look like rapid finger
movement), normalize each flex sensor against a stored calibration (so
"fully bent" always reads close to 4095 regardless of that specific
sensor's raw resistance range), and transmit the result over ESP-NOW.

The calibration routine (`runCalibrationRoutine`, triggered by sending `c`
over Serial) exists because two physically identical flex sensors don't
produce identical raw ADC values — without per-sensor calibration, that
manufacturing variance would show up in training data as noise unrelated
to the actual gesture.

---

## Phase 2 — Receiver Firmware

**Files:** `firmware/receiver/src/{receiver_firmware.ino, config.h, packet.h, frame.h}`

`packet.h` was copied byte-for-byte from the glove project — not
reimplemented, copied — because any divergence between the two copies
would cause silent misreads with no error raised anywhere.

**The key design decision here**, and the one most worth understanding:
the receiver does **not** wait for a matched left+right pair before
forwarding data to the Pi. Early in the design, a "wait for both hands"
approach was considered and rejected — a single dropped packet from either
glove would stall the entire pipeline. Instead, `receiver_firmware.ino`
runs on a fixed 20ms timer (`FORWARD_INTERVAL_MS`, matching the gloves'
50Hz) and forwards whatever the *freshest known* data from each hand is at
that moment, tagging each hand `left_valid`/`right_valid` based on whether
it arrived within the last 30ms. This is called "sample-and-hold" in the
code comments, and it's why `frame.h` carries those two validity flags —
the receiver doesn't decide what stale data means, it just reports
freshness and lets the Pi decide.

`frame.h` is the second data contract — this one between the receiver and
the Pi, carrying a frame sequence number, both hands' validity flags, and
both hands' raw packets, wrapped in sync bytes (`0xAA 0x55`) and a length
prefix so the Pi's Python parser can resynchronize if it ever loses byte
alignment on the UART stream.

A small but real fix happened here partway through: the firmware's debug
stats originally printed a boolean "have we ever seen this glove" instead
of an actual delivery ratio. This was caught and fixed when building the
later testing tools (Phase 6) that needed a real percentage to log —
`printDebugStats()` now computes `(expected - dropped) / expected` from the
sequence numbers instead.

---

## Phase 3 — Raspberry Pi Hub Application

**Files:** `pi-side/signyales_hub/*.py`

Built in dependency order, each module doing one job:

- **`serial_link.py`** — the Python half of the `frame.h` contract. The
  struct format string (`GLOVE_FMT = "<BII5H3f3fB"`) has to match the C
  struct field-for-field; this was verified with an actual round-trip test
  (Phase 3b below), not just written and assumed correct.
- **`windowing.py`** — turns a stream of individual frames into fixed-size
  (50-frame) windows, since the model needs a full window of motion to
  classify a gesture, not a single instant.
- **`model_runtime.py`** — loads a TFLite model, but is deliberately
  written to degrade gracefully when no model exists yet (`predict()`
  returns `(None, 0.0)` instead of raising). This was intentional: it let
  the rest of the pipeline be built and tested *before* a trained model
  existed, rather than blocking on Phase 4 finishing first.
- **`gesture_debounce.py`** — only lets a gesture through to output once
  it's been predicted consistently, above a confidence threshold, for
  several consecutive inferences. Without this, raw per-window predictions
  flicker between adjacent gestures mid-transition.
- **`tts_engine.py`** — runs speech synthesis on a background thread with a
  queue, so speaking a phrase never blocks the next frame from being read.
- **`status_led.py`** — originally written against `RPi.GPIO`, then
  rebuilt against `gpiozero`/`lgpio` once the target hardware was specified
  as a Raspberry Pi 5, because `RPi.GPIO` doesn't reliably support the Pi
  5's RP1 I/O chip.
- **`main.py`** — wires all of the above into one loop: read frame → extract
  features → push to window → run inference every N frames → debounce →
  speak.

**Phase 3b — verification, not assumption:** `tests/test_frame_roundtrip.py`
was written specifically to pack a synthetic frame using the exact C struct
layout, confirm Python decodes it back correctly, and confirm a
deliberately corrupted byte gets rejected. This was run and passed before
trusting the format in any other code. Separately, the entire `main.py`
loop was run with `--simulate` (synthetic data, no hardware) to confirm the
whole chain executes without errors, both with and without a model present.

---

## Phase 4 — TinyML Training Pipeline

**Files:** `training/{src/*.py, train.ipynb}`

Built after the hub existed, because the training pipeline's entire job is
producing an artifact (`model.tflite` + `labels.json` + `scaler.json`) that
the hub already knew how to consume — building it first would have meant
guessing at a format instead of matching one that already worked.

- **`collect_gesture.py`** (lives in `pi-side/tools/`, not `training/`,
  deliberately — it needs the hub's own live serial connection) reuses
  `windowing.py`'s `extract_features()` directly, rather than
  re-implementing feature extraction, specifically so training data is
  guaranteed to be built from the identical feature vector the hub uses
  at inference time.
- **`dataset.py` / `model.py` / `export.py` / `train.py`** — a standard
  load → train → evaluate → export pipeline, using a compact 1D-CNN sized
  to not overfit a hand-collected dataset.

**Verification here was unusually thorough**, because this is the one
layer that can't be checked by inspection — a bug here produces a model
that trains successfully but predicts garbage. A synthetic dataset (3
distinguishable classes) was generated, trained with the real `train.py`,
and the exported model was loaded back through the hub's *actual*
`model_runtime.py` — not a separate test script — and correctly classified
a held-out example. This caught a real bug: `train.py`'s default output
path only resolved correctly depending on which directory it was run from.
It was fixed by computing the default from the script's own file location
(`Path(__file__).resolve()...`) instead of a directory-relative string, and
re-verified with the same end-to-end test afterward.
(Later change, October 2026: `train.py` no longer has a default output folder;
`--out-dir` is required, so a model is never written into `pi-side/model` by
accident. It also writes `train_report.json` and needs at least 10 recordings
per word. See `training/README.md`.)

---

## Phase 5 — Testing & Evaluation Tooling

**Files:** `pi-side/tools/{accuracy_logger.py, performance_logger.py, receiver_link_logger.py}`

Built last among the core software, once there was something real to
evaluate. Each reuses the hub's actual modules rather than reimplementing
parsing/inference logic, so results reflect real deployed behavior:

- **`accuracy_logger.py`** — prompts a tester through randomized gesture
  trials, logs expected vs. predicted, and produces the proposal's
  Recognition Accuracy Matrix as both a CSV and a plotted figure.
- **`performance_logger.py`** — logs packet delivery ratio (from the
  `left_valid`/`right_valid` flags already in every frame) and recognition
  latency over a session.
- **`receiver_link_logger.py`** — a lower-level alternative that taps the
  receiver's own debug serial output (the fixed stats-printing bug from
  Phase 2) for an ESP-NOW-hop-specific delivery ratio.

All three were smoke-tested with `--simulate` before being considered done.

---

## Phase 6 — Documentation

Six documents were produced after the code, deliberately in that order —
documenting a system that already existed and had been verified, rather
than documenting a plan:

1. **Software Requirements** — the original ranked component list, formalized
2. **System Implementation and Integration** — what was built and what was
   verified (the frame round-trip test, the synthetic end-to-end run),
   plus an explicit "not yet verified on real hardware" section
3. **Hardware Assembly Guide** — Bill of Materials plus two wiring diagrams
   (drawn with matplotlib for precision, iterated twice after the first
   draft had overlapping elements)
4. **Research Instruments** — the Google Forms questionnaire content
5. **Survey Analysis Template** — a working `.xlsx` with live formulas,
   recalculated and checked against a known example row before delivery
6. **Field Testing Procedure** — the protocol tying the hardware, the
   logging tools, and the survey together into one repeatable session

---

## Phase 7 — Repo Integration

The four components were restructured into a single repo-ready layout:
firmware converted to PlatformIO projects (with build-flag-based left/right
glove selection instead of hand-editing `config.h`), and everything merged
against the user's existing repository — which required reconciling a
pre-existing draft `packet_schema.md` (superseded, replaced with a document
explaining *why* the implemented format differs, not just that it does),
and renaming `pi-hub` → `pi-side` to match the existing repo's convention,
followed by a full re-verification that nothing broke in the rename
(`test_frame_roundtrip.py` re-run, and the training → export → hub-load
chain re-run from scratch after the folder move).

---

## How to use this document

If you're trying to understand how a specific piece works, the fastest
path is: find which phase built it above, read that section for the *why*,
then open the actual file for the *how* — every file referenced here still
has its own inline comments written at the same time as the code, not
added after the fact.
