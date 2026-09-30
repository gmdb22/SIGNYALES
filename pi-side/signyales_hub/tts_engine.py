"""
Signyales Pi Hub — Text-to-Speech

Offline-only, by project requirement — no cloud TTS APIs. Uses
pyttsx3 (which drives espeak/espeak-ng under the hood on Linux) as the
primary backend, with a direct espeak-ng subprocess call as a fallback
if pyttsx3 fails to initialize (this has been known to happen on some
Raspberry Pi OS audio configurations — worth testing early since audio
routing on a Pi 5, e.g. HDMI vs. 3.5mm jack vs. USB/Bluetooth speaker,
sometimes needs `raspi-config` or `alsamixer` attention regardless of
what this code does).

Runs on a background thread with a queue so that speaking a phrase
never blocks the main sampling/inference loop — gesture recognition
keeps running while a previous phrase is still being spoken.
"""

import logging
import queue
import subprocess
import threading

log = logging.getLogger("signyales.tts")


class TTSEngine:
    def __init__(self):
        self._queue: "queue.Queue[str | None]" = queue.Queue()
        self._engine = None
        self._backend = None
        self._init_engine()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _init_engine(self):
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._backend = "pyttsx3"
            log.info("TTS backend: pyttsx3")
        except Exception as exc:
            log.warning("pyttsx3 unavailable (%s) — falling back to espeak-ng subprocess", exc)
            self._backend = "espeak-ng"

    def _worker(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                self._speak_sync(text)
            except Exception:
                log.exception("TTS playback failed for: %s", text)

    def _speak_sync(self, text: str):
        if self._backend == "pyttsx3" and self._engine is not None:
            self._engine.say(text)
            self._engine.runAndWait()
        else:
            subprocess.run(["espeak-ng", text], check=False)

    def speak(self, text: str):
        """Non-blocking: queues text and returns immediately."""
        self._queue.put(text)

    def shutdown(self):
        self._queue.put(None)
        self._thread.join(timeout=2)
