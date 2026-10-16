"""
Signyales GUI — record gesture repetitions with Start/Stop buttons.

Saves files in exactly the format pi-side/tools/collect_gesture.py writes
(<out>/<label>/rep_NNNN.npz with "features" (window, 22) and "label"), and
uses that tool's own resample_to_fixed_length, so the training pipeline
can't tell the two apart.

One difference by design: the GUI's pipeline reads the serial port all
the time, so a repetition starts from the current frame, not from frames
that piled up while waiting (finding F2 does not apply here). Findings F1
and F3 still apply: repetitions are resampled to the window length, and
frames with a missing hand are kept. Both change with the F1-F5 work.

No Tk imports.
"""

import importlib.util
import re
import threading
from pathlib import Path

import numpy as np

from .env import PI_SIDE, ensure_pi_side_on_path

ensure_pi_side_on_path()
from signyales_hub.config import HubConfig  # noqa: E402

LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _load_resample():
    path = PI_SIDE / "tools" / "collect_gesture.py"
    spec = importlib.util.spec_from_file_location("collect_gesture_for_gui", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.resample_to_fixed_length


resample_to_fixed_length = _load_resample()


def check_label(label: str):
    """Returns an error message, or None if the label is usable as a folder name."""
    if not LABEL_RE.match(label or ""):
        return ("Use lowercase letters, digits, '-' or '_' only, starting with a letter or digit "
                "(e.g. salamat, rest). The folder name is the word the system speaks.")
    return None


def count_reps(out_dir, label) -> int:
    d = Path(out_dir) / label
    return len(list(d.glob("rep_*.npz"))) if d.is_dir() else 0


class GestureRecorder:
    """Attach to a LivePipeline with pipeline.add_frame_listener(recorder.on_frame)."""

    def __init__(self, out_dir, cfg=None):
        self.out_dir = Path(out_dir)
        self.cfg = cfg or HubConfig()
        self._buf = None
        self._lock = threading.Lock()

    @property
    def recording(self):
        return self._buf is not None

    @property
    def frame_count(self):
        """Frames collected so far in the current repetition (0 if not recording)."""
        with self._lock:
            return len(self._buf) if self._buf is not None else 0

    def on_frame(self, frame, features):
        with self._lock:
            if self._buf is not None:
                self._buf.append(features)

    def start_rep(self):
        with self._lock:
            self._buf = []

    def cancel_rep(self):
        with self._lock:
            self._buf = None

    def stop_rep(self, label):
        """Saves the repetition. Returns (path, frames) or raises ValueError."""
        err = check_label(label)
        if err:
            raise ValueError(err)
        with self._lock:
            buf, self._buf = self._buf, None
        if buf is None:
            raise ValueError("Not recording.")
        if len(buf) < 2:
            raise ValueError("Too short (fewer than 2 frames). Hold the sign a little longer.")
        window = resample_to_fixed_length(np.stack(buf), self.cfg.window_size_samples)
        label_dir = self.out_dir / label
        label_dir.mkdir(parents=True, exist_ok=True)
        idx = len(list(label_dir.glob("rep_*.npz")))
        path = label_dir / f"rep_{idx:04d}.npz"
        while path.exists():
            idx += 1
            path = label_dir / f"rep_{idx:04d}.npz"
        np.savez(path, features=window, label=label)
        return path, len(buf)
