"""
Signyales — Recording Inspector (no model required)
===================================================
Read-only sanity check of data recorded by collect_gesture.py, to run
BEFORE training. Does not modify any file.

For each gesture label it reports how many repetitions exist, whether any
contain NaN, how repeatable the flex values are across repetitions, and
whether each hand actually moved. Then it compares labels: channels whose
average value barely differs between two gestures (relative to how much the
same gesture varies) are flagged, since they can't help tell those gestures
apart.

Feature layout (see signyales_hub/windowing.py): columns 0-5 left flex,
6-11 right flex (thumb, index, middle, ring, pinky, palm), 12-23 accel/gyro.
Flex is stored scaled to 0-1 and shown here back in raw counts (0-4095).

Thresholds below are heuristics chosen for this tool, not proposal values.

Usage (from pi-side/, venv active):
    python tools/inspect_recordings.py --root ../training/data
"""

import argparse
import itertools
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from signyales_hub.serial_link import FLEX_NAMES, FLEX_PER_GLOVE  # noqa: E402

FLAT_STD_COUNTS = 5.0      # a hand whose flex never changes more than this is "flat"
MIN_REPS_WARN = 5
F = FLEX_PER_GLOVE
NAMES = [f"L{n[:3]}" for n in FLEX_NAMES] + [f"R{n[:3]}" for n in FLEX_NAMES]  # e.g. Lthu ... Rpal


def load_label(label_dir: Path):
    reps = []
    for f in sorted(label_dir.glob("rep_*.npz")):
        with np.load(f) as z:
            reps.append(z["features"])
    return np.stack(reps) if reps else None  # (N, T, 24)


def main():
    p = argparse.ArgumentParser(description="Sanity-check recorded gesture data")
    p.add_argument("--root", default="../training/data")
    args = p.parse_args()

    root = Path(args.root)
    labels = sorted(d for d in root.iterdir() if d.is_dir()) if root.is_dir() else []
    data = {}
    for d in labels:
        arr = load_label(d)
        if arr is not None:
            data[d.name] = arr
    if not data:
        print(f"No rep_*.npz recordings found under {root.resolve()}")
        return

    print(f"Found {len(data)} label(s) under {root.resolve()}\n")
    means, stds, problems = {}, {}, []
    for label, arr in data.items():
        n, t, f = arr.shape
        if f != 2 * F + 12:
            problems.append(f"{label}: {f} features per sample, expected {2 * F + 12} "
                            f"({F} flex per glove). Recorded with an older format? Re-record it.")
            continue
        flex_counts = arr[:, :, :2 * F] * 4095.0            # (N, T, 12)
        rep_mean = flex_counts.mean(axis=1)                  # (N, 12)
        means[label] = rep_mean.mean(axis=0)
        stds[label] = rep_mean.std(axis=0)                   # variation across reps
        motion = flex_counts.std(axis=1).mean(axis=0)        # movement inside a rep

        print(f"[{label}] reps={n} window={t}x{f}")
        if np.isnan(arr).any():
            problems.append(f"{label}: contains NaN values")
        if n < MIN_REPS_WARN:
            problems.append(f"{label}: only {n} reps (fewer than {MIN_REPS_WARN})")
        print("   channel : " + " ".join(f"{c:>6}" for c in NAMES))
        print("   mean    : " + " ".join(f"{v:6.0f}" for v in means[label]))
        print("   std/reps: " + " ".join(f"{v:6.0f}" for v in stds[label]))
        print("   in-rep  : " + " ".join(f"{v:6.0f}" for v in motion))
        for hand, sl in (("left", slice(0, F)), ("right", slice(F, 2 * F))):
            if motion[sl].max() < FLAT_STD_COUNTS:
                problems.append(f"{label}: {hand} hand flex never moved inside a rep "
                                f"(stale side, or hand genuinely still)")
        print()

    if len(means) > 1:
        print("Label vs label: channels that do NOT separate the two gestures")
        any_flag = False
        for a, b in itertools.combinations(means, 2):
            diff = np.abs(means[a] - means[b])
            noise = np.maximum(stds[a], stds[b])
            bad = [NAMES[i] for i in range(2 * F) if diff[i] <= noise[i]]
            if bad:
                any_flag = True
                print(f"   {a} vs {b}: {' '.join(bad)}")
        if not any_flag:
            print("   none flagged")
        print("   (flag = mean difference no larger than the across-rep std; flex channels only.)\n")

    print("Problems found:" if problems else "No problems flagged by the heuristics.")
    for pr in problems:
        print(f"  - {pr}")
    print("\nThis checks data consistency only. It says nothing about model accuracy.")


if __name__ == "__main__":
    main()
