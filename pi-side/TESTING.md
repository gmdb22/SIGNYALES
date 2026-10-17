# Signyales — Testing & Evaluation Tooling

These tools produce the data behind the proposal's Recognition Accuracy
Matrix and Technical Performance Checklist. They're not part of the
deployed system — they run *against* it during a testing session.

| Tool | Produces | Extra hardware needed |
|---|---|---|
| `tools/accuracy_logger.py` | Recognition Accuracy Matrix (CSV + PNG), per-gesture accuracy, recognition latency | None beyond the normal system |
| `tools/performance_logger.py` | Pi-side packet delivery ratio, recognition latency over a session | None beyond the normal system |
| `tools/receiver_link_logger.py` | ESP-NOW-hop-specific packet delivery ratio (lower-level) | A second USB cable, receiver dongle → laptop |

All three reuse the actual `signyales_hub` modules (serial parsing,
windowing, model inference, debouncing) — they measure the real deployed
pipeline's behavior, not a simplified stand-in for it.

## Before every session: screen, speaker and link

Takes a minute and catches the most common demo failures (wrong audio output,
muted speaker, laptop not connected):

- Console: `python tools/output_check.py` (from `pi-side/`, venv active) shows a
  large test word and speaks a test phrase.
- GUI: Testing mode → **Subtitle and speaker check**. If a laptop mirrors the Pi,
  press **Send test word** on the Pi's Recognize tab: the laptop must show and
  speak "salamat".

These are listen-and-look checks with no automatic pass; write down what you
saw and heard.

## Recognition Accuracy Matrix

```
pip install -r requirements.txt -r requirements-testing.txt
python tools/accuracy_logger.py --gestures kumusta salamat oo hindi tulong \
    --trials 10 --model-dir model --out results/accuracy_session1
```

For each of the 50 trials (5 gestures × 10, in this example), it prompts
you to perform one named gesture, gives it up to `--timeout` seconds
(default 5s) to produce a stable recognition, and records whether the
result matched. Trial order is randomized by default (pass `--seed` for a
reproducible order) so the tester doesn't unconsciously perform gestures
better toward the end of a block.

Outputs:
- `..._accuracy_session1.csv` — one row per trial (expected, predicted,
  confidence, latency, correct)
- `..._accuracy_session1_matrix.csv` — the confusion matrix as a table
- `..._accuracy_session1_matrix.png` — the same, plotted (needs matplotlib)
- A printed summary: overall accuracy, per-gesture accuracy, and mean/std
  recognition latency — the same mean/SD treatment used elsewhere in the
  proposal's methodology

A `no_response` column captures trials where nothing stabilized within the
timeout — worth distinguishing from a wrong answer when writing up results,
since it points at a different problem (recognition too slow/uncertain,
rather than confusing two specific gestures).

If the model has a rest class whose label is listed in `silent_labels` in
`signyales_hub/config.py` (default `rest`), a confirmed rest is never
reported as a gesture, so a trial where only rest was recognized is also
recorded as `no_response`. Don't include the rest label in `--gestures`.

## Performance logging

```
python tools/performance_logger.py --model-dir model --duration 300 \
    --out results/perf_session1
```

Runs for a fixed duration (or until Ctrl+C) and reports:

- **Packet delivery ratio (Pi-side):** the percentage of frames where each
  hand's data was fresh, computed from `left_valid`/`right_valid` — no
  second cable needed.
- **Recognition latency:** time from usable sensor data resuming to a
  stable gesture being confirmed. This is *pipeline* latency, not the full
  human-gesture-to-speech latency — see the caveat in the script's own
  docstring before reporting it as the latter in your results chapter.
- **Stage timing:** inference time per `predict()` call (mean, p95, max),
  debounce wait per recognized gesture, and the spacing between frames
  reaching the Pi (about 20 ms expected; much less means a backlog burst).
  These are pieces of a latency budget measured on the Pi, not the
  glove-to-speech latency. Add `--log-inferences` to also save every
  inference (label, confidence, timing) to `<out>_inferences.csv`, for
  choosing the confidence threshold and debounce count.

## Lower-level link diagnostics (optional)

If accuracy or performance numbers look off and you need to know whether
the problem is the ESP-NOW hop specifically (gloves → receiver) rather
than something downstream, connect a second USB cable from the receiver
dongle to your laptop and run:

```
python tools/receiver_link_logger.py --port /dev/ttyUSB0 --duration 300 \
    --out results/receiver_link_session1.csv
```

This taps the receiver firmware's own once-per-second debug line (see the
receiver firmware README) and logs its per-hand delivery ratio, computed
on the dongle itself from actual sequence-number gaps — a more precise,
lower-level figure than the Pi-side ratio above, at the cost of needing
that extra cable.

## Freezing before field testing

Right before the first participant session, on the machine that will run
the sessions:

```
python tools/freeze_manifest.py --model-dir model --out results/freeze_manifest.json --strict
```

It writes the git commit, the SHA-256 of `model.tflite`, `labels.json`,
`scaler.json` (and `train_report.json` if it was copied too), every
`config.py` value and the installed package versions, and warns about
uncommitted changes or a model the hub can't load. `--strict` makes any
warning exit with code 1. Run it again (with a new `--out` name) after the
last session: if anything differs, something changed mid-study.

## A note on battery performance

None of these tools log battery data — that metric in the proposal's
checklist (runtime under continuous use) is inherently a physical
measurement (multimeter/voltage log against a stopwatch), not something
the software pipeline observes. Record it manually with a simple
timestamp + voltage reading table alongside a `performance_logger.py` run,
so both are on the same session timeline for the results chapter.
