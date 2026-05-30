"""RAI Audio Analyzer v2 — tkinter GUI.

IMPORT SAFETY: this module must be importable without tkinter (or tkinterdnd2,
or matplotlib) installed, because the packaging / CI environment may be headless.
Therefore ALL GUI-library imports live inside functions and are never executed at
module load time.  The producer runs this on their Mac where every dependency is
present; the headless verification environment only needs `import rai_analyzer.gui`
and `py_compile` to succeed.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers (pure Python, no GUI imports)
# ---------------------------------------------------------------------------

def _run_analysis(path: str):
    """Run the full analysis pipeline and return (AnalysisResult, Features).

    This is designed to be called from a worker thread.  It returns a 2-tuple
    so the GUI can plot the tempogram without a second load.
    """
    from rai_analyzer.config import DEFAULT_CONFIG
    from rai_analyzer.contracts import AnalysisResult
    from rai_analyzer.io_audio import load_audio
    from rai_analyzer.loudness import measure_loudness
    from rai_analyzer.resolver import resolve_tempo
    from rai_analyzer.tempogram import build_features

    signal = load_audio(path)
    feats = build_features(signal, DEFAULT_CONFIG)
    tempo = resolve_tempo(feats, DEFAULT_CONFIG)

    loudness = None
    try:
        loudness = measure_loudness(signal)
    except Exception:
        loudness = None

    result = AnalysisResult(
        path=path,
        duration=signal.duration,
        sr=signal.sr_native,
        channels=signal.channels,
        tempo=tempo,
        loudness=loudness,
    )
    return result, feats


# ---------------------------------------------------------------------------
# Main application class
# ---------------------------------------------------------------------------

class RAIApp:
    """The main application window.

    Instantiated by ``main()``.  Expects a root window (either a
    TkinterDnD.Tk or a plain tk.Tk) passed in so the constructor is
    testable / mockable.
    """

    WINDOW_TITLE = "RAI Audio Analyzer v2"
    WINDOW_SIZE = "920x660"

    # Colours
    COLOR_GREEN = "#1fa35c"
    COLOR_RED = "#d9534f"
    COLOR_BG_BANNER = "#1c1c1e"
    COLOR_FG_LIGHT = "#f2f2f7"
    COLOR_IDLE = "#3a3a3c"

    def __init__(self, root, has_dnd: bool):
        self._root = root
        self._has_dnd = has_dnd
        self._result = None       # last AnalysisResult
        self._feats = None        # last Features
        self._work_queue: queue.Queue = queue.Queue()

        self._build_ui()
        if has_dnd:
            self._register_dnd()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        import tkinter as tk
        from tkinter import ttk

        root = self._root
        root.title(self.WINDOW_TITLE)
        root.geometry(self.WINDOW_SIZE)
        root.minsize(640, 480)
        root.configure(bg=self.COLOR_BG_BANNER)

        # ---- drop zone / browse row ----
        drop_frame = tk.Frame(root, bg=self.COLOR_BG_BANNER)
        drop_frame.pack(fill=tk.X, padx=12, pady=(10, 4))

        self._drop_label = tk.Label(
            drop_frame,
            text="Drop a WAV file here" if self._has_dnd else "No drag-drop (tkinterdnd2 missing)",
            font=("Helvetica", 13),
            bg=self.COLOR_IDLE,
            fg=self.COLOR_FG_LIGHT,
            relief=tk.FLAT,
            padx=14,
            pady=10,
        )
        self._drop_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        browse_btn = tk.Button(
            drop_frame,
            text="Browse…",
            font=("Helvetica", 12),
            bg="#2c2c2e",
            fg=self.COLOR_FG_LIGHT,
            activebackground="#48484a",
            activeforeground=self.COLOR_FG_LIGHT,
            relief=tk.FLAT,
            padx=14,
            pady=10,
            cursor="hand2",
            command=self._on_browse,
        )
        browse_btn.pack(side=tk.LEFT, padx=(8, 0))

        # ---- status banner ----
        self._banner = tk.Label(
            root,
            text="",
            font=("Helvetica", 14, "bold"),
            bg=self.COLOR_BG_BANNER,
            fg=self.COLOR_FG_LIGHT,
            pady=6,
        )
        self._banner.pack(fill=tk.X, padx=12)

        # ---- notebook ----
        style = ttk.Style(root)
        # Use a base theme that is available cross-platform.
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook", background=self.COLOR_BG_BANNER)
        style.configure("TNotebook.Tab", font=("Helvetica", 11), padding=[10, 4])

        self._notebook = ttk.Notebook(root)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self._build_analysis_tab(tk)
        self._build_tempogram_tab(tk)

    def _build_analysis_tab(self, tk):
        """Build the "Analysis" tab with its monospaced text widget."""
        from tkinter import ttk

        frame = ttk.Frame(self._notebook)
        self._notebook.add(frame, text="Analysis")

        # Scrollbars
        v_scroll = tk.Scrollbar(frame, orient=tk.VERTICAL)
        h_scroll = tk.Scrollbar(frame, orient=tk.HORIZONTAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self._text = tk.Text(
            frame,
            font=("Courier", 12),
            wrap=tk.NONE,
            bg="#1c1c1e",
            fg="#e5e5ea",
            insertbackground="#e5e5ea",
            selectbackground="#3a3a3c",
            relief=tk.FLAT,
            state=tk.DISABLED,
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set,
        )
        self._text.pack(fill=tk.BOTH, expand=True)
        v_scroll.config(command=self._text.yview)
        h_scroll.config(command=self._text.xview)

    def _build_tempogram_tab(self, tk):
        """Build the "Tempogram" tab — matplotlib if available, else text fallback."""
        from tkinter import ttk

        frame = ttk.Frame(self._notebook)
        self._notebook.add(frame, text="Tempogram")

        # Try to set up matplotlib canvas.
        self._mpl_frame = frame
        self._mpl_canvas = None
        self._mpl_ax = None
        self._mpl_figure = None

        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            import matplotlib

            matplotlib.rcParams.update({
                "figure.facecolor": "#1c1c1e",
                "axes.facecolor": "#2c2c2e",
                "axes.edgecolor": "#636366",
                "axes.labelcolor": "#e5e5ea",
                "xtick.color": "#aeaeb2",
                "ytick.color": "#aeaeb2",
                "text.color": "#e5e5ea",
                "grid.color": "#3a3a3c",
                "grid.linestyle": "--",
                "grid.alpha": 0.6,
            })

            fig = Figure(figsize=(8, 3.6), dpi=100)
            self._mpl_figure = fig
            ax = fig.add_subplot(111)
            self._mpl_ax = ax
            ax.set_xlabel("BPM")
            ax.set_ylabel("Salience")
            ax.set_title("Tempogram (drop a file to analyse)")
            ax.grid(True)

            canvas = FigureCanvasTkAgg(fig, master=frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
            self._mpl_canvas = canvas

        except ImportError:
            # matplotlib unavailable — text fallback
            self._mpl_fallback = tk.Text(
                frame,
                font=("Courier", 11),
                wrap=tk.WORD,
                bg="#1c1c1e",
                fg="#e5e5ea",
                relief=tk.FLAT,
                state=tk.DISABLED,
            )
            self._mpl_fallback.pack(fill=tk.BOTH, expand=True)
            self._set_text_widget(
                self._mpl_fallback,
                "(matplotlib not installed — tempogram plot unavailable)\n"
                "Install it with:  pip install matplotlib",
            )
            self._mpl_fallback_widget = self._mpl_fallback

    # ------------------------------------------------------------------
    # Drag-and-drop registration
    # ------------------------------------------------------------------

    def _register_dnd(self):
        """Register the drop zone (only called when tkinterdnd2 is present)."""
        try:
            from tkinterdnd2 import DND_FILES
            self._drop_label.drop_target_register(DND_FILES)
            self._drop_label.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            # Safety valve: if DnD registration fails at runtime, degrade gracefully.
            pass

    def _on_drop(self, event):
        """Handle a file dropped onto the drop zone."""
        raw = event.data.strip()
        # tkinterdnd2 wraps paths with braces when there are spaces.
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        # Multiple files — take the first one.
        path = raw.split("} {")[0] if "} {" in raw else raw
        path = path.strip()
        if path:
            self._start_analysis(path)

    # ------------------------------------------------------------------
    # Browse button
    # ------------------------------------------------------------------

    def _on_browse(self):
        """Open a file dialog and start analysis on the chosen file."""
        import tkinter.filedialog as fd
        path = fd.askopenfilename(
            title="Open audio file",
            filetypes=[
                ("WAV files", "*.wav *.WAV"),
                ("Audio files", "*.wav *.WAV *.aiff *.aif *.flac *.mp3"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._start_analysis(path)

    # ------------------------------------------------------------------
    # Analysis pipeline (worker thread)
    # ------------------------------------------------------------------

    def _start_analysis(self, path: str):
        """Kick off analysis in a background thread; update UI immediately."""
        self._set_status("Analyzing…", color=self.COLOR_IDLE)
        self._set_report("Analyzing  " + os.path.basename(path) + "\n\nPlease wait…")
        if self._mpl_ax is not None:
            self._clear_plot("Analyzing…")

        t = threading.Thread(target=self._worker, args=(path,), daemon=True)
        t.start()
        self._root.after(50, self._poll_result)

    def _worker(self, path: str):
        """Background worker; puts (result, feats) or Exception into the queue."""
        try:
            result, feats = _run_analysis(path)
            self._work_queue.put((result, feats))
        except Exception as exc:
            self._work_queue.put(exc)

    def _poll_result(self):
        """Poll the result queue from the Tk event loop."""
        try:
            item = self._work_queue.get_nowait()
        except queue.Empty:
            self._root.after(100, self._poll_result)
            return

        if isinstance(item, Exception):
            self._on_error(item)
        else:
            result, feats = item
            self._on_result(result, feats)

    def _on_error(self, exc: Exception):
        """Display an error without crashing."""
        import tkinter.messagebox as mb
        self._set_status("Error", color=self.COLOR_RED)
        self._set_report(f"Analysis failed:\n\n{type(exc).__name__}: {exc}")
        mb.showerror("Analysis error", f"{type(exc).__name__}: {exc}")

    def _on_result(self, result, feats):
        """Populate both tabs after a successful analysis."""
        # ---- status banner ----
        if result.tempo.ambiguous:
            self._set_status(
                "⚠  AMBIGUOUS — human tiebreak", color=self.COLOR_RED
            )
        else:
            self._set_status("✓  reliable", color=self.COLOR_GREEN)

        # ---- Analysis tab ----
        self._set_report(result.to_report())

        # ---- Tempogram tab ----
        self._result = result
        self._feats = feats
        self._update_plot(result, feats)

    # ------------------------------------------------------------------
    # UI state helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = COLOR_BG_BANNER):
        self._banner.config(text=text, fg=self.COLOR_FG_LIGHT, bg=color)

    def _set_report(self, text: str):
        self._set_text_widget(self._text, text)

    @staticmethod
    def _set_text_widget(widget, text: str):
        import tkinter as tk
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text)
        widget.config(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Tempogram plotting
    # ------------------------------------------------------------------

    def _clear_plot(self, title: str = ""):
        if self._mpl_ax is None:
            return
        ax = self._mpl_ax
        ax.cla()
        ax.set_xlabel("BPM")
        ax.set_ylabel("Salience")
        ax.set_title(title)
        ax.grid(True)
        self._mpl_canvas.draw_idle()

    def _update_plot(self, result, feats):
        """Redraw the tempogram salience curve with candidate BPM markers."""
        if self._mpl_ax is None:
            # matplotlib unavailable — write a text summary to the fallback widget
            if hasattr(self, "_mpl_fallback_widget"):
                tc = feats.tempo_curve
                t = result.tempo
                lines = [
                    "(matplotlib not installed — text summary of tempogram peaks)\n",
                    f"Primary BPM  : {t.primary_bpm:.2f}",
                ]
                if t.felt_bpm is not None:
                    lines.append(f"Felt BPM     : {t.felt_bpm:.2f}")
                lines.append("\nCandidates:")
                for c in t.candidates:
                    lines.append(
                        f"  {c.bpm:7.2f}  sal={c.salience:.3f}  {c.relationship.value}"
                    )
                self._set_text_widget(
                    self._mpl_fallback_widget, "\n".join(lines)
                )
            return

        ax = self._mpl_ax
        ax.cla()

        tc = feats.tempo_curve
        ax.plot(tc.bpms, tc.salience, color="#30d158", linewidth=1.5, label="product salience")
        ax.fill_between(tc.bpms, tc.salience, alpha=0.15, color="#30d158")

        t = result.tempo

        # Primary BPM — solid line
        ax.axvline(
            t.primary_bpm,
            color="#ff9f0a",
            linewidth=2.0,
            linestyle="-",
            label=f"primary {t.primary_bpm:.2f}",
        )

        # Felt BPM — dashed line (only if different from primary)
        if t.felt_bpm is not None and abs(t.felt_bpm - t.primary_bpm) > 0.5:
            ax.axvline(
                t.felt_bpm,
                color="#64d2ff",
                linewidth=1.6,
                linestyle="--",
                label=f"felt {t.felt_bpm:.2f}",
            )

        # Other candidates — lighter dotted lines, labelled with relationship
        for c in t.candidates:
            if abs(c.bpm - t.primary_bpm) < 0.5:
                continue  # skip primary (already drawn)
            if t.felt_bpm is not None and abs(c.bpm - t.felt_bpm) < 0.5:
                continue  # skip felt (already drawn)
            ax.axvline(
                c.bpm,
                color="#8e8e93",
                linewidth=1.0,
                linestyle=":",
                alpha=0.75,
                label=f"{c.bpm:.1f} ({c.relationship.value})",
            )

        ax.set_xlabel("BPM")
        ax.set_ylabel("Salience")
        fname = os.path.basename(result.path)
        ax.set_title(f"Tempogram — {fname}")
        ax.grid(True)

        # Legend: put it outside the axes if there are many candidates
        n_lines = 1 + (1 if t.felt_bpm is not None else 0) + len(t.candidates)
        if n_lines <= 6:
            ax.legend(loc="upper right", fontsize=8)
        else:
            ax.legend(
                loc="upper left",
                bbox_to_anchor=(1.01, 1),
                borderaxespad=0,
                fontsize=7,
            )

        self._mpl_canvas.draw_idle()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Launch the RAI Audio Analyzer v2 GUI.

    Tries tkinterdnd2 for drag-and-drop first; falls back to plain tk.Tk
    with a Browse button if tkinterdnd2 is not installed.
    """
    has_dnd = False
    root = None

    try:
        from tkinterdnd2 import TkinterDnD
        root = TkinterDnD.Tk()
        has_dnd = True
    except Exception:
        pass  # drag-drop unavailable; file picker still works

    if root is None:
        import tkinter as tk
        root = tk.Tk()

    app = RAIApp(root, has_dnd=has_dnd)  # noqa: F841
    root.mainloop()


if __name__ == "__main__":
    main()
