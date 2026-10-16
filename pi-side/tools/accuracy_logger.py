"""
Signyales — Recognition Accuracy Logger
==========================================
Testing tool that produces the Recognition Accuracy Matrix described in the
proposal's evaluation methodology: for each named gesture, prompts the
tester to perform it, runs the live pipeline, and records whether the
system correctly recognized it within a timeout.

Deliberately reuses the exact serial_link / windowing / model_runtime /
gesture_debounce modules the hub uses at runtime — this measures the real
deployed behavior, not a simplified test harness that could pass while the
actual system doesn't.

Usage:
    python tools/accuracy_logger.py --gestures kumusta salamat oo hindi \\
        --trials 10 --model-dir model --out results/accuracy_run1

    # Dry run of the TOOL itself — synthetic data, no hardware/model needed:
    python tools/accuracy_logger.py --gestures a b --trials 2 --simulate
"""

import argparse
import csv
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.serial_link import SerialFrameReader, SimulatedFrameSource  # noqa: E402
from signyales_hub.windowing import WindowBuffer, extract_features  # noqa: E402
from signyales_hub.model_runtime import GestureClassifier  # noqa: E402
from signyales_hub.gesture_debounce import GestureDebouncer  # noqa: E402

NO_RESPONSE = "no_response"


def run_trial(source_iter, cfg, classifier, timeout_s):
    """
    Runs the live pipeline for up to timeout_s seconds, or until a stable
    gesture is confirmed.
    Returns (predicted_label_or_NO_RESPONSE, confidence, latency_s).
    """
    window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)
    debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold,
                                 silent_labels=cfg.silent_labels)

    start = time.monotonic()
    frame_count = 0

    for frame in source_iter:
        if time.monotonic() - start > timeout_s:
            return NO_RESPONSE, 0.0, timeout_s

        frame_count += 1
        hands_ok = frame["left_valid"] or frame["right_valid"]
        if not hands_ok:
            continue

        window.push(extract_features(frame))
        if not window.is_full():
            continue
        if frame_count % cfg.stride_samples != 0:
            continue

        label, confidence = classifier.predict(window.as_array())
        if label is None:
            continue

        stable = debouncer.update(label, confidence)
        if stable:
            return stable, confidence, time.monotonic() - start

    return NO_RESPONSE, 0.0, timeout_s  # source exhausted — shouldn't normally happen


def main():
    p = argparse.ArgumentParser(description="Record Recognition Accuracy Matrix trials")
    p.add_argument("--gestures", nargs="+", required=True, help="Gesture labels to test")
    p.add_argument("--trials", type=int, default=10, help="Trials per gesture")
    p.add_argument("--timeout", type=float, default=5.0, help="Seconds to wait for a stable prediction per trial")
    p.add_argument("--model-dir", default="model")
    p.add_argument("--out", default="results/accuracy_run", help="Output path prefix (no extension)")
    p.add_argument("--seed", type=int, default=None, help="Shuffle seed for trial order (default: random each run)")
    p.add_argument("--port", default=None)
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--simulate", action="store_true",
                    help="Test the TOOL itself with synthetic data — not valid for real evaluation")
    args = p.parse_args()

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud
    if args.model_dir:
        cfg.model_dir = args.model_dir

    classifier = GestureClassifier(cfg.model_dir, expected_window=cfg.window_size_samples,
                                   expected_features=cfg.feature_count)
    if not classifier.available:
        print(f"FATAL: no usable model at '{cfg.model_dir}'. Train and export one first "
              f"(see training/) before running accuracy tests.")
        return

    if args.simulate:
        source = SimulatedFrameSource(rate_hz=50)
    else:
        source = SerialFrameReader(cfg.serial_port, cfg.serial_baud)
    source_iter = iter(source)

    trial_plan = []
    for label in args.gestures:
        trial_plan += [label] * args.trials
    rng = random.Random(args.seed)
    rng.shuffle(trial_plan)  # randomized order avoids order-effect bias in the results

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = out_path.with_suffix(".csv")

    rows = []
    print(f"Running {len(trial_plan)} trials across {len(args.gestures)} gestures "
          f"({args.trials} each, order randomized).\n")

    for i, expected in enumerate(trial_plan, start=1):
        input(f"[{i}/{len(trial_plan)}] Perform gesture: '{expected}' — press Enter to start "
              f"({args.timeout:.0f}s to recognize)...")
        predicted, confidence, latency = run_trial(source_iter, cfg, classifier, args.timeout)
        correct = predicted == expected
        print(f"  -> predicted '{predicted}' (confidence={confidence:.2f}, latency={latency:.2f}s) "
              f"{'CORRECT' if correct else 'WRONG'}")
        rows.append({
            "trial": i, "expected": expected, "predicted": predicted,
            "confidence": confidence, "latency_s": latency, "correct": correct,
        })

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["trial", "expected", "predicted", "confidence", "latency_s", "correct"]
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nRaw results saved to {csv_path}")

    labels = sorted(set(args.gestures))
    matrix_labels = labels + [NO_RESPONSE]
    matrix = np.zeros((len(labels), len(matrix_labels)), dtype=int)
    for row in rows:
        i = labels.index(row["expected"])
        j = matrix_labels.index(row["predicted"]) if row["predicted"] in matrix_labels else matrix_labels.index(NO_RESPONSE)
        matrix[i, j] += 1

    matrix_csv_path = out_path.parent / (out_path.name + "_matrix.csv")
    with open(matrix_csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["actual \\ predicted"] + matrix_labels)
        for i, label in enumerate(labels):
            writer.writerow([label] + list(matrix[i]))
    print(f"Confusion matrix saved to {matrix_csv_path}")

    try:
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(1.2 * len(matrix_labels) + 2, 1.2 * len(labels) + 2))
        im = ax.imshow(matrix, cmap="Blues")
        ax.set_xticks(range(len(matrix_labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(matrix_labels, rotation=45, ha="right")
        ax.set_yticklabels(labels)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual (performed) gesture")
        ax.set_title("Recognition Accuracy Matrix")
        for i in range(len(labels)):
            for j in range(len(matrix_labels)):
                ax.text(j, i, matrix[i, j], ha="center", va="center",
                        color="white" if matrix[i, j] > matrix.max() / 2 else "black")
        plt.colorbar(im)
        plt.tight_layout()
        png_path = out_path.parent / (out_path.name + "_matrix.png")
        plt.savefig(png_path, dpi=150)
        print(f"Confusion matrix plot saved to {png_path}")
    except ImportError:
        print("matplotlib not installed — skipping the plotted matrix (CSV was still saved). "
              "pip install matplotlib to enable it.")

    total = len(rows)
    correct_count = sum(r["correct"] for r in rows)
    overall_accuracy = correct_count / total if total else 0.0
    latencies = [r["latency_s"] for r in rows if r["predicted"] != NO_RESPONSE]

    print("\n=== Summary ===")
    print(f"Overall accuracy: {overall_accuracy * 100:.1f}% ({correct_count}/{total})")
    for label in labels:
        label_rows = [r for r in rows if r["expected"] == label]
        label_correct = sum(r["correct"] for r in label_rows)
        pct = (label_correct / len(label_rows) * 100) if label_rows else 0.0
        print(f"  {label}: {pct:.1f}% ({label_correct}/{len(label_rows)})")

    if latencies:
        mean_latency = statistics.mean(latencies)
        # Sample standard deviation (n - 1), as the proposal specifies.
        std_text = f"{statistics.stdev(latencies):.2f}s" if len(latencies) > 1 else "n/a (needs 2+ trials)"
        print(f"Recognition latency (trials with a response): mean={mean_latency:.2f}s, "
              f"sample std={std_text}")


if __name__ == "__main__":
    main()
