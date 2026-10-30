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
from core.live import LinkStats, LivePipeline, link_stats_text  # noqa: E402
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
        return {"glove_id": gid, "seq": seq, "timestamp_ms": seq * 20, "flex": (flex,) * 6,
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
        assert window.shape == (50, 24)
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
live = [t for t in tasks.tasks_for(tasks.PI) if t.key == "liveview"][0]
check("tasks: the live data check uses the saved receiver link (no fixed --port)",
      "--port" not in tasks.resolve_cmd(live), tasks.resolve_cmd(live))
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
      st["fps"] > 0 and st["left_fresh_pct"] == 100 and len(st["right_flex"]) == 6)
check("live: status has the Pi's link numbers (no lost packets in fake data, no receiver stats)",
      st["left_received_pct"] == 100.0 and st["left_lost"] == 0 and st["right_lost"] == 0
      and st["receiver"] is None, st)
started = [e for e in events if e["type"] == "started"][0]
check("live: started event says which link and port (empty for fake data)",
      started.get("link") == "" and started.get("port") == "", started)

ls = LinkStats()
for seq in (10, 10, 11, 12, 15, 15, 16):      # 13 and 14 lost; repeats don't count
    ls.update(seq)
check("link stats: repeats ignored, a gap counts as lost",
      (ls.expected, ls.lost, ls.received_pct) == (7, 2, 71.4), (ls.expected, ls.lost, ls.received_pct))
ls.update(0)                                  # the glove restarted
ls.update(1)
check("link stats: a glove restart starts counting again",
      (ls.expected, ls.lost) == (9, 2), (ls.expected, ls.lost))
check("link stats: nothing seen yet = 0 %", LinkStats().received_pct == 0.0)
rx = {"frames": 9, "left_ratio": 99.5, "left_dropped": 2, "left_corrupt": 1,
      "right_ratio": 98.0, "right_dropped": 3, "right_corrupt": 0}
check("link text: the receiver's own numbers when present (USB)",
      link_stats_text({"receiver": rx, "left_received_pct": 50.0, "left_lost": 9,
                       "right_received_pct": 50.0, "right_lost": 9}).startswith("Receiver: left 99.5%"))
check("link text: the Pi's numbers otherwise (UART), and nothing for an old status event",
      link_stats_text({"receiver": None, "left_received_pct": 97.5, "left_lost": 4,
                       "right_received_pct": 100.0, "right_lost": 0}).startswith("Measured on the Pi: left 97.5%")
      and link_stats_text({"fps": 50}) == "")

# ---------------------------------------------------------------- recorder
with tempfile.TemporaryDirectory() as tmp:
    rec = recorder.GestureRecorder(tmp)
    check("recorder: bad labels rejected", recorder.check_label("Salamat") is not None
          and recorder.check_label("salamat") is None and recorder.check_label("rest") is None)
    rec.start_rep()
    for i in range(37):
        rec.on_frame(frame(i), np.full(24, i, dtype=np.float32))
    path, n = rec.stop_rep("salamat")
    with np.load(path) as data:          # close the file: Windows can't delete open files
        shape, label = data["features"].shape, str(data["label"])
    check("recorder: saves rep_0000.npz like collect_gesture.py",
          path.name == "rep_0000.npz" and shape == (50, 24) and label == "salamat" and n == 37)
    rec.start_rep()
    rec.on_frame(frame(1), np.zeros(24, dtype=np.float32))
    try:
        rec.stop_rep("salamat")
        short_ok = False
    except ValueError:
        short_ok = True
    check("recorder: a 1-frame repetition is refused", short_ok)
    rec.start_rep()
    for i in range(10):
        rec.on_frame(frame(i), np.zeros(24, dtype=np.float32))
    path2, _ = rec.stop_rep("salamat")
    check("recorder: numbering continues", path2.name == "rep_0001.npz"
          and recorder.count_reps(tmp, "salamat") == 2)
    check("recorder: frames are ignored when not recording", not rec.recording)
    rec.start_rep()
    for i in range(3):
        rec.on_frame(frame(i), np.zeros(24, dtype=np.float32))
    check("recorder: frame_count shows frames in the current repetition", rec.frame_count == 3)
    rec.cancel_rep()
    check("recorder: frame_count is 0 when not recording", rec.frame_count == 0)

# ---------------------------------------------------------------- data folder check
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    ok, msg, _ = recorder.describe_data_folder(root)
    check("data folder: empty folder is refused with a hint", not ok and "No recordings" in msg)
    sess = root / "W01_S01"
    for word in ("salamat", "oo"):
        (sess / word).mkdir(parents=True)
        for r in range(recorder.MIN_REPS_PER_WORD):
            np.savez(sess / word / f"rep_{r:04d}.npz", features=np.zeros((50, 24), np.float32), label=word)
    ok, msg, words = recorder.describe_data_folder(root)
    check("data folder: picking the parent of sessions is explained", not ok and "W01_S01" in msg, msg)
    ok, msg, words = recorder.describe_data_folder(sess)
    check("data folder: a session folder with 2 words x 10 is accepted", ok and words == {"oo": 10, "salamat": 10},
          words)
    (sess / "oo" / "rep_0009.npz").unlink()
    ok, msg, words = recorder.describe_data_folder(sess)
    check("data folder: a word with fewer than 10 recordings is refused", not ok and "oo (9)" in msg, msg)
    np.savez(sess / "oo" / "rep_0009.npz", features=np.zeros((50, 24), np.float32), label="oo")
    ok, msg, words = recorder.describe_data_folder(sess / "salamat")
    check("data folder: a single word folder is refused", not ok)
    (sess / "_stage7b").mkdir()
    np.savez(sess / "_stage7b" / "rep_0000.npz", features=np.zeros((50, 24), np.float32), label="x")
    ok, msg, words = recorder.describe_data_folder(sess)
    check("data folder: '_' folders are not counted (like training)", "_stage7b" not in words)

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

# ---------------------------------------------------------------- speech helper process
import subprocess  # noqa: E402
worker = subprocess.Popen([sys.executable, str(GUI / "core" / "speech_worker.py")], env=env.child_env(),
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          text=True, encoding="utf-8")
try:
    lines = []
    for _ in range(20):                      # skip any diagnostic lines before READY
        line = worker.stdout.readline().strip()
        lines.append(line)
        if line.startswith("READY") or not line:
            break
    check("speech helper: starts and reports its backend", lines[-1].startswith("READY"), lines)
    worker.stdin.write("\n")                 # empty line: nothing is spoken, so no sound in tests
    worker.stdin.flush()
    check("speech helper: answers each request", worker.stdout.readline().strip() == "OK")
finally:
    worker.stdin.close()
    worker.wait(timeout=10)
check("speech helper: exits when the GUI closes its input", worker.returncode == 0, worker.returncode)

# ---------------------------------------------------------------- screen size, options, kiosk lock
from core import display  # noqa: E402
check("display: design size on a 1180x780 screen = scale 1.0",
      display.ui_scale(1180, 780, allow_grow=False) == 1.0)
check("display: 800x480 LCD shrinks the text (about 0.62)",
      0.6 <= display.ui_scale(800, 480, allow_grow=False) < 0.65, display.ui_scale(800, 480, False))
check("display: full app never grows on a big screen; kiosk does (capped at 2.0)",
      display.ui_scale(1920, 1080, allow_grow=False) == 1.0
      and 1.3 < display.ui_scale(1920, 1080, allow_grow=True) <= 2.0
      and display.ui_scale(3840, 2160, allow_grow=True) == 2.0)
check("display: --scale override is used, within limits",
      display.ui_scale(800, 480, False, override=1.5) == 1.5 and display.ui_scale(800, 480, False, override=9) == 2.0)
w, h, mx = display.window_size(800, 480)
check("display: window fits a small screen and is maximized there", (w, h, mx) == (800, 440, True), (w, h, mx))
check("display: normal laptop screen keeps the 1180x780 window",
      display.window_size(1920, 1080) == (1180, 780, False), display.window_size(1920, 1080))
check("options: --link usb/uart parsed, default None (= the saved setting)",
      display.parse_args(["--kiosk", "--link", "uart"]).link == "uart"
      and display.parse_args(["--kiosk"]).link is None)
o = display.parse_args(["--kiosk", "--simulate", "--port", "COM7", "--no-speech"])
check("options: --kiosk --simulate --port --no-speech parsed",
      o.kiosk and o.simulate and o.port == "COM7" and o.no_speech and not o.share and o.model_dir is None)
check("options: no options = normal window", not display.parse_args([]).kiosk)
with tempfile.TemporaryDirectory() as tmp:
    a, b = display.SingleInstance(Path(tmp) / "k.lock"), display.SingleInstance(Path(tmp) / "k.lock")
    first, second = a.acquire(), b.acquire()
    a.release()
    third = b.acquire()
    b.release()
    check("kiosk lock: a second copy is refused, and allowed once the first closes",
          first and not second and third, (first, second, third))
check("kiosk errors: missing port, permission and busy port get plain advice",
      "doesn't exist" in display.friendly_error("Could not start: [Errno 2] No such file or directory", "/dev/ttyAMA0")
      and "dialout" in display.friendly_error("[Errno 13] Permission denied: '/dev/ttyAMA0'", "/dev/ttyAMA0")
      and "systemctl stop signyales" in display.friendly_error("Device or resource busy", "/dev/ttyAMA0"))
check("kiosk errors: no receiver on USB says to plug it in or choose UART",
      "data cable" in display.friendly_error("Could not start: no receiver found on USB (looked for ...)", None)
      and "UART" in display.friendly_error("no receiver found on USB", None))
check("kiosk errors: a missing USB port is not blamed on the UART setting",
      "raspi" not in display.friendly_error("[Errno 2] No such file or directory: '/dev/ttyUSB0'", "/dev/ttyUSB0")
      and "4.5" in display.friendly_error("[Errno 2] No such file or directory", "/dev/ttyAMA0"))

# ---------------------------------------------------------------- hardware helpers
check("mac: parsed from the MAC utility's line",
      hardware.parse_mac("MAC Address: 24:6f:28:ab:cd:ef") == "24:6F:28:AB:CD:EF")
check("mac: no MAC in an ordinary line", hardware.parse_mac("Setup complete. Streaming...") is None)
cfg_mac = hardware.read_config_mac()
# config.h has the placeholder in git, or your receiver's MAC once you paste it in (Stage 1b).
check("mac: reads RECEIVER_MAC from config.h (placeholder or a real MAC)",
      cfg_mac == hardware.PLACEHOLDER or bool(cfg_mac and hardware.parse_mac(cfg_mac) == cfg_mac), cfg_mac)
check("mac: placeholder is reported",
      "placeholder" in hardware.compare_mac("24:6F:28:AB:CD:EF", hardware.PLACEHOLDER))
check("mac: match and mismatch verdicts",
      hardware.compare_mac("24:6F:28:AB:CD:EF", "24:6F:28:AB:CD:EF").startswith("OK")
      and hardware.compare_mac("24:6F:28:AB:CD:EF", "24:6F:28:AB:CD:E0").startswith("MISMATCH"))

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("All GUI core checks passed (synthetic data only; no window, no hardware).")
