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
"""

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import tasks  # noqa: E402
from core.env import is_raspberry_pi, machine_name  # noqa: E402
from widgets import INK, MUTED, Speaker  # noqa: E402

MACHINES = {"Laptop (no Pi needed for testing)": tasks.LAPTOP, "Raspberry Pi": tasks.PI}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Signyales")
        self.geometry("1180x780")
        self.minsize(1000, 680)
        self._calls = queue.Queue()
        self.after(40, self._drain)
        self.speaker = Speaker(on_message=lambda m: self.call(self._speech_message, m))

        style = ttk.Style(self)
        if "clam" in style.theme_names() and sys.platform != "win32":
            style.theme_use("clam")

        top = tk.Frame(self, background="#eef1f4")
        top.pack(fill="x")
        tk.Label(top, text="Signyales", font=("Segoe UI", 16, "bold"), fg=INK, bg="#eef1f4").pack(
            side="left", padx=12, pady=8)
        tk.Label(top, text=f"detected: {machine_name()}", fg=MUTED, bg="#eef1f4").pack(side="left")

        self.mode = tk.StringVar(value="testing")
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
        self.protocol("WM_DELETE_WINDOW", self.on_close)

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
        self.after(40, self._drain)

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
            self.destroy()


def main():
    try:
        app = App()
    except tk.TclError as exc:
        print(f"Could not open a window: {exc}\nOn the Pi, run this from the desktop (not plain SSH), "
              "and install Tk with: sudo apt install python3-tk")
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
