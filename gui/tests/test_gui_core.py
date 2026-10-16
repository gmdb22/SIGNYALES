"""
Signyales GUI — tests for the window-free logic (no Tk, no hardware, no model).

Covers: task lists per machine, the process runner, the live pipeline
(including agreement with main.py's debounce behaviour), the GUI recorder's
file format, the Pi-to-laptop mirror link over localhost, and the MAC
helpers. Needs numpy only.

Run (from the repo root, venv active):
    python gui/tests/test_gui_core.py
"""

import sys
import tempfile
import threading
import time
from pathlib import Path

GUI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GUI))

import numpy as np  # noqa: E402

from core import env, hardware, mirror, recorder, tasks  # noqa: E402
from core.live import LivePipeline  # noqa: E402
from core.procs import ProcessRunner  # noqa: E402

failures = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def wait_for(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def frame(seq, left_valid=True, right_valid=True, flex=1000):
    def glove(gid):
        return {"glove_id": gid, "seq": seq, "timestamp_ms": seq * 20, "flex": (flex,) * 5,
                "accel": (0.0, 0.0, 1.0), "gyro": (0.0, 0.0, 0.0), "checksum": 0}
    return {"frame_seq": seq, "frame_timestamp_ms": seq * 20, "left_valid": left_valid,
            "right_valid": right_valid, "left": glove(0), "right": glove(1), "checksum": 0}


class FakeClassifier:
    """Returns labels from a script, one per predict() call."""
    available = True

    def __init__(self, script):
        self.labels = sorted(set(script))
        self._script = list(script)

    def predict(self, window):
        assert window.shape == (50, 22)
        return (self._script.pop(0), 0.95) if self._script else ("rest", 0.95)


def run_pipeline(frames, classifier):
    events = []
    p = LivePipeline(lambda: iter(frames), lambda: classifier, events.append)
    p.start()
    p.join(10)
    return events


# ---------------------------------------------------------------- env / tasks
check("env: repo root found", (env.PI_SIDE / "signyales_hub").is_dir())
laptop = {t.key for t in tasks.tasks_for(tasks.LAPTOP)}
pi = {t.key for t in tasks.tasks_for(tasks.PI)}
check("tasks: laptop has software, training and compile checks",
      {"roundtrip", "units", "pipeline", "native", "training", "compile_left_glove"} <= laptop)
check("tasks: laptop has no Pi-only checks", not ({"loopback", "liveview", "freeze"} & laptop))
check("tasks: Pi has UART loopback, live view, freeze and the software checks",
      {"roundtrip", "units", "pipeline", "loopback", "liveview", "freeze"} <= pi)
freeze = [t for t in tasks.tasks_for(tasks.PI) if t.key == "freeze"][0]
check("tasks: freeze manifest gets a fresh file name per click",
      "freeze_manifest_" in " ".join(tasks.resolve_cmd(freeze)))

# ---------------------------------------------------------------- runner
lines, done = [], {}
r = ProcessRunner(lines.append, lambda rc, to: done.update(rc=rc, to=to))
r.start([sys.executable, "-c", "print('one'); print('two')"], GUI)
wait_for(lambda: "rc" in done)
check("runner: streams output lines and exit code", lines == ["one", "two"] and done.get("rc") == 0,
      f"{lines} {done}")
done.clear()
r = ProcessRunner(lambda s: None, lambda rc, to: done.update(rc=rc, to=to))
r.start([sys.executable, "-c", "import time; time.sleep(30)"], GUI, timeout=0.5)
check("runner: timeout stops a long command and reports it", wait_for(lambda: "rc" in done, 6)
      and done.get("to") is True)

# ---------------------------------------------------------------- live pipeline
# 50 frames fill the window; inference every 5th frame (frames 50, 55, 60, ...).
frames = [frame(i) for i in range(1, 50 + 5 * 12)]
script = ["oo"] * 4 + ["rest"] * 3 + ["oo"] * 3 + ["salamat"] * 2
ev = run_pipeline(frames, FakeClassifier(script))
gestures = [e["label"] for e in ev if e["type"] == "gesture"]
check("live: same debounce result as main.py (oo, rest re-arms, oo again; 2x salamat too few)",
      gestures == ["oo", "oo"], gestures)
check("live: started and stopped events", ev[0]["type"] == "started" and ev[-1]["type"] == "stopped")
preds = [e for e in ev if e["type"] == "prediction"]
check("live: one prediction per stride once the window is full", len(preds) == 12, len(preds))

bad = [frame(i) for i in range(1, 60)] + [frame(i, False, False) for i in range(60, 70)]
ev = run_pipeline(bad, FakeClassifier(["oo"] * 10))
check("live: frames with both hands invalid are skipped (no inference after frame 59)",
      len([e for e in ev if e["type"] == "prediction"]) == 2)

events = []
from signyales_hub.serial_link import SimulatedFrameSource  # noqa: E402
p = LivePipeline(lambda: SimulatedFrameSource(rate_hz=50), None, events.append)
p.start()
got_status = wait_for(lambda: any(e["type"] == "status" for e in events), 3)
p.stop()
p.join(3)
check("live: simulated source gives status events without a model", got_status)
check("live: stop() ends the thread", not p.running)
st = [e for e in events if e["type"] == "status"][0]
check("live: status has fps, fresh % and flex values",
      st["fps"] > 0 and st["left_fresh_pct"] == 100 and len(st["right_flex"]) == 5)

# ---------------------------------------------------------------- recorder
with tempfile.TemporaryDirectory() as tmp:
    rec = recorder.GestureRecorder(tmp)
    check("recorder: bad labels rejected", recorder.check_label("Salamat") is not None
          and recorder.check_label("salamat") is None and recorder.check_label("rest") is None)
    rec.start_rep()
    for i in range(37):
        rec.on_frame(frame(i), np.full(22, i, dtype=np.float32))
    path, n = rec.stop_rep("salamat")
    with np.load(path) as data:          # close the file: Windows can't delete open files
        shape, label = data["features"].shape, str(data["label"])
    check("recorder: saves rep_0000.npz like collect_gesture.py",
          path.name == "rep_0000.npz" and shape == (50, 22) and label == "salamat" and n == 37)
    rec.start_rep()
    rec.on_frame(frame(1), np.zeros(22, dtype=np.float32))
    try:
        rec.stop_rep("salamat")
        short_ok = False
    except ValueError:
        short_ok = True
    check("recorder: a 1-frame repetition is refused", short_ok)
    rec.start_rep()
    for i in range(10):
        rec.on_frame(frame(i), np.zeros(22, dtype=np.float32))
    path2, _ = rec.stop_rep("salamat")
    check("recorder: numbering continues", path2.name == "rep_0001.npz"
          and recorder.count_reps(tmp, "salamat") == 2)
    check("recorder: frames are ignored when not recording", not rec.recording)

# ---------------------------------------------------------------- mirror
received, disconnected = [], []
server = mirror.MirrorServer(host="127.0.0.1", port=0)
server.start()
client = mirror.MirrorClient(received.append, disconnected.append)
client.connect("127.0.0.1", server.port)
wait_for(lambda: server.client_count == 1)
server.publish({"type": "prediction", "label": "x", "confidence": 0.5})
server.publish({"type": "gesture", "label": "salamat", "confidence": 0.97})
wait_for(lambda: received)
check("mirror: laptop receives the recognized word", received and received[0]["label"] == "salamat",
      received)
check("mirror: per-inference predictions are not sent", all(e["type"] != "prediction" for e in received))
server.publish({"type": "started", "model": True, "labels": ["oo", "salamat"]})
late = []
client2 = mirror.MirrorClient(late.append)
client2.connect("127.0.0.1", server.port)
wait_for(lambda: late)
check("mirror: a laptop that connects later still gets the word list",
      late and late[0]["type"] == "started" and late[0]["labels"] == ["oo", "salamat"], late)
client2.close()
server.stop()
check("mirror: laptop is told when the Pi stops sharing", wait_for(lambda: disconnected, 3))
client.close()
check("mirror: local IP list is not empty", bool(mirror.local_ip_addresses()))

# ---------------------------------------------------------------- hardware helpers
check("mac: parsed from the MAC utility's line",
      hardware.parse_mac("MAC Address: 24:6f:28:ab:cd:ef") == "24:6F:28:AB:CD:EF")
check("mac: no MAC in an ordinary line", hardware.parse_mac("Setup complete. Streaming...") is None)
cfg_mac = hardware.read_config_mac()
check("mac: reads RECEIVER_MAC from config.h", cfg_mac == hardware.PLACEHOLDER, cfg_mac)
check("mac: placeholder is reported", "placeholder" in hardware.compare_mac("24:6F:28:AB:CD:EF", cfg_mac))
check("mac: match and mismatch verdicts",
      hardware.compare_mac("24:6F:28:AB:CD:EF", "24:6F:28:AB:CD:EF").startswith("OK")
      and hardware.compare_mac("24:6F:28:AB:CD:EF", "24:6F:28:AB:CD:E0").startswith("MISMATCH"))

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("All GUI core checks passed (synthetic data only; no window, no hardware).")
