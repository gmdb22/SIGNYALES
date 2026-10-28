"""
Signyales — Gesture Data Collection Tool
==========================================
Layer: feeds the training pipeline (training/). Records
labeled repetitions of a single gesture, one at a time, via the same
receiver-dongle UART link the hub application uses at runtime.

Deliberately imports serial_link.py and windowing.py FROM
signyales_hub rather than reimplementing frame parsing/feature
extraction here — this guarantees training data is built from the
exact same feature vector the hub will feed the model at inference
time. Re-deriving that logic separately is how these two things
quietly drift apart.

Each repetition is variable-length (you decide when a sign starts and
ends by pressing Enter) and is resampled to a fixed number of frames
(cfg.window_size_samples) via per-feature linear interpolation, since
a trained model needs a fixed input shape but a human doesn't sign at
a perfectly fixed speed.

Usage:
    python tools/collect_gesture.py --label kumusta --reps 20 \\
        --out ../training/data

    # Dry run of the TOOL itself (not for building a real dataset):
    python tools/collect_gesture.py --label test --reps 3 --simulate
"""

import argparse
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.serial_link import SimulatedFrameSource, open_receiver  # noqa: E402
from signyales_hub.windowing import extract_features  # noqa: E402


def resample_to_fixed_length(sequence: np.ndarray, target_len: int) -> np.ndarray:
    """
    sequence: (T, feature_count) array, T >= 2, arbitrary length.
    Returns: (target_len, feature_count), each feature independently
    resampled across time via linear interpolation.
    """
    t_orig = np.linspace(0, 1, num=sequence.shape[0])
    t_target = np.linspace(0, 1, num=target_len)
    resampled = np.empty((target_len, sequence.shape[1]), dtype=np.float32)
    for feature_idx in range(sequence.shape[1]):
        resampled[:, feature_idx] = np.interp(t_target, t_orig, sequence[:, feature_idx])
    return resampled


def record_one_repetition(source_iter, window_size: int) -> np.ndarray:
    """Buffers feature vectors until Enter is pressed, then resamples
    the buffered sequence to a fixed length."""
    print("  Recording... press Enter when the sign is finished.")
    buffer = []
    stop_flag = {"stop": False}

    def wait_for_enter():
        input()
        stop_flag["stop"] = True

    listener = threading.Thread(target=wait_for_enter, daemon=True)
    listener.start()

    for frame in source_iter:
        if stop_flag["stop"]:
            break
        buffer.append(extract_features(frame))

    if len(buffer) < 2:
        raise RuntimeError(
            "Recording too short (fewer than 2 samples) — try again, "
            "holding the sign a little longer before pressing Enter."
        )

    return resample_to_fixed_length(np.stack(buffer), window_size)


def main():
    p = argparse.ArgumentParser(description="Record labeled gesture windows for training")
    p.add_argument("--label", required=True, help="Gesture label, e.g. 'kumusta'")
    p.add_argument("--reps", type=int, default=20, help="Number of repetitions to record")
    p.add_argument("--out", default="../training/data", help="Output data root directory")
    p.add_argument("--port", default=None)
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--simulate", action="store_true",
                    help="Use synthetic frames — for testing this TOOL, not for building a real dataset")
    args = p.parse_args()

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud

    label_dir = Path(args.out) / args.label
    label_dir.mkdir(parents=True, exist_ok=True)
    start_index = len(list(label_dir.glob("rep_*.npz")))

    if args.simulate:
        print("NOTE: --simulate produces random data. Fine for testing this tool, "
              "useless for actually training a model.")
        source = SimulatedFrameSource(rate_hz=50)
    else:
        source = open_receiver(cfg)

    print(f"Recording gesture '{args.label}': {args.reps} repetitions -> {label_dir}")
    source_iter = iter(source)

    recorded = 0
    while recorded < args.reps:
        rep_num = start_index + recorded
        input(f"\n[{recorded + 1}/{args.reps}] Press Enter to START repetition {rep_num}...")
        try:
            window = record_one_repetition(source_iter, cfg.window_size_samples)
        except RuntimeError as exc:
            print(f"  Skipped: {exc}")
            continue

        out_path = label_dir / f"rep_{rep_num:04d}.npz"
        np.savez(out_path, features=window, label=args.label)
        print(f"  Saved {out_path} (shape={window.shape})")
        recorded += 1

    print(f"\nDone. {recorded} repetitions saved to {label_dir}")


if __name__ == "__main__":
    main()
