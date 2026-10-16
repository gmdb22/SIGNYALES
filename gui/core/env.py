"""
Signyales GUI — environment: paths, which machine this is, which Python to use.

No Tk imports here, so it can be unit-tested anywhere.
"""

import os
import platform
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PI_SIDE = REPO_ROOT / "pi-side"
FIRMWARE = REPO_ROOT / "firmware"
TRAINING = REPO_ROOT / "training"

IS_WINDOWS = platform.system() == "Windows"


def is_raspberry_pi() -> bool:
    """True on a Raspberry Pi (reads the device-tree model string)."""
    try:
        model = Path("/proc/device-tree/model").read_bytes().decode(errors="ignore")
        return "Raspberry Pi" in model
    except OSError:
        return False


def machine_name() -> str:
    return "Raspberry Pi" if is_raspberry_pi() else ("Windows laptop" if IS_WINDOWS else platform.system())


def pi_side_python() -> str:
    """The pi-side venv's Python if it exists, else the Python running this app."""
    candidate = PI_SIDE / "venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
    return str(candidate) if candidate.exists() else sys.executable


def default_serial_port() -> str:
    """The hub's configured port (/dev/ttyAMA0 on the Pi 5)."""
    ensure_pi_side_on_path()
    from signyales_hub.config import HubConfig
    return HubConfig().serial_port


def ensure_pi_side_on_path():
    p = str(PI_SIDE)
    if p not in sys.path:
        sys.path.insert(0, p)


def find_tool(name: str):
    """Finds an executable on PATH, plus PlatformIO's private install folder
    (VS Code's PlatformIO extension installs `pio` there, not on PATH)."""
    found = shutil.which(name)
    if found:
        return found
    if name == "pio":
        home = Path.home() / ".platformio" / "penv"
        for c in (home / "Scripts" / "pio.exe", home / "bin" / "pio"):
            if c.exists():
                return str(c)
    return None


def child_env() -> dict:
    """Environment for child processes: unbuffered UTF-8 output, quiet TF."""
    env = dict(os.environ)
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "TF_CPP_MIN_LOG_LEVEL": "2"})
    return env
