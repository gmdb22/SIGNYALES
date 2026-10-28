"""
Signyales GUI — kiosk mode (plug and play).

Started with:  signyales_gui.py --kiosk   (the Pi's autostart does this)

Full screen, no clicking: it connects to the receiver, loads the model if
there is one, shows each recognized word as a big subtitle and speaks it.
Everything that can go wrong is shown in plain words at the top, and it
keeps retrying by itself, so the device can be switched on in any order:

    receiver not readable  -> "Can't read the receiver ... trying again"
    no data arriving       -> "Waiting for the receiver ..."
    gloves not heard       -> "Waiting for the gloves ..." (per-glove lights)
    no trained model       -> "No trained model yet ..." (lights still work)

Keys: Esc leaves/enters full screen, F2 opens the full app, F3 shows or
hides the link numbers (received %, lost, damaged, frame rate), Ctrl+Q quits.
The receiver link is the one saved in Active mode (USB by default); the port
is looked up again at every retry, so the receiver can be plugged in late.
The recognition steps are the same LivePipeline the Recognize tab uses.
"""

import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from core import mirror
from core.display import friendly_error
from core.env import PI_SIDE, receiver_link
from core.live import LivePipeline, link_stats_text, load_classifier, make_source
from widgets import PANEL_BG, PANEL_FG, SubtitlePanel

RETRY_S = 5           # seconds between reconnect attempts after an error
NO_DATA_S = 3.0       # no status for this long = no data from the receiver
GREEN, AMBER, RED, GREY = "#3fb46b", "#e0a030", "#e0563f", "#6b7682"
DIM = "#8a96a3"


class KioskView(tk.Frame):
    def __init__(self, master, app, port=None, model_dir=None, simulate=False, speak=True, share=False,
                 link=None):
        super().__init__(master, background=PANEL_BG)
        self.app = app
        self.port = port or None        # None = found by the receiver link at each start
        self.link_override = link or None
        self.link = self.link_override or receiver_link()
        self._open_port = None          # the port actually opened (from the "started" event)
        self.model_dir = str(model_dir or (PI_SIDE / "model"))
        self.simulate = simulate
        self.speak = speak
        self.pipeline = None
        self.server = None
        self._closing = False
        self._retry_id = None
        self._watch_id = None
        self._error = None
        self._started_at = None
        self._last_status = None
        self._fresh = None              # (left %, right %) from the last status event
        self._has_model = False
        self._model_files = False
        self._said_ready = False
        self._recent = []

        f_title = tkfont.Font(family="Segoe UI", size=14, weight="bold")
        f_glove = tkfont.Font(family="Segoe UI", size=13)
        f_msg = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        f_recent = tkfont.Font(family="Segoe UI", size=13)
        f_hint = tkfont.Font(family="Segoe UI", size=10)

        top = tk.Frame(self, background=PANEL_BG)
        top.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(top, text="Signyales", font=f_title, fg=PANEL_FG, bg=PANEL_BG).pack(side="left")
        self.gloves = {}
        for hand in ("right", "left"):            # packed from the right: Left ends up first
            box = tk.Frame(top, background=PANEL_BG)
            box.pack(side="right", padx=(18, 0))
            size = max(12, f_glove.metrics("linespace") - 4)
            dot = tk.Canvas(box, width=size, height=size, highlightthickness=0, background=PANEL_BG)
            dot.create_oval(1, 1, size - 1, size - 1, fill=GREY, outline="", tags="dot")
            dot.pack(side="left", padx=(0, 6))
            text = tk.Label(box, text=f"{hand.title()} glove", font=f_glove, fg=DIM, bg=PANEL_BG)
            text.pack(side="left")
            self.gloves[hand] = (dot, text)

        self.message = tk.Label(self, text="Starting...", font=f_msg, fg=DIM, bg=PANEL_BG,
                                anchor="w", justify="left")
        self.message.pack(fill="x", padx=16, pady=(6, 0))
        self.message.bind("<Configure>", lambda e: self.message.configure(
            wraplength=max(200, e.width - 8)))

        # Link numbers, hidden until F3 is pressed.
        self.stats = tk.Label(self, text="", font=f_hint, fg=DIM, bg=PANEL_BG, anchor="w", justify="left")
        self.stats.bind("<Configure>", lambda e: self.stats.configure(wraplength=max(200, e.width - 8)))
        self._stats_visible = False
        self._stats_text = "Link numbers: waiting for data..."

        self.subtitle = SubtitlePanel(self, idle_text="Listening...", max_size=420, height=10)
        self.subtitle.pack(fill="both", expand=True, padx=16, pady=8)

        self.recent = tk.Label(self, text="", font=f_recent, fg=DIM, bg=PANEL_BG, anchor="w")
        self.recent.pack(fill="x", padx=16)

        bottom = tk.Frame(self, background=PANEL_BG)
        bottom.pack(fill="x", padx=16, pady=(2, 8))
        tk.Label(bottom, text="Esc: full screen on/off    F2: full app    F3: link numbers    Ctrl+Q: quit",
                 font=f_hint, fg=GREY, bg=PANEL_BG).pack(side="left")
        tk.Button(bottom, text="Full app", font=f_hint, fg=PANEL_FG, bg="#25303a", relief="flat",
                  activebackground="#33414e", activeforeground=PANEL_FG,
                  command=self.app.open_full_app).pack(side="right")

        if share:
            self._start_share()
        self.after(300, self.start)
        self._watch_id = self.after(1000, self._watchdog)

    # ------------------------------------------------------------ pipeline
    def start(self):
        if self._closing:
            return
        self._retry_id = None
        self._error = None
        self._fresh = None
        self._last_status = None
        self._open_port = None
        self.link = self.link_override or receiver_link()   # picks up a change made in Active mode
        self._model_files = (Path(self.model_dir) / "model.tflite").exists()
        classifier = (lambda: load_classifier(self.model_dir)) if self._model_files else None
        link = self.link
        self.pipeline = LivePipeline(lambda: make_source(port=self.port, simulate=self.simulate, link=link),
                                     classifier, lambda e: self.app.call(self._on_event, e))
        self._started_at = time.monotonic()
        self.pipeline.start()
        self._refresh()

    def _schedule_retry(self):
        if not self._closing and self._retry_id is None:
            self._retry_id = self.after(RETRY_S * 1000, self.start)

    def _on_event(self, e):
        if self._closing:
            return
        if self.server:
            self.server.publish(e)
        t = e["type"]
        if t == "started":
            self._has_model = bool(e["model"])
            self._open_port = e.get("port") or None
            if self._has_model and self.speak and not self._said_ready:
                self._said_ready = True
                self.app.speaker.say("Signyales ready")
        elif t == "status":
            self._last_status = time.monotonic()
            self._fresh = (e["left_fresh_pct"], e["right_fresh_pct"])
            src = self._src_text()
            self._set_stats(f"{src[:1].upper()}{src[1:]}: {e.get('fps', 0)} frames/s (about 50 expected). "
                            + link_stats_text(e))
            for hand, pct in zip(("left", "right"), self._fresh):
                if pct >= 90:
                    self._set_glove(hand, GREEN, f"{hand.title()} glove")
                elif pct > 0:
                    self._set_glove(hand, AMBER, f"{hand.title()} glove: weak ({pct}%)")
                else:
                    self._set_glove(hand, RED, f"{hand.title()} glove: not heard")
        elif t == "gesture":
            self.subtitle.show(e["label"])
            self._recent = ([e["label"]] + self._recent)[:6]
            self.recent.configure(text="Recent:  " + "   ·   ".join(self._recent))
            if self.speak:
                self.app.speaker.say(e["label"])
        elif t == "error":
            self._error = e["message"]
        elif t == "stopped":
            self._schedule_retry()
        self._refresh()

    # ------------------------------------------------------------ link numbers (F3)
    def toggle_stats(self):
        self._stats_visible = not self._stats_visible
        if self._stats_visible:
            self.stats.configure(text=self._stats_text)
            self.stats.pack(fill="x", padx=16, pady=(2, 0), after=self.message)
        else:
            self.stats.pack_forget()

    def _set_stats(self, text):
        self._stats_text = text
        if self._stats_visible:
            self.stats.configure(text=text)

    def _src_text(self):
        if self.simulate:
            return "fake glove data"
        port = self._open_port or self.port
        cable = "USB cable" if self.link == "usb" else "UART wires"
        return f"the receiver ({cable}{', ' + port if port else ''})"

    def _set_glove(self, hand, colour, text):
        dot, label = self.gloves[hand]
        dot.itemconfigure("dot", fill=colour)
        label.configure(text=text, fg=PANEL_FG if colour == GREEN else DIM)

    def _no_data(self):
        if self._started_at is None:
            return False
        ref = self._last_status if self._last_status is not None else self._started_at
        return time.monotonic() - ref > NO_DATA_S

    def _watchdog(self):
        if self._closing:
            return
        if self.pipeline and self.pipeline.running and self._no_data():
            self._fresh = None
            for hand in ("left", "right"):
                self._set_glove(hand, GREY, f"{hand.title()} glove: no data")
        self._refresh()
        self._watch_id = self.after(1000, self._watchdog)

    def _refresh(self):
        """One plain-language line: the most important thing that is wrong, or 'Ready'."""
        running = bool(self.pipeline and self.pipeline.running)
        src = self._src_text()
        if self._error and not running:
            text, colour = (f"Can't read {src}: {friendly_error(self._error, self._open_port or self.port)}. "
                            f"Trying again every {RETRY_S} s.", RED)
        elif not running:
            text, colour = ("Starting...", DIM)
        elif self._no_data():
            where = ("plugged into a Pi USB port with a data cable" if self.link == "usb"
                     else "powered and wired to the Pi's GPIO pins")
            text, colour = (f"Waiting for {src}: no data yet. Is the receiver {where}?", AMBER)
        elif self._fresh is None:
            text, colour = ("Connecting...", DIM)
        elif self._fresh == (0, 0):
            text, colour = ("Receiver connected. Waiting for the gloves: are they switched on?", AMBER)
        elif 0 in self._fresh:
            side = "right" if self._fresh[0] else "left"
            text, colour = (f"The {side} glove isn't heard. Check that it is switched on.", AMBER)
        elif self._model_files and not self._has_model:
            text, colour = (f"The model in {self.model_dir} didn't load: it doesn't match this "
                            "version or TensorFlow is missing. Showing glove status only.", RED)
        elif not self._model_files:
            text, colour = (f"No trained model yet (expected in {self.model_dir}). "
                            "Showing glove status only.", AMBER)
        else:
            text, colour = ("Ready. Sign a word.", GREEN)
        if self.message.cget("text") != text:
            self.message.configure(text=text, fg=colour)

    # ------------------------------------------------------------ sharing
    def _start_share(self):
        try:
            self.server = mirror.MirrorServer()
            self.server.start()
        except OSError as exc:
            self.server = None
            self.recent.configure(text=f"Sharing with a laptop failed (port {mirror.DEFAULT_PORT}): {exc}",
                                  fg=RED)

    # ------------------------------------------------------------ teardown
    def shutdown(self):
        self._closing = True
        for after_id in (self._retry_id, self._watch_id):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except tk.TclError:
                    pass
        if self.pipeline and self.pipeline.running:
            self.pipeline.stop()
        if self.server:
            self.server.stop()
            self.server = None
