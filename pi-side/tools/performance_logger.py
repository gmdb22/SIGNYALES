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

Stage timing (measured on whatever machine runs this, all Pi-side):
  - inference_ms: wall time of each classifier.predict() call
    (normalisation + TFLite invoke), over every inference in the session.
  - debounce_wait_s: per recognized gesture, time from the first of the
    consecutive agreeing predictions to the one that confirmed it.
  - inter_frame_ms: time between consecutive frames reaching this loop.
    About 20 ms is expected at 50 Hz; much smaller values mean frames
    arrived in a burst (a backlog), larger ones mean gaps.
  NOT measured here: glove sampling and filtering, ESP-NOW and UART
  transit, and text-to-speech playback (speech is queued asynchronously).
  These figures are building blocks for a latency budget, not the
  proposal's glove-to-speech latency on their own.

  --log-inferences also writes one row per inference (time, frame_seq,
  label, confidence, inference_ms, candidate count, emitted label), which
  is useful for choosing the confidence threshold and debounce count.

Usage:
    python tools/performance_logger.py --model-dir model --duration 300 \\
        --out results/perf_run1

    # Tool smoke-test only, no hardware/model required:
    python tools/performance_logger.py --simulate --duration 20
"""

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.serial_link import SimulatedFrameSource, open_receiver  # noqa: E402
from signyales_hub.windowing import WindowBuffer, extract_features  # noqa: E402
from signyales_hub.model_runtime import GestureClassifier  # noqa: E402
from signyales_hub.gesture_debounce import GestureDebouncer  # noqa: E402


def _percentile(values, pct):
    """Nearest-rank percentile (pct in 0-100) of a non-empty list."""
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * pct // 100))  # ceil(n * pct / 100), at least 1
    return ordered[int(rank) - 1]


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
    p.add_argument("--log-inferences", action="store_true",
                    help="Also write <out>_inferences.csv with one row per inference")
    args = p.parse_args()

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud
    if args.model_dir:
        cfg.model_dir = args.model_dir

    classifier = GestureClassifier(cfg.model_dir, expected_window=cfg.window_size_samples,
                                   expected_features=cfg.feature_count)
    window = WindowBuffer(cfg.window_size_samples, cfg.feature_count)
    debouncer = GestureDebouncer(cfg.debounce_required_consecutive, cfg.confidence_threshold,
                                 silent_labels=cfg.silent_labels)

    if args.simulate:
        source = SimulatedFrameSource(rate_hz=50)
    else:
        source = open_receiver(cfg)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    events_csv = out_path.parent / (out_path.name + "_events.csv")
    inferences_csv = out_path.parent / (out_path.name + "_inferences.csv")

    total_frames = 0
    left_valid_count = 0
    right_valid_count = 0
    both_valid_count = 0

    # (session_time_s, label, confidence, latency_s, inference_ms, debounce_wait_s)
    recognition_events = []
    pending_window_start = None
    frame_count_for_stride = 0

    inference_ms = []        # every predict() call
    inter_frame_ms = []      # gap between consecutive frames reaching the loop
    inference_rows = []      # only filled with --log-inferences
    candidate_start = None   # time of the first agreeing prediction in the current run
    prev_frame_time = None

    start_time = time.monotonic()
    print(f"Logging performance for up to {args.duration:.0f}s. Ctrl+C to stop early.\n")

    try:
        for frame in source:
            now = time.monotonic()
            if now - start_time > args.duration:
                break
            if prev_frame_time is not None:
                inter_frame_ms.append((now - prev_frame_time) * 1000)
            prev_frame_time = now

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
                candidate_start = None
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

            t0 = time.perf_counter()
            label, confidence = classifier.predict(window.as_array())
            infer_ms = (time.perf_counter() - t0) * 1000
            if label is None:
                continue
            inference_ms.append(infer_ms)

            stable = debouncer.update(label, confidence)
            if debouncer.candidate_count == 1:
                candidate_start = now
            elif debouncer.candidate_count == 0:
                candidate_start = None

            if args.log_inferences:
                inference_rows.append((round(now - start_time, 3), frame["frame_seq"], label,
                                       round(confidence, 4), round(infer_ms, 3),
                                       debouncer.candidate_count, stable or ""))

            if stable:
                latency = now - pending_window_start
                debounce_wait = (now - candidate_start) if candidate_start is not None else None
                recognition_events.append((
                    round(now - start_time, 2), stable, confidence, round(latency, 3),
                    round(infer_ms, 3),
                    round(debounce_wait, 3) if debounce_wait is not None else None,
                ))
                print(f"[{now - start_time:6.1f}s] recognized '{stable}' "
                      f"(confidence={confidence:.2f}, latency={latency:.2f}s since input resumed)")
                pending_window_start = now  # reset baseline for the next gesture

    except KeyboardInterrupt:
        print("\nStopped early by user.")

    elapsed = time.monotonic() - start_time

    with open(events_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["session_time_s", "label", "confidence", "latency_s",
                         "inference_ms", "debounce_wait_s"])
        writer.writerows(recognition_events)
    print(f"\nRecognition events saved to {events_csv}")

    if args.log_inferences:
        with open(inferences_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["session_time_s", "frame_seq", "label", "confidence",
                             "inference_ms", "candidate_count", "emitted"])
            writer.writerows(inference_rows)
        print(f"Per-inference log saved to {inferences_csv}")

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
        "latency_std_method": "sample (n-1)",
        "inference_count": len(inference_ms),
        "inference_ms_mean": round(statistics.mean(inference_ms), 3) if inference_ms else None,
        "inference_ms_p95": round(_percentile(inference_ms, 95), 3) if inference_ms else None,
        "inference_ms_max": round(max(inference_ms), 3) if inference_ms else None,
        "debounce_wait_mean_s": None,
        "inter_frame_ms_mean": round(statistics.mean(inter_frame_ms), 2) if inter_frame_ms else None,
        "inter_frame_ms_p95": round(_percentile(inter_frame_ms, 95), 2) if inter_frame_ms else None,
        "inter_frame_ms_max": round(max(inter_frame_ms), 2) if inter_frame_ms else None,
    }
    waits = [e[5] for e in recognition_events if e[5] is not None]
    if waits:
        summary["debounce_wait_mean_s"] = round(statistics.mean(waits), 3)
    if recognition_events:
        latencies = [e[3] for e in recognition_events]
        mean_latency = statistics.mean(latencies)
        summary["latency_mean_s"] = round(mean_latency, 3)
        # Sample standard deviation (divides by n - 1), as the proposal's
        # statistical treatment specifies. Undefined for a single event.
        if len(latencies) > 1:
            summary["latency_std_s"] = round(statistics.stdev(latencies), 3)

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
        std_text = (f"{summary['latency_std_s']}s" if summary["latency_std_s"] is not None
                    else "n/a (needs 2+ events)")
        print(f"Recognition latency: mean={summary['latency_mean_s']}s, sample std={std_text}")
    if summary["inference_ms_mean"] is not None:
        print(f"Inference time ({summary['inference_count']} calls): mean={summary['inference_ms_mean']} ms, "
              f"p95={summary['inference_ms_p95']} ms, max={summary['inference_ms_max']} ms")
    if summary["debounce_wait_mean_s"] is not None:
        print(f"Debounce wait (first agreeing prediction to confirmation): "
              f"mean={summary['debounce_wait_mean_s']}s")
    if summary["inter_frame_ms_mean"] is not None:
        print(f"Frame spacing: mean={summary['inter_frame_ms_mean']} ms, "
              f"p95={summary['inter_frame_ms_p95']} ms, max={summary['inter_frame_ms_max']} ms "
              f"(about 20 ms expected at 50 Hz)")


if __name__ == "__main__":
    main()
