"""
Signyales GUI — speech helper process.

Speaks each line it reads on stdin in this process's MAIN thread, then
prints "OK" or "FAIL".

Why a separate process, and why direct SAPI on Windows:
- Windows' speech stayed silent when the GUI called it from a background
  thread, so speech runs here instead.
- Through pyttsx3, only the first phrase played on the dev laptop when
  there was a pause between phrases (later ones returned without sound).
  On Windows this helper therefore talks to the built-in SAPI voice
  directly (the same voice pyttsx3 uses), with a synchronous Speak() call.
  If that fails, it falls back to the hub's TTSEngine (pyttsx3/espeak-ng).
  On Linux (the Pi) it always uses TTSEngine.

Protocol (UTF-8 lines): prints "READY <backend>" once, then one "OK"/"FAIL"
per input line. Any other output is diagnostic text.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pi-side"))


def _windows_sapi():
    """(name, speak) using Windows' SAPI voice directly, or None."""
    try:
        import comtypes.client
        voice = comtypes.client.CreateObject("SAPI.SpVoice")
    except Exception as exc:
        try:
            import win32com.client
            voice = win32com.client.Dispatch("SAPI.SpVoice")
        except Exception as exc2:
            print(f"Direct Windows speech unavailable ({exc}; {exc2}); using pyttsx3.", flush=True)
            return None

    def speak(text):
        voice.Speak(text)          # flags 0 = synchronous: returns when finished
        return True
    return "sapi (Windows built-in voice)", speak


def _hub_engine():
    from signyales_hub.tts_engine import TTSEngine
    engine = TTSEngine()
    return engine.backend, engine.speak_blocking


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    found = _windows_sapi() if sys.platform == "win32" else None
    name, speak = found or _hub_engine()
    print(f"READY {name}", flush=True)
    for line in sys.stdin:
        text = line.rstrip("\r\n")
        if not text.strip():
            ok = True
        else:
            try:
                ok = speak(text)
            except Exception as exc:
                print(f"Speaking failed: {exc}", flush=True)
                ok = False
        print("OK" if ok else "FAIL", flush=True)


if __name__ == "__main__":
    main()
