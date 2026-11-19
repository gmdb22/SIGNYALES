"""
Signyales: turn a model label into the words shown and spoken.

Labels must be safe as folder names (lowercase letters, digits, - and _),
so a phrase is recorded as, for example, "sorry-i-dont-understand". The
subtitles and the voice should say "sorry, I don't understand". The text is
chosen in this order:
  1. display_names.json in the model folder, if there is one:
         {"sorry-i-dont-understand": "sorry, I don't understand"}
  2. BUILT_IN below (the phrases of the one-glove demo)
  3. otherwise - and _ become spaces, and a few words get fixed
     (i -> I, im -> I'm, dont -> don't, ...)
The raw label is still what labels.json, the logs and the accuracy logger use.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger("signyales.label_text")

DISPLAY_NAMES_FILE = "display_names.json"

# Keyed by the label with _ turned into - (see _key).
BUILT_IN = {
    "sorry-i-dont-understand": "sorry, I don't understand",
}

WORD_FIXES = {
    "i": "I",
    "im": "I'm",
    "ive": "I've",
    "ill": "I'll",
    "dont": "don't",
    "cant": "can't",
    "didnt": "didn't",
    "doesnt": "doesn't",
    "wont": "won't",
}


def _key(label: str) -> str:
    return label.strip().lower().replace("_", "-")


def label_to_text(label, names=None) -> str:
    """The words to show and speak for one label. names: the dict from
    load_display_names(), or None."""
    if label is None:
        return ""
    label = str(label)
    key = _key(label)
    if names and key in names:
        return names[key]
    if key in BUILT_IN:
        return BUILT_IN[key]
    words = [w for w in key.split("-") if w]
    if not words:
        return label
    return " ".join(WORD_FIXES.get(w, w) for w in words)


def load_display_names(model_dir) -> dict:
    """Reads display_names.json from the model folder. Missing file: {}.
    A broken file is reported in the log and ignored (the model still loads)."""
    path = Path(model_dir) / DISPLAY_NAMES_FILE
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("expected {\"label\": \"text\", ...}")
    except Exception as exc:
        log.warning("Ignoring %s (%s); showing labels with the built-in rules.", path, exc)
        return {}
    names = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            names[_key(k)] = v.strip()
        else:
            log.warning("Ignoring entry %r in %s (label and text must both be text)", k, path)
    return names
