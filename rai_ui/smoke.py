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

Exit codes: 0 = pass · 1 = failure (window/DnD/analysis) · 2 = analysis
timeout. Audio playback problems are REPORTED (``audio_ok``/``audio_error``)
but never fail the probe — CI runners and headless Macs have no output
device, and that says nothing about the build.
"""

from __future__ import annotations

import json
import os
import platform
import tempfile
import time
import traceback

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2

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
        app.processEvents()

        if timed_out:
            return EXIT_TIMEOUT
        if report["dnd_delivered"] and report["analysis_ok"]:
            return EXIT_OK
        return EXIT_FAILED
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
