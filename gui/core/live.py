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
RECEIVER_STATS_FRESH_S = 3.0   # the receiver prints [stats] once a second


def make_source(port=None, baud=None, simulate=False, link=None):
    """A frame source exactly like main.py's: the receiver (USB by default,
    found automatically; or UART), or simulated. port/link override the
    saved setting (receiver_link.resolve)."""
    from signyales_hub.serial_link import SimulatedFrameSource, open_receiver
    if simulate:
        return SimulatedFrameSource(rate_hz=50)
    return open_receiver(HubConfig(), port=port or None, baud=baud, link=link or None)


def link_stats_text(st) -> str:
    """One line of link numbers from a status event: the receiver's own
    [stats] (USB link) if present, else what the Pi worked out itself."""
    rx = st.get("receiver")
    if rx:
        return (f"Receiver: left {rx['left_ratio']:.1f}% received ({rx['left_dropped']} lost, "
                f"{rx['left_corrupt']} damaged) | right {rx['right_ratio']:.1f}% "
                f"({rx['right_dropped']} lost, {rx['right_corrupt']} damaged)")
    if "left_received_pct" not in st:
        return ""
    return (f"Measured on the Pi: left {st['left_received_pct']:.1f}% received ({st['left_lost']} lost) | "
            f"right {st['right_received_pct']:.1f}% ({st['right_lost']} lost)")


class LinkStats:
    """
    One glove's packets received vs lost, worked out on the Pi from the
    glove's sequence numbers (works on both links). Call update() only for
    frames where that hand is fresh. The receiver repeats a glove's last
    packet until a new one arrives, so a repeated number is not counted; a
    jump of more than 1 counts the missing packets as lost; a number going
    backwards (the glove restarted) starts counting from there again.
    Can read a little higher than the receiver's own "dropped": a packet the
    receiver replaced with a newer one before forwarding also counts here.
    """

    def __init__(self):
        self.last = None
        self.expected = 0
        self.lost = 0

    def update(self, seq):
        if self.last is None or seq < self.last:
            self.expected += 1
        elif seq > self.last:
            gap = seq - self.last - 1
            self.lost += gap
            self.expected += gap + 1
        self.last = seq

    @property
    def received_pct(self):
        return round(100.0 * (self.expected - self.lost) / self.expected, 1) if self.expected else 0.0


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
      {"type": "started", "model": bool, "labels": [...], "link": "usb"/"uart"/"", "port": str}
      {"type": "status", "frames", "fps", "left_fresh_pct", "right_fresh_pct",
       "left_flex", "right_flex", "left_valid", "right_valid",
       "left_received_pct", "left_lost", "right_received_pct", "right_lost",
       "receiver": the receiver's own [stats] dict (USB link) or None}
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

    def _receiver_stats(self, now):
        """The receiver's latest [stats] numbers if they are recent (USB link only)."""
        at = getattr(self._source, "receiver_stats_at", None)
        if at is None or now - at > RECEIVER_STATS_FRESH_S:
            return None
        return dict(self._source.receiver_stats)

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
                    "labels": list(classifier.labels) if has_model else [],
                    "link": getattr(self._source, "link", "") or "",
                    "port": getattr(self._source, "port", "") or ""})
        debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold,
                                     silent_labels=cfg.silent_labels)
        window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)

        frame_count = 0
        link_stats = {"left": LinkStats(), "right": LinkStats()}
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
                for hand in ("left", "right"):
                    if frame[f"{hand}_valid"]:
                        link_stats[hand].update(frame[hand]["seq"])
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
                        "left_received_pct": link_stats["left"].received_pct,
                        "left_lost": link_stats["left"].lost,
                        "right_received_pct": link_stats["right"].received_pct,
                        "right_lost": link_stats["right"].lost,
                        "receiver": self._receiver_stats(now),
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
