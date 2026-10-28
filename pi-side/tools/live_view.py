"""
Signyales — Live Frame Viewer (no model required)
=================================================
Hardware-bring-up tool. Prints what the Pi is actually receiving from the
receiver dongle: per-hand validity, flex values, accel/gyro, achieved frame
rate and sequence gaps. Use it to confirm both gloves' data reaches the Pi
and responds to real hand movement BEFORE collecting training data.

Why it exists: `python -m signyales_hub.main` prints nothing per frame when
no model is loaded, so a healthy link and a dead link look identical.

Read-only: does not change any file. Same link as the hub: the receiver's
USB cable by default (found automatically), or the UART pins (/dev/ttyAMA0)
if that is the saved choice or --link uart / --port /dev/ttyAMA0 is given.
On the USB link it also prints the receiver's own [stats] numbers.

Usage (Pi bash, from pi-side/, venv active; works the same on the laptop):
    python tools/live_view.py --duration 30               # saved link (USB by default)
    python tools/live_view.py --link uart --duration 30   # GPIO wires, /dev/ttyAMA0
    python tools/live_view.py --simulate --duration 3     # tool self-test only

Press Ctrl+C to stop; a summary is printed at the end.
"""

import _thread
import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.receiver_link import describe  # noqa: E402
from signyales_hub.serial_link import (  # noqa: E402
    FLEX_NAMES, FLEX_PER_GLOVE, SimulatedFrameSource, open_receiver)

LOSS_AFTER_S = 2.0  # a hand with no fresh data for this long counts as "lost"
FLEX_SPREAD_WARN = 200  # counts (0-4095 scale). Heuristic, not from the proposal.
NO_DATA_WARN_S = 3.0


class HandStats:
    def __init__(self):
        self.valid = 0
        self.last_seq = None
        self.seq_gaps = 0
        self.flex_min = [None] * FLEX_PER_GLOVE
        self.flex_max = [None] * FLEX_PER_GLOVE

    def update(self, hand_dict, valid):
        if valid:
            self.valid += 1
        seq = hand_dict["seq"]
        if self.last_seq is not None and seq > self.last_seq + 1:
            self.seq_gaps += seq - self.last_seq - 1
        if self.last_seq is None or seq != self.last_seq:
            self.last_seq = seq
        for i, v in enumerate(hand_dict["flex"]):
            if self.flex_min[i] is None or v < self.flex_min[i]:
                self.flex_min[i] = v
            if self.flex_max[i] is None or v > self.flex_max[i]:
                self.flex_max[i] = v


class LinkEvents:
    """Detects when a hand stops sending fresh data (e.g. battery died, out of
    range) and when it comes back. Brief single-frame dropouts are ignored;
    a hand is only reported lost after LOSS_AFTER_S seconds without fresh
    data. This is how to find a glove's cutoff time: the receiver's [stats]
    ratio freezes when a glove goes silent, it does not drop to 0%."""

    def __init__(self, names=("LEFT", "RIGHT"), loss_after_s=LOSS_AFTER_S):
        self.loss_after_s = loss_after_s
        self.hands = {n: {"stale_since": None, "lost": False, "episodes": 0,
                          "longest": 0.0} for n in names}

    def update(self, now, valid_by_name):
        """now: monotonic seconds. Returns a list of (hand, kind, since, dur)
        tuples: kind is "lost" (since = when data stopped) or "back" (dur =
        length of the outage in seconds)."""
        out = []
        for name, valid in valid_by_name.items():
            h = self.hands[name]
            if valid:
                if h["lost"]:
                    dur = now - h["stale_since"]
                    h["longest"] = max(h["longest"], dur)
                    out.append((name, "back", h["stale_since"], dur))
                h["stale_since"], h["lost"] = None, False
            else:
                if h["stale_since"] is None:
                    h["stale_since"] = now
                if not h["lost"] and now - h["stale_since"] >= self.loss_after_s:
                    h["lost"] = True
                    h["episodes"] += 1
                    out.append((name, "lost", h["stale_since"], 0.0))
        return out

    def finish(self, now):
        """Close any outage still open at the end of the run."""
        for h in self.hands.values():
            if h["lost"]:
                h["longest"] = max(h["longest"], now - h["stale_since"])


def clock(mono, t0, wall0):
    return time.strftime("%H:%M:%S", time.localtime(wall0 + (mono - t0)))


def fmt_hand(name, hand, valid):
    flex = " ".join(f"{v:4d}" for v in hand["flex"])
    acc = " ".join(f"{v:+5.2f}" for v in hand["accel"])
    gyr = " ".join(f"{v:+7.1f}" for v in hand["gyro"])
    state = "ok   " if valid else "STALE"
    return f"  {name} {state} flex[{flex}] acc[{acc}] gyro[{gyr}]"


def main():
    p = argparse.ArgumentParser(description="Live view of frames arriving at the Pi")
    p.add_argument("--port", default=None)
    p.add_argument("--baud", type=int, default=None)
    p.add_argument("--link", choices=("usb", "uart"), default=None,
                   help="Receiver link (default: the saved GUI setting, else usb)")
    p.add_argument("--interval", type=float, default=0.5, help="Seconds between printed lines")
    p.add_argument("--duration", type=float, default=0.0, help="Stop after N seconds (0 = until Ctrl+C)")
    p.add_argument("--simulate", action="store_true", help="Test the TOOL itself with synthetic data")
    args = p.parse_args()

    cfg = HubConfig()
    if args.port:
        cfg.serial_port = args.port
    if args.baud:
        cfg.serial_baud = args.baud
    if args.link:
        cfg.receiver_link = args.link

    if args.simulate:
        print("NOTE: --simulate = random synthetic data. Tool self-test only, not a hardware result.")
        source = SimulatedFrameSource(rate_hz=50)
    else:
        try:
            source = open_receiver(cfg)
        except Exception as exc:  # serial.SerialException, ReceiverNotFound etc.
            print(f"Could not open the receiver: {exc}")
            sys.exit(1)
        print(f"Listening on {describe(source.link, source.port)} (Ctrl+C to stop)")

    left, right = HandStats(), HandStats()
    events = LinkEvents()
    wall0 = time.time()
    state = {"frames": 0, "last_frame_t": None, "stop": False}
    t0 = time.monotonic()
    print(f"Started at {clock(t0, t0, wall0)}")

    def watchdog():
        while not state["stop"]:
            time.sleep(1.0)
            if args.duration and time.monotonic() - t0 >= args.duration:
                _thread.interrupt_main()  # stops the loop even if no frames arrive
                return
            ref = state["last_frame_t"] if state["last_frame_t"] is not None else t0
            if time.monotonic() - ref > NO_DATA_WARN_S:
                print(f"  !! No frames for {time.monotonic() - ref:.0f}s — check receiver power, "
                      f"the cable (USB: a data cable; UART: TX/RX crossed), port and baud.")

    threading.Thread(target=watchdog, daemon=True).start()

    last_print = t0
    frames_at_last_print = 0
    try:
        for frame in source:
            now = time.monotonic()
            state["frames"] += 1
            state["last_frame_t"] = now
            left.update(frame["left"], frame["left_valid"])
            right.update(frame["right"], frame["right_valid"])
            for name, kind, since, dur in events.update(
                    now, {"LEFT": frame["left_valid"], "RIGHT": frame["right_valid"]}):
                if kind == "lost":
                    print(f"[{clock(now, t0, wall0)}] {name} glove: no fresh data since "
                          f"{clock(since, t0, wall0)} (t={since - t0:.1f}s)")
                else:
                    print(f"[{clock(now, t0, wall0)}] {name} glove: fresh data again "
                          f"after {dur:.1f}s")

            if now - last_print >= args.interval:
                rate = (state["frames"] - frames_at_last_print) / (now - last_print)
                print(f"t={now - t0:6.1f}s  rate={rate:5.1f} Hz  frame_seq={frame['frame_seq']}")
                print(fmt_hand("L", frame["left"], frame["left_valid"]))
                print(fmt_hand("R", frame["right"], frame["right_valid"]))
                rx = getattr(source, "receiver_stats", None)
                if rx:
                    print(f"  receiver: left {rx['left_ratio']:.1f}% received ({rx['left_dropped']} lost, "
                          f"{rx['left_corrupt']} damaged) | right {rx['right_ratio']:.1f}% "
                          f"({rx['right_dropped']} lost, {rx['right_corrupt']} damaged)")
                last_print = now
                frames_at_last_print = state["frames"]

            if args.duration and now - t0 >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        state["stop"] = True

    events.finish(time.monotonic())
    elapsed = max(time.monotonic() - t0, 1e-9)
    n = state["frames"]
    print("\n===== Summary =====")
    print(f"Frames: {n} in {elapsed:.1f}s  (avg {n / elapsed:.1f} Hz)")
    if n == 0:
        print("No frames received. Nothing to evaluate.")
        return
    for name, h in (("Left ", left), ("Right", right)):
        ev = events.hands[name.strip().upper()]
        still = " (STILL LOST at end of run)" if ev["lost"] else ""
        print(f"{name}: fresh in {100.0 * h.valid / n:5.1f}% of frames | glove seq gaps seen: {h.seq_gaps}"
              f" | outages >{LOSS_AFTER_S:.0f}s: {ev['episodes']} (longest {ev['longest']:.1f}s){still}")
        for i in range(FLEX_PER_GLOVE):
            spread = h.flex_max[i] - h.flex_min[i]
            flag = "  <-- small spread (flex didn't move, or sensor not responding?)" if spread < FLEX_SPREAD_WARN else ""
            print(f"   {FLEX_NAMES[i]:>6}: min={h.flex_min[i]:4d} max={h.flex_max[i]:4d} spread={spread:4d}{flag}")
    print(f"(Spread warning threshold = {FLEX_SPREAD_WARN} counts is a heuristic chosen for this tool, "
          f"and only meaningful if you flexed all fingers and the palm during the run.)")


if __name__ == "__main__":
    main()
