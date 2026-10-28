"""
Signyales Pi-Side App — Receiver Link (which cable, which port)

How the receiver dongle is connected to the Pi:

  "usb"  (default since 29 Oct 2026): one USB data cable from the
         receiver's USB-C port to a Pi USB-A port. It powers the receiver
         and carries the frames. The port name (/dev/ttyUSB0, COM9, ...)
         can change, so it is found automatically by the receiver's USB
         serial chip (a CH340 on the project's receiver board).
  "uart": three jumper wires from the receiver's D17/D18/GND to the Pi's
         GPIO pins 10/8/6, read as /dev/ttyAMA0 (the receiver's USB cable
         then only gives power). Needs the serial port turned on in
         raspi-config.

The receiver firmware sends every frame on its UART pins, and also on USB
while the Pi keeps asking (serial_link.SerialFrameReader does the asking),
so switching between the two needs no change on the receiver.

The choice is saved in ~/.signyales_settings.json (the GUI's Active mode
writes it), so the kiosk uses it when the Pi starts. A --port given on the
command line wins over the saved choice; a /dev/ttyAMA*, /dev/serial* or
/dev/ttyS* port means "uart", anything else means "usb".

No pyserial import at module level, so this works in --simulate mode and
in tests without pyserial installed.
"""

import json
import os
from pathlib import Path

LINK_USB = "usb"
LINK_UART = "uart"
LINKS = (LINK_USB, LINK_UART)
DEFAULT_LINK = LINK_USB
LINK_NAMES = {LINK_USB: "USB cable", LINK_UART: "UART wires (GPIO pins)"}

# USB serial chips to look for, most likely first. The project's receiver
# board has a CH340. The glove boards have a CP210x, so if a glove is also
# plugged in (e.g. on a laptop), the CH340 is still picked first.
USB_SERIAL_CHIPS = (
    (0x1A86, "CH340"),
    (0x10C4, "CP210x"),
    (0x0403, "FTDI"),
    (0x303A, "ESP32 USB"),
)

_UART_PREFIXES = ("/dev/ttyama", "/dev/serial", "/dev/ttys")


class ReceiverNotFound(OSError):
    """No receiver found on USB."""


def settings_path() -> Path:
    """The settings file. SIGNYALES_SETTINGS overrides it (used by the tests)."""
    override = os.environ.get("SIGNYALES_SETTINGS")
    return Path(override) if override else Path.home() / ".signyales_settings.json"


def load_settings(path=None) -> dict:
    """All saved settings, or {} if the file is missing or unreadable."""
    try:
        data = json.loads(Path(path or settings_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_setting(key, value, path=None):
    """Saves one setting, keeping the others."""
    p = Path(path or settings_path())
    data = load_settings(p)
    data[key] = value
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_link(path=None) -> str:
    """The saved link ("usb" or "uart"), or DEFAULT_LINK."""
    link = str(load_settings(path).get("receiver_link", DEFAULT_LINK)).lower()
    return link if link in LINKS else DEFAULT_LINK


def save_link(link, path=None):
    if link not in LINKS:
        raise ValueError(f"receiver link must be one of {LINKS}, not {link!r}")
    save_setting("receiver_link", link, path)


def is_uart_port(port) -> bool:
    """True for the Pi's GPIO serial ports (/dev/ttyAMA0 etc.)."""
    return str(port).lower().startswith(_UART_PREFIXES)


def find_usb_receiver(ports=None):
    """
    (device, chip name) of the most likely receiver among the USB serial
    ports, or (None, None). `ports` is a list of objects with .device and
    .vid (pyserial's list_ports.comports() gives those); left out, the
    real ports are listed.
    """
    if ports is None:
        try:
            from serial.tools import list_ports
        except ImportError:
            return None, None
        ports = list_ports.comports()
    best = None
    for p in ports:
        vid = getattr(p, "vid", None)
        for rank, (chip_vid, chip) in enumerate(USB_SERIAL_CHIPS):
            if vid == chip_vid:
                cand = (rank, str(p.device), chip)
                if best is None or cand < best:
                    best = cand
    return (best[1], best[2]) if best else (None, None)


def resolve(cfg, port=None, baud=None, link=None, ports=None):
    """
    (port, baud, link) to open, from (in order) the arguments, the config
    (cfg.serial_port / cfg.serial_baud / cfg.receiver_link) and the saved
    setting. Raises ReceiverNotFound if the link is USB and no receiver is
    plugged in.
    """
    port = port or getattr(cfg, "serial_port", "") or None
    link = link or getattr(cfg, "receiver_link", "") or None
    if port:
        link = link or (LINK_UART if is_uart_port(port) else LINK_USB)
    else:
        link = link or load_link()
        if link == LINK_UART:
            port = cfg.uart_port
        else:
            port, _chip = find_usb_receiver(ports)
            if not port:
                raise ReceiverNotFound(
                    "no receiver found on USB (looked for a CH340 or CP210x USB serial chip). "
                    "Is it plugged into the Pi with a data cable (not a charge-only one)?")
    if link not in LINKS:
        raise ValueError(f"receiver link must be one of {LINKS}, not {link!r}")
    baud = baud or getattr(cfg, "serial_baud", 0) or (cfg.uart_baud if link == LINK_UART else cfg.usb_baud)
    return port, int(baud), link


def describe(link, port=None) -> str:
    """e.g. 'USB cable (/dev/ttyUSB0)'."""
    name = LINK_NAMES.get(link, link)
    return f"{name} ({port})" if port else name
