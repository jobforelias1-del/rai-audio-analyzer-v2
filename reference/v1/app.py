"""Tkinter UI for the RAI Audio Analyzer."""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from analyzer import (
    load_wav,
    load_wav_full,
    compute_peak_dbfs,
    compute_rms_dbfs,
    estimate_bpm,
    compute_lufs_approx,
    compute_dynamic_range,
    compute_spectrum,
    compute_band_energies,
    compute_stereo_width,
    analyze_track,
    compare_tracks,
)

# Frequency bands for the low-end energy analysis (v2).
_LOW_BANDS = [
    ("Sub", 20.0, 60.0),
    ("Bass", 60.0, 120.0),
]

# Display order for the compare-mode metric grid (v3).
# (key on TrackMetrics, label, formatter)
_COMPARE_ROWS = [
    ("file_name",     "File name",    lambda v: str(v)),
    ("duration",      "Duration",     lambda v: f"{v:.2f} s"),
    ("sample_rate",   "Sample rate",  lambda v: f"{v} Hz"),
    ("channels",      "Channels",     lambda v: str(v)),
    ("bpm",           "BPM",          lambda v: f"{v:.1f}"),
    ("peak_db",       "Peak",         lambda v: f"{v:.2f} dBFS" if v != float('-inf') else "-inf"),
    ("rms_db",        "RMS",          lambda v: f"{v:.2f} dBFS" if v != float('-inf') else "-inf"),
    ("lufs",          "LUFS",         lambda v: f"{v:.1f}"      if v != float('-inf') else "-inf"),
    ("dynamic_range", "DR",           lambda v: f"{v:.1f} dB"),
    ("sub_pct",       "Sub Energy",   lambda v: f"{v:.1f}%"),
    ("bass_pct",      "Bass Energy",  lambda v: f"{v:.1f}%"),
    ("stereo_width",  "Stereo Width", lambda v: str(v)),
]

# Optional drag-and-drop. Falls back to Browse button if tkinterdnd2 is missing.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


class AudioAnalyzerApp:
    def __init__(self):
        if DND_AVAILABLE:
            self.root = TkinterDnD.Tk()
        else:
            self.root = tk.Tk()

        self.root.title("RAI Audio Analyzer v2")
        self.root.geometry("1000x980")

        self.current_path = None
        self.samples = None
        self.sample_rate = None
        self.duration = None
        self.raw_channels = None  # v2: raw multichannel data for stereo width

        # v3: compare-mode state
        self.metrics_a = None
        self.metrics_b = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True)

        single_tab = ttk.Frame(notebook)
        notebook.add(single_tab, text="Single Track")

        compare_tab = ttk.Frame(notebook)
        notebook.add(compare_tab, text="Compare")

        # === Single Track tab (v1 + v2 UI; behavior unchanged) ===
        top = ttk.Frame(single_tab, padding=10)
        top.pack(fill=tk.X)

        drop_text = (
            "Drag and drop a WAV file here"
            if DND_AVAILABLE
            else "Drag-and-drop unavailable — click Browse below"
        )
        self.drop_zone = tk.Label(
            top,
            text=drop_text,
            relief="ridge",
            bd=2,
            height=4,
            bg="#eef2f7",
            fg="#333",
            font=("Helvetica", 13),
        )
        self.drop_zone.pack(fill=tk.X, padx=5, pady=5)

        if DND_AVAILABLE:
            self.drop_zone.drop_target_register(DND_FILES)
            self.drop_zone.dnd_bind("<<Drop>>", self._on_drop)

        button_row = ttk.Frame(top)
        button_row.pack(fill=tk.X, padx=5)
        ttk.Button(button_row, text="Browse...", command=self._browse).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Analyze", command=self._analyze).pack(side=tk.LEFT, padx=6)

        self.info_label = ttk.Label(top, text="No file loaded", anchor="w")
        self.info_label.pack(fill=tk.X, padx=5, pady=(8, 0))

        # Metrics panel.
        metrics = ttk.LabelFrame(single_tab, text="Metrics", padding=10)
        metrics.pack(fill=tk.X, padx=10, pady=8)

        self.bpm_label = ttk.Label(metrics, text="BPM: -", font=("Helvetica", 12))
        self.bpm_label.pack(side=tk.LEFT, padx=15)

        self.peak_label = ttk.Label(metrics, text="Peak: -", font=("Helvetica", 12))
        self.peak_label.pack(side=tk.LEFT, padx=15)

        self.rms_label = ttk.Label(metrics, text="RMS: -", font=("Helvetica", 12))
        self.rms_label.pack(side=tk.LEFT, padx=15)

        # ----- v2: Advanced metrics panel ------------------------------------
        advanced = ttk.LabelFrame(single_tab, text="Advanced Metrics", padding=10)
        advanced.pack(fill=tk.X, padx=10, pady=(0, 8))

        self.lufs_label = ttk.Label(advanced, text="LUFS: -", font=("Helvetica", 12))
        self.lufs_label.pack(side=tk.LEFT, padx=12)

        self.dr_label = ttk.Label(advanced, text="DR: -", font=("Helvetica", 12))
        self.dr_label.pack(side=tk.LEFT, padx=12)

        self.sub_label = ttk.Label(advanced, text="Sub Energy: -", font=("Helvetica", 12))
        self.sub_label.pack(side=tk.LEFT, padx=12)

        self.bass_label = ttk.Label(advanced, text="Bass Energy: -", font=("Helvetica", 12))
        self.bass_label.pack(side=tk.LEFT, padx=12)

        self.width_label = ttk.Label(advanced, text="Stereo Width: -", font=("Helvetica", 12))
        self.width_label.pack(side=tk.LEFT, padx=12)

        # Waveform plot.
        plot_frame = ttk.LabelFrame(single_tab, text="Waveform", padding=6)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        self.fig = Figure(figsize=(8, 2.6), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Amplitude")
        self.ax.grid(True, alpha=0.3)
        self.fig.tight_layout()

        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ----- v2: Spectrum plot ---------------------------------------------
        spectrum_frame = ttk.LabelFrame(single_tab, text="Frequency Spectrum", padding=6)
        spectrum_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.spec_fig = Figure(figsize=(8, 2.6), dpi=100)
        self.spec_ax = self.spec_fig.add_subplot(111)
        self.spec_ax.set_xlabel("Frequency (Hz)")
        self.spec_ax.set_ylabel("Magnitude (dB)")
        self.spec_ax.set_xscale("log")
        self.spec_ax.set_xlim(20.0, 20000.0)
        self.spec_ax.grid(True, which="both", alpha=0.3)
        self.spec_fig.tight_layout()

        self.spec_canvas = FigureCanvasTkAgg(self.spec_fig, master=spectrum_frame)
        self.spec_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # === Compare tab (v3) ===
        self._build_compare_tab(compare_tab)

    # -------------------------------------------------------------- Events
    def _on_drop(self, event):
        # tkinterdnd2 returns a Tcl list; splitlist handles paths with spaces.
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data.strip("{}")]

        if not paths:
            return
        path = paths[0]
        if not path.lower().endswith(".wav"):
            messagebox.showerror("Unsupported file", "Please drop a .wav file.")
            return
        self._load(path)
        self._analyze()

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select a WAV file",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if path:
            self._load(path)
            self._analyze()

    # --------------------------------------------------------- Load/Analyze
    def _load(self, path):
        try:
            (
                self.samples,
                self.sample_rate,
                self.duration,
                self.raw_channels,
            ) = load_wav_full(path)
            self.current_path = path
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not read WAV file:\n{exc}")
            return

        name = os.path.basename(path)
        n_ch = (
            self.raw_channels.shape[1]
            if self.raw_channels is not None and self.raw_channels.ndim > 1
            else 1
        )
        self.info_label.config(
            text=(
                f"File: {name}    "
                f"Duration: {self.duration:.2f} s    "
                f"Sample Rate: {self.sample_rate} Hz    "
                f"Channels: {n_ch}"
            )
        )
        self.drop_zone.config(text=f"Loaded: {name}")

    def _analyze(self):
        if self.samples is None:
            messagebox.showinfo("No file", "Load a WAV file first.")
            return

        # v1 metrics (unchanged behavior).
        peak = compute_peak_dbfs(self.samples)
        rms = compute_rms_dbfs(self.samples)
        bpm = estimate_bpm(self.samples, self.sample_rate)

        self.peak_label.config(text=f"Peak: {peak:.2f} dBFS")
        self.rms_label.config(text=f"RMS: {rms:.2f} dBFS")
        self.bpm_label.config(text=f"BPM: {bpm:.1f}")

        # v2 metrics.
        lufs = compute_lufs_approx(self.samples, self.sample_rate)
        dr = compute_dynamic_range(peak, rms)
        bands = compute_band_energies(self.samples, self.sample_rate, _LOW_BANDS)
        width = compute_stereo_width(self.raw_channels)

        lufs_text = f"{lufs:.1f}" if np.isfinite(lufs) else "-inf"
        self.lufs_label.config(text=f"LUFS: {lufs_text}")
        self.dr_label.config(text=f"DR: {dr:.1f} dB")
        self.sub_label.config(text=f"Sub Energy: {bands.get('Sub', 0.0):.1f}%")
        self.bass_label.config(text=f"Bass Energy: {bands.get('Bass', 0.0):.1f}%")
        self.width_label.config(text=f"Stereo Width: {width}")

        self._draw_waveform()
        self._draw_spectrum()

    def _draw_waveform(self):
        self.ax.clear()
        n = len(self.samples)
        time_axis = np.linspace(0.0, n / self.sample_rate, n)

        # Decimate for display so plotting stays snappy on long files.
        max_points = 8000
        if n > max_points:
            step = n // max_points
            self.ax.plot(time_axis[::step], self.samples[::step], linewidth=0.6, color="#1f77b4")
        else:
            self.ax.plot(time_axis, self.samples, linewidth=0.6, color="#1f77b4")

        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Amplitude")
        self.ax.set_xlim(0, n / self.sample_rate)
        self.ax.set_ylim(-1.05, 1.05)
        self.ax.grid(True, alpha=0.3)
        self.fig.tight_layout()
        self.canvas.draw()

    def _draw_spectrum(self):
        freqs, db = compute_spectrum(self.samples, self.sample_rate)
        self.spec_ax.clear()

        if freqs.size > 0:
            self.spec_ax.semilogx(freqs, db, linewidth=0.8, color="#d62728")
            # Pin Y range to a sensible window relative to the loudest bin.
            top = float(np.max(db))
            self.spec_ax.set_ylim(top - 80.0, top + 5.0)

        self.spec_ax.set_xscale("log")
        self.spec_ax.set_xlim(20.0, 20000.0)
        self.spec_ax.set_xlabel("Frequency (Hz)")
        self.spec_ax.set_ylabel("Magnitude (dB)")
        self.spec_ax.grid(True, which="both", alpha=0.3)
        self.spec_fig.tight_layout()
        self.spec_canvas.draw()

    # ------------------------------------------------------------- Compare
    def _build_compare_tab(self, parent):
        """v3: side-by-side TrackMetrics view + delta panel from compare_tracks."""
        button_row = ttk.Frame(parent, padding=10)
        button_row.pack(fill=tk.X)
        ttk.Button(
            button_row, text="Load Track A...", command=self._load_track_a
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            button_row, text="Load Track B...", command=self._load_track_b
        ).pack(side=tk.LEFT, padx=4)

        grid_frame = ttk.LabelFrame(parent, text="Metrics", padding=10)
        grid_frame.pack(fill=tk.X, padx=10, pady=(0, 8))

        header_font = ("Helvetica", 11, "bold")
        ttk.Label(grid_frame, text="Metric", font=header_font, width=14, anchor="w").grid(
            row=0, column=0, sticky="w", padx=4, pady=2
        )
        ttk.Label(grid_frame, text="Track A", font=header_font, width=24, anchor="w").grid(
            row=0, column=1, sticky="w", padx=4, pady=2
        )
        ttk.Label(grid_frame, text="Track B", font=header_font, width=24, anchor="w").grid(
            row=0, column=2, sticky="w", padx=4, pady=2
        )

        self.compare_a_labels = {}
        self.compare_b_labels = {}
        for i, (key, label_text, _) in enumerate(_COMPARE_ROWS, start=1):
            ttk.Label(grid_frame, text=label_text, anchor="w").grid(
                row=i, column=0, sticky="w", padx=4, pady=1
            )
            a_label = ttk.Label(grid_frame, text="-", anchor="w")
            a_label.grid(row=i, column=1, sticky="w", padx=4, pady=1)
            b_label = ttk.Label(grid_frame, text="-", anchor="w")
            b_label.grid(row=i, column=2, sticky="w", padx=4, pady=1)
            self.compare_a_labels[key] = a_label
            self.compare_b_labels[key] = b_label

        diff_frame = ttk.LabelFrame(parent, text="Differences", padding=10)
        diff_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.compare_diff_text = tk.Text(
            diff_frame,
            height=10,
            wrap="word",
            state="disabled",
            font=("Helvetica", 13),
            bg="#12182e",
            fg="#ffffff",
            insertbackground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        self.compare_diff_text.pack(fill=tk.BOTH, expand=True)
        self._refresh_compare_grid()

    def _load_track_a(self):
        path = filedialog.askopenfilename(
            title="Select Track A WAV",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.metrics_a = analyze_track(path)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not analyze WAV:\n{exc}")
            return
        self._refresh_compare_grid()

    def _load_track_b(self):
        path = filedialog.askopenfilename(
            title="Select Track B WAV",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.metrics_b = analyze_track(path)
        except Exception as exc:
            messagebox.showerror("Load failed", f"Could not analyze WAV:\n{exc}")
            return
        self._refresh_compare_grid()

    def _refresh_compare_grid(self):
        """Repopulate Track A/B columns and the diff panel from current state."""
        for key, _, fmt in _COMPARE_ROWS:
            if self.metrics_a is not None:
                self.compare_a_labels[key].config(text=fmt(getattr(self.metrics_a, key)))
            if self.metrics_b is not None:
                self.compare_b_labels[key].config(text=fmt(getattr(self.metrics_b, key)))

        self.compare_diff_text.config(state="normal")
        self.compare_diff_text.delete("1.0", tk.END)
        if self.metrics_a is not None and self.metrics_b is not None:
            for line in compare_tracks(self.metrics_a, self.metrics_b):
                self.compare_diff_text.insert(tk.END, line + "\n")
        else:
            self.compare_diff_text.insert(tk.END, "Load both tracks to see differences.\n")
        self.compare_diff_text.config(state="disabled")

    # ---------------------------------------------------------------- Run
    def run(self):
        self.root.mainloop()
