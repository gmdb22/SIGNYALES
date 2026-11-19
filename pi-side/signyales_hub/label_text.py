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

Going the other way (19 Nov 2026): the Record tab and collect_gesture.py
take the word as it should appear ("A", "Ñ", "I'm fine"), make the folder
name with word_to_label(), and keep the typed text in text.txt inside that
word's folder. train.py gathers those into the model's display_names.json.
"""

import json
import logging
import re
import unicodedata
from pathlib import Path

log = logging.getLogger("signyales.label_text")

DISPLAY_NAMES_FILE = "display_names.json"
WORD_TEXT_FILE = "text.txt"          # in each word's recording folder
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

# Whole words whose folder name is not just the letters (checked first).
SPECIAL_LABELS = {"ñ": "enye"}

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


def word_to_label(text):
    """Folder name for a typed word: "A" -> "a", "I'm fine" -> "im-fine",
    "Sorry, I don't understand" -> "sorry-i-dont-understand", "Ñ" -> "enye",
    "Niño" -> "ninyo". Returns None if nothing usable is left."""
    t = " ".join(str(text or "").split()).lower()
    if not t:
        return None
    if t in SPECIAL_LABELS:
        return SPECIAL_LABELS[t]
    t = t.replace("ñ", "ny").replace("'", "").replace("\u2019", "")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9_-]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-_")
    return t if LABEL_RE.match(t) else None


def read_word_text(label_dir):
    """The typed text saved in a word's folder, or None."""
    path = Path(label_dir) / WORD_TEXT_FILE
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def save_word_text(label_dir, text, replace=False):
    """Keeps the typed text in the word's folder (text.txt) and returns the
    text in use. A folder that already has a text keeps it unless replace=True,
    so typing "a" later does not turn a recorded "A" into "a". To change it,
    edit text.txt (or pass replace=True)."""
    label_dir = Path(label_dir)
    text = " ".join(str(text).split())
    old = read_word_text(label_dir)
    if old and (old == text or not replace):
        return old
    label_dir.mkdir(parents=True, exist_ok=True)
    (label_dir / WORD_TEXT_FILE).write_text(text + "\n", encoding="utf-8")
    return text


def collect_word_texts(data_dir, labels):
    """{label: typed text} for the labels whose folders have a text.txt.
    train.py writes this to the model folder as display_names.json."""
    names = {}
    for label in labels:
        text = read_word_text(Path(data_dir) / label)
        if text:
            names[label] = text
    return names

