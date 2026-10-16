"""
Signyales GUI — speech helper process.

Speaks each line it reads on stdin, using the hub's TTSEngine in this
process's MAIN thread (the way tools/output_check.py does), then prints
"OK" or "FAIL". Windows' speech (SAPI via pyttsx3) stayed silent when the
GUI called it from a background thread, so the GUI runs speech here instead.

Protocol (UTF-8 lines): prints "READY <backend>" once, then one "OK"/"FAIL"
per input line. Any other output is diagnostic text.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pi-side"))


def main():
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    from signyales_hub.tts_engine import TTSEngine
    engine = TTSEngine()
    print(f"READY {engine.backend}", flush=True)
    for line in sys.stdin:
        text = line.rstrip("\r\n")
        ok = engine.speak_blocking(text) if text.strip() else True
        print("OK" if ok else "FAIL", flush=True)


if __name__ == "__main__":
    main()
