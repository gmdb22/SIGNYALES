"""
Signyales — training pipeline smoke test (synthetic data, needs TensorFlow)

Trains on a small SYNTHETIC dataset in a temporary folder and checks the
training-to-hub contract end to end:
  - train.py refuses to run without --out-dir,
  - folders starting with "_" are skipped (F14),
  - a float32 export loads in the hub's GestureClassifier, agrees with the
    Keras model, and clears the hub's 0.70 confidence threshold (F6),
  - an int8 export loads, and its confidences are real probabilities in
    [0, 1] (F7),
  - train_report.json is written with the expected contents,
  - data whose window size doesn't match config.py is flagged, and the hub
    refuses the resulting model.

Synthetic data proves the code path works. It says nothing about accuracy
on real signing. Nothing is written inside the repo (all output goes to a
temporary folder that is deleted afterwards).

Needs: numpy, tensorflow (or tensorflow-cpu), scikit-learn.
Run (from the repo root or anywhere):
    python training/tests/test_train_smoke.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
TRAIN = REPO / "training" / "src" / "train.py"
sys.path.insert(0, str(REPO / "pi-side"))
sys.path.insert(0, str(REPO / "training" / "src"))

LABELS = ["alpha", "bravo", "charlie"]
REPS = 24
failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f"  ({detail})" if detail else ""))
        failures.append(name)


def make_dataset(root: Path, window: int):
    rng = np.random.default_rng(0)
    for ci, label in enumerate(LABELS):
        d = root / label
        d.mkdir(parents=True)
        for r in range(REPS):
            x = rng.normal(0, 1, (window, 22)).astype(np.float32)
            x[:, ci * 3:ci * 3 + 3] += 2.5          # class-dependent channels
            np.savez(d / f"rep_{r:04d}.npz", features=x * 100 + 2000, label=label)


def train(data: Path, out: Path = None, extra=()):
    cmd = [sys.executable, str(TRAIN), "--data-dir", str(data), "--epochs", "20", *extra]
    if out is not None:
        cmd += ["--out-dir", str(out)]
    env = dict(os.environ, TF_CPP_MIN_LOG_LEVEL="2")
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0 and out is not None:
        print((p.stdout + p.stderr)[-3000:])
    return p


def main():
    tmp = Path(tempfile.mkdtemp(prefix="signyales_train_smoke_"))
    try:
        data = tmp / "data"
        make_dataset(data, window=50)
        skip = data / "_stage7b_fist"
        skip.mkdir()
        shutil.copy(data / "alpha" / "rep_0000.npz", skip / "rep_0000.npz")

        from dataset import split_label_dirs
        used, skipped = split_label_dirs(data)
        check("dataset: '_' folder skipped, real labels kept",
              [d.name for d in used] == LABELS and [d.name for d in skipped] == ["_stage7b_fist"])

        p = train(data, out=None)
        check("train.py without --out-dir exits with an error",
              p.returncode != 0 and "--out-dir" in p.stderr)

        from signyales_hub.model_runtime import GestureClassifier
        X = np.stack([np.load(f)["features"] for lbl in LABELS
                      for f in sorted((data / lbl).glob("rep_*.npz"))])

        # ---- float32
        f32 = tmp / "model_f32"
        p = train(data, f32)
        check("float32: train.py exits 0", p.returncode == 0)
        report = json.loads((f32 / "train_report.json").read_text()) if p.returncode == 0 else {}
        check("float32: all four files written",
              all((f32 / n).exists() for n in ("model.tflite", "labels.json", "scaler.json",
                                                "train_report.json")))
        check("report: labels, counts and skipped folder recorded",
              report.get("data", {}).get("labels") == LABELS
              and report["data"]["samples_per_label"] == {lbl: REPS for lbl in LABELS}
              and report["data"]["skipped_folders"] == ["_stage7b_fist"])
        check("report: no config problems for 50x22 data",
              report.get("hub_config_check", {}).get("problems") == [])
        check("report: exported model agrees with Keras on every test window",
              report.get("export", {}).get("hub_runtime_agreement", {}).get("agree")
              == report.get("export", {}).get("hub_runtime_agreement", {}).get("total"))
        val_mean = report.get("confidence", {}).get("validation", {}).get("mean_confidence")
        check("F6: mean validation confidence clears the hub threshold (0.70)",
              val_mean is not None and val_mean >= 0.70, val_mean)

        clf = GestureClassifier(str(f32), expected_window=50, expected_features=22)
        check("float32: loads in the hub runtime", clf.available)

        # ---- int8
        i8 = tmp / "model_int8"
        p = train(data, i8, extra=("--quantize",))
        check("int8: train.py --quantize exits 0", p.returncode == 0)
        clf8 = GestureClassifier(str(i8), expected_window=50, expected_features=22)
        check("int8: loads in the hub runtime with int8 input",
              clf8.available and clf8.input_details[0]["dtype"] == np.int8)
        if clf8.available and clf.available:
            idx = np.random.default_rng(1).choice(len(X), 12, replace=False)
            preds8 = [clf8.predict(X[i]) for i in idx]
            preds32 = [clf.predict(X[i]) for i in idx]
            confs = [c for _, c in preds8]
            check("F7: int8 confidences are probabilities in [0, 1]",
                  all(0.0 <= c <= 1.0 for c in confs), f"min={min(confs)}, max={max(confs)}")
            agree = sum(a[0] == b[0] for a, b in zip(preds8, preds32))
            check("int8: labels agree with float32 on >= 10 of 12 windows", agree >= 10, agree)

        # ---- window mismatch
        data40 = tmp / "data40"
        make_dataset(data40, window=40)
        m40 = tmp / "model_w40"
        p = train(data40, m40, extra=("--epochs", "2"))
        r40 = json.loads((m40 / "train_report.json").read_text()) if p.returncode == 0 else {}
        check("mismatch: 40-sample data is flagged against config.py",
              any("40 samples" in s for s in r40.get("hub_config_check", {}).get("problems", [])))
        check("mismatch: hub refuses the 40-sample model",
              not GestureClassifier(str(m40), expected_window=50, expected_features=22).available)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {failures}")
        sys.exit(1)
    print("All training smoke checks passed (synthetic data only; not an accuracy result).")


if __name__ == "__main__":
    main()
