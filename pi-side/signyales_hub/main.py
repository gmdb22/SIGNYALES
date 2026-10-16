"""
Signyales Pi-Side App — Main Application

Layer 3 of the pipeline: gloves -> receiver -> **Pi hub** -> text/speech.
Target hardware: Raspberry Pi 5 (4GB), Raspberry Pi OS Bookworm (64-bit).

    receiver UART --> parse frames --> extract features --> sliding window
        --> TinyML inference --> debounce --> print text + speak

Run against real hardware:
    python -m signyales_hub.main --port /dev/ttyAMA0 --baud 460800 --model-dir model

Run without any hardware or trained model, to exercise the rest of
the pipeline (useful in early sprints, per the proposal's Agile Scrum
methodology, before the receiver or model are ready):
    python -m signyales_hub.main --simulate
"""

import argparse
import logging
import sys

from .config import HubConfig
from .serial_link import SerialFrameReader, SimulatedFrameSource
from .windowing import WindowBuffer, extract_features
from .model_runtime import GestureClassifier
from .gesture_debounce import GestureDebouncer
from .tts_engine import TTSEngine
from .status_led import StatusLed
from .subtitle_display import SubtitleDisplay

log = logging.getLogger("signyales.main")


def parse_args():
    p = argparse.ArgumentParser(description="Signyales Raspberry Pi 5 hub application")
    p.add_argument("--port", default=None, help="Serial port (default: config.py setting)")
    p.add_argument("--baud", type=int, default=None, help="Serial baud (default: config.py setting)")
    p.add_argument("--model-dir", default=None, help="Directory with model.tflite/labels.json/scaler.json")
    p.add_argument("--simulate", action="store_true",
                    help="Use synthetic frames instead of a real serial link (no hardware needed)")
    p.add_argument("--no-tts", action="store_true", help="Print gestures but don't speak them")
    p.add_argument("--subtitle", action="store_true",
                    help="Show recognized gestures as large fullscreen text, for demo use. "
                         "When on, logging is redirected to signyales.log instead of the "
                         "terminal, so it doesn't fight with the fullscreen display for the "
                         "same screen space.")
    p.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging")
    return p.parse_args()


def main():
    args = parse_args()

    if args.subtitle:
        # The fullscreen display owns the terminal's visible output —
        # logging to stdout at the same time would get wiped by every
        # screen clear, or flash messily between clears. Route it to a
        # file instead so diagnostics are still captured for later.
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            filename="signyales.log",
        )
    else:
        logging.basicConfig(
            level=logging.DEBUG if args.verbose else logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud
    if args.model_dir:
        cfg.model_dir = args.model_dir

    classifier = GestureClassifier(cfg.model_dir, expected_window=cfg.window_size_samples,
                                   expected_features=cfg.feature_count)
    debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold,
                                 silent_labels=cfg.silent_labels)
    tts = TTSEngine() if not args.no_tts else None
    led = StatusLed(cfg.status_led_pin, cfg.status_led_enabled)
    window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)

    subtitle = SubtitleDisplay() if args.subtitle else None
    if subtitle:
        subtitle.show_idle()

    if args.simulate:
        log.info("Running in --simulate mode: synthetic frames, no hardware required")
        source = SimulatedFrameSource(rate_hz=50)
    else:
        source = SerialFrameReader(cfg.serial_port, cfg.serial_baud)

    silent_in_model = sorted(set(cfg.silent_labels) & set(classifier.labels))
    if silent_in_model:
        log.info("Silent (rest) labels in this model, never spoken: %s", silent_in_model)

    if not classifier.available:
        log.warning(
            "No model loaded from '%s' — the pipeline will run (serial parsing, "
            "windowing, TTS wiring all exercised), but no gestures will be recognized "
            "until model.tflite/labels.json/scaler.json are placed there.",
            cfg.model_dir,
        )

    frame_count = 0
    try:
        for frame in source:
            frame_count += 1

            hands_ok = frame["left_valid"] or frame["right_valid"]
            if cfg.require_at_least_one_hand_valid and not hands_ok:
                debouncer.reset()
                led.set(False)
                continue

            features = extract_features(frame)
            window.push(features)
            led.set(True)

            if not window.is_full():
                continue
            if frame_count % cfg.stride_samples != 0:
                continue

            label, confidence = classifier.predict(window.as_array())
            if label is None:
                continue  # no model loaded — nothing to debounce yet

            stable_label = debouncer.update(label, confidence)
            if stable_label:
                if subtitle:
                    subtitle.show(stable_label)
                else:
                    print(f"[gesture] {stable_label}")
                log.info("Recognized gesture: %s", stable_label)
                if tts:
                    tts.speak(stable_label)

    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        if tts:
            tts.shutdown()
        led.cleanup()


if __name__ == "__main__":
    sys.exit(main())
