"""In-process smoke probe: prove the (frozen) UI works end-to-end.

WHY this exists (docs/ENVIRONMENT.md): the shipped v2 .app was dead on
arrival twice — dead drag-and-drop, and an uncatchable SIGABRT during window
creation — while terminal runs of the same stack passed. The only honest test
of a build is therefore: show the real window, deliver a REAL drop event
(``QDragEnterEvent`` + ``QDropEvent`` through ``QApplication.sendEvent``, so
the app's own DnD handlers run — never a direct ``open_path`` shortcut), run
a real analysis on a real WAV, and report machine-checkable JSON.
``build/smoke_frozen.sh`` drives this against the frozen bundle and asserts
on the JSON.

Platform note: this module deliberately does NOT force ``QT_QPA_PLATFORM``.
Under ``smoke_frozen.sh`` the probe must exercise the native cocoa platform
(the v2 crash only reproduced there); under CI, where the variable is already
``offscreen``, it simply proceeds under it.

Exit codes: 0 = pass · 1 = failure · 2 = analysis timeout. EXIT_OK requires
ALL of ``window_shown``, ``accepts_drops``, ``dnd_delivered``,
``analysis_ok``, ``tempo_ok``, ``signal_ok`` and ``truth_ok`` to be truthy
(see :data:`REQUIRED_TRUE_KEYS` / :func:`exit_code_for`). ``tempo_ok`` and
``signal_ok`` are load-bearing here, not advisory: the worker deliberately
degrades a metrics-layer crash to ``SignalResult=None`` (R-M2-15 — the
analysis stays green by design), so the exit code is the ONLY gate that
catches a silently-dead M1/M2 rendering layer. ``truth_ok`` (M3, R-M3-14,
same landmine-14 contract) proves the flagship round-trip against an
ISOLATED temp ground-truth store: posed confirm -> CONFIRMED · HUMAN
renders (verdict kind + HumanPill row) -> journal write + lookup
round-trip -> undo -> retraction written. The probe redirects the store's
injectable directory factory to a temp dir for its whole run — it performs
a REAL analysis in the user's environment, and touching the real journal
would be a defect (R-M3-2). ``build/smoke_frozen.sh`` keys probe 1 off this
exit code; its ``check_json`` field asserts are an independent, additive
layer and stay unchanged. Audio playback problems are REPORTED
(``audio_ok``/``audio_error``) but never fail the probe — CI runners and
headless Macs have no output device, and that says nothing about the build.
"""

from __future__ import annotations

import gc
import json
import os
import platform
import tempfile
import time
import traceback

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2

#: Report keys that must ALL be truthy for EXIT_OK. ``tempo_ok``/``signal_ok``
#: joined the required set when review found them write-only: a metrics-layer
#: death degrades to ``SignalResult=None`` with ``analysis_ok`` still true, so
#: an exit code keyed on analysis alone would stay green through it.
#: ``truth_ok`` (M3) is load-bearing by the same rule (R-M3-14): confirm/undo
#: degrade to logged no-ops by design, so only the exit code catches a dead
#: ground-truth lane.
REQUIRED_TRUE_KEYS = (
    "window_shown",
    "accepts_drops",
    "dnd_delivered",
    "analysis_ok",
    "tempo_ok",
    "signal_ok",
    "truth_ok",
)


def exit_code_for(report: dict, timed_out: bool) -> int:
    """Pure exit-code policy — the one place pass/fail is decided.

    Kept free of Qt and side effects so the failure direction is unit-testable
    (``tests/ui/test_smoke_exit.py``): timeout wins, then EXIT_OK only when
    every :data:`REQUIRED_TRUE_KEYS` entry is truthy (``None`` — never
    computed — fails exactly like ``False``). ``audio_ok`` is deliberately
    absent: the audio spike is reported, never required.
    """
    if timed_out:
        return EXIT_TIMEOUT
    if all(bool(report.get(key)) for key in REQUIRED_TRUE_KEYS):
        return EXIT_OK
    return EXIT_FAILED

# The synthetic fixture: an 8 s drill pattern at a notated 140 BPM — long
# enough for a stable tempogram, short enough that the whole probe stays
# interactive. 140 sits mid-band so a sane engine reports 140 (or flags the
# 70 half-time partner as ambiguous); either way `analysis_ok` is true and
# the shell layer checks bpm plausibility.
SMOKE_BPM = 140.0
SMOKE_DURATION_S = 8.0

ANALYSIS_TIMEOUT_MS = 60_000

# --smoke-audio: a polite 0.5 s A440 sine through the default output device.
AUDIO_TONE_HZ = 440.0
AUDIO_TONE_S = 0.5
AUDIO_TONE_GAIN = 0.2
AUDIO_SR = 44_100


def run_smoke(args) -> int:
    """Run the end-to-end probe. ``args`` is the parsed CLI namespace from
    ``rai_ui.__main__`` (``smoke_json`` path, ``smoke_audio`` flag)."""
    json_path = getattr(args, "smoke_json", None)
    want_audio = bool(getattr(args, "smoke_audio", False))

    report: dict = {
        "window_shown": False,
        "accepts_drops": False,
        "dnd_delivered": False,
        "analysis_ok": False,
        "bpm": None,
        "ambiguous": None,
        "tempo_ok": None,
        "signal_ok": None,
        "truth_ok": None,
        "seconds": None,
        "audio_ok": None,
        "commit": _commit(),
        "qt": None,
        "python": platform.python_version(),
    }

    try:
        exit_code = _probe(report, want_audio)
    except Exception:
        # The probe must ALWAYS emit its JSON — a crash with no report is
        # exactly the v2 failure mode this module exists to catch.
        report["error"] = traceback.format_exc()
        exit_code = EXIT_FAILED
    finally:
        _emit(report, json_path)
    return exit_code


def _probe(report: dict, want_audio: bool) -> int:
    """Store-isolated wrapper around the probe body (R-M3-2).

    The probe runs a REAL analysis (worker profile lookup, session store
    lookup) and a posed confirm/undo round-trip (journal writes) — every
    ground-truth store access is redirected to a throwaway temp dir for the
    probe's whole lifetime, so the user's real journal is never read OR
    written. The factory is restored exception-safely (``run_smoke`` may
    execute inside a test process).
    """
    import shutil

    from rai_ui.services import ground_truth_store

    original_store_dir = ground_truth_store._store_dir
    smoke_store_dir = tempfile.mkdtemp(prefix="rai_smoke_store_")
    ground_truth_store._store_dir = lambda: smoke_store_dir
    try:
        return _probe_body(report, want_audio)
    finally:
        ground_truth_store._store_dir = original_store_dir
        shutil.rmtree(smoke_store_dir, ignore_errors=True)


def _probe_body(report: dict, want_audio: bool) -> int:
    # Qt imports live here, not at module top: rai_ui.smoke stays importable
    # in Qt-less environments (the engine CI job collects this tree).
    from PySide6.QtCore import (
        QEventLoop,
        QMimeData,
        QPoint,
        QPointF,
        Qt,
        QTimer,
        QUrl,
        qVersion,
    )
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication

    from rai_ui.app import create_app
    from rai_ui.main_window import MainWindow

    app = create_app()
    report["qt"] = qVersion()

    # Deterministic-GC bracket, opening side (CI SIGSEGV, 2026-07-12): when
    # the probe runs inside a long-lived test process, cyclic garbage from
    # dozens of prior windows (PySide6/pyqtgraph wrapper cycles) is waiting
    # for the collector. If the threshold trips mid-loop.exec() below, the
    # collector tp_deallocs Qt C++ objects at an arbitrary unsafe moment —
    # the observed hard crash. Sweep at THIS safe point (top of stack, no
    # event loop, no workers) so our run doesn't inherit the storm.
    gc.collect()

    window = MainWindow()
    window.show()
    app.processEvents()  # let the first show actually happen
    report["window_shown"] = bool(window.isVisible())
    report["accepts_drops"] = bool(window.acceptDrops())

    wav_path = _write_fixture()
    try:
        session = window.session
        outcome: dict = {}
        loop = QEventLoop()

        def _on_result(result: object) -> None:
            outcome["result"] = result
            loop.quit()

        def _on_failed(message: str) -> None:
            outcome["error"] = str(message)
            loop.quit()

        # Connect BEFORE injecting the drop so a synchronously-emitted result
        # cannot slip past (loop.quit() on a not-yet-running loop is a no-op,
        # and we only exec() the loop if nothing has landed yet).
        session.result_ready.connect(_on_result)
        session.analysis_failed.connect(_on_failed)

        t0 = time.perf_counter()

        if report["accepts_drops"]:
            report["dnd_delivered"] = _inject_drop(
                QApplication,
                window,
                wav_path,
                QMimeData,
                QUrl,
                QPoint,
                QPointF,
                Qt,
                QDragEnterEvent,
                QDropEvent,
            )

        if not report["dnd_delivered"] and not outcome:
            # Fallback assert: the probe has ALREADY failed (dead DnD is the
            # v2 bug class), but still exercise the pipeline directly so the
            # JSON says whether analysis works — two diagnostics per run.
            window.open_path(wav_path)

        timed_out = False
        if not outcome:
            timer = QTimer(window)
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(ANALYSIS_TIMEOUT_MS)
            loop.exec()
            timed_out = not outcome

        session_seconds = getattr(session, "analysis_seconds", None)
        if session_seconds is None:
            session_seconds = time.perf_counter() - t0
        report["seconds"] = round(float(session_seconds), 2)

        result = outcome.get("result")
        if result is not None:
            report["analysis_ok"] = True
            report["bpm"] = round(float(result.tempo.primary_bpm), 2)
            report["ambiguous"] = bool(result.tempo.ambiguous)
            # M1 check: the Tempo section actually rendered the result — at
            # least one plot marker and one candidate table row. REQUIRED for
            # EXIT_OK (see REQUIRED_TRUE_KEYS); as a JSON key it stays
            # additive — build/smoke_frozen.sh's check_json reads only the
            # keys it knows, so older tooling tolerates it.
            vm = window.tempo_section.view()
            report["tempo_ok"] = bool(
                len(vm.markers) >= 1
                and window.tempo_section.candidates.model.rowCount() >= 1
            )
            # M2 check: the Signal section actually rendered the metrics — a
            # populated spectrum curve and all three metric cards showing
            # measurements, not absence dashes. The fixture is a mono
            # synthetic, so Stereo width legitimately reads "0 %" (a
            # measurement, R-M2-4) — any non-dash value counts as populated.
            # REQUIRED for EXIT_OK, same contract as tempo_ok above: the
            # worker degrades a metrics crash to SignalResult=None while
            # analysis_ok stays true (R-M2-15), so this key in the exit code
            # is what stops that death from passing the gate silently. As a
            # JSON key it stays additive for check_json.
            svm = window.signal_section.view()
            dash = "—"  # em dash — absence, never a measurement
            report["signal_ok"] = bool(
                svm.spectrum_freqs is not None
                and len(svm.spectrum_freqs) > 0
                and svm.width_card.value_text != dash
                and svm.sub_card.value_text != dash
                and svm.dr_card.value_text != dash
            )
            # M3 check (R-M3-14): the ground-truth round-trip, posed against
            # the ISOLATED temp store this probe redirected above. REQUIRED
            # for EXIT_OK — confirm/undo degrade to logged no-ops by design,
            # so the exit code is the only gate that catches a dead truth
            # lane. As a JSON key it stays additive for check_json.
            report["truth_ok"] = _check_truth(window, report)
        elif "error" in outcome:
            report["analysis_error"] = outcome["error"]
        elif timed_out:
            report["analysis_error"] = (
                f"timeout: no result_ready/analysis_failed within "
                f"{ANALYSIS_TIMEOUT_MS // 1000}s"
            )

        if want_audio:
            report["audio_ok"] = _play_tone(report)

        window.close()
        # Deterministic-GC bracket, closing side: retire THIS probe's window
        # through Qt's own deletion path (deleteLater inside event
        # processing), then collect the survivors here — a safe point — so
        # the probe's object graph can never become someone else's
        # mid-loop.exec() GC storm. Parked straggler threads (see
        # main_window._ORPHANED_THREADS) stay referenced and are untouched.
        window.deleteLater()
        app.processEvents()
        gc.collect()

        return exit_code_for(report, timed_out)
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _inject_drop(
    QApplication, window, wav_path: str, QMimeData, QUrl, QPoint, QPointF, Qt,
    QDragEnterEvent, QDropEvent,
) -> bool:
    """Deliver a real file-URL drag-enter + drop to the window.

    Returns True only if the window's own dropEvent accepted it — the same
    accept/ignore decision a Finder drag would see.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(wav_path)])
    center = QPoint(max(1, window.width() // 2), max(1, window.height() // 2))

    enter = QDragEnterEvent(
        center,
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, enter)

    drop = QDropEvent(
        QPointF(center),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, drop)
    return bool(drop.isAccepted())


def _check_truth(window, report: dict) -> bool:
    """The R-M3-14 ground-truth round-trip, posed against the isolated store.

    Runs entirely on state the real analysis just produced: confirm the
    primary bpm through ``session.confirm`` (the ONLY mutation entry point,
    R-M3-20), verify CONFIRMED · HUMAN actually renders (verdict kind + the
    HumanPill row via the same ``view()`` introspection hooks ``tempo_ok``
    uses), verify the journal write with a store lookup round-trip, then
    ``session.undo`` and verify the retraction landed (lookup cleared AND a
    retract record was appended — undo must survive a restart). Failure
    detail goes to ``report["truth_error"]``; never raises.
    """
    try:
        import json as _json

        from rai_ui.services import ground_truth_store

        session = window.session
        md5 = session.last_md5
        if not md5:
            report["truth_error"] = "worker produced no md5 for the fixture"
            return False
        bpm = float(session.last_result.tempo.primary_bpm)

        session.confirm(bpm)
        vm = window.tempo_section.view()
        confirmed_renders = bool(
            vm.readout.verdict.kind == "confirmed_human"
            and any(row.confirmed_human and row.is_primary for row in vm.candidates)
        )
        truth = ground_truth_store.lookup(md5)
        wrote = truth is not None and abs(truth.bpm - bpm) < 1e-9

        session.undo()
        vm_after = window.tempo_section.view()
        undone = vm_after.readout.verdict.kind != "confirmed_human"
        cleared = ground_truth_store.lookup(md5) is None
        with open(ground_truth_store.journal_path(), "r", encoding="utf-8") as fh:
            records = [_json.loads(line) for line in fh if line.strip()]
        retract_written = bool(
            records
            and records[-1].get("kind") == "retract"
            and records[-1].get("retracts_md5") == md5
        )

        checks = {
            "confirmed_renders": confirmed_renders,
            "store_write_roundtrip": wrote,
            "undo_restores_verdict": undone,
            "lookup_cleared": cleared,
            "retraction_written": retract_written,
        }
        if not all(checks.values()):
            report["truth_error"] = {k: bool(v) for k, v in checks.items()}
            return False
        return True
    except Exception as exc:
        report["truth_error"] = f"{type(exc).__name__}: {exc}"
        return False


def _write_fixture() -> str:
    """Synthesize the drill-pattern WAV into a temp file and return its path."""
    from rai_analyzer.synthetic import drill_pattern, write_wav

    fd, wav_path = tempfile.mkstemp(prefix="rai_smoke_", suffix=".wav")
    os.close(fd)
    write_wav(wav_path, drill_pattern(SMOKE_BPM, duration=SMOKE_DURATION_S))
    return wav_path


def _play_tone(report: dict) -> bool:
    """Best-effort 0.5 s sine through the default device. Never raises."""
    try:
        import numpy as np
        import sounddevice as sd

        t = np.arange(int(AUDIO_TONE_S * AUDIO_SR)) / AUDIO_SR
        tone = (AUDIO_TONE_GAIN * np.sin(2 * np.pi * AUDIO_TONE_HZ * t)).astype(
            np.float32
        )
        sd.play(tone, AUDIO_SR)
        sd.wait()
        return True
    except Exception as exc:  # no device, no permission, headless CI, ...
        report["audio_error"] = f"{type(exc).__name__}: {exc}"
        return False


def _commit() -> str:
    try:
        from rai_ui._buildinfo import COMMIT

        return COMMIT
    except Exception:
        return "unknown"


def _emit(report: dict, json_path) -> None:
    """Print the report and (atomically) write it to ``json_path``.

    Atomic replace matters: smoke_frozen.sh's probe 2 polls for the file and
    parses it the moment it exists — a partially-written JSON would turn a
    passing run into a flaky parse failure. The file is written BEFORE the
    stdout echo because a windowed frozen app may have a degenerate stdout,
    and the JSON file is the only channel probe 2 can see at all.
    """
    text = json.dumps(report, indent=2, default=str)
    if json_path:
        directory = os.path.dirname(os.path.abspath(json_path))
        os.makedirs(directory, exist_ok=True)
        tmp_path = f"{json_path}.tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        os.replace(tmp_path, json_path)
    try:
        print(text)
    except Exception:
        pass  # no usable stdout in a LaunchServices launch — the file is the report
