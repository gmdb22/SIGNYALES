"""
Signyales — Subtitle Display

Fullscreen, large-text terminal output for a recognized gesture — this is
the "visible text output" the proposal commits to, kept deliberately
within its "console or LED-based" scope language: no window, no mouse, no
buttons, nothing that resembles a GUI or mobile app. It's still just text
printed to a terminal; it's just printed BIG, so it's readable from across
a room during a demo rather than requiring someone to lean in and read
small print.

Uses pyfiglet (ASCII-art-style block text) if installed, since terminal
font size isn't something Python can control directly — the only way to
make text look bigger in a terminal is to draw it bigger, character by
character. Degrades to a simpler letter-spaced fallback if pyfiglet isn't
installed, so this never becomes a hard dependency for running the app at
all — consistent with how model_runtime.py and tts_engine.py handle their
own optional dependencies elsewhere in this codebase.
"""

import os
import shutil


class SubtitleDisplay:
    def __init__(self):
        self._figlet = None
        try:
            import pyfiglet
            self._figlet = pyfiglet.Figlet(font="big")
        except ImportError:
            pass  # falls back to _simple_render below

    def _clear_screen(self):
        # Works in real terminals (Linux/macOS/modern Windows Terminal) via
        # ANSI; falls back to the OS-specific clear command if ANSI isn't
        # honored for some reason. Either path is still just a terminal
        # operation — nothing GUI-related.
        print("\033c", end="")  # ANSI full reset, clears scrollback too
        os.system("cls" if os.name == "nt" else "clear")

    def _simple_render(self, text: str) -> str:
        """Fallback when pyfiglet isn't installed: spaced-out capital
        letters. Not true large-print, but still visually distinct from a
        normal line of text, and needs zero extra dependencies."""
        return " ".join(text.upper())

    def show(self, text: str):
        """Clears the screen and displays `text` as large as the current
        terminal reasonably allows, centered horizontally."""
        self._clear_screen()
        term_width = shutil.get_terminal_size(fallback=(80, 24)).columns

        if self._figlet is not None:
            try:
                rendered = self._figlet.renderText(text)
            except Exception:
                rendered = self._simple_render(text)
        else:
            rendered = self._simple_render(text)

        lines = rendered.rstrip("\n").split("\n")
        max_len = max((len(line) for line in lines), default=0)
        pad = max((term_width - max_len) // 2, 0)

        print("\n" * 2)
        for line in lines:
            print(" " * pad + line)
        print("\n" * 2)

    def show_idle(self, message: str = "Listening..."):
        """Shown at startup / when no hand data is currently valid, so the
        screen isn't just blank or stuck on a stale previous gesture."""
        self.show(message)
