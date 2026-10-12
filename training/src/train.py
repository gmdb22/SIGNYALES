"""
Signyales Training — Train and Export

Loads gesture windows collected by collect_gesture.py, trains the
compact 1D-CNN, evaluates it (including the accuracy matrix your
methodology chapter reports on), and exports model.tflite/labels.json/
scaler.json directly into the pi-side app's model/ directory.

--out-dir defaults to pi-side/model resolved from this file's own location,
so it's correct regardless of which directory you run this from:

Usage:
    python src/train.py --data-dir data
    python train.py --data-dir ../data          # if run from inside src/
    python src/train.py --data-dir data --quantize
"""

import argparse
from pathlib import Path

import numpy as np
import tensorflow as tf
from sklearn.model_selection import train_test_split
from sklearn.metrics import confusion_matrix, classification_report

from dataset import load_dataset
from model import build_model
from export import export_artifacts

# Computed from this file's own location rather than a string relative to
# the current working directory, so the default is correct whether you run
# this as `python src/train.py` from training/, or `python train.py` after
# cd-ing into training/src/ — both are documented usage patterns above, and
# a cwd-relative default would only work correctly for one of them.
DEFAULT_MODEL_OUT_DIR = str(Path(__file__).resolve().parent.parent.parent / "pi-side" / "model")


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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="data")
    p.add_argument("--out-dir", default=DEFAULT_MODEL_OUT_DIR,
                    help="Where to write model.tflite/labels.json/scaler.json. "
                         "Defaults to the pi-side app's model/ directory so it deploys "
                         "directly with no extra copying — override only if you want "
                         "the artifacts written somewhere else")
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--quantize", action="store_true",
                    help="Export an int8-quantized model instead of float32")
    args = p.parse_args()

    X, y, labels = load_dataset(args.data_dir)
    print(f"Loaded {X.shape[0]} samples across {len(labels)} labels: {labels}")
    if X.shape[0] < 20 * len(labels):
        print(
            "WARNING: fewer than ~20 samples per class on average. Results below "
            "are unlikely to generalize — this is a signal to collect more data, "
            "not to tune the model further."
        )

    # Stratified split so every class is represented in train/val/test
    # in roughly the same proportion it appears overall.
    X_train, X_temp, y_train, y_temp = train_test_split(
        X, y, test_size=0.3, stratify=y, random_state=42
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.5, stratify=y_temp, random_state=42
    )

    mean, std = compute_scaler(X_train)
    X_train_n = apply_scaler(X_train, mean, std)
    X_val_n = apply_scaler(X_val, mean, std)
    X_test_n = apply_scaler(X_test, mean, std)

    model = build_model(X.shape[1], X.shape[2], len(labels))
    model.summary()

    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_accuracy", patience=10, restore_best_weights=True
    )
    model.fit(
        X_train_n, y_train,
        validation_data=(X_val_n, y_val),
        epochs=args.epochs,
        batch_size=args.batch_size,
        callbacks=[early_stop],
        verbose=2,
    )

    test_loss, test_acc = model.evaluate(X_test_n, y_test, verbose=0)
    print(f"\nTest accuracy: {test_acc:.4f}  (loss: {test_loss:.4f})")

    y_pred = model.predict(X_test_n, verbose=0).argmax(axis=1)
    print("\nConfusion matrix (rows=actual, cols=predicted):")
    print(confusion_matrix(y_test, y_pred))
    print("\nPer-class report:")
    print(classification_report(y_test, y_pred, target_names=labels, zero_division=0))

    export_artifacts(
        model, labels, mean, std, args.out_dir,
        quantize=args.quantize,
        representative_data=X_train_n if args.quantize else None,
    )


if __name__ == "__main__":
    main()
