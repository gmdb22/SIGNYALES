"""
Signyales GUI — the live recognition pipeline, run on a background thread.

Same steps, in the same order, as signyales_hub/main.py:
  frame -> skip if both hands invalid (and reset the debouncer)
        -> extract_features -> WindowBuffer -> every stride: predict
        -> GestureDebouncer (with silent labels) -> stable gesture
It reports what happens as events (plain dicts) instead of printing, so the
window, the mirror link and the tests can all listen. If main.py's loop
changes, change this too; test_gui_core.py checks they agree on fake data.

No Tk imports.
"""

import threading
import time

from .env import ensure_pi_side_on_path

ensure_pi_side_on_path()

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.gesture_debounce import GestureDebouncer  # noqa: E402
from signyales_hub.windowing import WindowBuffer, extract_features  # noqa: E402

STATUS_EVERY_S = 0.5


def make_source(port=None, baud=None, simulate=False):
    """A frame source exactly like main.py's: real serial port, or simulated."""
    from signyales_hub.serial_link import SerialFrameReader, SimulatedFrameSource
    cfg = HubConfig()
    if simulate:
        return SimulatedFrameSource(rate_hz=50)
    return SerialFrameReader(port or cfg.serial_port, baud or cfg.serial_baud)


def load_classifier(model_dir):
    """GestureClassifier with the hub's config checks, or None if no folder given."""
    if not model_dir:
        return None
    from signyales_hub.model_runtime import GestureClassifier
    cfg = HubConfig()
    return GestureClassifier(str(model_dir), expected_window=cfg.window_size_samples,
                             expected_features=cfg.feature_count)


class LivePipeline:
    """
    on_event(dict) receives:
      {"type": "started", "model": bool, "labels": [...]}
      {"type": "status", "frames", "fps", "left_fresh_pct", "right_fresh_pct",
       "left_flex", "right_flex", "left_valid", "right_valid"}
      {"type": "prediction", "label", "confidence"}        every inference
      {"type": "gesture", "label", "confidence"}           a confirmed sign
      {"type": "stopped", "reason"} / {"type": "error", "message"}
    Frame listeners (add_frame_listener) get (frame, features) for every
    usable frame; the GUI recorder uses this.
    """

    def __init__(self, source_factory, classifier_factory=None, on_event=None, cfg=None):
        self.cfg = cfg or HubConfig()
        self._source_factory = source_factory
        self._classifier_factory = classifier_factory or (lambda: None)
        self._on_event = on_event or (lambda e: None)
        self._listeners = []
        self._stop = threading.Event()
        self._thread = None
        self._source = None

    def add_frame_listener(self, fn):
        self._listeners.append(fn)

    def remove_frame_listener(self, fn):
        if fn in self._listeners:
            self._listeners.remove(fn)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    @property
    def stopping(self):
        """True after stop() was called, while the thread is still finishing."""
        return self.running and self._stop.is_set()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        ser = getattr(self._source, "_ser", None)   # unblock a serial read
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def join(self, timeout=None):
        if self._thread:
            self._thread.join(timeout)

    def _emit(self, event):
        try:
            self._on_event(event)
        except Exception:
            pass

    def _run(self):
        try:
            classifier = self._classifier_factory()
            self._source = self._source_factory()
        except Exception as exc:
            self._emit({"type": "error", "message": f"Could not start: {exc}"})
            self._emit({"type": "stopped", "reason": "error"})
            return
        cfg = self.cfg
        has_model = bool(classifier is not None and classifier.available)
        self._emit({"type": "started", "model": has_model,
                    "labels": list(classifier.labels) if has_model else []})
        debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold,
                                     silent_labels=cfg.silent_labels)
        window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)

        frame_count = 0
        win = {"n": 0, "left": 0, "right": 0, "t0": time.monotonic()}
        reason = "stopped"
        try:
            for frame in self._source:
                if self._stop.is_set():
                    break
                frame_count += 1
                win["n"] += 1
                win["left"] += frame["left_valid"]
                win["right"] += frame["right_valid"]
                now = time.monotonic()
                if now - win["t0"] >= STATUS_EVERY_S:
                    n = win["n"]
                    self._emit({
                        "type": "status", "frames": frame_count,
                        "fps": round(n / (now - win["t0"]), 1),
                        "left_fresh_pct": round(100 * win["left"] / n),
                        "right_fresh_pct": round(100 * win["right"] / n),
                        "left_flex": list(frame["left"]["flex"]),
                        "right_flex": list(frame["right"]["flex"]),
                        "left_valid": frame["left_valid"], "right_valid": frame["right_valid"],
                    })
                    win = {"n": 0, "left": 0, "right": 0, "t0": now}

                hands_ok = frame["left_valid"] or frame["right_valid"]
                if cfg.require_at_least_one_hand_valid and not hands_ok:
                    debouncer.reset()
                    continue

                features = extract_features(frame)
                for fn in list(self._listeners):
                    try:
                        fn(frame, features)
                    except Exception:
                        pass
                window.push(features)

                if not has_model or not window.is_full():
                    continue
                if frame_count % cfg.stride_samples != 0:
                    continue
                label, confidence = classifier.predict(window.as_array())
                if label is None:
                    continue
                self._emit({"type": "prediction", "label": label, "confidence": round(confidence, 3)})
                stable = debouncer.update(label, confidence)
                if stable:
                    self._emit({"type": "gesture", "label": stable, "confidence": round(confidence, 3)})
        except Exception as exc:
            if not self._stop.is_set():
                self._emit({"type": "error", "message": str(exc)})
                reason = "error"
        self._emit({"type": "stopped", "reason": reason})
