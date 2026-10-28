"""
Signyales GUI — the checks behind the Testing-mode buttons.

Each Task is a command plus the folder to run it in. The commands are the
same ones the guides tell you to type, so a button result means the same
thing as running the command by hand. No Tk imports.
"""

import time
from dataclasses import dataclass, field

from .env import FIRMWARE, PI_SIDE, REPO_ROOT, find_tool, pi_side_python

LAPTOP, PI = "laptop", "pi"

# (button label, firmware folder, PlatformIO env or None)
FIRMWARE_TARGETS = [
    ("Left glove", FIRMWARE / "glove", "left_glove"),
    ("Right glove", FIRMWARE / "glove", "right_glove"),
    ("Receiver", FIRMWARE / "receiver", None),
    ("MAC address utility", FIRMWARE / "tools" / "get_mac_address", None),
    ("Glove hardware check", FIRMWARE / "tools" / "glove_hw_check", None),
]

UART_LOOPBACK = ("import serial,time; s=serial.Serial('/dev/ttyAMA0',115200,timeout=1); "
                 "s.write(b'hello'); time.sleep(0.2); r=s.read(5); print(r); "
                 "print('PASS: loopback works' if r==b'hello' else 'FAIL: expected b\\'hello\\''); "
                 "raise SystemExit(0 if r==b'hello' else 1)")


@dataclass
class Task:
    key: str
    title: str
    help: str
    cmd: object                         # list, or a function returning a list
    cwd: object
    where: tuple = (LAPTOP, PI)
    timeout: float = None
    success_on_timeout: bool = False   # for commands that run until stopped
    needs: list = field(default_factory=list)  # executables that must exist

    def missing(self):
        return [n for n in self.needs if not find_tool(n)]


def software_tasks():
    py = pi_side_python()
    return [
        Task("roundtrip", "Frame format round-trip",
             "Python and firmware agree on the 103-byte frame format (6 flex per glove).",
             [py, "tests/test_frame_roundtrip.py"], PI_SIDE),
        Task("units", "Pi-side unit tests",
             "Feature order, windowing, debouncer, rest label, subtitle and speech plumbing.",
             [py, "tests/test_hub_units.py"], PI_SIDE),
        Task("pipeline", "Pipeline smoke test (simulated, 8 s)",
             "Runs the real hub app on fake data for 8 seconds; stopping it is the pass.",
             [py, "-m", "signyales_hub.main", "--simulate", "--no-tts", "-v"], PI_SIDE,
             timeout=8, success_on_timeout=True),
        Task("native", "Native firmware logic tests",
             "Compiles packet.h / frame.h checks with g++ (skipped if g++ is not installed).",
             [py, "gui/core/run_native_tests.py"], REPO_ROOT),
        Task("training", "Training smoke test (about 1-3 min)",
             "Trains tiny models on synthetic data in a temp folder. Needs TensorFlow and scikit-learn.",
             [py, "training/tests/test_train_smoke.py"], REPO_ROOT, where=(LAPTOP,)),
    ]


def firmware_compile_tasks():
    tasks = []
    for label, folder, env in FIRMWARE_TARGETS:
        cmd = ["pio", "run"] + (["-e", env] if env else [])
        tasks.append(Task(f"compile_{env or folder.name}", f"Compile: {label}",
                          "PlatformIO build only, nothing is flashed. First run downloads the toolchain.",
                          cmd, folder, where=(LAPTOP,), needs=["pio"]))
    return tasks


def pi_hardware_tasks():
    py = pi_side_python()
    return [
        Task("loopback", "UART loopback (jumper GPIO14-15, UART option only)",
             "Only for the UART option (the USB cable doesn't need it). Receiver unplugged: jumper GPIO14 (pin 8) to GPIO15 (pin 10). Expects b'hello'. Remove the jumper afterwards.",
             [py, "-c", UART_LOOPBACK], PI_SIDE, where=(PI,), timeout=10),
        Task("liveview", "Live data check, 30 s (receiver connected, gloves on)",
             "Stage 6: tools/live_view.py summary of frame rate, fresh %, finger ranges, on the saved receiver link (USB by default).",
             [py, "tools/live_view.py", "--duration", "30"], PI_SIDE,
             where=(PI,), timeout=60),
        Task("freeze", "Freeze manifest (model folder 'model')",
             "Records commit, model hashes and config before field testing.",
             lambda: [py, "tools/freeze_manifest.py", "--model-dir", "model", "--out",
                      time.strftime("results/freeze_manifest_%Y%m%d_%H%M%S.json")],
             PI_SIDE, where=(PI,)),
    ]


def resolve_cmd(task: Task) -> list:
    """Replaces a bare tool name such as 'pio' with its full path."""
    cmd = list(task.cmd() if callable(task.cmd) else task.cmd)
    if cmd and cmd[0] in task.needs:
        cmd[0] = find_tool(cmd[0]) or cmd[0]
    return cmd


def tasks_for(machine: str):
    every = software_tasks() + firmware_compile_tasks() + pi_hardware_tasks()
    return [t for t in every if machine in t.where]


def inspect_cmd(folder):
    return [pi_side_python(), "tools/inspect_recordings.py", "--root", str(folder)], PI_SIDE


def train_cmd(data_dir, out_dir, quantize=False):
    cmd = [pi_side_python(), "train.py", "--data-dir", str(data_dir), "--out-dir", str(out_dir)]
    if quantize:
        cmd.append("--quantize")
    return cmd, REPO_ROOT / "training" / "src"


def benchmark_cmd(model_dir):
    return [pi_side_python(), "tools/benchmark_inference.py", "--model-dir", str(model_dir)], PI_SIDE
