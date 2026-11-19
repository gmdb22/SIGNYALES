"""
Signyales GUI — Active mode.

On the Pi:      Recognize (live subtitles + speech, optional sharing to a
                laptop) and Record (teach the model: Start/Stop per repetition).
On the laptop:  Mirror the Pi (subtitles + speech on the laptop) and the
                Hardware helper (compile/flash boards, serial monitor, MAC check).
"""

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import calibrate, hardware, mirror, recorder, tasks
from core.env import (IS_WINDOWS, PI_SIDE, find_tool, is_raspberry_pi, receiver_link,
                      save_receiver_link, uart_port)
from core.live import LivePipeline, event_text, load_classifier, make_source
from core.procs import ProcessRunner
from widgets import MUTED, OK, BAD, FullscreenSubtitles, HandStatus, LogBox, SubtitlePanel



class RecentWords(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        ttk.Label(self, text="Recent words").pack(anchor="w")
        self.box = tk.Listbox(self, height=8, width=28)
        self.box.pack(fill="both", expand=True)

    def add(self, word, confidence=None):
        stamp = time.strftime("%H:%M:%S")
        conf = f"  {confidence:.2f}" if confidence is not None else ""
        self.box.insert(0, f"{stamp}  {word}{conf}")
        self.box.delete(50, "end")

    def clear(self):
        self.box.delete(0, "end")


# ===================================================================== Pi
class PiActiveView(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.pipeline = None
        self.server = None
        self.recorder = None
        # Receiver link, shared by both tabs and saved, so the kiosk uses it too.
        self.link_var = tk.StringVar(value=receiver_link())
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.recognize_tab = ttk.Frame(nb)
        self.record_tab = ttk.Frame(nb)
        self.calibrate_tab = ttk.Frame(nb)
        nb.add(self.recognize_tab, text="  Recognize  ")
        nb.add(self.record_tab, text="  Record (teach the model)  ")
        nb.add(self.calibrate_tab, text="  Calibrate glove  ")
        self._build_recognize(self.recognize_tab)
        self._build_record(self.record_tab)
        self._build_calibrate(self.calibrate_tab)
        self._show_active_calibration()

    # ---------------------------------------------------------------- shared controls
    def _port_row(self, parent, row):
        """Receiver link (USB cable / UART wires) and an optional port. Returns the port variable."""
        ttk.Label(parent, text="Receiver link:").grid(row=row, column=0, sticky="w")
        box = ttk.Frame(parent)
        box.grid(row=row, column=1, sticky="w", padx=4)
        ttk.Radiobutton(box, text="USB cable", value="usb", variable=self.link_var,
                        command=self._link_changed).pack(side="left")
        ttk.Radiobutton(box, text="UART wires", value="uart", variable=self.link_var,
                        command=self._link_changed).pack(side="left", padx=(6, 0))
        ttk.Label(box, text="  Port:").pack(side="left")
        var = tk.StringVar(value="")
        ttk.Entry(box, textvariable=var, width=14).pack(side="left", padx=(2, 0))
        ttk.Label(box, text="(blank = automatic)", foreground=MUTED).pack(side="left", padx=4)
        return var

    def _link_changed(self):
        link = self.link_var.get()
        try:
            save_receiver_link(link)
        except OSError as exc:
            messagebox.showerror("Not saved", f"Could not save the receiver link setting: {exc}")
            return
        where = (f"the UART wires on {uart_port()}" if link == "uart"
                 else "the USB cable (port found automatically)")
        msg = (f"Receiver link saved: {where}. Used from the next Start/Connect, "
               "and by the kiosk when the Pi starts.")
        for log in (getattr(self, "r_log", None), getattr(self, "k_log", None)):
            if log is not None:
                log.append(msg, "muted")

    def _start_pipeline(self, model_dir, on_event, simulate=False, port=None):
        if self.pipeline and self.pipeline.stopping:
            self.pipeline.join(3)        # Disconnect was just pressed: let it finish first
        if self.pipeline and self.pipeline.running:
            messagebox.showinfo("Already connected", "Already connected. Press Stop / Disconnect first.")
            return False
        link = self.link_var.get()
        if not simulate and IS_WINDOWS and (str(port).startswith("/dev/") or (link == "uart" and not port)):
            messagebox.showinfo("No UART on this laptop",
                                f"{port or uart_port()} is the Raspberry Pi's serial port; it doesn't exist "
                                "on Windows. Choose 'USB cable' with the receiver plugged into this laptop, "
                                "or tick 'Fake glove data' to try this screen without hardware.")
            return False
        self.pipeline = LivePipeline(lambda: make_source(port=port or None, simulate=simulate, link=link),
                                     lambda: load_classifier(model_dir),
                                     lambda e: self.app.call(self._route_event, on_event, e),
                                     calibration=calibrate.cal_files.load_active())
        self.pipeline.start()
        return True

    def _route_event(self, on_event, e):
        """Calibration events go to the Calibrate tab (whichever tab connected);
        everything else to that tab, with the live bars also shown on Calibrate."""
        t = e.get("type")
        if t == "calibration":
            if e.get("state") == "done":
                e = calibrate.finish(self.pipeline, e)
            self._show_calibration_event(e)
            return
        if t == "status":
            self.c_hands.update_status(e)
        elif t == "stopped":
            self.c_hands.reset()
            self.c_state.configure(text="Not reading the gloves.", foreground=MUTED)
        elif t == "started":
            self.c_state.configure(text="Reading the gloves. Ready to calibrate.", foreground=OK)
        on_event(e)

    def stop_pipeline(self):
        if self.pipeline and self.pipeline.running:
            self.pipeline.stop()

    # ---------------------------------------------------------------- Recognize
    def _build_recognize(self, tab):
        ctl = ttk.Frame(tab)
        ctl.pack(fill="x", pady=(4, 6))
        self.r_port = self._port_row(ctl, 0)
        ttk.Label(ctl, text="Model folder:").grid(row=1, column=0, sticky="w")
        self.r_model = tk.StringVar(value=str(PI_SIDE / "model"))
        ttk.Entry(ctl, textvariable=self.r_model, width=46).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Button(ctl, text="Browse...", command=lambda: self._browse(self.r_model)).grid(row=1, column=2)
        self.r_speak = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Speak words on this Pi", variable=self.r_speak).grid(
            row=0, column=2, sticky="w", padx=8)
        self.r_share = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctl, text="Share with a laptop (Mirror)", variable=self.r_share,
                        command=self._toggle_share).grid(row=0, column=3, sticky="w", padx=8)
        self.r_sim = tk.BooleanVar(value=not is_raspberry_pi())
        ttk.Checkbutton(ctl, text="Fake glove data (demo without gloves)", variable=self.r_sim).grid(
            row=1, column=3, sticky="w", padx=8)
        self.share_label = ttk.Label(ctl, text="", foreground=MUTED)
        self.share_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(4, 0))

        btns = ttk.Frame(tab)
        btns.pack(fill="x")
        self.r_start = ttk.Button(btns, text="Start recognition", command=self.start_recognition)
        self.r_start.pack(side="left")
        ttk.Button(btns, text="Stop", command=self.stop_pipeline).pack(side="left", padx=6)
        ttk.Button(btns, text="Fullscreen subtitles", command=lambda: FullscreenSubtitles(
            self.app, self.r_subtitle)).pack(side="left")
        ttk.Button(btns, text="Send test word", command=self.send_test_word).pack(side="left", padx=6)
        self.r_state = ttk.Label(btns, text="Stopped.", foreground=MUTED)
        self.r_state.pack(side="left", padx=10)

        self.r_subtitle = SubtitlePanel(tab, height=230)
        self.r_subtitle.pack(fill="x", pady=8)
        low = ttk.Frame(tab)
        low.pack(fill="both", expand=True)
        self.r_hands = HandStatus(low)
        self.r_hands.pack(side="left", anchor="n")
        self.r_recent = RecentWords(low)
        self.r_recent.pack(side="right", fill="y")
        self.r_log = LogBox(low, height=6)
        self.r_log.pack(side="left", fill="both", expand=True, padx=8)

    def _browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or str(PI_SIDE))
        if d:
            var.set(d)

    def start_recognition(self):
        model = self.r_model.get().strip()
        if not (Path(model) / "model.tflite").exists():
            messagebox.showwarning("No model", f"No model.tflite in {model}.\n\nTrain a model first, then "
                                   "copy model.tflite, labels.json and scaler.json into this folder.")
            return
        if self._start_pipeline(model, self._on_recognize_event, simulate=self.r_sim.get(),
                                port=self.r_port.get().strip()):
            self.r_state.configure(text="Starting (loading the model can take a few seconds)...",
                                   foreground=MUTED)
            self.r_recent.clear()

    def _on_recognize_event(self, e):
        if self.server:
            self.server.publish(e)
        t = e["type"]
        if t == "started":
            if e.get("port"):
                self.r_log.append(f"Reading the receiver on {e['port']} ({e.get('link', '')} link).", "muted")
            self.r_log.append("Flex calibration: " + (e.get("calibration") or
                              "none (values used as they arrive; see the Calibrate glove tab)"), "muted")
            if e["model"]:
                words = ", ".join(e.get("texts") or e["labels"])
                self.r_state.configure(text="Running. Words: " + words, foreground=OK)
                self.r_subtitle.idle()
            else:
                self.r_state.configure(text="Model did not load: see the log.", foreground=BAD)
                self.r_log.append("The model folder's files don't match each other or config.py, or "
                                  "TensorFlow/LiteRT is missing. Check the terminal for the reason.", "fail")
        elif t == "status":
            self.r_hands.update_status(e)
        elif t == "gesture":
            text = event_text(e)
            self.r_subtitle.show(text)
            self.r_recent.add(text, e["confidence"])
            if self.r_speak.get():
                self.app.speaker.say(text)
        elif t == "error":
            self.r_log.append("ERROR: " + e["message"], "fail")
            m = e["message"].lower()
            if "no receiver found on usb" in m:
                self.r_log.append("Plug the receiver into a Pi USB port with a data cable, or choose "
                                  "'UART wires' if it is wired to the GPIO pins.", "muted")
            elif "could not open" in m or "no such file" in m or "busy" in m:
                self.r_log.append("Check the receiver link and port, and that no other program "
                                  "(the kiosk, or the auto-start service) is using it: "
                                  "pkill -f signyales_gui.py; sudo systemctl stop signyales", "muted")
        elif t == "stopped":
            self.r_state.configure(text="Stopped.", foreground=MUTED)
            self.r_hands.reset()
            self.r_subtitle.idle()

    def send_test_word(self):
        """
        Treats a test word exactly like a recognized sign: subtitle and speech
        here, and the same event to any connected laptop. For checking the
        display, speaker and mirror link before a demo; needs no model or gloves.
        """
        event = {"type": "gesture", "label": "salamat", "text": "salamat", "confidence": 1.0, "test": True}
        if self.server:
            self.server.publish(event)
            n = self.server.client_count
            self.r_log.append(f"Test word 'salamat' sent to {n} connected laptop(s)."
                              + ("" if n else " None connected: on the laptop, Active > Mirror the Pi > Connect."),
                              "muted")
        else:
            self.r_log.append("Test word shown here only. Tick 'Share with a laptop' to send it to a laptop too.",
                              "muted")
        self.r_subtitle.show(event["label"])
        self.r_recent.add(event["label"] + " (test)")
        if self.r_speak.get():
            self.app.speaker.say(event["label"])

    def _toggle_share(self):
        if self.r_share.get():
            try:
                self.server = mirror.MirrorServer(
                    on_clients_changed=lambda n: self.app.call(self._update_share_label, n),
                    on_command=lambda cmd: self.app.call(self._mirror_command, cmd))
                self.server.start()
            except OSError as exc:
                self.r_share.set(False)
                self.server = None
                messagebox.showerror("Sharing failed", f"Could not open port {mirror.DEFAULT_PORT}: {exc}")
                return
            self._update_share_label(0)
        else:
            if self.server:
                self.server.stop()
            self.server = None
            self.share_label.configure(text="")

    def _update_share_label(self, n):
        if self.server:
            ips = ", ".join(mirror.local_ip_addresses())
            self.share_label.configure(
                text=f"Sharing on port {mirror.DEFAULT_PORT}. On the laptop, enter one of: {ips}. "
                     f"Laptops connected: {n}. Use only on a cable or private network (no password).")

    # ---------------------------------------------------------------- Record
    def _build_record(self, tab):
        ctl = ttk.Frame(tab)
        ctl.pack(fill="x", pady=(4, 6))
        self.k_port = self._port_row(ctl, 0)
        ttk.Label(ctl, text="Save under:").grid(row=1, column=0, sticky="w")
        self.k_base = tk.StringVar(value=str(Path.home() / "signyales_data"))
        ttk.Entry(ctl, textvariable=self.k_base, width=40).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Button(ctl, text="Browse...", command=lambda: self._browse(self.k_base)).grid(row=1, column=2)
        ttk.Label(ctl, text="Signer code:").grid(row=2, column=0, sticky="w")
        self.k_signer = tk.StringVar(value="W01")
        ttk.Entry(ctl, textvariable=self.k_signer, width=8).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(ctl, text="Session:").grid(row=2, column=1, sticky="w", padx=(90, 0))
        self.k_session = tk.StringVar(value="S01")
        ttk.Entry(ctl, textvariable=self.k_session, width=8).grid(row=2, column=1, sticky="w", padx=(150, 0))
        ttk.Label(ctl, text="Codes only, never names.", foreground=MUTED).grid(
            row=2, column=2, columnspan=2, sticky="w")
        self.k_sim = tk.BooleanVar(value=not is_raspberry_pi())
        ttk.Checkbutton(ctl, text="Fake glove data (tool test only, not real data)",
                        variable=self.k_sim).grid(row=0, column=2, columnspan=2, sticky="w", padx=8)

        conn = ttk.Frame(tab)
        conn.pack(fill="x")
        ttk.Button(conn, text="1. Connect to gloves", command=self.start_recording_session).pack(side="left")
        ttk.Button(conn, text="Disconnect", command=self.stop_pipeline).pack(side="left", padx=6)
        self.k_state = ttk.Label(conn, text="Not connected.", foreground=MUTED)
        self.k_state.pack(side="left", padx=10)
        self.k_cal = ttk.Label(tab, text="", foreground=MUTED)
        self.k_cal.pack(anchor="w")

        word = ttk.Frame(tab)
        word.pack(fill="x", pady=8)
        ttk.Label(word, text="2. Word:", font=("Segoe UI", 11, "bold")).pack(side="left")
        self.k_word = ttk.Combobox(word, values=recorder.FSL_ALPHABET + ["rest"], width=24,
                                   font=("Segoe UI", 12), postcommand=self._refresh_word_list)
        self.k_word.set("A")
        self.k_word.pack(side="left", padx=6)
        self.k_word.bind("<<ComboboxSelected>>", lambda e: self._update_counts())
        self.k_word.bind("<KeyRelease>", lambda e: self._update_counts())
        ttk.Label(word, text="Target reps:").pack(side="left", padx=(12, 2))
        self.k_target = tk.IntVar(value=20)
        ttk.Spinbox(word, from_=1, to=200, textvariable=self.k_target, width=5,
                    command=self._update_counts).pack(side="left")
        self.k_count = ttk.Label(word, text="", font=("Segoe UI", 11))
        self.k_count.pack(side="left", padx=12)
        ttk.Label(tab, text="Type the word, letter or phrase exactly as it should appear and be "
                            "spoken (e.g. A, Ñ, I'm fine). Pick 'rest' for the hand doing nothing. "
                            "The list shows the alphabet and the words already recorded here.",
                  foreground=MUTED, wraplength=900).pack(anchor="w")

        self.k_button = tk.Button(tab, text="3. START repetition  (Space)", font=("Segoe UI", 16, "bold"),
                                  bg="#2f7a4f", fg="white", activebackground="#25613e", height=2,
                                  command=self.toggle_rep, state="disabled", takefocus=0)
        self.k_button.pack(fill="x", pady=4)
        secs = recorder.HubConfig().window_size_samples / 50
        ttk.Label(tab, text=f"Hand at rest, press START, sign the word once and return to rest. The "
                            f"recording stops and saves by itself after {secs:.1f} s. Pressing START/STOP "
                            "again before then, or Esc, discards it. Repeat until the target is reached, "
                            "then pick the next word.",
                  foreground=MUTED, wraplength=900).pack(anchor="w")
        low = ttk.Frame(tab)
        low.pack(fill="both", expand=True, pady=6)
        self.k_hands = HandStatus(low)
        self.k_hands.pack(side="left", anchor="n")
        self.k_log = LogBox(low, height=8)
        self.k_log.pack(side="left", fill="both", expand=True, padx=8)
        self._last_toggle = 0.0
        self._rep_started = 0.0
        self._space_held = False
        self.app.bind("<KeyPress-space>", self._space)
        self.app.bind("<KeyRelease-space>", self._space_up)
        # On Windows a clicked button keeps the keyboard focus, and Space would
        # "press" it (e.g. Connect again). On this tab Space only means START/STOP:
        # take it over on every button and tick box here, before their own action.
        self._claim_space(tab)
        self.app.bind("<Escape>", self._escape)

    def _out_dir(self):
        signer = self.k_signer.get().strip() or "W00"
        session = self.k_session.get().strip() or "S00"
        return Path(self.k_base.get().strip()) / f"{signer}_{session}"

    def start_recording_session(self):
        out = self._out_dir()
        if not self._start_pipeline(None, self._on_record_event, simulate=self.k_sim.get(),
                                    port=self.k_port.get().strip()):
            return                       # keep the existing recorder attached
        self.recorder = recorder.GestureRecorder(out)
        self.pipeline.add_frame_listener(self.recorder.on_frame)
        active = self.pipeline.calibration
        signer = self.k_signer.get().strip()
        if active is None:
            self.k_log.append("No flex calibration is active. Calibrate this signer first (Calibrate glove "
                              "tab), so recording and recognition use the same scale.", "fail")
        elif active.signer != signer:
            self.k_log.append(f"The active calibration is {active.signer!r}, but you are recording as "
                              f"{signer!r}. Calibrate {signer} (or use their saved calibration) first.", "fail")
        self.record_tab.focus_set()      # take keyboard focus off the Connect button
        self.k_state.configure(text=f"Connecting... saving to {out}", foreground=MUTED)
        self._update_counts()

    def _on_record_event(self, e):
        t = e["type"]
        if t == "started":
            self.k_state.configure(text=f"Connected. Saving to {self._out_dir()}", foreground=OK)
            self.k_button.configure(state="normal")
        elif t == "status":
            self.k_hands.update_status(e)
        elif t == "error":
            self.k_log.append("ERROR: " + e["message"], "fail")
        elif t == "stopped":
            if self.recorder:
                self.recorder.cancel_rep()
            self.k_state.configure(text="Not connected.", foreground=MUTED)
            self.k_button.configure(state="disabled", text="3. START repetition  (Space)", bg="#2f7a4f")
            self.k_hands.reset()

    def _typed_word(self):
        """(text as typed, folder name) for the word box; folder is None if unusable."""
        text = " ".join(self.k_word.get().split())
        return text, recorder.word_to_label(text)

    def _refresh_word_list(self):
        done = recorder.recorded_words(self._out_dir())
        rest = [w for w in recorder.FSL_ALPHABET + ["rest"] if w not in done]
        self.k_word.configure(values=done + rest)

    def _update_counts(self):
        text, label = self._typed_word()
        if label is None:
            self.k_count.configure(text="(type a word with at least one letter or digit)", foreground=BAD)
            return
        n = recorder.count_reps(self._out_dir(), label)
        target = self.k_target.get()
        shown = recorder.read_word_text(self._out_dir() / label) or text
        extra = f"   shown as \"{shown}\", folder {label}" if shown != label else ""
        self.k_count.configure(text=f"{n} / {target} recorded{extra}",
                               foreground=OK if n >= target else MUTED)

    def toggle_rep(self):
        if not self.recorder or not (self.pipeline and self.pipeline.running):
            return
        now = time.monotonic()
        if now - self._last_toggle < 0.35:
            return       # a second trigger from the same press (e.g. button + Space shortcut together)
        self._last_toggle = now
        text, label = self._typed_word()
        if label is None and not self.recorder.recording:
            messagebox.showwarning("Word", "Type the word first: it needs at least one letter or digit.")
            return
        if not self.recorder.recording:
            self._rep_label = label
            self._rep_text = text
            self.recorder.start_rep()
            self._rep_started = now
            self.k_button.configure(text="RECORDING... sign now  (Space = discard)", bg="#b3412c",
                                    activebackground="#8f3423")
            self.app.after(50, self._poll_rep)
        elif self.recorder.fixed_length and not self.recorder.complete:
            frames = self.recorder.frame_count
            self.recorder.cancel_rep()
            self.k_log.append(f"Discarded: stopped after {frames / 50:.1f} s, before the "
                              f"{self.recorder.target_frames / 50:.1f} s window was full. "
                              "Let it finish by itself.", "muted")
            self._reset_rep_button()
        else:
            self._finish_rep()

    def _poll_rep(self):
        """While a fixed-length repetition records: show progress, save it once full."""
        rec = self.recorder
        if not rec or not rec.recording:
            return
        if rec.complete:
            self._finish_rep()
            return
        elapsed = time.monotonic() - self._rep_started
        frames, target = rec.frame_count, rec.target_frames
        if frames == 0 and elapsed > 2.0:
            rec.cancel_rep()
            self.k_log.append(f"Not saved: no glove data reached the recorder (0 frames in {elapsed:.1f} s). "
                              "Check the glove status lights above (green = data), then Disconnect and "
                              "Connect again.", "fail")
            self._reset_rep_button()
            return
        self.k_button.configure(text=f"RECORDING... {frames / 50:.1f} / {target / 50:.1f} s  "
                                     "(Space = discard)")
        self.app.after(50, self._poll_rep)

    def _finish_rep(self):
        label = getattr(self, "_rep_label", None) or self._typed_word()[1]
        elapsed = time.monotonic() - self._rep_started
        frames = self.recorder.frame_count
        try:
            path, frames = self.recorder.stop_rep(label)
            note = calibrate.note_session(self._out_dir(), self.pipeline.calibration if self.pipeline else None)
            if note:
                self.k_log.append(note, "fail")
            typed = getattr(self, "_rep_text", None) or label
            shown = recorder.save_word_text(path.parent, typed)
            self.k_log.append(f"Saved {path.name} for \"{shown}\" ({frames} frames, "
                              f"{frames / 50:.1f} s)", "pass")
            if shown != typed:
                self.k_log.append(f"This folder already shows as \"{shown}\" (kept). To change it, "
                                  f"edit {path.parent / 'text.txt'}", "muted")
            self._update_counts()
        except ValueError as exc:
            if frames == 0:
                self.k_log.append(f"Not saved: no glove data reached the recorder (0 frames in "
                                  f"{elapsed:.1f} s). Check the glove status lights above (green = data), "
                                  "then Disconnect and Connect again.", "fail")
            else:
                self.k_log.append(f"Not saved: {exc}", "fail")
        self._reset_rep_button()

    def _reset_rep_button(self):
        self.k_button.configure(text="3. START repetition  (Space)", bg="#2f7a4f",
                                activebackground="#25613e")
        self._update_counts()

    def _space(self, event):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox)):
            return None                  # typing in a box: let the space through
        if self._space_held:
            return "break"               # key auto-repeat while held down
        self._space_held = True
        if str(self.k_button["state"]) == "normal":
            self.toggle_rep()
        return "break"

    def _space_up(self, event):
        self._space_held = False

    def _claim_space(self, widget):
        """Binds Space to START/STOP on all buttons and tick boxes under widget."""
        for child in widget.winfo_children():
            if isinstance(child, (tk.Button, ttk.Button, ttk.Checkbutton, tk.Checkbutton)):
                child.bind("<KeyPress-space>", self._space)
                child.bind("<KeyRelease-space>", lambda e: (self._space_up(e), "break")[1])
            self._claim_space(child)

    def _escape(self, event):
        if self.recorder and self.recorder.recording:
            self.recorder.cancel_rep()
            self.k_log.append("Repetition cancelled (not saved).", "muted")
            self.k_button.configure(text="3. START repetition  (Space)", bg="#2f7a4f")

    # ---------------------------------------------------------------- Calibrate (wireless)
    def _build_calibrate(self, tab):
        ttk.Label(tab, text="Calibrates the flex sensors over the wireless link: no USB cable. Do it for "
                            "each signer before recording, and after moving or re-taping a sensor. Needs the "
                            "glove firmware that sends uncalibrated values (19 Nov 2026 or later).",
                  foreground=MUTED, wraplength=900).pack(anchor="w", pady=(4, 6))
        ctl = ttk.Frame(tab)
        ctl.pack(fill="x")
        self.c_port = self._port_row(ctl, 0)
        self.c_sim = tk.BooleanVar(value=not is_raspberry_pi())
        ttk.Checkbutton(ctl, text="Fake glove data (tool test only)", variable=self.c_sim).grid(
            row=0, column=2, sticky="w", padx=8)
        ttk.Label(ctl, text="Signer code:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(ctl, textvariable=self.k_signer, width=8).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(ctl, text="(same code as the Record tab; codes only, never names)",
                  foreground=MUTED).grid(row=1, column=1, sticky="w", padx=(80, 0))

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=6)
        self.c_button = tk.Button(btns, text="Calibrate (8 s)", font=("Segoe UI", 13, "bold"),
                                  bg="#2f7a4f", fg="white", activebackground="#25603e",
                                  command=self.calibrate_now, padx=16, pady=6)
        self.c_button.pack(side="left")
        ttk.Button(btns, text="Disconnect", command=self.stop_pipeline).pack(side="left", padx=6)
        ttk.Label(btns, text="Saved:").pack(side="left", padx=(18, 2))
        self.c_saved = ttk.Combobox(btns, width=10, postcommand=self._refresh_saved_signers)
        self.c_saved.pack(side="left")
        ttk.Button(btns, text="Use this signer's saved calibration",
                   command=self.use_saved_calibration).pack(side="left", padx=6)
        self.c_state = ttk.Label(tab, text="Not reading the gloves.", foreground=MUTED)
        self.c_state.pack(anchor="w")
        self.c_active = ttk.Label(tab, text="", font=("Segoe UI", 11))
        self.c_active.pack(anchor="w", pady=(2, 0))
        self.c_big = ttk.Label(tab, text="", font=("Segoe UI", 20, "bold"))
        self.c_big.pack(anchor="w", pady=6)
        low = ttk.Frame(tab)
        low.pack(fill="both", expand=True)
        self.c_hands = HandStatus(low)
        self.c_hands.pack(side="left", anchor="n")
        self.c_log = LogBox(low, height=12)
        self.c_log.pack(side="left", fill="both", expand=True, padx=8)

    def _refresh_saved_signers(self):
        self.c_saved.configure(values=calibrate.cal_files.list_signers())

    def calibrate_now(self):
        signer = self.k_signer.get().strip()
        err = calibrate.check_signer(signer)
        if err:
            messagebox.showwarning("Signer code", err)
            return
        if not (self.pipeline and self.pipeline.running and not self.pipeline.stopping):
            # Nothing is reading the gloves yet: connect just for calibrating (no model).
            if not self._start_pipeline(None, lambda e: None, simulate=self.c_sim.get(),
                                        port=self.c_port.get().strip()):
                return
            self.c_state.configure(text="Connecting...", foreground=MUTED)
            self.after(1500, lambda: self._show_calibration_event(calibrate.start(self.pipeline, signer)))
            return
        self._show_calibration_event(calibrate.start(self.pipeline, signer))

    def use_saved_calibration(self):
        signer = self.c_saved.get().strip() or self.k_signer.get().strip()
        self._show_calibration_event(calibrate.use(self.pipeline, signer))

    def _mirror_command(self, cmd):
        ev = calibrate.handle_command(self.pipeline, cmd)
        if ev is not None:
            self.c_log.append(f"Laptop asked: {cmd.get('cmd')} {cmd.get('signer', '')}".rstrip(), "muted")
            self._show_calibration_event(ev)

    def _show_active_calibration(self):
        active = calibrate.cal_files.load_active()
        text = ("Active calibration: " + active.describe()) if active else \
               "Active calibration: none (flex values are used as they arrive)"
        self.c_active.configure(text=text)
        self.k_cal.configure(text=text)

    def _show_calibration_event(self, e):
        """Shows a calibration event here and sends it to connected laptops."""
        if self.server:
            self.server.publish(e)
        state = e.get("state")
        if state == "started":
            self.c_button.configure(state="disabled")
            self.c_big.configure(text=f"Calibrating {e['signer']}: 8 s", foreground=OK)
            self.c_log.append(calibrate.HOW_TO, "muted")
        elif state == "running":
            self.c_big.configure(text=f"Calibrating {e['signer']}: {e['seconds_left']:.0f} s", foreground=OK)
        elif state in ("saved", "active"):
            self.c_button.configure(state="normal")
            if state == "saved":
                good = e.get("all_ok")
                self.c_big.configure(text=f"Saved for {e['signer']}" + ("" if good else
                                     ": some sensors barely moved"), foreground=OK if good else BAD)
            else:
                self.c_big.configure(text=f"Using {e['signer']}'s saved calibration", foreground=OK)
            for line in calibrate.describe_rows(e.get("rows", {})):
                self.c_log.append(line, "fail" if "TOO SMALL" in line else None)
            self._show_active_calibration()
            for log in (self.r_log, self.k_log):
                log.append(f"Flex calibration now: {e.get('describe', e['signer'])}", "muted")
        elif state in ("failed", "error"):
            self.c_button.configure(state="normal")
            self.c_big.configure(text="Not calibrated", foreground=BAD)
            self.c_log.append(e.get("message", ""), "fail")
        elif state == "list":
            self.c_log.append("Saved calibrations: " + (", ".join(e.get("signers", [])) or "none"), "muted")

    def shutdown(self):
        self.app.unbind("<KeyPress-space>")
        self.app.unbind("<KeyRelease-space>")
        self.app.unbind("<Escape>")
        self.stop_pipeline()
        if self.server:
            self.server.stop()


# ===================================================================== laptop
class LaptopActiveView(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.client = None
        self.monitor = None
        self.runner = None
        self.last_mac = None
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        m, h = ttk.Frame(nb), ttk.Frame(nb)
        nb.add(m, text="  Mirror the Pi  ")
        nb.add(h, text="  Hardware helper  ")
        self._build_mirror(m)
        self._build_hardware(h)

    # ---------------------------------------------------------------- Mirror
    def _build_mirror(self, tab):
        ctl = ttk.Frame(tab)
        ctl.pack(fill="x", pady=(4, 6))
        ttk.Label(ctl, text="Pi address:").pack(side="left")
        self.m_host = tk.StringVar(value="")
        ttk.Entry(ctl, textvariable=self.m_host, width=18).pack(side="left", padx=4)
        ttk.Label(ctl, text=f"port {mirror.DEFAULT_PORT}", foreground=MUTED).pack(side="left")
        self.m_connect = ttk.Button(ctl, text="Connect", command=self.toggle_mirror)
        self.m_connect.pack(side="left", padx=8)
        self.m_speak = tk.BooleanVar(value=True)
        ttk.Checkbutton(ctl, text="Speak words on this laptop", variable=self.m_speak).pack(side="left")
        ttk.Button(ctl, text="Fullscreen subtitles", command=lambda: FullscreenSubtitles(
            self.app, self.m_subtitle)).pack(side="left", padx=8)
        self.m_state = ttk.Label(tab, text="On the Pi: Active mode, Recognize, tick 'Share with a laptop', "
                                           "start recognition, then type the address it shows here.",
                                 foreground=MUTED)
        self.m_state.pack(anchor="w")
        cal = ttk.Frame(tab)
        cal.pack(fill="x", pady=(6, 0))
        ttk.Label(cal, text="Glove calibration (wireless, done by the Pi):").pack(side="left")
        ttk.Label(cal, text="Signer code:").pack(side="left", padx=(8, 2))
        self.m_signer = tk.StringVar(value="W01")
        ttk.Entry(cal, textvariable=self.m_signer, width=8).pack(side="left")
        self.m_cal_button = ttk.Button(cal, text="Calibrate (8 s)",
                                       command=lambda: self._mirror_send("calibrate"))
        self.m_cal_button.pack(side="left", padx=6)
        ttk.Button(cal, text="Use saved", command=lambda: self._mirror_send("use_calibration")).pack(side="left")
        ttk.Button(cal, text="List saved", command=lambda: self._mirror_send("calibration_list")).pack(
            side="left", padx=6)
        self.m_cal_big = ttk.Label(tab, text="", font=("Segoe UI", 16, "bold"))
        self.m_cal_big.pack(anchor="w")
        self.m_subtitle = SubtitlePanel(tab, idle_text="Not connected", height=230)
        self.m_subtitle.pack(fill="x", pady=8)
        low = ttk.Frame(tab)
        low.pack(fill="both", expand=True)
        self.m_hands = HandStatus(low)
        self.m_hands.pack(side="left", anchor="n")
        self.m_recent = RecentWords(low)
        self.m_recent.pack(side="right", fill="y")
        self.m_log = LogBox(low, height=8)
        self.m_log.pack(side="left", fill="both", expand=True, padx=8)

    def toggle_mirror(self):
        if self.client:
            self.client.close()
            self._mirror_disconnected("disconnected")
            return
        host = self.m_host.get().strip()
        if not host:
            messagebox.showinfo("Pi address", "Type the Pi's address (shown on the Pi when sharing is on).")
            return
        self.client = mirror.MirrorClient(lambda e: self.app.call(self._on_mirror_event, e),
                                          lambda r: self.app.call(self._mirror_disconnected, r))
        try:
            self.client.connect(host)
        except OSError as exc:
            self.client = None
            messagebox.showerror("Could not connect", f"{host}:{mirror.DEFAULT_PORT}: {exc}\n\nCheck that "
                                 "sharing is ticked on the Pi, both are on the same cable or network, and "
                                 "the Windows firewall allows Python.")
            return
        self.m_connect.configure(text="Disconnect")
        self.m_state.configure(text=f"Connected to {host}. Waiting for recognition on the Pi...", foreground=OK)
        self.m_subtitle.idle_text = "Listening..."
        self.m_subtitle.idle()

    def _mirror_send(self, what):
        """Asks the Pi to calibrate (or use / list saved calibrations) over the mirror link."""
        if not self.client:
            messagebox.showinfo("Not connected", "Connect to the Pi first (Pi: Recognize, tick 'Share with "
                                "a laptop', start recognition; or the kiosk with sharing on).")
            return
        signer = self.m_signer.get().strip()
        if what != "calibration_list":
            err = calibrate.check_signer(signer)
            if err:
                messagebox.showwarning("Signer code", err)
                return
        try:
            self.client.send({"type": "command", "cmd": what, "signer": signer})
        except OSError as exc:
            self.m_log.append(f"Could not send to the Pi: {exc}", "fail")
            return
        self.m_log.append(f"Asked the Pi: {what.replace('_', ' ')} {signer}".rstrip(), "muted")

    def _mirror_calibration(self, e):
        state = e.get("state")
        if state == "started":
            self.m_cal_big.configure(text=f"Calibrating {e['signer']}: 8 s", foreground=OK)
            self.m_log.append(e.get("how_to", ""), "muted")
        elif state == "running":
            self.m_cal_big.configure(text=f"Calibrating {e['signer']}: {e['seconds_left']:.0f} s", foreground=OK)
        elif state in ("saved", "active"):
            good = e.get("all_ok", True)
            self.m_cal_big.configure(
                text=(f"Saved for {e['signer']}" if state == "saved" else f"Using {e['signer']}'s calibration")
                + ("" if good else ": some sensors barely moved"), foreground=OK if good else BAD)
            for line in calibrate.describe_rows(e.get("rows", {}), e.get("min_range", 500)):
                self.m_log.append(line, "fail" if "TOO SMALL" in line else None)
        elif state in ("failed", "error"):
            self.m_cal_big.configure(text="Not calibrated", foreground=BAD)
            self.m_log.append(e.get("message", ""), "fail")
        elif state == "list":
            self.m_log.append("Saved on the Pi: " + (", ".join(e.get("signers", [])) or "none")
                              + (f". Active: {e['describe']}" if e.get("describe") else ". None active."),
                              "muted")

    def _mirror_disconnected(self, reason):
        self.client = None
        self.m_connect.configure(text="Connect")
        self.m_state.configure(text=f"Not connected ({reason}).", foreground=MUTED)
        self.m_subtitle.idle_text = "Not connected"
        self.m_subtitle.idle()
        self.m_hands.reset()

    def _on_mirror_event(self, e):
        t = e.get("type")
        if t == "gesture":
            text = event_text(e)
            self.m_subtitle.show(text)
            if e.get("test"):
                self.m_recent.add(text + " (test)")
            else:
                self.m_recent.add(text, e.get("confidence"))
            if self.m_speak.get():
                self.app.speaker.say(text)
        elif t == "status":
            self.m_hands.update_status(e)
        elif t == "calibration":
            self._mirror_calibration(e)
        elif t == "started":
            words = ", ".join(e.get("texts") or e.get("labels", [])) or "no model"
            self.m_state.configure(text=f"Pi is recognizing. Words: {words}", foreground=OK)
            if "calibration" in e:
                self.m_log.append("Flex calibration on the Pi: " + (e["calibration"] or "none"), "muted")
        elif t == "stopped":
            self.m_state.configure(text="Pi stopped recognition (still connected).", foreground=MUTED)
            self.m_hands.reset()
            self.m_subtitle.idle()

    # ---------------------------------------------------------------- Hardware helper
    def _build_hardware(self, tab):
        top = ttk.Frame(tab)
        top.pack(fill="x", pady=(4, 4))
        ttk.Label(top, text="Board's USB port:").pack(side="left")
        self.h_port = ttk.Combobox(top, width=40, state="readonly")
        self.h_port.pack(side="left", padx=4)
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left")
        ttk.Label(top, text="Plug in ONE board at a time.", foreground=MUTED).pack(side="left", padx=8)

        fw = ttk.LabelFrame(tab, text="Firmware (PlatformIO)")
        fw.pack(fill="x", pady=4)
        for i, (label, folder, env) in enumerate(tasks.FIRMWARE_TARGETS):
            ttk.Label(fw, text=label, width=22).grid(row=i, column=0, sticky="w", padx=4)
            ttk.Button(fw, text="Compile", command=lambda f=folder, e=env, l=label: self.pio(f, e, l, False)
                       ).grid(row=i, column=1, padx=2, pady=1)
            ttk.Button(fw, text="Upload to selected port",
                       command=lambda f=folder, e=env, l=label: self.pio(f, e, l, True)).grid(row=i, column=2)
        ttk.Label(fw, text="Upload order: MAC utility on the receiver (Stage 1b), then both gloves, then the "
                           "receiver. Don't flash a glove build onto the receiver or the reverse. The glove "
                           "hardware check is a temporary test for one glove (send s, r, w, i or p); flash the "
                           "glove firmware back afterwards.",
                  foreground=MUTED, wraplength=760).grid(row=len(tasks.FIRMWARE_TARGETS), column=0,
                                                         columnspan=3, sticky="w", padx=4, pady=2)

        mon = ttk.LabelFrame(tab, text=f"Serial monitor ({hardware.MONITOR_BAUD} baud, USB debug output)")
        mon.pack(fill="both", expand=True, pady=4)
        row = ttk.Frame(mon)
        row.pack(fill="x")
        self.h_open = ttk.Button(row, text="Open monitor", command=self.toggle_monitor)
        self.h_open.pack(side="left")
        ttk.Button(row, text="Send 'c' (calibrate glove)", command=lambda: self._send("c")).pack(
            side="left", padx=4)
        self.h_send = tk.StringVar()
        ttk.Entry(row, textvariable=self.h_send, width=16).pack(side="left", padx=(12, 2))
        ttk.Button(row, text="Send", command=lambda: self._send(self.h_send.get())).pack(side="left")
        ttk.Button(row, text="Check RECEIVER_MAC in config.h", command=self.check_mac).pack(side="right")
        self.h_mac = ttk.Label(mon, text="", wraplength=900)
        self.h_mac.pack(anchor="w", pady=2)
        self.h_log = LogBox(mon, height=14)
        self.h_log.pack(fill="both", expand=True)
        self.refresh_ports()

    def refresh_ports(self):
        ports = hardware.list_serial_ports()
        self.h_port["values"] = [f"{d}  -  {desc}" for d, desc in ports]
        if ports:
            self.h_port.current(0)
        else:
            self.h_port.set("")
            self.h_log.append("No serial ports found. Plug in a board with a data USB cable, then Refresh.",
                              "muted")

    def _selected_port(self):
        v = self.h_port.get()
        return v.split("  -  ")[0] if v else None

    def pio(self, folder, env, label, upload):
        if self.runner and self.runner.running:
            messagebox.showinfo("Busy", "A PlatformIO command is still running.")
            return
        pio = find_tool("pio")
        if not pio:
            messagebox.showerror("PlatformIO not found", "Install VS Code's PlatformIO extension, or "
                                 "`pip install platformio`, then restart this app.")
            return
        cmd = [pio, "run"] + (["-e", env] if env else [])
        if upload:
            port = self._selected_port()
            if not port:
                messagebox.showinfo("No port", "Pick the board's port first (Refresh).")
                return
            if self.monitor and self.monitor.open:
                self.toggle_monitor()          # the port can't be shared
            cmd += ["-t", "upload", "--upload-port", port]
        action = "Upload" if upload else "Compile"
        self.h_log.append(f"=== {action}: {label}", "head")
        self.h_log.append("$ " + " ".join(cmd) + f"    (in {folder})", "muted")

        def done(rc, _):
            self.h_log.append(f"=== {action} {label}: {'PASS' if rc == 0 else 'FAIL'}",
                              "pass" if rc == 0 else "fail")
            if rc != 0 and upload:
                self.h_log.append("If it stopped at 'Connecting...': hold BOOT, tap EN, release BOOT when "
                                  "writing starts. 'Port busy': close other serial monitors.", "muted")
        self.runner = ProcessRunner(lambda l: self.app.call(self.h_log.append, l),
                                    lambda rc, to: self.app.call(done, rc, to))
        self.runner.start(cmd, folder)

    def toggle_monitor(self):
        if self.monitor and self.monitor.open:
            self.monitor.close()
            self.monitor = None
            self.h_open.configure(text="Open monitor")
            self.h_log.append("--- monitor closed", "muted")
            return
        port = self._selected_port()
        if not port:
            messagebox.showinfo("No port", "Pick the board's port first (Refresh).")
            return
        self.monitor = hardware.SerialMonitor(lambda l: self.app.call(self._monitor_line, l),
                                              lambda r: self.app.call(self._monitor_closed, r))
        try:
            self.monitor.start(port)
        except Exception as exc:
            self.monitor = None
            messagebox.showerror("Could not open port", f"{port}: {exc}\n\nClose any other serial monitor "
                                 "(VS Code, pio device monitor) and try again.")
            return
        self.h_open.configure(text="Close monitor")
        self.h_log.append(f"--- monitor open on {port}. Press EN/RST on the board to see its boot messages.",
                          "muted")

    def _monitor_line(self, line):
        self.h_log.append(line)
        mac = hardware.parse_mac(line)
        if mac and ("MAC" in line.upper()):
            self.last_mac = mac
            self.check_mac()

    def _monitor_closed(self, reason):
        self.monitor = None
        self.h_open.configure(text="Open monitor")
        self.h_log.append(f"--- monitor closed: {reason}", "muted")

    def _send(self, text):
        if self.monitor and self.monitor.open and text:
            self.monitor.send(text)
            self.h_log.append(f">>> sent {text!r}", "muted")
        elif not (self.monitor and self.monitor.open):
            messagebox.showinfo("Monitor closed", "Open the monitor first.")

    def check_mac(self):
        verdict = hardware.compare_mac(self.last_mac, hardware.read_config_mac())
        colour = OK if verdict.startswith("OK") else (BAD if verdict.startswith("MISMATCH") else "#b06a12")
        self.h_mac.configure(text=verdict, foreground=colour)

    def shutdown(self):
        if self.client:
            self.client.close()
        if self.monitor:
            self.monitor.close()
        if self.runner and self.runner.running:
            self.runner.stop()
