"""
Signyales GUI — one app for the laptop and the Raspberry Pi.

    Testing mode: every check is a button (software tests, firmware compile,
                  Pi hardware checks, subtitle + speaker check, training).
    Active mode:  Pi     -> Recognize (subtitles + speech) and Record (teach).
                  Laptop -> Mirror the Pi, and the hardware helper.

Start it (from the repo root):
    Windows:  pi-side\\venv\\Scripts\\python.exe gui\\signyales_gui.py
    Pi:       pi-side/venv/bin/python gui/signyales_gui.py
The Pi needs a desktop and Tk: sudo apt install python3-tk

It detects whether it is running on a Raspberry Pi; the "This machine"
menu overrides that (e.g. to try the Pi screens on the laptop with fake data).

Plug-and-play (kiosk) mode, which the Pi's autostart uses:
    pi-side/venv/bin/python gui/signyales_gui.py --kiosk
Full screen, straight to recognition with big subtitles and speech, and it
retries by itself. Try it on the laptop with fake gloves:
    pi-side\\venv\\Scripts\\python.exe gui\\signyales_gui.py --kiosk --simulate --windowed
All options: --help. Text is scaled to fit the screen (smaller LCDs) and, in
kiosk mode, enlarged on big screens; --scale overrides.
"""

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import tasks  # noqa: E402
from core.display import SingleInstance, parse_args, ui_scale, window_size  # noqa: E402
from core.env import is_raspberry_pi, machine_name  # noqa: E402
from widgets import INK, MUTED, PANEL_BG, Speaker  # noqa: E402

MACHINES = {"Laptop (no Pi needed for testing)": tasks.LAPTOP, "Raspberry Pi": tasks.PI}


class App(tk.Tk):
    def __init__(self, options=None):
        super().__init__()
        self.options = options or parse_args([])
        self.kiosk = bool(self.options.kiosk)
        self.title("Signyales")
        self._calls = queue.Queue()
        self._drain_id = self.after(40, self._drain)
        self.speaker = Speaker(on_message=lambda m: self.call(self._speech_message, m))
        self.view = None
        self.top = None
        self.body = None
        self.scale = self._apply_scale()

        style = ttk.Style(self)
        if "clam" in style.theme_names() and sys.platform != "win32":
            style.theme_use("clam")

        self.bind_all("<Control-q>", lambda e: self.on_close())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.kiosk:
            self._start_kiosk()
        else:
            self._build_full_app()

    # ------------------------------------------------------------ screen size
    def _apply_scale(self):
        """Scales all text to the screen before any widget is made (see core/display.py)."""
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        s = ui_scale(sw, sh, allow_grow=self.kiosk, override=self.options.scale)
        if s != 1.0:
            # Point-sized fonts follow Tk's scaling; pixel-sized named fonts are scaled by hand.
            self.tk.call("tk", "scaling", float(self.tk.call("tk", "scaling")) * s)
            for name in tkfont.names(root=self):
                f = tkfont.nametofont(name, root=self)
                size = int(f.cget("size"))
                if size < 0:
                    f.configure(size=min(-6, int(round(size * s))))
        return s

    def _maximize(self):
        try:
            if sys.platform == "win32":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except tk.TclError:
            pass

    def set_fullscreen(self, on):
        if on:
            # Size to the screen first, so it fills it even where the fullscreen
            # flag isn't honoured (no window manager); then ask for fullscreen.
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        try:
            self.attributes("-fullscreen", on)
        except tk.TclError:
            pass
        if not on:
            w, h, _ = window_size(self.winfo_screenwidth(), self.winfo_screenheight())
            self.geometry(f"{w}x{h}")

    def _toggle_fullscreen(self):
        try:
            on = bool(self.attributes("-fullscreen"))
        except tk.TclError:
            on = False
        self.set_fullscreen(not on)

    # ------------------------------------------------------------ kiosk mode
    def _start_kiosk(self):
        from kiosk_view import KioskView
        self._normal_bg = self.cget("background")
        self.configure(background=PANEL_BG)
        if self.options.windowed:
            w, h, _ = window_size(self.winfo_screenwidth(), self.winfo_screenheight())
            self.geometry(f"{w}x{h}")
        else:
            self.set_fullscreen(True)
        self.bind("<Escape>", lambda e: self._toggle_fullscreen())
        self.bind("<F2>", lambda e: self.open_full_app())
        o = self.options
        self.view = KioskView(self, self, port=o.port, model_dir=o.model_dir, simulate=o.simulate,
                              speak=not o.no_speech, share=o.share)
        self.view.pack(fill="both", expand=True)

    def open_full_app(self):
        """Leaves kiosk mode for the normal window (maintenance, recording, tests)."""
        if not self.kiosk:
            return
        self.kiosk = False
        self.unbind("<Escape>")
        self.unbind("<F2>")
        if self.view is not None:
            self.view.shutdown()
            self.view.destroy()
            self.view = None
        self.set_fullscreen(False)
        self.configure(background=getattr(self, "_normal_bg", "#d9d9d9"))
        self._build_full_app(mode="active")

    # ------------------------------------------------------------ full app
    def _build_full_app(self, mode="testing"):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h, maximize = window_size(sw, sh)
        self.geometry(f"{w}x{h}")
        self.minsize(min(1000, w), min(680, h))
        if maximize:
            self._maximize()

        top = tk.Frame(self, background="#eef1f4")
        self.top = top
        top.pack(fill="x")
        tk.Label(top, text="Signyales", font=("Segoe UI", 16, "bold"), fg=INK, bg="#eef1f4").pack(
            side="left", padx=12, pady=8)
        tk.Label(top, text=f"detected: {machine_name()}", fg=MUTED, bg="#eef1f4").pack(side="left")

        self.mode = tk.StringVar(value=mode)
        for text, value in (("Active", "active"), ("Testing", "testing")):
            ttk.Radiobutton(top, text=text, value=value, variable=self.mode,
                            command=self.rebuild).pack(side="right", padx=6)
        tk.Label(top, text="Mode:", bg="#eef1f4", font=("Segoe UI", 10, "bold")).pack(side="right")
        self.machine = tk.StringVar(value=[k for k, v in MACHINES.items()
                                           if v == (tasks.PI if is_raspberry_pi() else tasks.LAPTOP)][0])
        box = ttk.Combobox(top, textvariable=self.machine, values=list(MACHINES), state="readonly", width=32)
        box.pack(side="right", padx=(4, 20))
        box.bind("<<ComboboxSelected>>", lambda e: self.rebuild())
        tk.Label(top, text="This machine:", bg="#eef1f4").pack(side="right")

        self.body = ttk.Frame(self)
        self.body.pack(fill="both", expand=True)
        self.view = None
        self.rebuild()

    # Background threads must not touch Tk directly; they queue calls here.
    def call(self, fn, *args):
        self._calls.put((fn, args))

    def _drain(self):
        try:
            while True:
                fn, args = self._calls.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass          # the widget was closed in the meantime
        except queue.Empty:
            pass
        self._drain_id = self.after(40, self._drain)

    def _speech_message(self, msg):
        view = self.view
        log = getattr(view, "log", None) or getattr(view, "r_log", None)
        if log is not None:
            log.append(msg, "fail")

    def rebuild(self):
        if self.view is not None:
            self.view.shutdown()
            self.view.destroy()
        machine = MACHINES[self.machine.get()]
        if self.mode.get() == "testing":
            from testing_view import TestingView
            self.view = TestingView(self.body, self, machine)
        elif machine == tasks.PI:
            from active_view import PiActiveView
            self.view = PiActiveView(self.body, self)
        else:
            from active_view import LaptopActiveView
            self.view = LaptopActiveView(self.body, self)
        self.view.pack(fill="both", expand=True)

    def on_close(self):
        try:
            if self.view is not None:
                self.view.shutdown()
            self.speaker.close()
        finally:
            try:
                self.after_cancel(self._drain_id)
            except tk.TclError:
                pass
            self.destroy()


def main(argv=None):
    options = parse_args(argv)
    lock = None
    if options.kiosk:
        lock = SingleInstance()
        if not lock.acquire():
            print("Signyales kiosk is already running; not starting a second copy.")
            return 0
    try:
        try:
            app = App(options)
        except tk.TclError as exc:
            print(f"Could not open a window: {exc}\nOn the Pi, run this from the desktop (not plain SSH), "
                  "and install Tk with: sudo apt install python3-tk")
            return 1
        app.mainloop()
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    sys.exit(main())
