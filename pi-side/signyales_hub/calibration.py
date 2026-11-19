"""
Signyales: flex calibration done on the Pi, over the wireless link (19 Nov 2026).

The glove sends its flex readings uncalibrated (glove firmware SEND_RAW_FLEX).
For 8 seconds the wearer makes fists and opens the hand fully; the Pi keeps
each sensor's lowest and highest reading. From then on every frame's flex
values are stretched so that this wearer's open hand reads about 0 and a
full bend about 4095, the same 0-4095 scale the glove used to make itself.
No USB cable is needed: the readings come through the receiver like any
other frame.

One calibration is kept per signer code (W01.json, W02.json, ...) in
~/signyales_data/calibration, and one of them is active (active.json).
Everything that turns frames into model input applies the active one the
same way (GUI Recognize/Record/kiosk, main.py, collect_gesture.py,
accuracy_logger.py, performance_logger.py), so recordings and recognition
always match. Without any calibration, frames pass through unchanged
(right for a glove still running the older firmware that calibrates itself).

Set SIGNYALES_CALIBRATION_DIR to keep the files somewhere else.
"""

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

FLEX_NAMES = ("thumb", "index", "middle", "ring", "pinky", "palm")
HANDS = ("left", "right")
FULL_SCALE = 4095
MIN_RANGE = 500            # max - min below this: the sensor barely moved (or is not connected)
CAPTURE_SECONDS = 8.0
ACTIVE_FILE = "active.json"
SIGNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")


def calibration_dir() -> Path:
    d = os.environ.get("SIGNYALES_CALIBRATION_DIR")
    return Path(d) if d else Path.home() / "signyales_data" / "calibration"


def check_signer(signer) -> str:
    """Returns an error message, or "" if the signer code is usable."""
    if not signer or not SIGNER_RE.match(str(signer)):
        return "Signer code: letters, digits, - or _ only, e.g. W01 (codes only, never names)."
    return ""


class FlexCalibration:
    """Per-hand, per-sensor min/max. A hand without numbers is passed through as it arrives."""

    def __init__(self, signer="", hands=None, created=""):
        self.signer = signer
        self.created = created or datetime.now().isoformat(timespec="seconds")
        self.hands = {}
        for hand, v in (hands or {}).items():
            if hand in HANDS and v:
                lo, hi = [int(x) for x in v["min"]], [int(x) for x in v["max"]]
                if len(lo) == len(hi) == len(FLEX_NAMES):
                    self.hands[hand] = {"min": lo, "max": hi}

    def scale(self, hand, values):
        """Calibrated 0-4095 values for one hand's raw flex readings."""
        cal = self.hands.get(hand)
        if not cal:
            return values
        out = []
        for v, lo, hi in zip(values, cal["min"], cal["max"]):
            if hi <= lo:
                out.append(v)            # never moved during calibration: leave as it is
                continue
            x = (v - lo) * FULL_SCALE // (hi - lo)
            out.append(0 if x < 0 else FULL_SCALE if x > FULL_SCALE else x)
        return tuple(out)

    def apply(self, frame):
        """A copy of the frame with calibrated flex values (the rest is shared, not copied)."""
        if not self.hands:
            return frame
        out = dict(frame)
        for hand in self.hands:
            if hand in frame:
                out[hand] = dict(frame[hand])
                out[hand]["flex"] = self.scale(hand, frame[hand]["flex"])
        return out

    def report(self, hand):
        """[(name, min, max, range, ok)] for one hand, or []."""
        cal = self.hands.get(hand)
        if not cal:
            return []
        return [(n, lo, hi, hi - lo, hi - lo >= MIN_RANGE)
                for n, lo, hi in zip(FLEX_NAMES, cal["min"], cal["max"])]

    def describe(self):
        hands = " + ".join(self.hands) or "no hands"
        return f"{self.signer or '(no signer)'}, {hands}, {self.created.replace('T', ' ')[:16]}"

    def to_dict(self):
        return {"signer": self.signer, "created": self.created, "flex_order": list(FLEX_NAMES),
                "hands": self.hands}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("signer", ""), d.get("hands") or {}, d.get("created", ""))

    def merged_with(self, older):
        """This calibration, keeping hands from an older one of the same signer
        that were not captured this time (e.g. only the right glove was worn)."""
        if older is None:
            return self
        hands = dict(older.hands)
        hands.update(self.hands)
        return FlexCalibration(self.signer, hands, self.created)


class CalibrationCapture:
    """Feed it raw frames for CAPTURE_SECONDS; then result() has each sensor's min/max."""

    def __init__(self, seconds=CAPTURE_SECONDS, clock=time.monotonic):
        self.seconds = seconds
        self._clock = clock
        self._t0 = None
        self.frames = {h: 0 for h in HANDS}
        self._lo = {h: [FULL_SCALE] * len(FLEX_NAMES) for h in HANDS}
        self._hi = {h: [0] * len(FLEX_NAMES) for h in HANDS}

    @property
    def remaining(self):
        if self._t0 is None:
            return self.seconds
        return max(0.0, self.seconds - (self._clock() - self._t0))

    @property
    def done(self):
        return self._t0 is not None and self.remaining <= 0

    def on_raw_frame(self, frame):
        if self._t0 is None:
            self._t0 = self._clock()
        if self.done:
            return
        for hand in HANDS:
            if not frame.get(f"{hand}_valid"):
                continue
            self.frames[hand] += 1
            lo, hi = self._lo[hand], self._hi[hand]
            for i, v in enumerate(frame[hand]["flex"]):
                if v < lo[i]:
                    lo[i] = v
                if v > hi[i]:
                    hi[i] = v

    def result(self, signer, min_frames=25):
        """FlexCalibration with the hands that sent at least min_frames frames
        (half a second at 50 Hz), so a glove that is off is not calibrated."""
        hands = {h: {"min": list(self._lo[h]), "max": list(self._hi[h])}
                 for h in HANDS if self.frames[h] >= min_frames}
        return FlexCalibration(signer, hands)


# ------------------------------------------------------------------ files
def _write(path, cal):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cal.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)


def _read(path):
    try:
        return FlexCalibration.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(cal, directory=None, make_active=True):
    """Saves <signer>.json (and active.json). Returns the signer file's path."""
    d = Path(directory) if directory else calibration_dir()
    err = check_signer(cal.signer)
    if err:
        raise ValueError(err)
    path = d / f"{cal.signer}.json"
    _write(path, cal)
    if make_active:
        _write(d / ACTIVE_FILE, cal)
    return path


def load_signer(signer, directory=None):
    d = Path(directory) if directory else calibration_dir()
    return _read(d / f"{signer}.json") if not check_signer(signer) else None


def load_active(directory=None):
    """The active calibration, or None (frames then pass through unchanged)."""
    d = Path(directory) if directory else calibration_dir()
    return _read(d / ACTIVE_FILE)


def set_active(signer, directory=None):
    """Makes a signer's saved calibration the active one. Returns it, or None if there is none."""
    cal = load_signer(signer, directory)
    if cal is not None:
        d = Path(directory) if directory else calibration_dir()
        _write(d / ACTIVE_FILE, cal)
    return cal


def list_signers(directory=None):
    d = Path(directory) if directory else calibration_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json") if p.name != ACTIVE_FILE)


def apply_to_stream(frames, cal):
    """Frames with the calibration applied (for the command-line tools)."""
    if cal is None:
        yield from frames
        return
    for frame in frames:
        yield cal.apply(frame)
