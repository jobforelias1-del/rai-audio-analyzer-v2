"""Session state for the RAI v3 shell.

One SessionState instance lives on the MainWindow and is the single place the
rest of the UI looks for "what happened last". The worker never touches
widgets directly: MainWindow feeds completions in here, and every widget that
cares (report pane, header chip, status bar, tempo section) subscribes to the
signals. That one-way flow is what keeps the shell testable — tests can drive
the whole UI by calling ``begin`` / ``finish`` / ``fail`` with fake payloads.

The session also owns the app's single ``VerdictState`` (M1): every lifecycle
call feeds the corresponding event through the pure reducer in
``rai_ui.state.verdict`` and broadcasts the new state. The reducer stays the
one source of truth for verdict semantics (incl. its stale-completion guard);
this class never inspects or branches on verdict kinds itself.

Signal contract (shared interface — other agents rely on these exact names):

* ``result_ready(object)``   — emits ``rai_analyzer.contracts.AnalysisResult``
* ``analysis_failed(str)``   — plain-language failure message
* ``working(bool)``          — True while an analysis is in flight
* ``verdict_changed(object)``— emits ``rai_ui.state.verdict.VerdictState``
  after every reduction (begin/finish/fail), even when the reducer returned
  the state unchanged — subscribers re-render idempotently, and "did anything
  change" is the reducer's business, not the wiring's.

Ordering contract inside ``finish`` (widgets rely on it): stored fields
(``last_result``/``last_features``/``last_signal_obj``/``analysis_seconds``)
are set FIRST, then the verdict reduces and ``verdict_changed`` fires, then
``result_ready``, then ``working(False)`` — so a ``result_ready`` subscriber
already sees both the fresh payload and the fresh verdict.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from rai_ui.state import verdict


class SessionState(QObject):
    """Holds the last analysis + verdict and broadcasts lifecycle changes."""

    result_ready = Signal(object)  # AnalysisResult
    analysis_failed = Signal(str)
    working = Signal(bool)
    verdict_changed = Signal(object)  # VerdictState

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.path: Optional[str] = None
        self.last_result = None  # AnalysisResult | None
        self.last_features = None  # Features | None
        self.last_signal_obj = None  # AudioSignal | None
        self.analysis_seconds: Optional[float] = None
        self.verdict_state: verdict.VerdictState = verdict.INITIAL

    def _reduce(self, event: verdict.Event) -> None:
        """Feed one event through the pure reducer and broadcast the result."""
        self.verdict_state = verdict.reduce(self.verdict_state, event)
        self.verdict_changed.emit(self.verdict_state)

    def begin(self, path: str) -> None:
        """An analysis of ``path`` just started."""
        self.path = path
        self._reduce(verdict.OpenFile(path=path))
        self.working.emit(True)

    def finish(self, result, features, signal_obj, seconds: Optional[float]) -> None:
        """Store a completed analysis and notify subscribers.

        The verdict reduces after the payload fields are stored and before
        ``result_ready`` fires (see the module docstring's ordering contract);
        ``result_ready`` still fires before ``working(False)`` so listeners
        that re-render on the working flag (the status bar) already see the
        fresh data when they redraw.
        """
        self.last_result = result
        self.last_features = features
        self.last_signal_obj = signal_obj
        self.analysis_seconds = float(seconds) if seconds is not None else None
        tempo = result.tempo
        self._reduce(
            verdict.AnalysisOk(
                ambiguous=tempo.ambiguous,
                # The resolver's no-tempo shape: empty candidates, primary 0.0.
                has_tempo=bool(tempo.candidates) and tempo.primary_bpm > 0,
                # M1 has no persisted human confirmations to restore; M3 will
                # pass a stored confirmed_bpm here when re-opening such files.
                confirmed_bpm=None,
            )
        )
        self.result_ready.emit(result)
        self.working.emit(False)

    def fail(self, message: str) -> None:
        """An analysis failed; previous results are kept untouched."""
        self._reduce(verdict.AnalysisFailed(msg=message))
        self.working.emit(False)
        self.analysis_failed.emit(message)
