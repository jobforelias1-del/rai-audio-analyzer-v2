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

M3 (R-M3-3/20): ``confirm(bpm)`` / ``undo()`` are the ONLY ground-truth
mutation entry points — each dispatches the matching reducer event and, when
the reducer accepts, journals a confirm/retraction record in the
ground-truth store keyed by ``last_md5`` (the worker-computed whole-file
hash). ``finish`` looks the md5 up in the store and feeds any effective
confirmation into ``AnalysisOk(confirmed_bpm=...)`` — the display-overlay
re-open path (D7): the engine result object is never touched. Illegal-state
calls no-op with a log; the reducer's guards are the truth.

Signal contract (shared interface — other agents rely on these exact names):

* ``result_ready(object)``   — emits ``rai_analyzer.contracts.AnalysisResult``
* ``analysis_failed(str)``   — plain-language failure message
* ``working(bool)``          — True while an analysis is in flight
* ``verdict_changed(object)``— emits ``rai_ui.state.verdict.VerdictState``
  after every reduction (begin/finish/fail), even when the reducer returned
  the state unchanged — subscribers re-render idempotently, and "did anything
  change" is the reducer's business, not the wiring's.

Ordering contract inside ``finish`` (widgets rely on it): stored fields
(``last_result``/``last_features``/``last_signal_obj``/``last_signal_result``/
``analysis_seconds``) are set FIRST, then the verdict reduces and
``verdict_changed`` fires, then ``result_ready``, then ``working(False)`` —
so a ``result_ready`` subscriber already sees both the fresh payload and the
fresh verdict.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from PySide6.QtCore import QObject, Signal

from rai_ui.services import ground_truth_store
from rai_ui.state import verdict

log = logging.getLogger(__name__)


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
        self.last_signal_result = None  # metrics SignalResult | None (M2)
        self.last_md5: Optional[str] = None  # whole-file md5 | None (M3)
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

    def finish(
        self,
        result,
        features,
        signal_obj,
        seconds: Optional[float],
        signal_result=None,
        md5: Optional[str] = None,
    ) -> None:
        """Store a completed analysis and notify subscribers.

        The verdict reduces after the payload fields are stored and before
        ``result_ready`` fires (see the module docstring's ordering contract);
        ``result_ready`` still fires before ``working(False)`` so listeners
        that re-render on the working flag (the status bar) already see the
        fresh data when they redraw.

        ``signal_result`` is the worker-composed M2 metrics record — a
        keyword-additive parameter (R-M2-15) so every pre-M2 caller keeps
        working; it is stored in the fields-FIRST phase like the rest of the
        payload so ``verdict_changed`` subscribers already see it. ``md5``
        (M3, same additive rule) is the worker-computed whole-file hash: when
        the ground-truth store holds an effective confirmation for it, the
        verdict boots directly to CONFIRMED · HUMAN via the reserved
        ``AnalysisOk(confirmed_bpm=...)`` hook (R-M3-3) — a display overlay
        over the live engine result, quiet by design (no toast).
        """
        self.last_result = result
        self.last_features = features
        self.last_signal_obj = signal_obj
        self.last_signal_result = signal_result
        self.last_md5 = md5
        self.analysis_seconds = float(seconds) if seconds is not None else None

        # Stored-truth lookup (R-M3-3): a tiny JSONL replay; never fatal —
        # the store degrades unreadable journals to "no stored truth".
        truth = ground_truth_store.lookup(md5) if md5 else None

        tempo = result.tempo
        self._reduce(
            verdict.AnalysisOk(
                ambiguous=tempo.ambiguous,
                # The resolver's no-tempo shape: empty candidates, primary 0.0.
                has_tempo=bool(tempo.candidates) and tempo.primary_bpm > 0,
                confirmed_bpm=truth.bpm if truth is not None else None,
            )
        )
        self.result_ready.emit(result)
        self.working.emit(False)

    def confirm(self, bpm: float) -> None:
        """Human tiebreak: confirm ``bpm`` as this file's ground truth.

        Dispatches the reducer ``Confirm`` event and, when the reducer
        accepts (CONFIDENT/AMBIGUOUS -> CONFIRMED_HUMAN, or a re-confirm),
        appends a confirm record to the journal BEFORE broadcasting — the
        verdict copy says "saved as ground truth", so the save comes first.
        Illegal states no-op with a log (R-M3-20); a store write failure is
        logged and the in-session confirmation still stands (losing the
        user's click over a disk hiccup would be worse — the log is the
        diagnosable trail).
        """
        bpm = float(bpm)
        after = verdict.reduce(self.verdict_state, verdict.Confirm(bpm=bpm))
        if after is self.verdict_state:
            log.warning(
                "confirm(%.2f) ignored — nothing to confirm in state %s",
                bpm,
                self.verdict_state.kind.value,
            )
            return
        if self.last_md5:
            try:
                ground_truth_store.append_confirm(
                    md5=self.last_md5,
                    bpm=bpm,
                    name=os.path.basename(self.path) if self.path else "",
                    path=self.path or "",
                )
            except Exception:
                log.exception("ground-truth confirm record could not be written")
        else:
            log.warning("confirm(%.2f) without a file md5 — not persisted", bpm)
        self.verdict_state = after
        self.verdict_changed.emit(after)

    def undo(self) -> None:
        """Take back the confirmation: reducer ``Undo`` + journal retraction.

        The retraction record is what makes undo work across sessions
        (R-M3-1) — replay clears the md5. Same discipline as ``confirm``:
        reducer guards are the truth, persistence precedes broadcast,
        write failures log instead of crashing.
        """
        after = verdict.reduce(self.verdict_state, verdict.Undo())
        if after is self.verdict_state:
            log.warning(
                "undo() ignored — nothing to undo in state %s",
                self.verdict_state.kind.value,
            )
            return
        if self.last_md5:
            try:
                ground_truth_store.append_retract(self.last_md5)
            except Exception:
                log.exception("ground-truth retraction could not be written")
        self.verdict_state = after
        self.verdict_changed.emit(after)

    def fail(self, message: str) -> None:
        """An analysis failed; previous results are kept untouched."""
        self._reduce(verdict.AnalysisFailed(msg=message))
        self.working.emit(False)
        self.analysis_failed.emit(message)
