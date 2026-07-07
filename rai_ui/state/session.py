"""Session state for the RAI v3 shell.

One SessionState instance lives on the MainWindow and is the single place the
rest of the UI looks for "what happened last". The worker never touches
widgets directly: MainWindow feeds completions in here, and every widget that
cares (report pane, header chip, status bar) subscribes to the signals. That
one-way flow is what keeps the shell testable — tests can drive the whole UI
by calling ``begin`` / ``finish`` / ``fail`` with fake payloads.

Signal contract (shared interface — other agents rely on these exact names):

* ``result_ready(object)``  — emits ``rai_analyzer.contracts.AnalysisResult``
* ``analysis_failed(str)``  — plain-language failure message
* ``working(bool)``         — True while an analysis is in flight
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal


class SessionState(QObject):
    """Holds the last analysis and broadcasts lifecycle changes."""

    result_ready = Signal(object)  # AnalysisResult
    analysis_failed = Signal(str)
    working = Signal(bool)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.path: Optional[str] = None
        self.last_result = None  # AnalysisResult | None
        self.last_features = None  # Features | None
        self.last_signal_obj = None  # AudioSignal | None
        self.analysis_seconds: Optional[float] = None

    def begin(self, path: str) -> None:
        """An analysis of ``path`` just started."""
        self.path = path
        self.working.emit(True)

    def finish(self, result, features, signal_obj, seconds: Optional[float]) -> None:
        """Store a completed analysis and notify subscribers.

        ``result_ready`` fires before ``working(False)`` so listeners that
        re-render on the working flag (the status bar) already see the fresh
        data when they redraw.
        """
        self.last_result = result
        self.last_features = features
        self.last_signal_obj = signal_obj
        self.analysis_seconds = float(seconds) if seconds is not None else None
        self.result_ready.emit(result)
        self.working.emit(False)

    def fail(self, message: str) -> None:
        """An analysis failed; previous results are kept untouched."""
        self.working.emit(False)
        self.analysis_failed.emit(message)
