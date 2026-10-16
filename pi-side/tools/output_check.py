"""
Signyales — Output Check (subtitles and speaker, no model or gloves needed)
===========================================================================
Shows the hub's large subtitle text and plays a test phrase through the
speech engine, using the same SubtitleDisplay and TTSEngine classes the hub
uses, so a person can confirm that both outputs are readable and audible.

It cannot tell whether sound actually came out of a speaker: "speech
engine reported no error" only means the software ran. Listen, and write
down what you saw and heard.

Usage (from pi-side/, venv active; works on the Pi and on a laptop):
    python tools/output_check.py
    python tools/output_check.py --word kumusta --seconds 8
    python tools/output_check.py --no-speech          # subtitles only
    python tools/output_check.py --no-subtitle        # speaker only

The subtitle appears in the terminal window this runs in (over SSH, that is
the SSH window on your laptop). The sound plays on the machine this runs on.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from signyales_hub.subtitle_display import SubtitleDisplay  # noqa: E402

DEFAULT_PHRASE = "Signyales speaker test. Salamat. Kumusta."


def check_subtitle(word: str, seconds: float) -> dict:
    display = SubtitleDisplay()
    style = "large block letters (pyfiglet)" if display._figlet is not None \
        else "spaced capitals (pyfiglet not installed)"
    display.show_idle()
    time.sleep(min(seconds, 3))
    display.show(word)
    time.sleep(seconds)
    return {"style": style}


def check_speech(phrase: str) -> dict:
    from signyales_hub.tts_engine import TTSEngine
    engine = TTSEngine()
    print(f"Speech backend: {engine.backend}")
    print(f'Speaking: "{phrase}"')
    ok = engine.speak_blocking(phrase)
    engine.shutdown()
    return {"backend": engine.backend, "ok": ok}


def main():
    p = argparse.ArgumentParser(description="Check the subtitle display and the speaker")
    p.add_argument("--word", default="salamat", help="Word to show as a subtitle (default: salamat)")
    p.add_argument("--seconds", type=float, default=5.0, help="How long to show the word (default: 5)")
    p.add_argument("--phrase", default=DEFAULT_PHRASE, help="Phrase to speak")
    p.add_argument("--no-subtitle", action="store_true", help="Skip the subtitle check")
    p.add_argument("--no-speech", action="store_true", help="Skip the speaker check")
    args = p.parse_args()

    sub_result = None if args.no_subtitle else check_subtitle(args.word, args.seconds)
    speech_result = None if args.no_speech else check_speech(args.phrase)

    print("\n=== Output check summary ===")
    if sub_result:
        print(f"Subtitle: shown '{args.word}' for {args.seconds:.0f}s as {sub_result['style']}.")
        print("  Write down: was it readable from about 2 m away? Centered? Any garbled characters?")
    if speech_result:
        status = "reported no error" if speech_result["ok"] else "FAILED (see the error above)"
        print(f"Speech:   backend {speech_result['backend']}, {status}.")
        print("  Write down: did you hear the whole phrase? Which speaker (USB/HDMI/other)?")
        print("  Was 'Salamat' and 'Kumusta' understandable?")
    if not speech_result or speech_result["ok"]:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
