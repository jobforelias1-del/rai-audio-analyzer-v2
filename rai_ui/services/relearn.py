"""Relearn service (R-M3-11/12): rebuild the user fingerprint from confirmed
ground truth, with backup and one-step revert.

The pipeline (plan D6, concretized by R-M3-11) is::

    ground_truth_store.effective_truths()
        → md5 re-verify each confirmed file on disk (skip + report mismatches)
        → load_audio + build_features per surviving file (~1 s each)
        → learn_fingerprint(items, DEFAULT_CONFIG)
        → save_fingerprint(...) to drill.user.json.tmp-<pid> (staged, same dir)
        → validate the STAGED file with the store's reader-shape check
        → backup any existing user profile to drill.user.backup.json
        → os.replace(tmp, drill.user.json)   (atomic swap)
        → clear_fingerprint_cache()          (exactly once, after the swap)

Every path comes from :mod:`rai_ui.services.ground_truth_store`'s injectable
``_store_dir`` factory (R-M3-2), so the service writes ONLY under the
per-user App Support dir — never ``rai_analyzer/fingerprints/`` (the packaged
default the gate reads; writing there is the forbidden act, R-M3-13) — and
tests redirect everything to temp dirs.

Abort-writes-nothing: verification and feature-building happen BEFORE any
disk write. If fewer than ``RELEARN_MIN_CONFIRMS`` tracks survive re-verify
and decode, :class:`RelearnError` is raised and neither backup nor profile is
touched — a profile that claims "learned from your confirmed truths" is never
quietly built from less than the gate the button promised. The same holds for
cancellation: ``run_relearn`` polls an optional ``cancelled`` callable between
per-file feature builds (and once more before the write phase), and a
cancelled run raises :class:`RelearnCancelled` having written NOTHING.

Atomic publish (adversarial-review fix): the new profile is serialized to a
temp file IN THE SAME DIRECTORY (``drill.user.json.tmp-<pid>``), validated
there with the store's own reader-shape check, and only then ``os.replace``-d
onto ``drill.user.json``. ``os.replace`` is an atomic rename on the same
filesystem, so any concurrent reader (the analysis worker's
``validate_profile_file``/``load_fingerprint``, ``profile_state``) sees the
OLD profile or the NEW profile — never a torn/truncated file. A failure at
any point (disk full mid-dump, validation failure, crash before the replace)
leaves the previous on-disk state fully intact; the worker's R-M3-12 fallback
toast can never be caused by relearn itself. ``clear_fingerprint_cache()``
runs exactly once, AFTER the replace — the engine's load cache is path-keyed
and content-blind (recon §1), so clearing before the swap could let a reader
re-poison the cache with the old profile.

Engine imports (``load_audio``/``build_features``/``learn_fingerprint``/
``save_fingerprint``/``clear_fingerprint_cache``/``DEFAULT_CONFIG``) are lazy
and read-only — zero engine files change (R-M3-19; the gate proves it).

Threading: the synchronous core (:func:`run_relearn`, :func:`revert_profile`,
:func:`profile_state`) is Qt-free so this module imports in the engine venv.
When PySide6 is present, :class:`RelearnWorker` + :class:`RelearnController`
wrap the core in the house QThread pattern (M0 landmines 1–2: workers are
Python-owned — never ``deleteLater`` from the dying thread — bound-method
signal connections only, ``QMetaObject.invokeMethod`` to start, and a
generation tag read back via ``sender()`` so a stale completion can never be
mistaken for the current one).

Controller API contract (the Wire stage gates cross-module mutual exclusion
— no analysis during relearn and vice versa — on exactly this surface)::

    RelearnController.is_running() -> bool
    RelearnController.cancel()                    # thread-safe, idempotent
    RelearnController.started                     # Signal()
    RelearnController.finished(ok: bool, message: str)   # every terminal path
    RelearnController.progress(done: int, total: int)    # status-bar nicety

``finished`` fires for success (``ok=True``, message = the toast-ready
"Profile relearned from N confirmed tracks"), failure (``ok=False``, human
RelearnError text verbatim) and cancellation (``ok=False``,
``CANCELLED_MESSAGE``) — there is no separate ``failed`` signal anymore.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from rai_ui.services import ground_truth_store

log = logging.getLogger(__name__)

# The explicit-button gate (R-M3-11 / D6): relearn is offered at >= 3
# effective confirmations, and run_relearn holds the SAME floor against the
# md5-re-verified survivor count — the profile never claims more than it has.
RELEARN_MIN_CONFIRMS = 3

# Skip-reason vocabulary (stable copy — surfaced in reports/logs).
SKIP_NO_PATH = "no stored path (legacy record)"
SKIP_MISSING = "file missing"
SKIP_CHANGED = "file changed (md5 mismatch)"
SKIP_UNREADABLE = "unreadable"

# Terminal-status copy for the controller's finished(ok, message) signal.
# CANCELLED_MESSAGE is a stable token: the Wire stage / tests may compare it.
CANCELLED_MESSAGE = "relearn cancelled — nothing was written"
RELEARN_DONE_MESSAGE_FMT = "Profile relearned from {n} confirmed tracks"


class RelearnError(RuntimeError):
    """Relearn could not (or must not) produce a profile. Nothing was written
    (the atomic-publish staging means a failure never touches the live
    profile). Carries the skip report."""

    def __init__(self, message: str, skipped: tuple["SkippedTruth", ...] = ()) -> None:
        super().__init__(message)
        self.skipped = skipped


class RelearnCancelled(RelearnError):
    """The run was cancelled cooperatively. NOTHING was written: the cancel
    flag is polled between per-file feature builds and once more immediately
    before the write phase, all of which precede any disk mutation."""


@dataclass(frozen=True)
class SkippedTruth:
    """One confirmed truth relearn could not consume, and why."""

    name: str
    md5: str
    reason: str


@dataclass(frozen=True)
class RelearnReport:
    """What a successful relearn actually did."""

    learned: int  # tracks that fed the fingerprint
    skipped: tuple[SkippedTruth, ...]  # re-verify/decode casualties
    profile_path: str  # the written drill.user.json
    backup_path: Optional[str]  # backup written (None = no prior profile)


@dataclass(frozen=True)
class ProfileState:
    """The popover's state payload (R-M3-11) — what the engine will read on
    the next analysis, derived with the worker's own validation test."""

    kind: str  # "user" | "packaged"
    relearned_at: Optional[str]  # "YYYY-MM-DD" when recorded in _meta
    confirmed_count: int
    backup_exists: bool


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def run_relearn(
    progress: Optional[Callable[[int, int], None]] = None,
    min_confirms: int = RELEARN_MIN_CONFIRMS,
    cancelled: Optional[Callable[[], bool]] = None,
) -> RelearnReport:
    """Relearn the user fingerprint from the effective confirmed truths.

    ``progress(done, total)`` is called after each feature build (``total`` =
    md5-verified survivors). Raises :class:`RelearnError` when fewer than
    ``min_confirms`` tracks survive verification + decode — in that case
    nothing has been written.

    ``cancelled`` (optional, must be thread-safe) is polled between per-file
    steps and once more before the write phase; a poll returning True raises
    :class:`RelearnCancelled` — again with nothing written.
    """

    def _check_cancel() -> None:
        if cancelled is not None and cancelled():
            raise RelearnCancelled(CANCELLED_MESSAGE, skipped=tuple(skipped))

    # Engine imports: lazy and read-only (worker.py precedent) — a broken
    # optional dependency surfaces per-run, not at module import.
    from rai_analyzer.config import DEFAULT_CONFIG
    from rai_analyzer.evidence.fingerprint import (
        clear_fingerprint_cache,
        learn_fingerprint,
        save_fingerprint,
    )
    from rai_analyzer.io_audio import load_audio
    from rai_analyzer.tempogram import build_features

    truths = list(ground_truth_store.effective_truths().values())
    skipped: list[SkippedTruth] = []

    # --- phase 1: md5 re-verify on disk (R-M3-11: skip + report) -------------
    verified: list[ground_truth_store.ConfirmedTruth] = []
    for truth in truths:
        _check_cancel()  # md5 of a big file is per-file work too
        if not truth.path:
            skipped.append(SkippedTruth(truth.name, truth.md5, SKIP_NO_PATH))
        elif not os.path.exists(truth.path):
            skipped.append(SkippedTruth(truth.name, truth.md5, SKIP_MISSING))
        elif ground_truth_store.file_md5(truth.path) != truth.md5:
            skipped.append(SkippedTruth(truth.name, truth.md5, SKIP_CHANGED))
        else:
            verified.append(truth)

    # --- phase 2: features per surviving file (still nothing written) --------
    total = len(verified)
    if progress is not None:
        progress(0, total)
    items: list[tuple[object, float]] = []
    for done, truth in enumerate(verified, 1):
        _check_cancel()  # between per-file feature builds (cooperative abort)
        try:
            signal = load_audio(truth.path)
            features = build_features(signal, DEFAULT_CONFIG)
        except Exception as exc:  # decode/DSP casualty: skip + report
            log.warning("relearn: %s unreadable (%s)", truth.path, exc)
            skipped.append(
                SkippedTruth(truth.name, truth.md5, f"{SKIP_UNREADABLE}: {exc}")
            )
        else:
            items.append((features, truth.bpm))
        if progress is not None:
            progress(done, total)

    # --- the gate, against what actually survived ----------------------------
    if len(items) < min_confirms:
        raise RelearnError(
            f"only {len(items)} of {len(truths)} confirmed truths are usable on "
            f"disk — relearn needs {min_confirms}; nothing was written",
            skipped=tuple(skipped),
        )

    # --- phase 3: learn (pure), then the atomic publish -----------------------
    fingerprint = learn_fingerprint(items, DEFAULT_CONFIG)
    meta = fingerprint.get("_meta")
    if isinstance(meta, dict):
        # Additive metadata for the popover's source line ("relearned {date}",
        # R-M3-11); save_fingerprint passes _-keys through verbatim.
        meta["relearned_at"] = _now_iso()

    _check_cancel()  # last exit before any disk write: a cancel writes NOTHING

    profile_path = ground_truth_store.user_profile_path()
    backup_path: Optional[str] = None
    # Stage → validate → backup → atomically swap. The temp file lives in the
    # SAME directory as the profile so os.replace is an atomic rename on one
    # filesystem: concurrent readers (worker validate/load, profile_state)
    # see the old profile or the new one, NEVER a torn/truncated file. Any
    # failure inside this block leaves the previous on-disk state intact —
    # the live profile is only ever touched by the final os.replace.
    tmp_path = f"{profile_path}.tmp-{os.getpid()}"
    try:
        save_fingerprint(fingerprint, tmp_path)  # creates parent dirs

        # Self-check with the store's own reader-shape validation, ON THE
        # STAGED FILE: the bytes the worker will inject must be the bytes we
        # think we wrote. A failure here means the live profile was never
        # touched — relearn can never strand the R-M3-12 fallback path.
        if not ground_truth_store.validate_profile_file(tmp_path):
            raise RelearnError(
                "relearned profile failed validation — previous state untouched",
                skipped=tuple(skipped),
            )

        if os.path.exists(profile_path):
            backup_path = ground_truth_store.user_profile_backup_path()
            shutil.copyfile(profile_path, backup_path)  # one-step revert (D6)

        os.replace(tmp_path, profile_path)  # the atomic publish
    finally:
        # Failure/crash cleanup; after a successful replace the temp is gone
        # (ENOENT swallowed). A stray .tmp-<pid> from a hard kill is inert:
        # nothing ever reads that name.
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    # Exactly once, AFTER the replace: the load cache is keyed by path, not
    # content (recon §1) — without this the process keeps scoring against the
    # stale in-memory profile. Readers between the replace and this clear
    # still get a coherent (possibly old) profile, never a torn one.
    clear_fingerprint_cache()

    return RelearnReport(
        learned=len(items),
        skipped=tuple(skipped),
        profile_path=profile_path,
        backup_path=backup_path,
    )


def revert_profile() -> str:
    """One-step revert (R-M3-11): the backup becomes the profile again.

    The backup is consumed (``os.replace``) — "previous" means exactly one
    step, matching the popover's backup-gated link. Raises
    :class:`RelearnError` when there is nothing to revert to.
    """
    from rai_analyzer.evidence.fingerprint import clear_fingerprint_cache

    backup_path = ground_truth_store.user_profile_backup_path()
    if not os.path.exists(backup_path):
        raise RelearnError("no previous profile to revert to")
    profile_path = ground_truth_store.user_profile_path()
    os.replace(backup_path, profile_path)
    clear_fingerprint_cache()
    return profile_path


def profile_state() -> ProfileState:
    """The popover's payload: what the engine READS next analysis.

    ``kind`` is ``"user"`` only when the profile passes the same shape
    validation the worker applies before injecting (R-M3-12) — an
    invalid-but-present user file honestly reports as packaged, because
    that is what the next analysis will actually use.
    """
    profile_path = ground_truth_store.user_profile_path()
    kind = "packaged"
    relearned_at: Optional[str] = None
    if os.path.exists(profile_path) and ground_truth_store.validate_profile_file(
        profile_path
    ):
        kind = "user"
        try:
            with open(profile_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh).get("_meta", {})
            raw = meta.get("relearned_at")
            if isinstance(raw, str) and len(raw) >= 10:
                relearned_at = raw[:10]  # ISO date part for the source line
        except Exception:  # metadata is a nicety, never a crash
            relearned_at = None
    return ProfileState(
        kind=kind,
        relearned_at=relearned_at,
        confirmed_count=ground_truth_store.confirmed_count(),
        backup_exists=os.path.exists(ground_truth_store.user_profile_backup_path()),
    )


# ---------------------------------------------------------------------------
# Qt worker + controller (defined only when PySide6 is importable, so the
# synchronous core above stays collectible in the Qt-less engine venv)
# ---------------------------------------------------------------------------

try:  # pragma: no cover - trivial import guard
    from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

    _QT_AVAILABLE = True
except ImportError:  # engine venv: core-only module
    _QT_AVAILABLE = False


if _QT_AVAILABLE:

    # close()'s bounded wait. Cancellation is polled per file (~1 s of work),
    # so 2 s covers the normal case with margin; beyond it, close() detaches.
    _CLOSE_WAIT_MS = 2000

    # Threads deliberately leaked by close()'s fallback (see close()): kept
    # referenced so neither Python GC nor Qt parent-destruction can destroy a
    # QThread that is still running (qFatal).
    _ORPHANED_THREADS: list = []

    class RelearnWorker(QObject):
        """Runs one relearn off the UI thread and reports over signals.

        Signals: ``progress(done, total)`` per feature build, and a single
        terminal ``finished(ok, message)`` for EVERY outcome — success
        (``ok=True``, toast-ready message), failure (``ok=False``,
        RelearnError text verbatim — it is written for humans) and
        cancellation (``ok=False``, ``CANCELLED_MESSAGE``). Never raises
        across the thread boundary.

        Cancellation is a ``threading.Event`` set via :meth:`request_cancel`
        (thread-safe, callable from any thread); ``run_relearn`` polls it
        between per-file feature builds, so a cancelled run writes nothing
        and returns within roughly one file's work.
        """

        progress = Signal(int, int)
        finished = Signal(bool, str)  # ok, message — the single terminal signal

        def __init__(self) -> None:
            super().__init__()
            self._cancel_event = threading.Event()

        def request_cancel(self) -> None:
            """Thread-safe, idempotent cooperative-cancel request."""
            self._cancel_event.set()

        @Slot()
        def run(self) -> None:
            try:
                report = run_relearn(
                    progress=self._report_progress,
                    cancelled=self._cancel_event.is_set,
                )
            except RelearnCancelled:
                self.finished.emit(False, CANCELLED_MESSAGE)
                return
            except RelearnError as exc:
                self.finished.emit(False, str(exc))
                return
            except Exception as exc:  # honest last line, toast-sized
                import traceback

                last = traceback.format_exception_only(type(exc), exc)[-1].strip()
                self.finished.emit(False, last)
                return
            log.info(
                "relearn: learned=%d skipped=%d -> %s",
                report.learned,
                len(report.skipped),
                report.profile_path,
            )
            self.finished.emit(True, RELEARN_DONE_MESSAGE_FMT.format(n=report.learned))

        def _report_progress(self, done: int, total: int) -> None:
            # Bound method on purpose: the signal emit is thread-safe and the
            # cross-thread delivery happens on the *connection*, which the
            # controller makes bound-method-to-bound-method (landmine 2).
            self.progress.emit(done, total)

    class RelearnController(QObject):
        """Owns the relearn QThread lifecycle for the shell (Stage-3 sink).

        API contract (the Wire stage gates the analysis⇄relearn mutual
        exclusion in main_window on exactly this surface)::

            is_running() -> bool
            cancel()                      # thread-safe cooperative cancel
            started                       # Signal()
            finished(ok: bool, message: str)   # every terminal path
            progress(done: int, total: int)    # status-bar nicety

        One relearn at a time: ``start()`` refuses (returns False) while a
        run is live. Signals mirror the worker's, re-emitted only for the
        CURRENT generation — the ``sender()._generation`` gate is the same
        stale-completion story as MainWindow's analysis workers. Call
        ``close()`` from the shell's ``closeEvent`` (cancel + bounded wait;
        workers stay Python-owned per landmine 1 — no ``deleteLater``).
        """

        started = Signal()
        progress = Signal(int, int)
        finished = Signal(bool, str)  # ok, message — success/failure/cancel

        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self._generation = 0
            self._threads: list[tuple[QThread, RelearnWorker]] = []

        def is_running(self) -> bool:
            return any(thread.isRunning() for thread, _worker in self._threads)

        def start(self) -> bool:
            """Kick off a relearn; False if one is already running."""
            if self.is_running():
                log.warning("relearn already running — start() refused")
                return False
            self._generation += 1
            self._prune_finished_threads()

            thread = QThread(self)
            worker = RelearnWorker()  # no parent: moveToThread requires it
            worker._generation = self._generation
            worker.moveToThread(thread)
            # Bound-method connections ONLY (landmine 2): functor/lambda
            # connections misdeliver across threads in this Qt pairing.
            worker.progress.connect(self._on_worker_progress)
            worker.finished.connect(self._on_worker_finished)
            worker.finished.connect(thread.quit)
            self._threads.append((thread, worker))
            thread.start()
            QMetaObject.invokeMethod(
                worker, "run", Qt.ConnectionType.QueuedConnection
            )
            self.started.emit()
            return True

        def cancel(self) -> None:
            """Request cooperative cancellation of any live run.

            Thread-safe and idempotent (a ``threading.Event`` per worker; no
            Qt machinery involved, so it is safe from any thread). The worker
            polls the flag between per-file feature builds: a cancelled run
            writes NOTHING and terminates with
            ``finished(False, CANCELLED_MESSAGE)``.
            """
            for thread, worker in self._threads:
                if thread.isRunning():
                    worker.request_cancel()

        def close(self) -> None:
            """Shell shutdown path: cancel, quit, then a BOUNDED wait.

            ``cancel()`` makes the worker exit at its next per-file check, so
            the ``wait(_CLOSE_WAIT_MS)`` (2 s) normally returns almost
            immediately — never the old unbounded-in-N 10 s UI freeze.

            Documented fallback: a thread that outlives the bound (one
            enormous decode mid-flight) is detached from this controller's
            parent chain and parked in a module-level list. Destroying a
            running QThread is a Qt qFatal ('QThread: Destroyed while thread
            is still running' — hard abort), so leaking the pair until
            process exit is the deliberate, safe choice; its worker is
            already cancelled and can no longer write anything.
            """
            self.cancel()
            for thread, worker in self._threads:
                thread.quit()
                if not thread.wait(_CLOSE_WAIT_MS):
                    log.warning(
                        "relearn thread outlived close()'s %d ms bound — "
                        "detaching and leaking it (qFatal guard); the worker "
                        "is cancelled and writes nothing",
                        _CLOSE_WAIT_MS,
                    )
                    thread.setParent(None)  # out of the window's destruction chain
                    _ORPHANED_THREADS.append((thread, worker))
            self._threads = []

        # -- worker completions (generation-gated) --------------------------

        def _sender_is_current(self) -> bool:
            worker = self.sender()
            return (
                worker is not None
                and getattr(worker, "_generation", None) == self._generation
            )

        def _on_worker_progress(self, done: int, total: int) -> None:
            if self._sender_is_current():
                self.progress.emit(done, total)

        def _on_worker_finished(self, ok: bool, message: str) -> None:
            if self._sender_is_current():
                self.finished.emit(ok, message)

        def _prune_finished_threads(self) -> None:
            self._threads = [
                (t, w) for (t, w) in self._threads if t.isRunning() or not t.isFinished()
            ]
