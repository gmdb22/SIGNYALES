# Signyales — TinyML Training Pipeline

This is the offline half of the pipeline — it doesn't run at translation time.
It turns recorded gesture data into `model.tflite` + `labels.json` +
`scaler.json`, which `pi-side` loads at runtime.

```
collect_gesture.py (on the Pi, live gloves)
    -> data/<label>/rep_NNNN.npz
        -> train.ipynb or src/train.py (on a laptop, this project)
            -> model.tflite + labels.json + scaler.json
                -> copied by hand onto the Pi, into its pi-side/model/
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
python train.py --data-dir ../data --out-dir <folder outside the repo>
```

`--out-dir` is required. Write to a scratch folder outside the repo while a
model is being evaluated, so it can't be committed by accident and a
half-tested model never sits where the app looks for one. Only an accepted
model goes to the Pi (Step 3).

Besides the three model files, `train.py` writes `train_report.json` to the
same folder: label counts, a SHA-256 fingerprint of the data, the git commit,
the seed, library versions, the training history, the confusion matrix and
per-class report, and these checks:

- the data's window size and feature count against `pi-side/signyales_hub/config.py`
  (the hub refuses a model that doesn't match),
- mean and minimum confidence on validation and test windows against the
  hub's `confidence_threshold` (0.70). A model can be accurate and still
  never speak if its confidence sits below the threshold; the script prints
  a WARNING when the validation mean is below it,
- whether the exported files, loaded with the hub's own `GestureClassifier`,
  agree with the Keras model on the test windows.

`--seed` (default 42) fixes the data split and weight initialisation, so a
rerun on the same machine and library versions gives the same model.

Subfolders of `data/` whose names start with `_` or `.` are skipped. Rename
recordings that must not be trained on, such as the hardware handoff's
Stage 7b sanity set, e.g. `data/fist` to `data/_stage7b_fist`.

`train.ipynb` runs the same pipeline with the same seed. Its export cell
writes to `OUTPUT_DIR = "../../signyales_model_out"` (the folder next to the
repo folder); change it if you want another scratch folder. The notebook does
not write `train_report.json`.

Add `--quantize` to export an int8 model instead of float32 — mainly relevant
if this model ever needs to run on ESP32-class hardware directly (a future
direction mentioned in the proposal); for inference on the Pi 5 itself,
float32 is simpler to debug and fast enough.

## Step 3 — Deploy to the Pi

Training happens on a laptop and the app runs on the Pi, so the model does not
reach the Pi by itself. Once the model is accepted (confusion matrix, per-class
report, and mean confidence on held-out data above the hub's 0.70 threshold),
copy the three files onto the Pi, into its `pi-side/model/` folder:

- `model.tflite`
- `labels.json`
- `scaler.json`

Any method works: `scp`, a USB stick, or a shared folder. For example, from
PowerShell on the laptop (replace the user, address and repo path with your
Pi's; this command has not been tested here):

```
scp <scratch folder>\model.tflite <scratch folder>\labels.json <scratch folder>\scaler.json <pi-user>@<pi-address>:<path-to-repo>/pi-side/model/
```

The three files are git-ignored, so `git pull` will never bring them over and
they will not be committed. Copy all three together: they are one model, and
`labels.json` and `scaler.json` must come from the same training run as the
`.tflite`.

Then verify **on the Pi** (bash, folder `pi-side`, venv active):

```
source venv/bin/activate
python -m signyales_hub.main --simulate --model-dir model -v
```

You should see `Model loaded from model (N classes)` instead of the
"no usable model" warning. Then run `python tools/benchmark_inference.py` on
the Pi to confirm inference fits the real-time budget.

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
