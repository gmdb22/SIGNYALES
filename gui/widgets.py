"""
Signyales GUI — shared Tk widgets: log box, subtitle panel, glove status,
and the speaker used by every view.
"""

import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import font as tkfont
from tkinter import scrolledtext, ttk

from core.env import IS_WINDOWS, child_env

INK = "#1f2933"
MUTED = "#5c6670"
OK = "#2f7a4f"
BAD = "#b3412c"
WARN = "#b06a12"
PANEL_BG = "#10161c"
PANEL_FG = "#f4f6f8"

_BAD_WORD = re.compile(r"\bFAIL(ED)?\b|ERROR\b|\bTRACEBACK\b")

STATUS_STYLE = {
    "idle": ("Not run", MUTED), "running": ("Running...", WARN), "pass": ("PASS", OK),
    "fail": ("FAIL", BAD), "skipped": ("Skipped", MUTED), "stopped": ("Stopped", MUTED),
}


class LogBox(ttk.Frame):
    def __init__(self, master, height=12):
        super().__init__(master)
        self.text = scrolledtext.ScrolledText(self, height=height, wrap="word", state="disabled",
                                              font=("Consolas", 9), background="#f7f8fa")
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("pass", foreground=OK)
        self.text.tag_configure("fail", foreground=BAD)
        self.text.tag_configure("head", foreground=INK, font=("Consolas", 9, "bold"))
        self.text.tag_configure("muted", foreground=MUTED)

    def append(self, line, tag=None):
        if tag is None:
            up = line.upper().lstrip()
            if up.startswith(("PASS", "OK:", "ALL ")) and "FAIL" not in up:
                tag = "pass"
            elif _BAD_WORD.search(up):
                tag = "fail"
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n", (tag,) if tag else ())
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class SubtitlePanel(tk.Frame):
    """Large, centered word on a dark background, sized to fit the panel."""

    def __init__(self, master, idle_text="Listening...", max_size=150, height=180):
        super().__init__(master, background=PANEL_BG, height=height)
        self.pack_propagate(False)
        self.idle_text = idle_text
        self.max_size = max_size
        self._text = idle_text
        self._font = tkfont.Font(family="Segoe UI", size=48, weight="bold")
        self.label = tk.Label(self, text=idle_text, font=self._font, fg=PANEL_FG, bg=PANEL_BG)
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.bind("<Configure>", lambda e: self._fit())
        self._mirrors = []

    def _fit(self):
        w, h = max(self.winfo_width(), 50), max(self.winfo_height(), 50)
        size = min(self.max_size, int(h * 0.55))
        self._font.configure(size=size)
        while size > 10 and self._font.measure(self._text) > w * 0.9:
            size -= 4
            self._font.configure(size=size)
        dim = self._text == self.idle_text
        self.label.configure(text=self._text, fg="#8a96a3" if dim else PANEL_FG)

    def show(self, text):
        self._text = text
        self._fit()
        for m in list(self._mirrors):
            m.show(text)

    def idle(self):
        self.show(self.idle_text)

    def add_mirror(self, other):
        self._mirrors.append(other)

    def remove_mirror(self, other):
        if other in self._mirrors:
            self._mirrors.remove(other)


class FullscreenSubtitles:
    """A separate fullscreen window that copies a SubtitlePanel. Esc closes it."""

    def __init__(self, root, source_panel):
        self.source = source_panel
        self.win = tk.Toplevel(root, background=PANEL_BG)
        self.win.title("Signyales subtitles")
        # Size to the screen first, so it fills it even where the fullscreen
        # flag isn't honoured (no window manager); then ask for fullscreen.
        self.win.geometry(f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}+0+0")
        try:
            self.win.attributes("-fullscreen", True)
        except tk.TclError:
            pass
        self.panel = SubtitlePanel(self.win, idle_text=source_panel.idle_text, max_size=400, height=10)
        self.panel.pack(fill="both", expand=True)
        tk.Label(self.win, text="Esc to close", fg="#55606b", bg=PANEL_BG).pack(side="bottom", pady=4)
        self.panel.show(source_panel._text)
        source_panel.add_mirror(self.panel)
        self.win.bind("<Escape>", lambda e: self.close())
        self.win.protocol("WM_DELETE_WINDOW", self.close)

    def close(self):
        self.source.remove_mirror(self.panel)
        self.win.destroy()


class HandStatus(ttk.Frame):
    """Per-glove light (fresh / stale / no data), fresh %, and one bar per flex
    sensor (thumb, index, middle, ring, pinky, palm)."""

    def __init__(self, master):
        super().__init__(master)
        self.rows = {}
        for col, hand in enumerate(("left", "right")):
            f = ttk.Frame(self)
            f.grid(row=0, column=col, padx=8, sticky="w")
            dot = tk.Canvas(f, width=14, height=14, highlightthickness=0)
            dot.create_oval(2, 2, 12, 12, fill=MUTED, outline="", tags="dot")
            dot.grid(row=0, column=0)
            lbl = ttk.Label(f, text=f"{hand.title()} glove: no data", width=26)
            lbl.grid(row=0, column=1, sticky="w", padx=4)
            bars = tk.Canvas(f, width=130, height=34, highlightthickness=0, background="#eef1f4")
            bars.grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
            self.rows[hand] = (dot, lbl, bars)
        self.fps = ttk.Label(self, text="", foreground=MUTED)
        self.fps.grid(row=1, column=0, columnspan=2, sticky="w", padx=8)

    def update_status(self, st):
        for hand in ("left", "right"):
            dot, lbl, bars = self.rows[hand]
            pct = st.get(f"{hand}_fresh_pct", 0)
            colour = OK if pct >= 90 else (WARN if pct > 0 else BAD)
            dot.itemconfigure("dot", fill=colour)
            lbl.configure(text=f"{hand.title()} glove: {pct}% fresh")
            bars.delete("all")
            for i, v in enumerate(st.get(f"{hand}_flex", [])[:6]):
                h = int(30 * max(0, min(v, 4095)) / 4095)
                bars.create_rectangle(4 + i * 21, 32 - h, 20 + i * 21, 32, fill="#3d6a8a", outline="")
        self.fps.configure(text=f"{st.get('fps', 0)} frames/s (about 50 expected), "
                                f"{st.get('frames', 0)} frames so far")

    def reset(self):
        for hand in ("left", "right"):
            dot, lbl, bars = self.rows[hand]
            dot.itemconfigure("dot", fill=MUTED)
            lbl.configure(text=f"{hand.title()} glove: no data")
            bars.delete("all")
        self.fps.configure(text="")


def _safe(fn):
    if fn is not None:
        try:
            fn()
        except Exception:
            pass


class Speaker:
    """
    Speaks words in order without blocking the window. The speaking itself
    happens in a separate helper process (core/speech_worker.py) that uses
    the hub's TTSEngine on its own main thread: on Windows, SAPI speech
    called from a background thread of the GUI stayed silent.
    say() never blocks; on_start / on_done run on a background thread, so
    wrap any Tk work in app.call.
    """

    def __init__(self, on_message=None):
        self._q = queue.Queue()
        self._on_message = on_message or (lambda m: None)
        self.backend = None
        self._proc = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _start_worker(self):
        worker = Path(__file__).resolve().parent / "core" / "speech_worker.py"
        kwargs = {}
        if IS_WINDOWS:
            kwargs["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            [sys.executable, str(worker)], env=child_env(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1, **kwargs)
        threading.Thread(target=self._pump_stderr, daemon=True).start()
        reply = self._read_reply()
        if reply.startswith("READY"):
            self.backend = reply.split(" ", 1)[1] if " " in reply else "?"
            return True
        self._on_message(f"Speech unavailable: the speech helper did not start ({reply or 'no reply'}).")
        return False

    def _pump_stderr(self):
        proc = self._proc
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                self._on_message(f"[speech] {line}")

    def _read_reply(self):
        """Next protocol line (READY/OK/FAIL); other output is passed on as a message."""
        while True:
            line = self._proc.stdout.readline()
            if not line:
                return ""
            line = line.strip()
            if line.startswith(("READY", "OK", "FAIL")):
                return line
            if line:
                self._on_message(f"[speech] {line}")

    def _speak(self, text):
        if self._proc is None or self._proc.poll() is not None:
            return False
        try:
            self._proc.stdin.write(text.replace("\n", " ") + "\n")
            self._proc.stdin.flush()
        except OSError:
            return False
        return self._read_reply() == "OK"

    def _loop(self):
        try:
            ok = self._start_worker()
        except Exception as exc:
            self._on_message(f"Speech unavailable: {exc}")
            ok = False
        while True:
            item = self._q.get()
            if item is None:
                break
            text, on_start, on_done = item
            _safe(on_start)
            if not text.strip():
                pass                     # marker item: callbacks only, nothing to say
            elif not ok:
                time.sleep(0.8)          # keep any on-screen sequence readable without sound
            elif not self._speak(text):
                self._on_message(f"Speech failed for '{text}' (backend {self.backend}).")
            _safe(on_done)
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()

    def say(self, text, on_start=None, on_done=None):
        """Queues text. on_start / on_done are called (on the speech thread)
        just before and just after it is spoken; wrap any Tk work in app.call."""
        self._q.put((text, on_start, on_done))

    def close(self):
        self._q.put(None)
