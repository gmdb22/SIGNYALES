"""
Signyales — Pi-side unit tests (no hardware, no model, no TensorFlow)

Checks the pure-logic pieces of the hub and its tools with synthetic
inputs: feature order, the rolling window, the debouncer (including the
silent rest label), the recorder's resampling, the model loader's
"no model" behaviour, and the helper functions in the testing tools.
Needs only numpy (and pyserial is NOT needed).

Run (from pi-side/, venv active):
    python tests/test_hub_units.py

Exit code 0 = all checks passed. Like test_frame_roundtrip.py, this is a
plain script so it runs without pytest.
"""

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

PI_SIDE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PI_SIDE))

import numpy as np  # noqa: E402

from signyales_hub.config import HubConfig  # noqa: E402
from signyales_hub.gesture_debounce import GestureDebouncer  # noqa: E402
from signyales_hub.model_runtime import GestureClassifier  # noqa: E402
from signyales_hub.windowing import WindowBuffer, extract_features  # noqa: E402

failures = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS  {name}")
    else:
        print(f"FAIL  {name}" + (f"  ({detail})" if detail else ""))
        failures.append(name)


def load_tool(name):
    """Import pi-side/tools/<name>.py as a module (tools/ is not a package)."""
    path = PI_SIDE / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"tool_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_frame(left_flex, right_flex, la, lg, ra, rg):
    def glove(flex, accel, gyro):
        return {"flex": tuple(flex), "accel": tuple(accel), "gyro": tuple(gyro)}
    return {"left_valid": True, "right_valid": True,
            "left": glove(left_flex, la, lg), "right": glove(right_flex, ra, rg)}


# ---------------------------------------------------------------- config
cfg = HubConfig()
check("config: 24 features, 50-sample window, 0.70 threshold, 3 consecutive",
      (cfg.feature_count, cfg.window_size_samples, cfg.confidence_threshold,
       cfg.debounce_required_consecutive) == (24, 50, 0.70, 3))
from signyales_hub.serial_link import FLEX_NAMES, FLEX_PER_GLOVE  # noqa: E402
check("config: feature_count = 2 x 6 flex + 12 accel/gyro, matching serial_link",
      FLEX_PER_GLOVE == 6 and len(FLEX_NAMES) == 6 and cfg.feature_count == 2 * FLEX_PER_GLOVE + 12)
check("config: silent_labels is a tuple containing 'rest'",
      isinstance(cfg.silent_labels, tuple) and "rest" in cfg.silent_labels)

# ------------------------------------------------------- extract_features
frame = make_frame([0, 4095, 1000, 2000, 3000, 3500], [10, 20, 30, 40, 50, 60],
                   (1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0), (10.0, 11.0, 12.0))
f = extract_features(frame)
check("features: length matches config.feature_count", f.shape == (cfg.feature_count,), f.shape)
check("features: float32", f.dtype == np.float32, f.dtype)
check("features: left flex first, scaled by 1/4095",
      np.allclose(f[0:6], np.array([0, 4095, 1000, 2000, 3000, 3500]) / 4095.0))
check("features: right flex next, scaled by 1/4095",
      np.allclose(f[6:12], np.array([10, 20, 30, 40, 50, 60]) / 4095.0))
check("features: then left accel, left gyro, right accel, right gyro (unscaled)",
      np.allclose(f[12:24], np.arange(1.0, 13.0)), f[12:24])

# ----------------------------------------------------------- WindowBuffer
wb = WindowBuffer(window_size=4, feature_count=2)
for i in range(3):
    wb.push(np.array([i, -i], dtype=np.float32))
check("window: not full after 3 of 4 pushes", not wb.is_full())
wb.push(np.array([3, -3], dtype=np.float32))
check("window: full after 4 pushes", wb.is_full())
wb.push(np.array([4, -4], dtype=np.float32))
arr = wb.as_array()
check("window: keeps the newest 4, oldest first", np.array_equal(arr[:, 0], [1, 2, 3, 4]), arr[:, 0])
arr[0, 0] = 99
check("window: as_array returns a copy", wb.as_array()[0, 0] == 1)

# --------------------------------------------------------------- debouncer
d = GestureDebouncer(3, 0.70)
out = [d.update("oo", 0.9) for _ in range(5)]
check("debounce: emits once on the 3rd consecutive confident prediction",
      out == [None, None, "oo", None, None], out)
d = GestureDebouncer(3, 0.70)
out = [d.update("oo", c) for c in (0.9, 0.9, 0.5, 0.9, 0.9, 0.9)]
check("debounce: a low-confidence prediction breaks the run",
      out == [None, None, None, None, None, "oo"], out)
d = GestureDebouncer(3, 0.70)
out = [d.update(lbl, 0.9) for lbl in ["oo"] * 3 + ["hindi"] * 3 + ["oo"] * 3]
check("debounce: a different gesture is emitted, then the first again",
      out[2] == "oo" and out[5] == "hindi" and out[8] == "oo", out)
d = GestureDebouncer(3, 0.70)
[d.update("oo", 0.9) for _ in range(3)]
d.reset()
out = [d.update("oo", 0.9) for _ in range(3)]
check("debounce: reset() re-arms the same gesture", out[-1] == "oo", out)
check("debounce: None label never emits", GestureDebouncer(1, 0.7).update(None, 1.0) is None)

d = GestureDebouncer(3, 0.70, silent_labels=("rest",))
seq = ["oo"] * 3 + ["rest"] * 3 + ["oo"] * 3
out = [d.update(lbl, 0.9) for lbl in seq]
check("silent: rest is never returned", "rest" not in out, out)
check("silent: confirmed rest lets the same word be spoken again",
      out[2] == "oo" and out[8] == "oo", out)
d = GestureDebouncer(3, 0.70, silent_labels=("rest",))
seq = ["oo"] * 3 + ["rest"] * 2 + ["oo"] * 3
out = [d.update(lbl, 0.9) for lbl in seq]
check("silent: an unconfirmed rest (2 of 3) does not re-arm", out.count("oo") == 1, out)
d = GestureDebouncer(3, 0.70)
out = [d.update(lbl, 0.9) for lbl in ["rest"] * 3]
check("silent: without silent_labels, 'rest' behaves like any gesture (old behaviour)",
      out[-1] == "rest", out)
d = GestureDebouncer(3, 0.70)
counts = []
for c in (0.9, 0.9, 0.2):
    d.update("oo", c)
    counts.append(d.candidate_count)
check("debounce: candidate_count tracks the run and resets", counts == [1, 2, 0], counts)

# ------------------------------------------- recorder resampling (tools)
collect = load_tool("collect_gesture")
seq = np.stack([np.linspace(0, 1, 7), np.linspace(10, 4, 7)], axis=1).astype(np.float32)
res = collect.resample_to_fixed_length(seq, 50)
check("resample: output shape (50, features)", res.shape == (50, 2), res.shape)
check("resample: endpoints preserved", np.allclose(res[0], seq[0]) and np.allclose(res[-1], seq[-1]))
check("resample: linear ramps stay linear", np.allclose(res[:, 0], np.linspace(0, 1, 50), atol=1e-6))

# ------------------------------------------------- model loader, no model
with tempfile.TemporaryDirectory() as tmp:
    clf = GestureClassifier(tmp, expected_window=50, expected_features=24)
    check("model: missing files -> available is False", clf.available is False)
    check("model: predict() returns (None, 0.0) without a model",
          clf.predict(np.zeros((50, 24), dtype=np.float32)) == (None, 0.0))
    check("model: no interpreter library is imported when there is no model",
          not any(m in sys.modules for m in ("tensorflow", "tflite_runtime", "ai_edge_litert")))

# ------------------------------------------------- performance_logger helper
perf = load_tool("performance_logger")
vals = list(range(1, 101))
check("percentile: nearest-rank p95 of 1..100 is 95", perf._percentile(vals, 95) == 95)
check("percentile: p100 is the max, single value works",
      perf._percentile(vals, 100) == 100 and perf._percentile([7.5], 95) == 7.5)

# ------------------------------------------------------- freeze_manifest
freeze = load_tool("freeze_manifest")
with tempfile.TemporaryDirectory() as tmp:
    m = freeze.build_manifest(Path(tmp), note="unit test")
    check("freeze: missing model files are reported",
          sum("missing" in w for w in m["warnings"]) == 3, m["warnings"])
    check("freeze: config values recorded",
          m["config"]["window_size_samples"] == cfg.window_size_samples
          and m["config"]["silent_labels"] == list(cfg.silent_labels))
    check("freeze: manifest is JSON-serialisable", bool(json.dumps(m)))
    (Path(tmp) / "model.tflite").write_bytes(b"abc")
    m = freeze.build_manifest(Path(tmp))
    check("freeze: SHA-256 of model.tflite recorded",
          m["model_files"]["model.tflite"]["sha256"]
          == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

# ------------------------------------------------- receiver link (USB / UART)
from types import SimpleNamespace  # noqa: E402
from signyales_hub import receiver_link as rl  # noqa: E402
from signyales_hub.serial_link import parse_stats_line  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    sp = Path(tmp) / "settings.json"
    check("link: default is usb when nothing is saved", rl.load_link(sp) == "usb")
    rl.save_link("uart", sp)
    check("link: saved choice is read back", rl.load_link(sp) == "uart")
    rl.save_setting("other", 1, sp)
    check("link: saving another setting keeps the link", rl.load_link(sp) == "uart")
    sp.write_text('{"receiver_link": "wifi"}')
    check("link: an unknown saved value falls back to usb", rl.load_link(sp) == "usb")
    sp.write_text("not json")
    check("link: an unreadable settings file falls back to usb", rl.load_link(sp) == "usb")
    try:
        rl.save_link("wifi", sp)
        check("link: saving an unknown link is refused", False)
    except ValueError:
        check("link: saving an unknown link is refused", True)

ports = [SimpleNamespace(device="/dev/ttyAMA0", vid=None),
         SimpleNamespace(device="/dev/ttyUSB1", vid=0x10C4),     # a glove (CP210x)
         SimpleNamespace(device="/dev/ttyUSB0", vid=0x1A86)]     # the receiver (CH340)
check("link: the CH340 receiver is picked over a CP210x glove",
      rl.find_usb_receiver(ports) == ("/dev/ttyUSB0", "CH340"), rl.find_usb_receiver(ports))
check("link: no USB serial chip -> (None, None)",
      rl.find_usb_receiver([SimpleNamespace(device="/dev/ttyAMA0", vid=None)]) == (None, None))
check("link: GPIO ports are recognised as UART",
      rl.is_uart_port("/dev/ttyAMA0") and rl.is_uart_port("/dev/serial0")
      and not rl.is_uart_port("/dev/ttyUSB0") and not rl.is_uart_port("COM9"))

c = HubConfig()
check("link: config defaults (usb 115200, uart /dev/ttyAMA0 460800, nothing forced)",
      (c.receiver_link, c.usb_baud, c.uart_port, c.uart_baud, c.serial_port, c.serial_baud)
      == ("", 115200, "/dev/ttyAMA0", 460800, "", 0))
c = HubConfig(receiver_link="usb")
check("link: usb -> the CH340 port at 115200",
      rl.resolve(c, ports=ports) == ("/dev/ttyUSB0", 115200, "usb"), rl.resolve(c, ports=ports))
c = HubConfig(receiver_link="uart")
check("link: uart -> /dev/ttyAMA0 at 460800",
      rl.resolve(c, ports=ports) == ("/dev/ttyAMA0", 460800, "uart"), rl.resolve(c, ports=ports))
c = HubConfig(serial_port="/dev/ttyAMA0")
check("link: --port /dev/ttyAMA0 means uart", rl.resolve(c)[1:] == (460800, "uart"), rl.resolve(c))
c = HubConfig(serial_port="COM9")
check("link: --port COM9 means usb at 115200", rl.resolve(c) == ("COM9", 115200, "usb"), rl.resolve(c))
c = HubConfig(serial_port="COM9", serial_baud=9600)
check("link: --baud wins", rl.resolve(c)[1] == 9600)
c = HubConfig(receiver_link="usb")
try:
    rl.resolve(c, ports=[])
    check("link: no receiver on USB raises ReceiverNotFound", False)
except rl.ReceiverNotFound as exc:
    check("link: no receiver on USB raises ReceiverNotFound", "no receiver found on usb" in str(exc).lower())
with tempfile.TemporaryDirectory() as tmp:
    import os  # noqa: E402
    old = os.environ.get("SIGNYALES_SETTINGS")
    os.environ["SIGNYALES_SETTINGS"] = str(Path(tmp) / "s.json")
    try:
        rl.save_link("uart")
        check("link: the saved choice is used when config leaves it empty",
              rl.resolve(HubConfig(), ports=ports)[2] == "uart")
    finally:
        if old is None:
            os.environ.pop("SIGNYALES_SETTINGS", None)
        else:
            os.environ["SIGNYALES_SETTINGS"] = old

st = parse_stats_line("[stats] frames=5 | left: ratio=99.5% dropped=2 corrupt=1 | right: ratio=0.0% dropped=0 corrupt=0")
check("stats: the receiver's [stats] line is parsed",
      st is not None and st["frames"] == 5 and st["left_ratio"] == 99.5 and st["left_corrupt"] == 1, st)
check("stats: other text is not a stats line", parse_stats_line("Setup complete. Waiting for gloves...") is None)

# ------------------------------------------------- output (subtitle / speech)
import io  # noqa: E402
import contextlib  # noqa: E402
from signyales_hub.subtitle_display import SubtitleDisplay  # noqa: E402
from signyales_hub import tts_engine  # noqa: E402

sd = SubtitleDisplay()
sd._clear_screen = lambda: None          # don't clear the test runner's terminal
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    sd.show("salamat")
check("subtitle: show() renders text without errors", len(buf.getvalue().strip()) > 0)

engine = tts_engine.TTSEngine()
check("speech: backend is reported", engine.backend in ("pyttsx3", "espeak-ng"), engine.backend)
engine._backend = "espeak-ng"            # force the subprocess path, without making a sound
real_run = tts_engine.subprocess.run


def _missing(*a, **k):
    raise FileNotFoundError("espeak-ng")


tts_engine.subprocess.run = _missing
try:
    check("speech: speak_blocking returns False when no backend can speak",
          engine.speak_blocking("test") is False)
finally:
    tts_engine.subprocess.run = real_run
    engine.shutdown()

print()
if failures:
    print(f"{len(failures)} check(s) FAILED: {failures}")
    sys.exit(1)
print("All Pi-side unit checks passed (synthetic inputs only; says nothing about hardware).")
