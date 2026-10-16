"""
Signyales GUI — laptop-side hardware helpers: serial ports, the ESP32 serial
monitor, and the RECEIVER_MAC check.

The serial monitor here is for the boards' USB debug output at 115200 baud
(boot messages, calibration, the receiver's [stats] lines). It is NOT the
receiver-to-Pi frame link, which uses separate pins at 460800 baud.

No Tk imports.
"""

import re
import threading
from pathlib import Path

from .env import FIRMWARE

MONITOR_BAUD = 115200
MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\b")
CONFIG_H = FIRMWARE / "glove" / "src" / "config.h"
CONFIG_MAC_RE = re.compile(r"RECEIVER_MAC\s*\[\s*6\s*\]\s*=\s*\{([^}]*)\}")
PLACEHOLDER = "AA:BB:CC:DD:EE:FF"


def list_serial_ports():
    """[(device, description)], e.g. [("COM5", "Silicon Labs CP210x ...")]."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description or "") for p in sorted(list_ports.comports(), key=lambda p: p.device)]


def parse_mac(text: str):
    """The first MAC address in a line of text, upper-case, or None."""
    m = MAC_RE.search(text or "")
    return m.group(1).upper() if m else None


def read_config_mac(path=CONFIG_H):
    """RECEIVER_MAC from the glove's config.h as 'AA:BB:..', or None if not found."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.strip().startswith("//"):
            continue
        m = CONFIG_MAC_RE.search(line)
        if m:
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            try:
                return ":".join(f"{int(p, 16):02X}" for p in parts)
            except ValueError:
                return None
    return None


def compare_mac(read_mac: str, config_mac: str) -> str:
    """Plain-language verdict for the MAC check."""
    if not config_mac:
        return "Could not find RECEIVER_MAC in firmware/glove/src/config.h."
    if config_mac == PLACEHOLDER:
        return (f"config.h still has the placeholder {PLACEHOLDER}. Put {read_mac or 'the receiver MAC'} "
                f"into RECEIVER_MAC (Stage 1b), then flash both gloves. Don't commit config.h.")
    if read_mac and read_mac == config_mac:
        return f"OK: config.h RECEIVER_MAC matches the receiver ({read_mac})."
    if read_mac:
        return (f"MISMATCH: receiver reports {read_mac}, config.h has {config_mac}. "
                f"Fix config.h and re-flash both gloves.")
    return f"config.h has {config_mac}. Read the receiver's MAC to compare."


class SerialMonitor:
    """Reads text lines from a board's USB serial port on a background thread."""

    def __init__(self, on_line, on_closed=None):
        self._on_line = on_line
        self._on_closed = on_closed or (lambda reason: None)
        self._ser = None
        self._closing = False

    @property
    def open(self):
        return self._ser is not None and self._ser.is_open

    def start(self, port, baud=MONITOR_BAUD):
        import serial
        self._closing = False
        self._ser = serial.Serial(port, baud, timeout=0.3)
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        buf = b""
        reason = "closed"
        try:
            while not self._closing:
                chunk = self._ser.read(256)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._on_line(line.decode("utf-8", errors="replace").rstrip("\r"))
        except Exception as exc:
            reason = str(exc)
        if not self._closing:
            self._on_closed(reason)

    def send(self, text: str):
        if self.open:
            self._ser.write(text.encode())

    def close(self):
        self._closing = True
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
