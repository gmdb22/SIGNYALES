"""
Signyales Training — Train and Export

Loads gesture windows collected by collect_gesture.py, trains the
compact 1D-CNN, evaluates it (including the accuracy matrix your
methodology chapter reports on), and exports model.tflite/labels.json/
scaler.json plus a train_report.json into --out-dir.

--out-dir is required. Write to a scratch folder outside the repo while a
model is being evaluated, and copy the three model files to the Pi's
pi-side/model/ only once the model is accepted (see training/README.md).

Usage (from training/src/):
    python train.py --data-dir ../data --out-dir <folder outside the repo>
    python train.py --data-dir ../data --out-dir <folder> --quantize
    python train.py --data-dir ../data --out-dir <folder> --seed 7

After training it also:
  - checks the data's window size and feature count against the hub's
    pi-side/signyales_hub/config.py,
  - reports how confident the model is on validation and test windows
    compared with the hub's confidence_threshold (an accurate model whose
    confidence sits below the threshold never speaks; see finding F6),
  - loads the exported files with the hub's own GestureClassifier and
    checks it agrees with the Keras model on the test windows,
  - writes train_report.json (data counts and fingerprint, git commit,
    seed, versions, training history, metrics, the checks above).
"""

import argparse
import datetime
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, classification_report

from dataset import load_dataset, split_label_dirs
from model import build_model
from export import export_artifacts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PI_SIDE_DIR = REPO_ROOT / "pi-side"
APP_MODEL_DIR = PI_SIDE_DIR / "model"

# The hub's config.py is the single source of truth for the window size,
# feature count and confidence threshold. It has no third-party imports,
# so importing it here is cheap.
sys.path.append(str(PI_SIDE_DIR))
from signyales_hub.config import HubConfig  # noqa: E402


# The 70/15/15 stratified split needs every word in every part. 10 recordings
# per word always satisfies that (checked for 2 to 30 words); fewer can fail.
MIN_REPS_PER_WORD = 10


def compute_scaler(X_train: np.ndarray):
    """Mean/std per feature, computed ONLY on the training split —
    never on validation/test data, or the evaluation numbers would be
    quietly optimistic."""
    flattened = X_train.reshape(-1, X_train.shape[-1])
    mean = flattened.mean(axis=0)
    std = flattened.std(axis=0)
    std[std == 0] = 1.0  # guard against a constant feature column
    return mean, std


def apply_scaler(X: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    return (X - mean) / std


def confidence_summary(probs: np.ndarray, y_true: np.ndarray, threshold: float) -> dict:
    """How the model's top-class confidence compares with the hub threshold."""
    top = probs.max(axis=1)
    correct = probs.argmax(axis=1) == y_true
    return {
        "windows": int(len(top)),
        "mean_confidence": round(float(top.mean()), 4) if len(top) else None,
        "min_confidence": round(float(top.min()), 4) if len(top) else None,
        "fraction_at_or_above_threshold": round(float((top >= threshold).mean()), 4) if len(top) else None,
        "fraction_correct_and_above_threshold": (
            round(float((correct & (top >= threshold)).mean()), 4) if len(top) else None),
    }


def data_fingerprint(label_dirs) -> str:
    """SHA-256 over every rep_*.npz (relative path + bytes), in sorted order.
    Same data -> same fingerprint, so a model can be traced to its dataset."""
    h = hashlib.sha256()
    for d in label_dirs:
        for f in sorted(d.glob("rep_*.npz")):
            h.update(f"{d.name}/{f.name}".encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def git_info() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    commit = run("rev-parse", "HEAD")
    return {
        "commit": commit or None,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD") or None,
        "uncommitted_changes": bool(run("status", "--porcelain")) if commit else None,
    }


def runtime_agreement(out_dir: Path, X_test_raw: np.ndarray, keras_pred: np.ndarray,
                      labels, cfg: HubConfig) -> dict:
    """Loads the exported files with the hub's own GestureClassifier and
    compares its labels with the Keras model on the (unnormalised) test
    windows. Catches export, scaler or label-order mistakes before the Pi."""
    from signyales_hub.model_runtime import GestureClassifier
    clf = GestureClassifier(str(out_dir), expected_window=cfg.window_size_samples,
                            expected_features=cfg.feature_count)
    if not clf.available:
        return {"loaded": False, "agree": None, "total": int(len(X_test_raw))}
    agree = sum(clf.predict(x)[0] == labels[p] for x, p in zip(X_test_raw, keras_pred))
    return {"loaded": True, "agree": int(agree), "total": int(len(X_test_raw))}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", required=True,
                    help="Where to write model.tflite/labels.json/scaler.json/train_report.json. "
                         "Use a scratch folder outside the repo until the model is accepted.")
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--seed", type=int, default=42,
                    help="Seed for the data split and weight initialisation (default 42)")
    p.add_argument("--quantize", action="store_true",
                    help="Export an int8-quantized model instead of float32")
    args = p.parse_args()

    out_dir = Path(args.out_dir).resolve()
    if out_dir == APP_MODEL_DIR.resolve():
        print(f"NOTE: writing straight into the app's model folder ({APP_MODEL_DIR}). "
              f"Only do this for a model that has already been accepted.")

    cfg = HubConfig()
    threshold = cfg.confidence_threshold

    # Seeds Python, NumPy and TensorFlow. Makes reruns repeatable on the same
    # machine and library versions; results can still differ slightly across
    # machines or TensorFlow versions.
    tf.keras.utils.set_random_seed(args.seed)

    X, y, labels = load_dataset(args.data_dir)
    label_dirs, skipped_dirs = split_label_dirs(args.data_dir)
    print(f"Loaded {X.shape[0]} samples across {len(labels)} labels: {labels}")
    too_few = {lbl: int((y == i).sum()) for i, lbl in enumerate(labels)
               if (y == i).sum() < MIN_REPS_PER_WORD}
    if too_few:
        listing = ", ".join(f"{w} ({n})" for w, n in too_few.items())
        print(f"ERROR: too few recordings to train: {listing}. Each word needs at least "
              f"{MIN_REPS_PER_WORD} (20 or more recommended) so it can appear in the training, "
              f"validation and test parts. Record more, then train again.")
        sys.exit(2)
    if X.shape[0] < 20 * len(labels):
        print(
            "WARNING: fewer than ~20 samples per class on average. Results below "
            "are unlikely to generalize — this is a signal to collect more data, "
            "not to tune the model further."
        )

    config_problems = []
    if X.shape[1] != cfg.window_size_samples:
        config_problems.append(f"data windows have {X.shape[1]} samples but config.py "
                               f"window_size_samples is {cfg.window_size_samples}")
    if X.shape[2] != cfg.feature_count:
        config_problems.append(f"data has {X.shape[2]} features but config.py "
                               f"feature_count is {cfg.feature_count}")
    for msg in config_problems:
        print(f"WARNING: {msg}. The hub will refuse to load this model until they match.")

    # Stratified split so every class is represented in train/val/test
    # in roughly the same proportion it appears overall.
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=args.seed
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, stratify=y_temp, random_state=args.seed
    )

    mean, std = compute_scaler(X_train)
    X_train_n = apply_scaler(X_train, mean, std)
    X_val_n = apply_scaler(X_val, mean, std)
    X_test_n = apply_scaler(X_test, mean, std)

    model = build_model(X.shape[1], X.shape[2], len(labels))
    model.summary()

    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=10, restore_best_weights=True
    )
    history = model.fit(
        X_train_n, y_train,
        validation_data=(X_val_n, y_val),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=[early_stop],
        verbose=2,
    )

    test_loss, test_acc = model.evaluate(X_test_n, y_test, verbose=0)
    print(f"\nTest accuracy: {test_acc:.4f}  (loss: {test_loss:.4f})")

    test_probs = model.predict(X_test_n, verbose=0)
    val_probs = model.predict(X_val_n, verbose=0)
    y_pred = test_probs.argmax(axis=1)
    cm = confusion_matrix(y_test, y_pred, labels=list(range(len(labels))))
    print("\nConfusion matrix (rows=actual, cols=predicted):")
    print(cm)
    print("\nPer-class report:")
    print(classification_report(y_test, y_pred, labels=list(range(len(labels))),
                                target_names=labels, zero_division=0))

    val_conf = confidence_summary(val_probs, y_val, threshold)
    test_conf = confidence_summary(test_probs, y_test, threshold)
    print(f"Confidence vs the hub threshold ({threshold:.2f}):")
    for name, c in (("validation", val_conf), ("test", test_conf)):
        print(f"  {name}: mean={c['mean_confidence']}, min={c['min_confidence']}, "
              f"at/above threshold={c['fraction_at_or_above_threshold']:.0%}, "
              f"correct and at/above={c['fraction_correct_and_above_threshold']:.0%}")
    if val_conf["mean_confidence"] is not None and val_conf["mean_confidence"] < threshold:
        print(f"WARNING: mean validation confidence is below {threshold:.2f}. The hub would "
              f"stay silent on many correct predictions. Train longer or collect more data "
              f"before accepting this model.")

    export_artifacts(
        model, labels, mean, std, str(out_dir),
        quantize=args.quantize,
        representative_data=X_train_n if args.quantize else None,
    )

    agreement = runtime_agreement(out_dir, X_test, y_pred, labels, cfg)
    if agreement["loaded"]:
        print(f"Hub runtime check: exported model agrees with Keras on "
              f"{agreement['agree']}/{agreement['total']} test windows.")
        if agreement["agree"] < agreement["total"]:
            print("  Some disagreement is normal for --quantize; for float32 it points at an "
                  "export or scaler problem.")
    else:
        print("WARNING: the hub's GestureClassifier could not load the exported model "
              "(see the warning above for the reason).")

    epochs_run = len(history.history["loss"])
    val_losses = history.history.get("val_loss", [])
    report = {
        "created": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": "Generated by training/src/train.py. Describes this run only.",
        "git": git_info(),
        "versions": {
            "python": platform.python_version(),
            "tensorflow": tf.__version__,
            "numpy": np.__version__,
            "platform": platform.platform(),
        },
        "args": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
        "data": {
            "data_dir": str(Path(args.data_dir).resolve()),
            "labels": labels,
            "samples_per_label": {lbl: int((y == i).sum()) for i, lbl in enumerate(labels)},
            "skipped_folders": [d.name for d in skipped_dirs],
            "window_size": int(X.shape[1]),
            "feature_count": int(X.shape[2]),
            "split_counts": {"train": int(len(y_train)), "val": int(len(y_val)),
                             "test": int(len(y_test))},
            "split_method": "random stratified 70/15/15 (not grouped by session or wearer)",
            "fingerprint_sha256": data_fingerprint(label_dirs),
        },
        "hub_config_check": {
            "window_size_samples": cfg.window_size_samples,
            "feature_count": cfg.feature_count,
            "confidence_threshold": threshold,
            "problems": config_problems,
        },
        "training": {
            "epochs_run": epochs_run,
            "best_epoch": int(np.argmin(val_losses)) + 1 if val_losses else None,
            "stopped_early": epochs_run < args.epochs,
            "history": {k: [round(float(v), 6) for v in vals]
                        for k, vals in history.history.items()},
        },
        "test": {
            "accuracy": round(float(test_acc), 4),
            "loss": round(float(test_loss), 4),
            "confusion_matrix": cm.tolist(),
            "per_class": classification_report(y_test, y_pred, labels=list(range(len(labels))),
                                               target_names=labels, zero_division=0,
                                               output_dict=True),
        },
        "confidence": {"validation": val_conf, "test": test_conf},
        "export": {"quantized_int8": args.quantize, "hub_runtime_agreement": agreement},
    }
    with open(out_dir / "train_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Training report written to {out_dir / 'train_report.json'}")


if __name__ == "__main__":
    main()
