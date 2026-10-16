"""
Signyales — Test Dashboard
=============================
A local, double-click-able GUI for running every test that doesn't need
hardware, without remembering commands, folders, or venv activation.

Run it:
    python tools/test_dashboard.py          (from the repo root)

Uses only Python's standard library (tkinter), so there's nothing extra to
install to run the dashboard itself — only the individual tests it calls
have their own normal requirements (numpy for the pipeline test, g++ for
the native logic tests, PlatformIO for the firmware compile check), and
each button explains clearly if its tool isn't available rather than
crashing the whole dashboard.

All paths are computed from this script's own location, not the current
working directory, so it works correctly no matter which folder you
launch it from — the same lesson learned the hard way from a real path
bug in training/src/train.py earlier in this project.
"""

import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

REPO_ROOT = Path(__file__).resolve().parent.parent
PI_SIDE_DIR = REPO_ROOT / "pi-side"
FIRMWARE_DIR = REPO_ROOT / "firmware"
NATIVE_TESTS_DIR = FIRMWARE_DIR / "tests" / "native"

IS_WINDOWS = platform.system() == "Windows"


def find_pi_side_python():
    """Prefer pi-side's own venv if it exists, so the dashboard works
    correctly even if launched from a terminal that doesn't have it
    activated — falls back to whatever Python is currently running this
    script if no venv is found."""
    if IS_WINDOWS:
        candidate = PI_SIDE_DIR / "venv" / "Scripts" / "python.exe"
    else:
        candidate = PI_SIDE_DIR / "venv" / "bin" / "python"
    return str(candidate) if candidate.exists() else sys.executable


PI_SIDE_PYTHON = find_pi_side_python()


class TestRunner:
    """One row in the dashboard: a button, a status indicator, and the
    subprocess command it runs."""

    def __init__(self, app, key, label, run_fn):
        self.app = app
        self.key = key
        self.label = label
        self.run_fn = run_fn
        self.status = "not run"

    def run(self):
        self.app.set_status(self.key, "running")
        self.app.log(f"\n{'=' * 60}\n{self.label}\n{'=' * 60}")
        try:
            passed, output = self.run_fn()
        except FileNotFoundError as e:
            passed = None  # tool not available — not a real failure
            output = f"Required tool not found: {e}\n" \
                     f"This test is optional — see the dashboard's README for setup, " \
                     f"or just skip it."
        except Exception as e:
            passed = False
            output = f"Unexpected error: {e}"
        self.app.log(output)
        if passed is None:
            self.app.set_status(self.key, "skipped")
        elif passed:
            self.app.set_status(self.key, "pass")
        else:
            self.app.set_status(self.key, "fail")


def run_subprocess(cmd, cwd, timeout=None):
    """Runs a command, returns (passed, combined_output). Raises
    FileNotFoundError if the command itself isn't installed, which
    callers handle specially (not the same as the test failing)."""
    result = subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output


def test_frame_roundtrip():
    return run_subprocess([PI_SIDE_PYTHON, "tests/test_frame_roundtrip.py"], PI_SIDE_DIR)


def test_hub_units():
    return run_subprocess([PI_SIDE_PYTHON, "tests/test_hub_units.py"], PI_SIDE_DIR)


def test_train_smoke():
    # Needs tensorflow and scikit-learn in the pi-side venv. Trains three tiny
    # models on synthetic data in a temp folder (about a minute).
    return run_subprocess([PI_SIDE_PYTHON, "training/tests/test_train_smoke.py"],
                          PI_SIDE_DIR.parent, timeout=600)


def test_native_logic():
    ext = ".exe" if IS_WINDOWS else ""
    results = []
    overall_pass = True

    for src, inc_dir, exe_name in [
        ("test_packet_logic.cpp", "../../glove/src", f"test_packet_logic{ext}"),
        ("test_frame_logic.cpp", "../../receiver/src", f"test_frame_logic{ext}"),
    ]:
        compile_cmd = ["g++", "-Wall", "-Wextra", f"-I{inc_dir}", "-o", exe_name, src]
        ok, out = run_subprocess(compile_cmd, NATIVE_TESTS_DIR)
        results.append(f"--- compiling {src} ---\n{out}")
        if not ok:
            overall_pass = False
            continue
        run_cmd = [str(NATIVE_TESTS_DIR / exe_name)] if not IS_WINDOWS else [exe_name]
        ok, out = run_subprocess(run_cmd, NATIVE_TESTS_DIR)
        results.append(out)
        overall_pass = overall_pass and ok

    return overall_pass, "\n".join(results)


def test_pipeline_smoke():
    cmd = [PI_SIDE_PYTHON, "-m", "signyales_hub.main", "--simulate", "--no-tts", "-v"]
    try:
        result = subprocess.run(cmd, cwd=str(PI_SIDE_DIR), capture_output=True, text=True, timeout=6)
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output
    except subprocess.TimeoutExpired as e:
        # Expected: this test loops forever by design under --simulate.
        # Being killed by our own timeout IS the pass condition, not a failure.
        # e.stdout/e.stderr can come back as raw bytes even with text=True,
        # depending on exactly when the timeout hit — decode each piece
        # BEFORE concatenating, not after, or a str+bytes mix crashes here.
        stdout = e.stdout or ""
        stderr = e.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        output = stdout + stderr
        return True, output + "\n\n(Stopped after 6s on purpose — this test runs continuously by design.)"


def test_firmware_compile():
    targets = [
        ("left glove", FIRMWARE_DIR / "glove", "left_glove"),
        ("right glove", FIRMWARE_DIR / "glove", "right_glove"),
        ("receiver", FIRMWARE_DIR / "receiver", None),
        ("MAC utility", FIRMWARE_DIR / "tools" / "get_mac_address", None),
    ]
    results = []
    overall_pass = True
    for name, dir_, env in targets:
        cmd = ["pio", "run"] + (["-e", env] if env else [])
        ok, out = run_subprocess(cmd, dir_, timeout=300)
        results.append(f"--- {name} ---\n{out}")
        overall_pass = overall_pass and ok
    return overall_pass, "\n".join(results)


STATUS_COLORS = {
    "not run": "#888888",
    "running": "#d9a441",
    "pass": "#2f7a4f",
    "fail": "#b3412c",
    "skipped": "#5c6670",
}
STATUS_LABELS = {
    "not run": "Not run",
    "running": "Running...",
    "pass": "PASS",
    "fail": "FAIL",
    "skipped": "Skipped (tool not found)",
}


class DashboardApp:
    def __init__(self, root):
        self.root = root
        root.title("Signyales Test Dashboard")
        root.geometry("820x600")

        self.queue = queue.Queue()
        self.status_labels = {}

        header = tk.Label(
            root, text="Signyales \u2014 No-Hardware Test Dashboard",
            font=("Segoe UI", 14, "bold"), pady=10,
        )
        header.pack()

        subtitle = tk.Label(
            root,
            text="Runs each test for you \u2014 no commands, no folders, no venv activation needed.",
            font=("Segoe UI", 9), fg="#555555",
        )
        subtitle.pack(pady=(0, 10))

        self.runners = {
            "frame": TestRunner(self, "frame", "Frame Format Round-Trip Test", test_frame_roundtrip),
            "units": TestRunner(self, "units", "Pi-Side Unit Tests", test_hub_units),
            "native": TestRunner(self, "native", "Native Firmware Logic Tests", test_native_logic),
            "pipeline": TestRunner(self, "pipeline", "Pi-Side Pipeline Smoke Test", test_pipeline_smoke),
            "firmware": TestRunner(self, "firmware", "Firmware Compile Check (slow, needs internet)", test_firmware_compile),
            "training": TestRunner(self, "training", "Training Smoke Test (slow, needs TensorFlow)", test_train_smoke),
        }

        button_frame = tk.Frame(root)
        button_frame.pack(fill="x", padx=16)

        for key, runner in self.runners.items():
            row = tk.Frame(button_frame)
            row.pack(fill="x", pady=3)
            btn = tk.Button(row, text=f"Run: {runner.label}", width=38, anchor="w",
                             command=lambda r=runner: self.run_one(r))
            btn.pack(side="left")
            status_lbl = tk.Label(row, text=STATUS_LABELS["not run"],
                                    fg=STATUS_COLORS["not run"], font=("Segoe UI", 9, "bold"), width=24)
            status_lbl.pack(side="left", padx=10)
            self.status_labels[key] = status_lbl

        run_all_btn = tk.Button(root, text="Run All (except firmware compile and training)", bg="#1f2933", fg="white",
                                  font=("Segoe UI", 10, "bold"), command=self.run_all)
        run_all_btn.pack(pady=10)

        log_label = tk.Label(root, text="Output:", font=("Segoe UI", 9, "bold"))
        log_label.pack(anchor="w", padx=16)

        self.log_text = tk.Text(root, height=20, font=("Consolas", 9), bg="#1d2227", fg="#e8e6e1")
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.root.after(100, self.poll_queue)

    def log(self, text):
        self.queue.put(("log", text))

    def set_status(self, key, status):
        self.queue.put(("status", key, status))

    def poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "log":
                    self.log_text.insert("end", item[1] + "\n")
                    self.log_text.see("end")
                elif item[0] == "status":
                    _, key, status = item
                    lbl = self.status_labels[key]
                    lbl.config(text=STATUS_LABELS[status], fg=STATUS_COLORS[status])
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def run_one(self, runner):
        threading.Thread(target=runner.run, daemon=True).start()

    def run_all(self):
        def _run():
            for key in ("frame", "units", "native", "pipeline"):
                self.runners[key].run()
        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = DashboardApp(root)
    root.mainloop()
