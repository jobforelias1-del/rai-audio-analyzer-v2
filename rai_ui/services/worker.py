"""Background analysis worker for the RAI v3 shell.

Runs the exact analysis composition the proven v2 pipeline uses (see
``rai_analyzer/gui.py:_run_analysis`` and ``rai_analyzer/analyzer.py``) but
Qt-native: an ``AnalysisWorker`` is moved to a ``QThread`` by the caller and
reports back over signals, so the UI thread never blocks on librosa.

Nothing is imported from ``rai_analyzer.gui`` — that module is the legacy
tkinter shell; only its call *semantics* are replicated here. Engine imports
happen inside ``run`` so importing this module stays cheap and so a broken
optional dependency (e.g. loudness) surfaces per-analysis, not at import.

The worker itself is stateless and reusable, but the shell treats analyses as
one-at-a-time: MainWindow owns a generation counter and drops stale
completions, so a worker never needs cancellation support in M0.
"""

from __future__ import annotations

import time
import traceback

from PySide6.QtCore import QObject, Signal, Slot


class AnalysisWorker(QObject):
    """Analyze one file off the UI thread and emit the outcome.

    Signals:

    * ``finished(result, features, signal_obj, seconds)`` — the
      ``AnalysisResult``, the ``Features`` (so plot panes never re-load the
      file), the ``AudioSignal``, and the wall-clock analysis time in seconds
      (pure pipeline time, measured inside the worker).
    * ``failed(message)`` — the last line of the traceback, suitable for a
      toast; never raises across the thread boundary.
    """

    finished = Signal(object, object, object, float)
    failed = Signal(str)

    @Slot(str)
    def run(self, path: str) -> None:
        t0 = time.perf_counter()
        try:
            from rai_analyzer.config import DEFAULT_CONFIG
            from rai_analyzer.contracts import AnalysisResult
            from rai_analyzer.io_audio import load_audio
            from rai_analyzer.resolver import resolve_tempo
            from rai_analyzer.tempogram import build_features

            signal = load_audio(path)
            features = build_features(signal, DEFAULT_CONFIG)
            tempo = resolve_tempo(features, DEFAULT_CONFIG)

            # Loudness is a nicety; never let it sink the tempo verdict
            # (same best-effort contract as analyzer.py).
            loudness = None
            try:
                from rai_analyzer.loudness import measure_loudness

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
        except Exception as exc:
            last_line = traceback.format_exception_only(type(exc), exc)[-1].strip()
            self.failed.emit(last_line)
            return
        self.finished.emit(result, features, signal, time.perf_counter() - t0)
