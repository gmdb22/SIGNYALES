"""
Signyales GUI: wireless flex calibration, shared by the Pi's Calibrate tab,
the kiosk, and a laptop asking through the mirror link.

The running LivePipeline captures 8 s of raw flex readings
(pipeline.start_calibration); when it reports {"type": "calibration",
"state": "done"}, finish() saves it for the signer, makes it active, and
applies it to the running pipeline at once. Every step is also turned into an
event that can be published to connected laptops.

Laptop -> Pi commands (one JSON line, see mirror.py):
  {"type": "command", "cmd": "calibrate", "signer": "W01"}
  {"type": "command", "cmd": "use_calibration", "signer": "W01"}
  {"type": "command", "cmd": "calibration_list"}

No Tk imports.
"""

from .env import ensure_pi_side_on_path

ensure_pi_side_on_path()

from signyales_hub import calibration as cal_files  # noqa: E402
from signyales_hub.calibration import FlexCalibration, check_signer  # noqa: E402

HOW_TO = ("For 8 seconds: make a tight fist, then open the hand fully flat, again and again; "
          "also cup and flatten the palm and bend each finger to its limit.")


def rows_of(cal):
    """{"left": [[name, min, max, range, ok], ...], "right": [...]} for the hands it has."""
    return {h: [list(r) for r in cal.report(h)] for h in cal.hands}


def info_event(state, signer="", **extra):
    e = {"type": "calibration", "state": state, "signer": signer}
    e.update(extra)
    return e


def start(pipeline, signer):
    """Starts a capture on the running pipeline. Returns the event to show/publish."""
    err = check_signer(signer)
    if err:
        return info_event("error", signer, message=err)
    if pipeline is None or not pipeline.running or pipeline.stopping:
        return info_event("error", signer, message="The Pi is not reading the gloves. Start recognition "
                                                   "(or connect) on the Pi first.")
    if not pipeline.start_calibration(signer):
        return info_event("error", signer, message="A calibration is already running.")
    return info_event("started", signer, seconds=cal_files.CAPTURE_SECONDS, how_to=HOW_TO)


def finish(pipeline, done_event, directory=None):
    """Saves a finished capture and applies it. Returns the event to show/publish."""
    signer = done_event.get("signer", "")
    new = FlexCalibration.from_dict(done_event.get("result") or {})
    if not new.hands:
        return info_event("failed", signer, message="No glove data arrived during the 8 seconds: check "
                                                    "that the glove is on its battery and shows fresh "
                                                    "data, then try again. Nothing was changed.")
    cal = new.merged_with(cal_files.load_signer(signer, directory))
    path = cal_files.save(cal, directory)
    if pipeline is not None:
        pipeline.calibration = cal
    rows = rows_of(new)
    all_ok = all(r[4] for hand_rows in rows.values() for r in hand_rows)
    return info_event("saved", signer, describe=cal.describe(), rows=rows, all_ok=all_ok,
                      path=str(path), min_range=cal_files.MIN_RANGE)


def use(pipeline, signer, directory=None):
    """Makes a signer's saved calibration active and applies it."""
    cal = cal_files.set_active(signer, directory)
    if cal is None:
        return info_event("error", signer, message=f"No saved calibration for {signer!r}. Calibrate first.")
    if pipeline is not None:
        pipeline.calibration = cal
    return info_event("active", signer, describe=cal.describe(), rows=rows_of(cal))


def listing(directory=None):
    active = cal_files.load_active(directory)
    return info_event("list", active.signer if active else "",
                      signers=cal_files.list_signers(directory),
                      describe=active.describe() if active else "")


def handle_command(pipeline, cmd, directory=None):
    """A laptop's command (dict). Returns the event to publish, or None if it is not a calibration command."""
    if cmd.get("type") != "command":
        return None
    what, signer = cmd.get("cmd"), str(cmd.get("signer", "")).strip()
    if what == "calibrate":
        return start(pipeline, signer)
    if what == "use_calibration":
        return use(pipeline, signer, directory)
    if what == "calibration_list":
        return listing(directory)
    return None


def describe_rows(rows, min_range=cal_files.MIN_RANGE):
    """Plain-text lines for a results table (log boxes, the laptop)."""
    lines = []
    for hand, hand_rows in rows.items():
        lines.append(f"{hand.title()} glove:")
        for name, lo, hi, rng, ok in hand_rows:
            mark = "OK" if ok else f"TOO SMALL (want {min_range}+): check sensor/wire"
            lines.append(f"  {name:<6} {lo:>4}-{hi:<4} range {rng:<4} {mark}")
    return lines


SESSION_FILE = "calibration.json"


def note_session(session_dir, cal):
    """Keeps a copy of the calibration a recording session used
    (<session>/calibration.json, written with the first saved repetition).
    Returns a warning if this repetition used a different one, else ""."""
    import json
    from pathlib import Path
    path = Path(session_dir) / SESSION_FILE
    now = cal.to_dict() if cal is not None else {"signer": "", "created": "", "hands": {}}
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(now, indent=2), encoding="utf-8")
        return ""
    try:
        first = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if (first.get("signer"), first.get("created")) != (now["signer"], now["created"]):
        return (f"This session started with calibration {first.get('signer') or 'none'} "
                f"({first.get('created', '')[:16]}) but this repetition used "
                f"{now['signer'] or 'none'} ({now['created'][:16]}). Mixing calibrations in one session "
                "makes the data inconsistent: use a new session code after recalibrating.")
    return ""
