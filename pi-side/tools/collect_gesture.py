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

Fixed-length recording (decision D1, 14 Nov 2026): each repetition is
exactly cfg.window_size_samples raw frames (2.5 s at 50 Hz), the same
stretch of time the live recogniser looks at, with no resampling. Press
Enter with the hand at rest, sign once, return to rest; the repetition
ends by itself when the window is full. Frames are read continuously in
the background, so a repetition starts from the current frame, not from
frames that piled up while waiting for Enter (finding F2).

--variable gives the old behaviour (Enter to start, Enter to stop, any
length, resampled to the window by linear interpolation). Kept only for
comparison; a model trained that way sees time stretched or squeezed
while the live recogniser does not (finding F1).

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


class BackgroundFrames:
    """Reads the frame source continuously on a thread. capture(n) returns
    the next n feature vectors that arrive after it is called."""

    def __init__(self, source_iter):
        self._iter = source_iter
        self._lock = threading.Lock()
        self._buf = None
        self._want = 0
        self._full = threading.Event()
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            for frame in self._iter:
                feats = extract_features(frame)
                with self._lock:
                    if self._buf is not None and len(self._buf) < self._want:
                        self._buf.append(feats)
                        if len(self._buf) >= self._want:
                            self._full.set()
        except Exception as exc:  # serial error: report it to capture()
            self.error = exc
            self._full.set()

    def capture(self, n: int, timeout: float = None, progress=None) -> np.ndarray:
        with self._lock:
            self._buf, self._want = [], n
            self._full.clear()
        timeout = timeout if timeout is not None else n / 50 * 3 + 2
        waited = 0.0
        while not self._full.wait(0.25):
            waited += 0.25
            if progress:
                with self._lock:
                    progress(len(self._buf), n)
            if waited >= timeout:
                with self._lock:
                    got, self._buf = len(self._buf), None
                raise RuntimeError(f"only {got} of {n} frames arrived in {timeout:.0f} s. "
                                   "Is the glove on and sending?")
        with self._lock:
            buf, self._buf = self._buf, None
        if self.error is not None:
            raise RuntimeError(f"frame source stopped: {self.error}")
        return np.stack(buf[:n]).astype(np.float32)


def record_one_repetition(source_iter, window_size: int) -> np.ndarray:
    """--variable mode only: buffers feature vectors until Enter is
    pressed, then resamples the buffered sequence to a fixed length."""
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
    p.add_argument("--variable", action="store_true",
                    help="Old mode: Enter to stop, any length, resampled (finding F1). Not for real data.")
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

    n = cfg.window_size_samples
    print(f"Recording gesture '{args.label}': {args.reps} repetitions -> {label_dir}")
    source_iter = iter(source)
    background = None if args.variable else BackgroundFrames(source_iter)
    if background:
        print(f"Each repetition is {n / 50:.1f} s. Hand at rest, press Enter, sign once, "
              "return to rest; it saves by itself.")

    def show(got, want):
        print(f"\r  Recording... {got / 50:.1f} / {want / 50:.1f} s", end="", flush=True)

    recorded = 0
    while recorded < args.reps:
        rep_num = start_index + recorded
        input(f"\n[{recorded + 1}/{args.reps}] Press Enter to START repetition {rep_num}...")
        try:
            if background:
                window = background.capture(n, progress=show)
                print()
            else:
                window = record_one_repetition(source_iter, n)
        except RuntimeError as exc:
            print(f"\n  Skipped: {exc}")
            continue

        out_path = label_dir / f"rep_{rep_num:04d}.npz"
        np.savez(out_path, features=window, label=args.label)
        print(f"  Saved {out_path} (shape={window.shape})")
        recorded += 1

    print(f"\nDone. {recorded} repetitions saved to {label_dir}")


if __name__ == "__main__":
    main()
