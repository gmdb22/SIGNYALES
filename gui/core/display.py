"""
Signyales GUI — screen size, start options, the single-instance lock and
plain-language serial-port errors (for kiosk mode).

No Tk imports here, so it can be unit-tested anywhere.

Screen scaling: the full app was laid out for a 1180 x 780 window. On a
smaller screen (e.g. an 800 x 480 or 1024 x 600 LCD) everything is scaled
down to fit; in kiosk mode it is also scaled up on large screens (a TV),
so the status text stays readable from a distance. The big subtitle sizes
itself to its panel either way.
"""

import argparse
import os
from pathlib import Path

DESIGN_W, DESIGN_H = 1180, 780
MIN_SCALE, MAX_SCALE = 0.6, 2.0


def screen_factor(screen_w: int, screen_h: int) -> float:
    """How much of the design size fits on this screen (1.0 = exactly)."""
    return min(screen_w / DESIGN_W, screen_h / DESIGN_H)


def ui_scale(screen_w: int, screen_h: int, allow_grow: bool, override: float = None) -> float:
    """
    Text scale for this screen. The full app only shrinks (allow_grow=False),
    so it looks the same as before on a normal laptop; kiosk mode also grows.
    override (--scale) wins, within the same limits.
    """
    if override:
        f = override
    else:
        f = screen_factor(screen_w, screen_h)
        if not allow_grow:
            f = min(f, 1.0)
    return round(max(MIN_SCALE, min(MAX_SCALE, f)), 3)


def window_size(screen_w: int, screen_h: int):
    """(width, height, maximize) for the full app's window on this screen."""
    w = min(DESIGN_W, screen_w)
    h = min(DESIGN_H, screen_h - 40)          # leave room for a taskbar
    maximize = screen_w <= DESIGN_W or screen_h - 40 <= DESIGN_H
    return w, h, maximize


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="signyales_gui.py",
        description="Signyales app. With no options it opens the normal window "
                    "(Testing and Active modes).")
    p.add_argument("--kiosk", action="store_true",
                   help="Plug-and-play mode: full screen, straight to recognition with big subtitles "
                        "and speech, retries by itself, no clicking needed. Used when the Pi starts.")
    p.add_argument("--windowed", action="store_true",
                   help="With --kiosk: use a normal window instead of full screen (for testing).")
    p.add_argument("--simulate", action="store_true",
                   help="With --kiosk: fake glove data instead of the receiver (demo/testing).")
    p.add_argument("--port", default=None,
                   help="Serial port of the receiver (default: found by the receiver link).")
    p.add_argument("--link", choices=("usb", "uart"), default=None,
                   help="Receiver link: usb (one data cable) or uart (GPIO wires, /dev/ttyAMA0). "
                        "Default: the choice saved in Active mode, else usb.")
    p.add_argument("--model-dir", default=None,
                   help="Model folder (default: pi-side/model).")
    p.add_argument("--no-speech", action="store_true", help="With --kiosk: subtitles only, no speech.")
    p.add_argument("--share", action="store_true",
                   help="With --kiosk: also share recognized words with a laptop (Mirror, port 50555).")
    p.add_argument("--scale", type=float, default=None,
                   help=f"Text size factor ({MIN_SCALE}-{MAX_SCALE}). Default: fitted to the screen.")
    args = p.parse_args(argv)
    if args.scale is not None and not (MIN_SCALE <= args.scale <= MAX_SCALE):
        p.error(f"--scale must be between {MIN_SCALE} and {MAX_SCALE}")
    return args


class SingleInstance:
    """
    An exclusive lock on a file, so the kiosk can't be started twice (e.g. by
    two autostart mechanisms). The OS releases it if the app crashes.
    """

    def __init__(self, path=None):
        self.path = Path(path) if path else Path.home() / ".signyales_kiosk.lock"
        self._fh = None

    def acquire(self) -> bool:
        self._fh = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fh.close()
            self._fh = None
            return False
        return True

    def release(self):
        if self._fh is not None:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self._fh.close()
            self._fh = None


def friendly_error(message: str, port: str) -> str:
    """Turns the usual serial-port errors into what to do about them."""
    m = message.lower()
    port = port or "the receiver's port"
    if "no receiver found on usb" in m:
        return ("no receiver found on USB. Plug it into a Pi USB port with a data cable "
                "(not a charge-only one). Wired to the GPIO pins instead? Choose UART in the "
                "full app (F2, Active mode)")
    if "no such file" in m or "could not find" in m or "filenotfound" in m:
        if str(port).startswith("/dev/ttyAMA"):
            return (f"{port} doesn't exist. For the UART option the Pi's serial port has to be "
                    "turned on (flashing kit, Raspberry Pi step 4.5); or choose USB")
        return f"{port} doesn't exist. Is the receiver still plugged in? Elsewhere, check --port"
    if "permission denied" in m:
        return (f"no permission to use {port}. Add this user to the 'dialout' group "
                "(sudo usermod -aG dialout $USER), then log out and back in")
    if "busy" in m or "resource temporarily unavailable" in m or "multiple access" in m:
        return (f"another program is using {port}. If the console auto-start service is "
                "installed: sudo systemctl stop signyales")
    return message.replace("Could not start: ", "")
