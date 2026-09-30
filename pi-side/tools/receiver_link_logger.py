"""
Signyales — Receiver Link Logger (optional, lower-level diagnostic)
=======================================================================
Taps the receiver dongle's USB debug console (a SEPARATE physical
connection from the dongle's normal UART wiring to the Pi) and logs its
once-per-second "[stats] ..." line to CSV.

Gives an ESP-NOW-hop-specific packet delivery ratio, distinct from
performance_logger.py's Pi-side "was this hand's data fresh in this
frame" ratio — useful for telling apart "the glove's packet never made
it to the receiver" from "it arrived but missed the sample-and-hold
window by a few milliseconds".

Requires a second USB cable from the receiver dongle to this computer,
in addition to its normal wiring to the Pi's UART pins.

Usage:
    python tools/receiver_link_logger.py --port /dev/ttyUSB0 --duration 300 \\
        --out results/receiver_link_run1.csv
"""

import argparse
import csv
import re
import time

STATS_RE = re.compile(
    r"\[stats\] frames=(\d+) \| left: ratio=([\d.]+)% dropped=(\d+) corrupt=(\d+) "
    r"\| right: ratio=([\d.]+)% dropped=(\d+) corrupt=(\d+)"
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True, help="Receiver dongle's USB debug serial port")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--duration", type=float, default=300.0)
    p.add_argument("--out", default="results/receiver_link.csv")
    args = p.parse_args()

    import serial  # imported lazily, same reasoning as SerialFrameReader
    ser = serial.Serial(args.port, args.baud, timeout=1.0)

    rows = []
    start = time.monotonic()
    print(f"Logging receiver link stats for up to {args.duration:.0f}s. Ctrl+C to stop early.")

    try:
        while time.monotonic() - start < args.duration:
            line = ser.readline().decode(errors="ignore").strip()
            if not line:
                continue
            match = STATS_RE.search(line)
            if not match:
                continue
            frames, l_ratio, l_dropped, l_corrupt, r_ratio, r_dropped, r_corrupt = match.groups()
            row = {
                "session_time_s": round(time.monotonic() - start, 1),
                "frames": int(frames),
                "left_ratio_pct": float(l_ratio), "left_dropped": int(l_dropped), "left_corrupt": int(l_corrupt),
                "right_ratio_pct": float(r_ratio), "right_dropped": int(r_dropped), "right_corrupt": int(r_corrupt),
            }
            rows.append(row)
            print(row)
    except KeyboardInterrupt:
        print("\nStopped early by user.")

    if not rows:
        print("No stats lines were captured — check the port and that the receiver is powered and running.")
        return

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nSaved {len(rows)} samples to {args.out}")

    last = rows[-1]
    print("\n=== Summary (final reading of the session) ===")
    print(f"Left-hand delivery ratio:  {last['left_ratio_pct']:.1f}% "
          f"(dropped={last['left_dropped']}, corrupt={last['left_corrupt']})")
    print(f"Right-hand delivery ratio: {last['right_ratio_pct']:.1f}% "
          f"(dropped={last['right_dropped']}, corrupt={last['right_corrupt']})")


if __name__ == "__main__":
    main()
