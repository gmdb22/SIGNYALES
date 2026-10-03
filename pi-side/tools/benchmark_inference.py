"""
Signyales Pi-Side App — Inference Benchmark

Measures how long a single model.predict() call actually takes on
this Pi 5, using random data shaped like a real window. Use this once
a real model is in place to decide whether config.py's stride_samples
(how often inference runs) is set sensibly — if inference takes
longer than the time between strides, the pipeline will fall behind
the live sensor stream.

Run: python tools/benchmark_inference.py --model-dir model --runs 200
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.model_runtime import GestureClassifier  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model-dir", default="model")
    p.add_argument("--runs", type=int, default=200)
    args = p.parse_args()

    cfg = HubConfig()
    classifier = GestureClassifier(args.model_dir)
    if not classifier.available:
        print(f"No model found in '{args.model_dir}' — nothing to benchmark. "
              f"Place model.tflite/labels.json/scaler.json there first.")
        return

    window = np.random.rand(cfg.window_size_samples, cfg.feature_count).astype(np.float32)

    # Warm up (first call often includes one-time setup cost).
    classifier.predict(window)

    durations_ms = []
    for _ in range(args.runs):
        start = time.perf_counter()
        classifier.predict(window)
        durations_ms.append((time.perf_counter() - start) * 1000)

    durations_ms.sort()
    mean_ms = sum(durations_ms) / len(durations_ms)
    p50 = durations_ms[len(durations_ms) // 2]
    p95 = durations_ms[int(len(durations_ms) * 0.95)]

    stride_period_ms = (cfg.stride_samples / 50.0) * 1000  # assumes 50 Hz sample rate
    print(f"Inference latency over {args.runs} runs:")
    print(f"  mean: {mean_ms:.2f} ms   p50: {p50:.2f} ms   p95: {p95:.2f} ms")
    print(f"  Current stride_samples={cfg.stride_samples} allows "
          f"{stride_period_ms:.1f} ms between inferences.")
    if p95 > stride_period_ms:
        print("  WARNING: p95 latency exceeds the time between strides — "
              "the pipeline will fall behind. Increase stride_samples in config.py.")
    else:
        print("  OK: comfortable margin at the current stride setting.")


if __name__ == "__main__":
    main()
