"""
Signyales Pi Hub — Windowing

Turns a stream of parsed frames into fixed-size (window_size x
feature_count) arrays for the TinyML model, using the feature layout
documented in config.py.
"""

import numpy as np


def extract_features(frame: dict) -> np.ndarray:
    """
    Flattens one parsed frame into the 22-value feature vector the
    model expects, in this exact order:
      left_flex(5), right_flex(5), left_accel(3), left_gyro(3),
      right_accel(3), right_gyro(3)

    Flex values are scaled to 0-1 (they arrive already calibrated to
    0-4095 by the glove firmware). Accel/gyro are left in their
    physical units (g and deg/s) — the model's scaler.json handles
    normalizing those ranges, not this function.
    """
    left, right = frame["left"], frame["right"]
    values = (
        [v / 4095.0 for v in left["flex"]]
        + [v / 4095.0 for v in right["flex"]]
        + list(left["accel"])
        + list(left["gyro"])
        + list(right["accel"])
        + list(right["gyro"])
    )
    return np.array(values, dtype=np.float32)


class WindowBuffer:
    """
    Fixed-size rolling buffer of feature vectors. Push one vector per
    incoming frame; once full, as_array() gives the model's input
    shape directly.
    """

    def __init__(self, window_size: int, feature_count: int):
        self.window_size = window_size
        self.feature_count = feature_count
        self._buf = np.zeros((window_size, feature_count), dtype=np.float32)
        self._filled = 0

    def push(self, features: np.ndarray):
        self._buf = np.roll(self._buf, -1, axis=0)
        self._buf[-1] = features
        self._filled = min(self._filled + 1, self.window_size)

    def is_full(self) -> bool:
        return self._filled >= self.window_size

    def as_array(self) -> np.ndarray:
        """Shape: (window_size, feature_count). Oldest sample first."""
        return self._buf.copy()
