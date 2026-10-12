"""
Signyales — Results Visualizer
==================================
A local GUI for turning accuracy_logger.py and performance_logger.py
output into something readable, instead of staring at raw CSVs.

Specifically built to support aggregating across MULTIPLE sessions —
the Field Testing Procedure explicitly calls for combining every
participant's accuracy CSVs into a single Recognition Accuracy Matrix
for Chapter IV, and nothing before this tool actually did that
aggregation; each session's matrix.png was a separate, standalone image.

Run it:
    python tools/results_visualizer.py          (from the repo root)

Uses matplotlib (already a project dependency via the training pipeline)
embedded directly in the window — no separate plot windows popping up.
"""

import csv
import json
import tkinter as tk
from collections import defaultdict
from pathlib import Path
from tkinter import filedialog, ttk

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

NO_RESPONSE = "no_response"


# ------------------------------------------------------------------
# Accuracy aggregation (reads the RAW per-trial CSVs accuracy_logger.py
# produces — not the matrix.csv files — so stats are recomputed fresh
# from pooled trials rather than trying to merge pre-aggregated tables)
# ------------------------------------------------------------------

def load_accuracy_csvs(paths):
    rows = []
    for p in paths:
        with open(p, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["_source_file"] = Path(p).name
                rows.append(row)
    return rows


def aggregate_accuracy(rows):
    labels = sorted({r["expected"] for r in rows})
    matrix_labels = labels + [NO_RESPONSE]
    matrix = {lbl: {m: 0 for m in matrix_labels} for lbl in labels}

    correct = 0
    latencies = []
    per_label_total = defaultdict(int)
    per_label_correct = defaultdict(int)

    for r in rows:
        expected = r["expected"]
        predicted = r["predicted"] if r["predicted"] in matrix_labels else NO_RESPONSE
        matrix[expected][predicted] += 1
        per_label_total[expected] += 1
        is_correct = r.get("correct", "").strip().lower() in ("true", "1")
        if is_correct:
            correct += 1
            per_label_correct[expected] += 1
        if predicted != NO_RESPONSE:
            try:
                latencies.append(float(r["latency_s"]))
            except (ValueError, KeyError):
                pass

    total = len(rows)
    overall_accuracy = (correct / total * 100) if total else 0.0
    per_label_accuracy = {
        lbl: (per_label_correct[lbl] / per_label_total[lbl] * 100) if per_label_total[lbl] else 0.0
        for lbl in labels
    }
    mean_latency = sum(latencies) / len(latencies) if latencies else None
    std_latency = (
        (sum((v - mean_latency) ** 2 for v in latencies) / len(latencies)) ** 0.5
        if latencies else None
    )

    return {
        "labels": labels,
        "matrix_labels": matrix_labels,
        "matrix": matrix,
        "total_trials": total,
        "overall_accuracy": overall_accuracy,
        "per_label_accuracy": per_label_accuracy,
        "mean_latency": mean_latency,
        "std_latency": std_latency,
        "num_sessions": len({r["_source_file"] for r in rows}),
    }


# ------------------------------------------------------------------
# Performance aggregation (reads the *_summary.json files
# performance_logger.py now produces)
# ------------------------------------------------------------------

def load_performance_summaries(paths):
    summaries = []
    for p in paths:
        with open(p) as f:
            data = json.load(f)
        data["_source_file"] = Path(p).name
        summaries.append(data)
    return summaries


# ------------------------------------------------------------------
# GUI
# ------------------------------------------------------------------

class VisualizerApp:
    def __init__(self, root):
        self.root = root
        root.title("Signyales Results Visualizer")
        root.geometry("900x700")

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self.accuracy_tab = tk.Frame(notebook)
        self.performance_tab = tk.Frame(notebook)
        notebook.add(self.accuracy_tab, text="Accuracy Results")
        notebook.add(self.performance_tab, text="Performance Results")

        self._build_accuracy_tab()
        self._build_performance_tab()

    # ---------------- Accuracy tab ----------------

    def _build_accuracy_tab(self):
        frame = self.accuracy_tab

        top = tk.Frame(frame)
        top.pack(fill="x", pady=8)
        tk.Button(top, text="Load Accuracy CSV(s)...", command=self.load_accuracy).pack(side="left", padx=8)
        self.accuracy_file_label = tk.Label(top, text="No files loaded", fg="#666666")
        self.accuracy_file_label.pack(side="left")

        body = tk.Frame(frame)
        body.pack(fill="both", expand=True)

        self.accuracy_fig = plt.Figure(figsize=(5, 4.5), dpi=100)
        self.accuracy_ax = self.accuracy_fig.add_subplot(111)
        self.accuracy_canvas = FigureCanvasTkAgg(self.accuracy_fig, master=body)
        self.accuracy_canvas.get_tk_widget().pack(side="left", fill="both", expand=True, padx=8)

        self.accuracy_text = tk.Text(body, width=40, font=("Consolas", 9))
        self.accuracy_text.pack(side="right", fill="y", padx=8)

        self._draw_empty_matrix("Load one or more accuracy CSVs to see the combined matrix")

    def _draw_empty_matrix(self, message):
        self.accuracy_ax.clear()
        self.accuracy_ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True, fontsize=10)
        self.accuracy_ax.axis("off")
        self.accuracy_canvas.draw()

    def load_accuracy(self):
        paths = filedialog.askopenfilenames(
            title="Select one or more accuracy_logger.py CSV files (the raw trial CSVs, not *_matrix.csv)",
            filetypes=[("CSV files", "*.csv")],
        )
        if not paths:
            return
        try:
            rows = load_accuracy_csvs(paths)
            if not rows:
                self._draw_empty_matrix("Selected file(s) contained no rows")
                return
            result = aggregate_accuracy(rows)
        except Exception as e:
            self._draw_empty_matrix(f"Could not parse file(s):\n{e}")
            return

        self.accuracy_file_label.config(text=f"{len(paths)} file(s), {result['total_trials']} trials")
        self._render_accuracy(result)

    def _render_accuracy(self, result):
        labels = result["labels"]
        matrix_labels = result["matrix_labels"]
        matrix = result["matrix"]

        import numpy as np
        data = np.array([[matrix[lbl][m] for m in matrix_labels] for lbl in labels])

        self.accuracy_ax.clear()
        im = self.accuracy_ax.imshow(data, cmap="Blues")
        self.accuracy_ax.set_xticks(range(len(matrix_labels)))
        self.accuracy_ax.set_yticks(range(len(labels)))
        self.accuracy_ax.set_xticklabels(matrix_labels, rotation=45, ha="right", fontsize=8)
        self.accuracy_ax.set_yticklabels(labels, fontsize=8)
        self.accuracy_ax.set_xlabel("Predicted", fontsize=9)
        self.accuracy_ax.set_ylabel("Actual", fontsize=9)
        self.accuracy_ax.set_title(f"Combined Recognition Accuracy Matrix\n({result['num_sessions']} session file(s))", fontsize=10)
        vmax = data.max() if data.size else 1
        for i in range(len(labels)):
            for j in range(len(matrix_labels)):
                val = data[i, j]
                self.accuracy_ax.text(j, i, str(val), ha="center", va="center", fontsize=8,
                                       color="white" if val > vmax / 2 else "black")
        self.accuracy_fig.tight_layout()
        self.accuracy_canvas.draw()

        lines = [
            f"Sessions combined: {result['num_sessions']}",
            f"Total trials: {result['total_trials']}",
            f"Overall accuracy: {result['overall_accuracy']:.1f}%",
            "",
            "Per-gesture accuracy:",
        ]
        for lbl in labels:
            lines.append(f"  {lbl}: {result['per_label_accuracy'][lbl]:.1f}%")
        lines.append("")
        if result["mean_latency"] is not None:
            lines.append(f"Latency mean: {result['mean_latency']:.2f}s")
            lines.append(f"Latency std:  {result['std_latency']:.2f}s")
        else:
            lines.append("No successful trials to compute latency from.")

        self.accuracy_text.delete("1.0", "end")
        self.accuracy_text.insert("1.0", "\n".join(lines))

    # ---------------- Performance tab ----------------

    def _build_performance_tab(self):
        frame = self.performance_tab

        top = tk.Frame(frame)
        top.pack(fill="x", pady=8)
        tk.Button(top, text="Load Performance Summary JSON(s)...",
                  command=self.load_performance).pack(side="left", padx=8)

        columns = ("session", "duration_s", "left_pct", "right_pct", "both_pct", "gestures", "lat_mean", "lat_std")
        self.perf_tree = ttk.Treeview(frame, columns=columns, show="headings", height=10)
        headers = {
            "session": "Session File", "duration_s": "Duration (s)",
            "left_pct": "Left %", "right_pct": "Right %", "both_pct": "Both %",
            "gestures": "Gestures", "lat_mean": "Lat. mean (s)", "lat_std": "Lat. std (s)",
        }
        for col in columns:
            self.perf_tree.heading(col, text=headers[col])
            self.perf_tree.column(col, width=100, anchor="center")
        self.perf_tree.pack(fill="x", padx=8, pady=8)

        self.perf_summary_label = tk.Label(frame, text="", font=("Consolas", 10), justify="left", anchor="w")
        self.perf_summary_label.pack(fill="x", padx=8, pady=8)

    def load_performance(self):
        paths = filedialog.askopenfilenames(
            title="Select one or more performance_logger.py *_summary.json files",
            filetypes=[("JSON files", "*.json")],
        )
        if not paths:
            return
        try:
            summaries = load_performance_summaries(paths)
        except Exception as e:
            self.perf_summary_label.config(text=f"Could not parse file(s): {e}")
            return

        for row in self.perf_tree.get_children():
            self.perf_tree.delete(row)

        left_ratios, right_ratios, both_ratios = [], [], []
        total_gestures = 0

        for s in summaries:
            self.perf_tree.insert("", "end", values=(
                s.get("_source_file", ""),
                s.get("session_duration_s", ""),
                s.get("left_delivery_ratio_pct", ""),
                s.get("right_delivery_ratio_pct", ""),
                s.get("both_hands_fresh_ratio_pct", ""),
                s.get("gestures_recognized", ""),
                s.get("latency_mean_s", ""),
                s.get("latency_std_s", ""),
            ))
            if s.get("left_delivery_ratio_pct") is not None:
                left_ratios.append(s["left_delivery_ratio_pct"])
            if s.get("right_delivery_ratio_pct") is not None:
                right_ratios.append(s["right_delivery_ratio_pct"])
            if s.get("both_hands_fresh_ratio_pct") is not None:
                both_ratios.append(s["both_hands_fresh_ratio_pct"])
            total_gestures += s.get("gestures_recognized", 0) or 0

        def avg(vals):
            return sum(vals) / len(vals) if vals else None

        lines = [f"Sessions loaded: {len(summaries)}", f"Total gestures recognized across all sessions: {total_gestures}"]
        if left_ratios:
            lines.append(f"Average left delivery ratio:  {avg(left_ratios):.1f}%")
            lines.append(f"Average right delivery ratio: {avg(right_ratios):.1f}%")
            lines.append(f"Average both-hands-fresh:     {avg(both_ratios):.1f}%")
        self.perf_summary_label.config(text="\n".join(lines))


if __name__ == "__main__":
    root = tk.Tk()
    app = VisualizerApp(root)
    root.mainloop()
