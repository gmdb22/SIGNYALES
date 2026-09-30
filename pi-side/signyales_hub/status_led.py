"""
Signyales Pi Hub — Status LED (optional)

A simple visual "system is recognizing gestures" indicator for
demos, so nobody needs a laptop screen visible to confirm the system
is alive.

Uses gpiozero rather than RPi.GPIO: RPi.GPIO talks to GPIO hardware in
a way that does not support the Raspberry Pi 5's RP1 I/O chip, and
commonly fails outright there. gpiozero auto-selects a working pin
factory (lgpio on a Pi 5, once the `lgpio` or `rpi-lgpio` package is
installed — see requirements.txt) and is otherwise a drop-in
equivalent for a simple on/off LED like this one.

Safe to import and use on a non-Pi dev machine — GPIO access failures
are caught and logged once, after which calls become no-ops.
"""

import logging

log = logging.getLogger("signyales.status_led")


class StatusLed:
    def __init__(self, pin: int, enabled: bool):
        self.enabled = enabled
        self._led = None
        if not enabled:
            return
        try:
            from gpiozero import LED
            self._led = LED(pin)
            self._led.off()
        except Exception as exc:
            log.warning(
                "Status LED disabled — GPIO unavailable (%s). On a Pi 5, make sure "
                "the `lgpio` (or `rpi-lgpio`) package is installed; gpiozero needs "
                "it as a backend since RPi.GPIO does not support the RP1 chip.",
                exc,
            )
            self.enabled = False

    def set(self, on: bool):
        if not self.enabled or self._led is None:
            return
        self._led.on() if on else self._led.off()

    def cleanup(self):
        if self.enabled and self._led is not None:
            self._led.close()
