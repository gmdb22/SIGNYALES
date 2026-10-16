"""
Signyales GUI — Testing mode: every check is a button.

Each button runs the same command the guides use and shows PASS/FAIL plus
the full output. Nothing here changes the repo except where a button says
so (training writes to the folder you pick; the freeze manifest writes to
pi-side/results/).
"""

import json
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core import tasks
from core.env import PI_SIDE, REPO_ROOT
from core.live import LivePipeline, load_classifier, make_source
from core.procs import ProcessRunner
from widgets import STATUS_STYLE, HandStatus, LogBox, SubtitlePanel

OUTPUT_INTRO = "Signyales speaker test."
OUTPUT_WORDS = ["salamat", "kumusta"]


class TestingView(ttk.Frame):
    def __init__(self, master, app, machine):
        super().__init__(master)
        self.app, self.machine = app, machine
        self.rows = {}
        self.runner = None
        self.pipeline = None
        self.queue_all = []

        left = ttk.Frame(self)
        left.pack(side="left", fill="y", padx=(10, 6), pady=8)
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(6, 10), pady=8)

        canvas = tk.Canvas(left, width=430, highlightthickness=0)
        scroll = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="y", expand=True)
        scroll.pack(side="left", fill="y")

        all_tasks = tasks.tasks_for(machine)
        software = [t for t in all_tasks if t.key in ("roundtrip", "units", "pipeline", "native", "training")]
        self._section(inner, "Software checks (no hardware needed)")
        for t in software:
            self._task_row(inner, t)
        ttk.Button(inner, text="Run all software checks", command=lambda: self.run_many(
            [t for t in software if t.key != "training"])).pack(anchor="w", pady=(4, 8))

        if machine == tasks.LAPTOP:
            self._section(inner, "Firmware (laptop, PlatformIO)")
            for t in [t for t in all_tasks if t.key.startswith("compile_")]:
                self._task_row(inner, t)
        else:
            self._section(inner, "Pi hardware checks")
            for t in [t for t in all_tasks if t.key in ("loopback", "liveview", "freeze")]:
                self._task_row(inner, t)

        self._section(inner, "Output and data tools")
        self._tool_row(inner, "Subtitle and speaker check",
                       "Shows 'salamat' below and speaks a test phrase.", self.output_check)
        self._tool_row(inner, "Simulated pipeline (fake gloves)",
                       "Runs recognition on fake data; pick a model folder to see subtitles.",
                       self.toggle_simulation)
        self._tool_row(inner, "Inspect recordings...", "Checks a recorded data folder.", self.inspect)
        self._tool_row(inner, "Train a model...", "Runs train.py: pick the data and an output folder.",
                       self.train)
        self._tool_row(inner, "Benchmark a model...", "Times inference for a model folder.", self.benchmark)

        self.subtitle = SubtitlePanel(right, height=150)
        self.subtitle.pack(fill="x")
        self.hands = HandStatus(right)
        self.hands.pack(fill="x", pady=4)
        bar = ttk.Frame(right)
        bar.pack(fill="x")
        self.now_label = ttk.Label(bar, text="Pick a check on the left.")
        self.now_label.pack(side="left")
        ttk.Button(bar, text="Stop", command=self.stop_current).pack(side="right")
        ttk.Button(bar, text="Clear log", command=lambda: self.log.clear()).pack(side="right", padx=4)
        self.log = LogBox(right, height=18)
        self.log.pack(fill="both", expand=True, pady=(4, 0))

    # ---------------------------------------------------------------- layout helpers
    def _section(self, parent, title):
        ttk.Label(parent, text=title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))

    def _task_row(self, parent, task):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=1)
        btn = ttk.Button(row, text=task.title, width=44, command=lambda t=task: self.run_task(t))
        btn.pack(side="left")
        st = tk.Label(row, text=STATUS_STYLE["idle"][0], fg=STATUS_STYLE["idle"][1], width=10,
                      font=("Segoe UI", 9, "bold"))
        st.pack(side="left", padx=4)
        self.rows[task.key] = st
        _tooltip(btn, task.help)

    def _tool_row(self, parent, title, help_text, fn):
        btn = ttk.Button(parent, text=title, width=44, command=fn)
        btn.pack(anchor="w", pady=1)
        _tooltip(btn, help_text)

    def _set_status(self, key, status):
        if key in self.rows:
            text, colour = STATUS_STYLE[status]
            self.rows[key].configure(text=text, fg=colour)

    # ---------------------------------------------------------------- running commands
    def busy(self):
        if (self.runner and self.runner.running) or (self.pipeline and self.pipeline.running):
            messagebox.showinfo("Busy", "Something is still running. Wait for it, or press Stop.")
            return True
        return False

    def run_task(self, task, then=None):
        if self.busy():
            return
        missing = task.missing()
        if missing:
            self._set_status(task.key, "skipped")
            self.log.append(f"=== {task.title}: SKIPPED, not found: {', '.join(missing)}", "muted")
            if task.key.startswith("compile_"):
                self.log.append("Install VS Code's PlatformIO extension, or `pip install platformio`.", "muted")
            if then:
                then()
            return
        cmd = tasks.resolve_cmd(task)
        self._run(cmd, task.cwd, task.title, key=task.key, timeout=task.timeout,
                  success_on_timeout=task.success_on_timeout, then=then)

    def _run(self, cmd, cwd, title, key=None, timeout=None, success_on_timeout=False, then=None,
             on_success=None):
        self._set_status(key, "running")
        self.now_label.configure(text=f"Running: {title}")
        self.log.append(f"=== {title}", "head")
        self.log.append("$ " + " ".join(str(c) for c in cmd) + f"    (in {cwd})", "muted")
        started = time.monotonic()

        def on_exit(rc, timed_out):
            ok = rc == 0 or (timed_out and success_on_timeout)
            status = "pass" if ok else ("skipped" if rc == 2 and key == "native" else "fail")
            self._set_status(key, status)
            note = " (stopped after the time limit, as intended)" if timed_out and success_on_timeout else ""
            self.log.append(f"=== {title}: {STATUS_STYLE[status][0]}{note}, "
                            f"{time.monotonic() - started:.0f} s", "pass" if ok else "fail")
            self.now_label.configure(text="Done.")
            if ok and on_success:
                on_success()
            if then:
                then()

        self.runner = ProcessRunner(lambda line: self.app.call(self.log.append, line),
                                    lambda rc, to: self.app.call(on_exit, rc, to))
        self.runner.start(cmd, cwd, timeout=timeout)

    def run_many(self, task_list):
        if self.busy():
            return
        pending = list(task_list)

        def next_one():
            if pending:
                self.run_task(pending.pop(0), then=lambda: self.app.after(200, next_one))
        next_one()

    def stop_current(self):
        if self.runner and self.runner.running:
            self.runner.stop()
        if self.pipeline and self.pipeline.running:
            self.pipeline.stop()

    # ---------------------------------------------------------------- tools
    def output_check(self):
        """Says an intro, then each test word while that word is on screen, as
        the live app does when it recognizes a sign."""
        self.log.append("=== Subtitle and speaker check", "head")
        self.log.append(f'Speaking "{OUTPUT_INTRO}", then each word while it is shown above: '
                        + ", then ".join(OUTPUT_WORDS) + ".")
        self.log.append(f"Speech backend: {self.app.speaker.backend or 'still starting'} "
                        "(runs in a separate helper process)", "muted")
        self.log.append("Write down: readable from about 2 m? Did each word on screen match what you "
                        "heard? Which speaker?", "muted")
        call = self.app.call
        self.subtitle.idle()
        self.app.speaker.say(OUTPUT_INTRO)
        for word in OUTPUT_WORDS:
            self.app.speaker.say(word, on_start=lambda w=word: call(self.subtitle.show, w),
                                 on_done=lambda: time.sleep(0.6))
        self.app.speaker.say("", on_start=lambda: call(self.subtitle.idle),
                             on_done=lambda: call(self.log.append, "=== Subtitle and speaker check: done "
                                                  "(listen-and-look check, no automatic PASS)", "head"))

    def toggle_simulation(self):
        if self.pipeline and self.pipeline.running:
            self.pipeline.stop()
            return
        if self.runner and self.runner.running:
            messagebox.showinfo("Busy", "A check is still running. Wait for it, or press Stop.")
            return
        model_dir = filedialog.askdirectory(
            title="Model folder for the simulation (Cancel = run without a model)",
            initialdir=str(PI_SIDE / "model"))
        self.log.append("=== Simulated pipeline (fake glove data; press the button again or Stop to end)",
                        "head")
        if model_dir:
            self.log.append(f"Model folder: {model_dir}. Fake data, so recognized words are meaningless; "
                            "this shows the display and speech path working.", "muted")
        self.pipeline = LivePipeline(lambda: make_source(simulate=True),
                                     lambda: load_classifier(model_dir or None),
                                     lambda e: self.app.call(self._on_sim_event, e))
        self.now_label.configure(text="Running: simulated pipeline")
        self.pipeline.start()

    def _on_sim_event(self, e):
        t = e["type"]
        if t == "status":
            self.hands.update_status(e)
        elif t == "started":
            self.log.append("Model loaded: " + (", ".join(e["labels"]) if e["model"] else
                                                "no model (status only, no words)"))
        elif t == "gesture":
            self.subtitle.show(e["label"])
            self.app.speaker.say(e["label"])
            self.log.append(f"Recognized: {e['label']} ({e['confidence']:.2f})")
        elif t == "error":
            self.log.append("ERROR: " + e["message"], "fail")
        elif t == "stopped":
            self.log.append("=== Simulated pipeline stopped", "head")
            self.hands.reset()
            self.subtitle.idle()
            self.now_label.configure(text="Done.")

    def inspect(self):
        if self.busy():
            return
        folder = filedialog.askdirectory(title="Recorded data folder (with one subfolder per word)",
                                         initialdir=str(REPO_ROOT / "training" / "data"))
        if folder:
            cmd, cwd = tasks.inspect_cmd(folder)
            self._run(cmd, cwd, f"Inspect recordings: {folder}")

    def train(self):
        if self.busy():
            return
        data = filedialog.askdirectory(title="1/2: Data folder to train on (one subfolder per word)",
                                       initialdir=str(REPO_ROOT / "training" / "data"))
        if not data:
            return
        out = filedialog.askdirectory(title="2/2: Output folder for the model (outside the repo)",
                                      initialdir=str(Path.home()))
        if not out:
            return
        try:
            inside = Path(out).resolve().is_relative_to(REPO_ROOT.resolve())
        except AttributeError:
            inside = str(Path(out).resolve()).startswith(str(REPO_ROOT.resolve()))
        if inside and not messagebox.askyesno(
                "Output inside the repo", "That folder is inside the repo. Models there can be committed "
                "by accident. Continue anyway?"):
            return
        quantize = messagebox.askyesno("int8?", "Export an int8 (quantized) model?\n\nNo = float32 "
                                       "(simpler; fine on the Pi 5).")
        cmd, cwd = tasks.train_cmd(data, out, quantize)
        self._run(cmd, cwd, "Train model", on_success=lambda: self._show_report(Path(out)))

    def _show_report(self, out):
        try:
            r = json.loads((out / "train_report.json").read_text())
        except (OSError, ValueError):
            return
        conf = r.get("confidence", {}).get("validation", {})
        agree = r.get("export", {}).get("hub_runtime_agreement", {})
        self.log.append("--- Training report summary", "head")
        self.log.append(f"Words: {', '.join(r['data']['labels'])}")
        self.log.append(f"Test accuracy: {r['test']['accuracy']:.1%} on {r['data']['split_counts']['test']} "
                        f"windows (random split, not by person or session)")
        self.log.append(f"Validation confidence: mean {conf.get('mean_confidence')}, "
                        f"{conf.get('fraction_at_or_above_threshold', 0):.0%} at/above "
                        f"{r['hub_config_check']['confidence_threshold']}")
        self.log.append(f"Hub runtime agrees with Keras on {agree.get('agree')}/{agree.get('total')} test windows")
        for p in r["hub_config_check"]["problems"]:
            self.log.append("WARNING: " + p, "fail")
        self.log.append(f"Copy model.tflite, labels.json and scaler.json from {out} to the Pi's "
                        "pi-side/model/ once you accept this model.", "muted")

    def benchmark(self):
        if self.busy():
            return
        folder = filedialog.askdirectory(title="Model folder to benchmark", initialdir=str(PI_SIDE / "model"))
        if folder:
            cmd, cwd = tasks.benchmark_cmd(folder)
            self._run(cmd, cwd, f"Benchmark: {folder}")

    def shutdown(self):
        self.stop_current()


def _tooltip(widget, text):
    """Shows help text after hovering for half a second."""
    tip = {"win": None, "job": None}

    def show():
        x, y = widget.winfo_rootx() + 20, widget.winfo_rooty() + widget.winfo_height() + 2
        tip["win"] = w = tk.Toplevel(widget)
        w.wm_overrideredirect(True)
        w.wm_geometry(f"+{x}+{y}")
        tk.Label(w, text=text, background="#fffbe6", relief="solid", borderwidth=1, wraplength=360,
                 justify="left", padx=6, pady=3).pack()

    def enter(_):
        tip["job"] = widget.after(500, show)

    def leave(_):
        if tip["job"]:
            widget.after_cancel(tip["job"])
        if tip["win"]:
            tip["win"].destroy()
            tip["win"] = None

    widget.bind("<Enter>", enter)
    widget.bind("<Leave>", leave)
