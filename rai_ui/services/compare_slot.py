"""The Compare section's persistent B lane (M4, R-M4-2/3).

One ``CompareSlot`` lives on the MainWindow and owns everything about the
reference track B: its own :class:`AnalysisWorker` launches (same
QThread/moveToThread/invokeMethod recipe as the A lane — landmine 2: bound
methods only, never cross-thread lambdas), its OWN generation counter (an A
drop must never orphan an in-flight B and vice versa), and the B payload.

Doctrine enforced here:

* **B is a persistent reference** (R-M4-2): it survives A re-analyses —
  compare many candidates against one reference (the TRUCK workflow) — and is
  cleared ONLY by :meth:`clear` (the chip's ✕) or app restart. The slot
  stores ``result`` + ``signal_result`` ONLY: no session, no verdict reducer,
  no ground-truth lookup, no recents, no rail/bridge, no global working flag.
  A B completion never calls ``session.finish`` — the whole M3 truth pipeline
  belongs to A alone.
* **Analysis lanes are mutually exclusive** (R-M4-3): :meth:`start` refuses
  while A is WORKING or a relearn is running — the engine's fingerprint load
  cache is path-keyed and content-blind (M3 review finding 18), so a B
  analysis racing a relearn publish could score against two profiles. The
  gates are injected callables so this service never imports the session or
  the relearn controller; the refusal copy lives here (toast-ready, the
  RelearnController message precedent) and the caller shows it. The vice
  versa gates (A/relearn refuse while B works) live at the MainWindow entry
  points off :meth:`is_working`.
* **State gates flip before signal relays** (M3 postscript / landmine 22):
  ``status`` is updated BEFORE ``loaded``/``failed``/``changed`` emit, so a
  handler that re-reads the slot mid-signal always sees the settled truth.
* **A failed replacement keeps the old B** (authored, R-M4-2's persistence
  spirit — the design never drew a failing B): the previous payload is only
  swapped on a SUCCESSFUL completion, so a failed re-drop degrades back to
  the reference that was already loaded (or EMPTY if there was none).

Stale completions: rapid B re-drops simply orphan the older worker via the
generation tag (the exact A-lane semantics); ``clear`` also bumps the
generation so an in-flight B cannot land into a slot the user just emptied.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, Qt, QThread, Signal

from rai_ui.services.worker import AnalysisWorker
from rai_ui.state.compare_view import BStatus

# R-M4-3 refusal copy (RC copy — no designed surface; tone matches the M3
# mutual-exclusion toasts in main_window).
TOAST_B_BLOCKED_BY_ANALYSIS = "Analysis running — load the reference once it finishes"
TOAST_B_BLOCKED_BY_RELEARN = "Relearning — reference load ignored until it finishes"


class CompareSlot(QObject):
    """B-lane analysis service: own workers, own generation, B payload only.

    Signals (all emitted AFTER the status flip — landmine 22):

    * ``changed()`` — any lifecycle transition (start / finish / fail /
      clear); the shell rebuilds the Compare view-model on it.
    * ``loaded(object)`` — a fresh B ``AnalysisResult`` landed (status is
      already LOADED); the shell fires the design's verbatim toast off it.
    * ``failed(str)`` — a B analysis failed with a toast-ready message
      (status already restored to the previous LOADED payload or EMPTY).
    * ``profile_fallback(str)`` — the R-M3-12 one-shot notice relayed from
      the CURRENT B worker only (a stale worker's notice is dropped, same
      honesty rule as the A lane).
    """

    changed = Signal()
    loaded = Signal(object)  # AnalysisResult
    failed = Signal(str)
    profile_fallback = Signal(str)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        a_working: Callable[[], bool],
        relearn_running: Callable[[], bool],
    ) -> None:
        super().__init__(parent)
        self._a_working = a_working
        self._relearn_running = relearn_running
        self._generation = 0
        self._threads: list[tuple[QThread, AnalysisWorker]] = []
        self._status: BStatus = BStatus.EMPTY
        self.result = None  # AnalysisResult | None — the ONLY stored payload
        self.signal_result = None  # metrics SignalResult | None    (R-M4-2)

    # -- lifecycle ----------------------------------------------------------------

    @property
    def status(self) -> BStatus:
        return self._status

    def is_working(self) -> bool:
        """True while a B analysis is in flight (the vice-versa gate probe)."""
        return self._status is BStatus.WORKING

    def start(self, path: str) -> Optional[str]:
        """Analyze ``path`` into the B slot; returns a refusal message or None.

        ``None`` means the analysis started (status is now WORKING and
        ``changed`` has fired). A non-None return is the toast-ready R-M4-3
        refusal — nothing changed, nothing was launched. A start while B
        itself is WORKING is a REPLACE: the generation bump orphans the older
        worker exactly like rapid A re-drops.
        """
        if self._a_working():
            return TOAST_B_BLOCKED_BY_ANALYSIS
        if self._relearn_running():
            return TOAST_B_BLOCKED_BY_RELEARN

        self._generation += 1
        self._prune_finished_threads()

        thread = QThread(self)
        worker = AnalysisWorker()  # no parent: moveToThread requires it
        worker._generation = self._generation
        worker.moveToThread(thread)
        # Bound-method connections + invokeMethod (landmine 2): PySide6
        # functor connections resolve their thread context unreliably.
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.profile_fallback.connect(self._on_profile_fallback)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._threads.append((thread, worker))
        thread.start()
        QMetaObject.invokeMethod(
            worker, "run", Qt.ConnectionType.QueuedConnection, Q_ARG(str, path)
        )

        self._status = BStatus.WORKING  # gate flips before the relay
        self.changed.emit()
        return None

    def clear(self) -> None:
        """Empty the slot (the chip's ✕ — the ONE clearing act, R-M4-2).

        Bumps the generation so an in-flight B completion is orphaned rather
        than resurrecting into a slot the user just emptied.
        """
        self._generation += 1
        self.result = None
        self.signal_result = None
        self._status = BStatus.EMPTY
        self.changed.emit()

    def close(self) -> None:
        """Bounded worker-thread teardown (the MainWindow closeEvent recipe)."""
        for thread, _worker in self._threads:
            thread.quit()
            thread.wait(2000)

    # -- worker completion (main thread via queued signal delivery) -----------------

    def _sender_is_current(self) -> bool:
        worker = self.sender()
        return (
            worker is not None
            and getattr(worker, "_generation", None) == self._generation
        )

    def _on_worker_finished(
        self, result, features, signal_obj, seconds, signal_result=None, md5=None
    ) -> None:
        if not self._sender_is_current():
            return  # stale: replaced or cleared while in flight
        del features, signal_obj, seconds, md5  # R-M4-2: B stores result+metrics ONLY
        self.result = result
        self.signal_result = signal_result
        self._status = BStatus.LOADED  # gate flips before the relays
        self.loaded.emit(result)
        self.changed.emit()

    def _on_worker_failed(self, message: str) -> None:
        if not self._sender_is_current():
            return
        # Persistence over the failed replacement: the old B (if any) stands.
        self._status = BStatus.LOADED if self.result is not None else BStatus.EMPTY
        self.failed.emit(message)
        self.changed.emit()

    def _on_profile_fallback(self, message: str) -> None:
        if self._sender_is_current():
            self.profile_fallback.emit(message)

    def _prune_finished_threads(self) -> None:
        self._threads = [
            (t, w) for (t, w) in self._threads if t.isRunning() or not t.isFinished()
        ]
