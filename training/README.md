# Signyales — TinyML Training Pipeline

This is the offline half of the pipeline — it doesn't run at translation time.
It turns recorded gesture data into `model.tflite` + `labels.json` +
`scaler.json`, which `pi-side` loads at runtime.

```
collect_gesture.py (on the Pi, live gloves)
    -> data/<label>/rep_NNNN.npz
        -> train.ipynb or src/train.py (on a laptop, this project)
            -> model.tflite + labels.json + scaler.json
                -> copied into pi-side/model/
```

## What's in this folder

| File | Purpose |
|---|---|
| `train.ipynb` | The main entry point — narrated, step-by-step, matches the proposal's "developed in Jupyter Notebook" methodology. |
| `src/dataset.py` | Loads collected `.npz` windows into arrays. |
| `src/model.py` | The model architecture (compact 1D-CNN). |
| `src/export.py` | Converts the trained model to TFLite and writes the three deployment artifacts. |
| `src/train.py` | Same pipeline as the notebook, as a plain CLI script — useful for quick reruns without opening Jupyter. |
| `data/` | Where collected recordings go (empty until you record something). |

## Step 1 — Collect data

This step actually happens over in `pi-side`, since it needs the live
gloves and receiver connected to a Pi:

```
cd ../pi-side
python tools/collect_gesture.py --label kumusta --reps 20 --out ../training/data
python tools/collect_gesture.py --label salamat --reps 20 --out ../training/data
# ...repeat per gesture
```

Record from a few different sessions/wearers if possible — a model trained on
one uninterrupted 10-minute session tends to learn that session's specific
noise as much as the gesture itself, and won't generalize as well to a
field-testing day.

## Step 2 — Train

Either open `train.ipynb` in Jupyter and run cells top to bottom, or:

```
pip install -r requirements.txt
cd src
python train.py --data-dir ../data
```

`--out-dir` defaults to the pi-side app's `model/` directory automatically
(resolved from this script's own location, not your current directory), so
you don't need to pass it explicitly — it works the same whether you run
this from `training/` or from `training/src/`.

Add `--quantize` to export an int8 model instead of float32 — mainly relevant
if this model ever needs to run on ESP32-class hardware directly (a future
direction mentioned in the proposal); for inference on the Pi 5 itself,
float32 is simpler to debug and fast enough.

## Step 3 — Deploy

There's nothing left to do — the default `--out-dir` already points at the
pi-side app's `model/` directory, so the hub picks up the new model on its
next run. Verify with:

```
cd ../../pi-side
python -m signyales_hub.main --simulate --model-dir model -v
```

You should see `Model loaded from model (N classes)` instead of the
"no usable model" warning.

## The artifact contract, restated

`export_artifacts()` in `src/export.py` writes exactly what
`signyales_hub/model_runtime.py` expects to read:

- **`model.tflite`** — the trained model
- **`labels.json`** — gesture strings, index-aligned to output classes,
  **sorted alphabetically by folder name** (see `dataset.py` — this is where
  label ordering is decided; don't reorder it by hand afterward)
- **`scaler.json`** — per-feature mean/std, computed **only** on the training
  split (never on validation/test — that would leak test statistics into
  training and make reported accuracy look better than it really is)

The 22-feature order (`left_flex(5), right_flex(5), left_accel(3),
left_gyro(3), right_accel(3), right_gyro(3)`) is fixed by
`collect_gesture.py`/`windowing.py` on the hub side. This pipeline never
needs to know that order explicitly — it just trusts whatever shape the
`.npz` files already have — but it's worth remembering if you ever hand-craft
a `.npz` file for testing.

## What this notebook/script does NOT do

- **No live validation against real hardware.** A high test-set accuracy
  here only proves the model separates the *recorded* windows well — it
  doesn't prove the receiver's sample-and-hold synchronization, or a
  different wearer's hand size, won't degrade real-world accuracy. Budget
  real field-testing time separately, exactly as the proposal's Recognition
  Accuracy Matrix testing phase intends.
- **No automatic hyperparameter search.** Epochs, batch size, and the
  model architecture in `src/model.py` are reasonable starting points, not
  tuned results — expect to revisit them once real data volume is known.
