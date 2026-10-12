"""
Signyales — Performance Logger
=================================
Testing tool that runs the live pipeline (same modules as
signyales_hub.main) while logging two metrics for the proposal's
Technical Performance Checklist that normal operation doesn't need to
track:

  - Packet delivery ratio (Pi-side view): the fraction of incoming
    frames where each hand's data was fresh (left_valid/right_valid),
    computed from data already present in every frame — no second
    physical connection needed. See receiver_link_logger.py for the
    lower-level, ESP-NOW-hop-specific version of this same idea.
  - Recognition latency: wall-clock time from when usable sensor data
    resumed arriving to the moment a stable gesture is confirmed from
    it. This is PIPELINE latency (data arrival -> spoken output), not
    the full human-gesture-to-speech latency a stopwatch/video
    measurement would capture — don't report this figure as the
    latter without saying so.

Usage:
    python tools/performance_logger.py --model-dir model --duration 300 \\
        --out results/perf_run1

    # Tool smoke-test only, no hardware/model required:
    python tools/performance_logger.py --simulate --duration 20
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.serial_link import SerialFrameReader, SimulatedFrameSource  # noqa: E402
from signyales_hub.windowing import WindowBuffer, extract_features  # noqa: E402
from signyales_hub.model_runtime import GestureClassifier  # noqa: E402
from signyales_hub.gesture_debounce import GestureDebouncer  # noqa: E402


def main():
    p = argparse.ArgumentParser(
        description="Log packet delivery ratio and recognition latency during a live testing session"
    )
    p.add_argument("--model-dir", default="model")
    p.add_argument("--duration", type=float, default=120.0,
                    help="Seconds to run (Ctrl+C also stops early and still saves results)")
    p.add_argument("--out", default="results/perf_run", help="Output path prefix (no extension)")
    p.add_argument("--port", default=None)
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--simulate", action="store_true", help="Test the TOOL itself with synthetic data")
    args = p.parse_args()

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud
    if args.model_dir:
        cfg.model_dir = args.model_dir

    classifier = GestureClassifier(cfg.model_dir)
    window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)
    debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold)

    if args.simulate:
        source = SimulatedFrameSource(rate_hz=50)
    else:
        source = SerialFrameReader(cfg.serial_port, cfg.serial_baud)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events_csv = out_path.parent / (out_path.name + "_events.csv")

    total_frames = 0
    left_valid_count = 0
    right_valid_count = 0
    both_valid_count = 0

    recognition_events = []  # (session_time_s, label, confidence, latency_s)
    pending_window_start = None
    frame_count_for_stride = 0

    start_time = time.monotonic()
    print(f"Logging performance for up to {args.duration:.0f}s. Ctrl+C to stop early.\n")

    try:
        for frame in source:
            now = time.monotonic()
            if now - start_time > args.duration:
                break

            total_frames += 1
            if frame["left_valid"]:
                left_valid_count += 1
            if frame["right_valid"]:
                right_valid_count += 1
            if frame["left_valid"] and frame["right_valid"]:
                both_valid_count += 1

            hands_ok = frame["left_valid"] or frame["right_valid"]
            if not hands_ok:
                debouncer.reset()
                pending_window_start = None
                continue

            if pending_window_start is None:
                pending_window_start = now

            window.push(extract_features(frame))
            frame_count_for_stride += 1

            if not window.is_full():
                continue
            if frame_count_for_stride % cfg.stride_samples != 0:
                continue
            if not classifier.available:
                continue

            label, confidence = classifier.predict(window.as_array())
            if label is None:
                continue

            stable = debouncer.update(label, confidence)
            if stable:
                latency = now - pending_window_start
                recognition_events.append((round(now - start_time, 2), stable, confidence, round(latency, 3)))
                print(f"[{now - start_time:6.1f}s] recognized '{stable}' "
                      f"(confidence={confidence:.2f}, latency={latency:.2f}s since input resumed)")
                pending_window_start = now  # reset baseline for the next gesture

    except KeyboardInterrupt:
        print("\nStopped early by user.")

    elapsed = time.monotonic() - start_time

    with open(events_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["session_time_s", "label", "confidence", "latency_s"])
        writer.writerows(recognition_events)
    print(f"\nRecognition events saved to {events_csv}")

    # Build the summary as a dict first, so it can be both printed AND
    # saved to disk — previously this was print-only, which meant none of
    # these numbers (delivery ratio, latency mean/std) were recoverable
    # after the terminal closed, making them impossible to visualize or
    # aggregate across sessions later.
    summary = {
        "session_duration_s": round(elapsed, 1),
        "total_frames": total_frames,
        "left_delivery_ratio_pct": round(left_valid_count / total_frames * 100, 1) if total_frames else None,
        "right_delivery_ratio_pct": round(right_valid_count / total_frames * 100, 1) if total_frames else None,
        "both_hands_fresh_ratio_pct": round(both_valid_count / total_frames * 100, 1) if total_frames else None,
        "gestures_recognized": len(recognition_events),
        "latency_mean_s": None,
        "latency_std_s": None,
    }
    if recognition_events:
        latencies = [e[3] for e in recognition_events]
        mean_latency = sum(latencies) / len(latencies)
        std_latency = (sum((v - mean_latency) ** 2 for v in latencies) / len(latencies)) ** 0.5
        summary["latency_mean_s"] = round(mean_latency, 3)
        summary["latency_std_s"] = round(std_latency, 3)

    summary_json = out_path.parent / (out_path.name + "_summary.json")
    with open(summary_json, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Session summary saved to {summary_json}")

    print("\n=== Summary ===")
    print(f"Session duration: {summary['session_duration_s']}s, total frames received: {summary['total_frames']}")
    if summary["left_delivery_ratio_pct"] is not None:
        print(f"Left-hand packet delivery ratio (Pi-side):  {summary['left_delivery_ratio_pct']}%")
        print(f"Right-hand packet delivery ratio (Pi-side): {summary['right_delivery_ratio_pct']}%")
        print(f"Both-hands-fresh ratio:                     {summary['both_hands_fresh_ratio_pct']}%")
    print(f"Gestures recognized: {summary['gestures_recognized']}")
    if summary["latency_mean_s"] is not None:
        print(f"Recognition latency: mean={summary['latency_mean_s']}s, std={summary['latency_std_s']}s")


if __name__ == "__main__":
    main()
