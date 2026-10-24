"""
Signyales Training — Dataset Loader

Loads gesture windows recorded by pi-side/tools/collect_gesture.py.

Expected layout:
    data/
      kumusta/
        rep_0000.npz   (keys: "features" (window_size, 24), "label")
        rep_0001.npz
        ...
      salamat/
        rep_0000.npz
        ...

Folders whose names start with "_" or "." are skipped, so recordings
that must not be trained on (for example the hardware handoff's Stage 7b
sanity set) can be kept beside real data by renaming the folder, e.g.
data/_stage7b_fist/.

The label list returned is index-aligned to the model's eventual
output classes — this exact order gets written into labels.json by
export.py, and main.py on the Pi hub reads it back with that same
index alignment assumed. Don't reorder it by hand after training.
"""

from pathlib import Path

import numpy as np


def split_label_dirs(data_dir: str):
    """Returns (label_dirs, skipped_dirs), both sorted by name.
    Skipped = folders whose names start with "_" or "."."""
    data_dir = Path(data_dir)
    if not data_dir.is_dir():
        raise ValueError(f"Data directory {data_dir} does not exist.")
    dirs = sorted(d for d in data_dir.iterdir() if d.is_dir())
    used = [d for d in dirs if not d.name.startswith(("_", "."))]
    skipped = [d for d in dirs if d.name.startswith(("_", "."))]
    return used, skipped


def load_dataset(data_dir: str):
    data_dir = Path(data_dir)
    label_dirs, skipped = split_label_dirs(data_dir)
    for d in skipped:
        print(f"Skipping folder '{d.name}' (names starting with '_' or '.' are not trained on)")
    if not label_dirs:
        raise ValueError(
            f"No label subdirectories found in {data_dir}. Run collect_gesture.py "
            f"for at least one gesture first."
        )
    labels = [d.name for d in label_dirs]

    X, y = [], []
    for label_idx, label_dir in enumerate(label_dirs):
        rep_files = sorted(label_dir.glob("rep_*.npz"))
        if not rep_files:
            raise ValueError(f"No recordings found for label '{label_dir.name}' in {label_dir}")
        for rep_file in rep_files:
            data = np.load(rep_file)
            X.append(data["features"])
            y.append(label_idx)

    X = np.stack(X).astype(np.float32)  # (N, window_size, feature_count)
    y = np.array(y, dtype=np.int64)
    return X, y, labels
