"""Offscreen preview-shot harness for the Tempo (M1) + Overview/Signal (M2) lanes.

Renders the REAL app (create_app: fonts, theme QSS, pyqtgraph config) at
1280×860 offscreen, drives it through the M1/M2 states with REAL analyses on
synthesized WAVs, and saves window grabs as PNGs — the closest thing to
screenshots a headless review can get. RC (and Elias) eyeball these against
the approved Console mock.

Shots, in order:

    01-hero          first-run hero page (recents row appears on later runs
                     of the same harness invocation — settings are isolated)
    02-working       Tempo section mid-analysis (sweep, skeleton, WORKING)
    03-tempo-rail    result landed on Tempo, persistent rail mode
    04-tempo-bridge  the same result with the readout collapsed to the bridge
    05-no-tempo      a silent WAV — neutral no-periodicity state
    06-report        the classic report section (byte-verbatim text view)
    07-overview      the M2 Overview section on the drill result (cards +
                     waveform)
    08-signal        the M2 Signal section on the drill result (spectrum +
                     metric cards)
    09-signal-silence  the Signal section on the silent WAV (−∞ vs — + chips,
                     R-M2-8 spectrum copy)
    10-tiebreak-overlay  the C-14 tiebreak overlay open over the candidates
                     pane with the top-ranked card selected (the drill
                     fixture is honestly ambiguous, so the entry point is
                     the real header button)
    11-confirmed     CONFIRMED · HUMAN everywhere after a REAL confirm through
                     the overlay's own button (green rail verdict, ✓ HUMAN
                     row, moved tempogram marker) — journaled to the ISOLATED
                     temp store only
    12-compare       the M4 Compare section posed A+B: the confirmed drill vs
                     a second synthetic reference loaded through the REAL
                     open_reference lane (chips, Δ table, spectrum overlay)
    13-compare-bempty  the same screen after the chip's clear — dashed browse
                     chip, em-dashed B/Δ/Reading columns, the "reference (B)
                     not loaded" pill over a lone A curve
    14-profile-popover  the header chip's profile popover, placed by the real
                     entry point (post-M5 placement: below the header
                     hairline, clear of the rail) and posed armed — composite
                     grab, since a Qt.Popup never appears in window.grab()
    gate-<fixture>   one Tempo shot per acceptance-gate WAV present on disk
                     (validation/ground_truth.py paths; the WAVs are
                     .gitignored so this is existence-guarded)

Settings are redirected to a throwaway temp INI and the M3 ground-truth
store to a throwaway temp dir, so the harness never touches the user's real
recents, rail preference, or ground-truth journal/fingerprint.

Usage:
    QT_QPA_PLATFORM=offscreen .venv-v3/bin/python tools/preview_shots.py OUTDIR
(the harness defaults QT_QPA_PLATFORM to offscreen itself if unset)
"""

from __future__ import annotations

import os
import sys
import tempfile

# Offscreen by default — this is a headless harness. Set before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Repo root on sys.path so `python tools/preview_shots.py` works from anywhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

WINDOW_W = 1280
WINDOW_H = 860

ANALYSIS_TIMEOUT_MS = 120_000

SILENT_DURATION_S = 3.0
SILENT_SR = 44_100


def _isolate_settings() -> None:
    """Point every per-user store at throwaway temp locations (never the user's).

    QSettings (recents + rail preference) go to a temp INI; the M3
    ground-truth store directory factory (R-M3-2) goes to a temp dir — the
    harness runs REAL analyses, whose workers look up the user fingerprint
    and whose session completions look up stored truth, and touching the real
    ``~/Library/Application Support/RAI Audio Analyzer/`` from a harness is a
    defect. The process is throwaway, so nothing is restored.
    """
    from PySide6.QtCore import QSettings

    import rai_ui.main_window as mw
    from rai_ui.services import ground_truth_store, recent_files

    ini_dir = tempfile.mkdtemp(prefix="rai_preview_settings_")

    def _tmp_settings(name: str):
        return lambda: QSettings(
            os.path.join(ini_dir, name), QSettings.Format.IniFormat
        )

    recent_files._settings = _tmp_settings("recent.ini")
    mw._ui_settings = _tmp_settings("ui.ini")

    store_dir = tempfile.mkdtemp(prefix="rai_preview_store_")
    ground_truth_store._store_dir = lambda: store_dir


def _write_silent_wav() -> str:
    """A silent WAV — the engine's no-tempo shape, end to end."""
    import numpy as np

    from rai_analyzer.synthetic import write_wav

    fd, path = tempfile.mkstemp(prefix="rai_preview_silent_", suffix=".wav")
    os.close(fd)
    write_wav(path, np.zeros(int(SILENT_DURATION_S * SILENT_SR), dtype=np.float32), SILENT_SR)
    return path


def _write_reference_wav() -> str:
    """A second drill fixture (150 BPM) for the M4 Compare reference B."""
    from rai_analyzer.synthetic import drill_pattern, write_wav

    fd, path = tempfile.mkstemp(prefix="rai_preview_ref_", suffix=".wav")
    os.close(fd)
    return write_wav(path, drill_pattern(150.0, duration=8.0))


def _run_reference_analysis(app, window, path: str) -> None:
    """Drive one REAL B analysis through open_reference and wait (M4)."""
    from PySide6.QtCore import QEventLoop, QTimer

    outcome: dict = {}
    loop = QEventLoop()

    def _on_loaded(result: object) -> None:
        outcome["result"] = result
        loop.quit()

    def _on_failed(message: str) -> None:
        outcome["error"] = str(message)
        loop.quit()

    window.compare_slot.loaded.connect(_on_loaded)
    window.compare_slot.failed.connect(_on_failed)
    try:
        window.open_reference(path)
        if not outcome:
            timer = QTimer(window)
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(ANALYSIS_TIMEOUT_MS)
            loop.exec()
    finally:
        window.compare_slot.loaded.disconnect(_on_loaded)
        window.compare_slot.failed.disconnect(_on_failed)
    if "result" not in outcome and "error" not in outcome:
        raise RuntimeError(f"reference analysis of {path!r} timed out")
    if "error" in outcome:
        raise RuntimeError(f"reference analysis of {path!r} failed: {outcome['error']}")
    app.processEvents()


def _run_analysis(app, window, path: str) -> None:
    """Drive one REAL analysis through open_path and wait for completion."""
    from PySide6.QtCore import QEventLoop, QTimer

    outcome: dict = {}
    loop = QEventLoop()

    def _on_result(result: object) -> None:
        outcome["result"] = result
        loop.quit()

    def _on_failed(message: str) -> None:
        outcome["error"] = str(message)
        loop.quit()

    window.session.result_ready.connect(_on_result)
    window.session.analysis_failed.connect(_on_failed)
    try:
        window.open_path(path)
        if not outcome:
            timer = QTimer(window)
            timer.setSingleShot(True)
            timer.timeout.connect(loop.quit)
            timer.start(ANALYSIS_TIMEOUT_MS)
            loop.exec()
    finally:
        window.session.result_ready.disconnect(_on_result)
        window.session.analysis_failed.disconnect(_on_failed)
    if "result" not in outcome and "error" not in outcome:
        raise RuntimeError(f"analysis of {path!r} timed out")
    app.processEvents()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        print("error: exactly one argument required: the output directory")
        return 2
    outdir = os.path.abspath(argv[1])
    os.makedirs(outdir, exist_ok=True)

    _isolate_settings()

    import rai_ui.main_window as mw
    from rai_ui import smoke
    from rai_ui.app import create_app

    app = create_app()
    window = mw.MainWindow()
    window.resize(WINDOW_W, WINDOW_H)
    window.show()
    app.processEvents()

    saved: list[str] = []

    def shot(name: str) -> None:
        app.processEvents()
        path = os.path.join(outdir, f"{name}.png")
        if not window.grab().save(path):
            raise RuntimeError(f"could not save {path}")
        saved.append(path)

    temp_wavs: list[str] = []
    try:
        shot("01-hero")

        # The smoke fixture: an 8 s synthetic 140 BPM drill pattern.
        drill_wav = smoke._write_fixture()
        temp_wavs.append(drill_wav)

        # Working state, posed deterministically: begin() alone drives the
        # WORKING verdict + sweep/skeleton without racing a real worker.
        window.nav.set_current("Tempo")
        window.session.begin(drill_wav)
        shot("02-working")

        # The real thing (open_path re-begins; the generation guard makes the
        # posed begin() above harmless).
        _run_analysis(app, window, drill_wav)
        shot("03-tempo-rail")

        window.header.rail_toggle.click()
        shot("04-tempo-bridge")
        window.header.rail_toggle.click()  # back to rail mode

        silent_wav = _write_silent_wav()
        temp_wavs.append(silent_wav)
        _run_analysis(app, window, silent_wav)
        shot("05-no-tempo")

        window.nav.set_current("Report")
        shot("06-report")

        # M2 appends (R-M2-19 — existing names above stay untouched): the
        # Overview/Signal sections on the drill result, then Signal on the
        # silent WAV. Shots 01–06 still render exactly what they did in M1;
        # the drill re-analysis below only feeds the new frames.
        _run_analysis(app, window, drill_wav)
        window.nav.set_current("Overview")
        shot("07-overview")
        window.nav.set_current("Signal")
        shot("08-signal")

        _run_analysis(app, window, silent_wav)
        window.nav.set_current("Signal")
        shot("09-signal-silence")

        # M3 appends (same append-only rule): the tiebreak overlay and the
        # confirmed state, driven through the REAL entry points — the drill
        # fixture is honestly ambiguous (raw-peak vs prior octave disagreement),
        # so the header "Open tiebreak" button is live.
        _run_analysis(app, window, drill_wav)
        window.nav.set_current("Tempo")
        pane = window.tempo_section.candidates
        pane.tiebreak_button.click()  # -> MainWindow opens the overlay (R-M3-6)
        overlay = pane.tiebreak
        # Posed-state trick (the 02-working precedent): the 220ms raiIn
        # entrance is decorative — stop it and render the settled overlay so
        # the grab isn't caught mid-fade.
        overlay._entrance.stop()
        overlay._effect.setOpacity(1.0)
        overlay.move(overlay._target_pos)
        # Select the SECOND-ranked card (the 04 demo's own scenario confirms a
        # non-primary): shot 11 then proves the R-M3-4 display recompute —
        # the ✓ HUMAN pill, raised row, and tempogram marker all move OFF the
        # engine primary.
        overlay.cards[1].clicked.emit()
        shot("10-tiebreak-overlay")

        # A REAL confirm through the overlay button: session.confirm ->
        # journal append (isolated temp store) -> CONFIRMED · HUMAN fan-out.
        overlay.confirm_button.click()
        window.toast.hide()  # the 2.4 s toast would cover the rail's rows
        shot("11-confirmed")

        # M4 appends (same append-only rule): the Compare section — A (the
        # confirmed drill result, still current) vs a second synthetic
        # reference loaded through the REAL entry point (open_reference ->
        # CompareSlot's own worker lane), then the B-empty state after the
        # one designed clearing act. Store isolation is inherited: the B
        # worker's md5/profile probes hit the same temp dirs.
        ref_wav = _write_reference_wav()
        temp_wavs.append(ref_wav)
        window.nav.set_current("Compare")
        _run_reference_analysis(app, window, ref_wav)
        window.toast.hide()  # the reference-loaded toast would cover the well
        shot("12-compare")

        window.compare_slot.clear()
        shot("13-compare-bempty")

        # Post-ship append (same append-only rule): the profile popover,
        # placed by the REAL chip entry point (the M5 placement fix — below
        # the header hairline, clear of the rail), then posed to the rich
        # armed state (user profile, 3 confirms, backup) so the shot shows
        # every row. A Qt.Popup is its own top-level window — invisible to
        # window.grab() — so this shot composites the popover's grab onto
        # the window frame at its global offset.
        from PySide6.QtCore import QPoint as _QPoint, QRect as _QRect
        from PySide6.QtGui import QColor as _QColor, QPainter as _QPainter, QPen as _QPen

        from rai_ui.theme._tokens_gen import (
            COLOR_BORDER_HAIRLINE as _POP_BORDER,
            COLOR_SURFACE_PANEL as _POP_SURFACE,
        )

        _run_analysis(app, window, drill_wav)
        window.nav.set_current("Tempo")
        window._open_profile_popover()  # real placement math
        window.profile_popover.set_state(
            profile_kind="user",
            relearned_date="2026-07-07",
            confirmed_count=3,
            backup_exists=True,
        )
        window.profile_popover.adjustSize()  # settle height for the posed rows
        app.processEvents()
        frame = window.grab()
        pop = window.profile_popover
        pop_offset = pop.frameGeometry().topLeft() - window.mapToGlobal(_QPoint(0, 0))
        painter = _QPainter(frame)
        # Offscreen, grab() of a WA_TranslucentBackground popup loses its QSS
        # panel background (the real screen paints it) — recreate the panel
        # chrome from the popover's own tokens, then draw the content grab.
        painter.setRenderHint(_QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(_QColor(_POP_SURFACE))
        painter.setPen(_QPen(_QColor(_POP_BORDER)))
        painter.drawRoundedRect(_QRect(pop_offset, pop.size()), 7, 7)
        painter.drawPixmap(pop_offset, pop.grab())
        painter.end()
        pop_path = os.path.join(outdir, "14-profile-popover.png")
        if not frame.save(pop_path):
            raise RuntimeError(f"could not save {pop_path}")
        saved.append(pop_path)
        window.profile_popover.hide()

        # Acceptance-gate fixtures, if the producer has them on disk.
        from validation.ground_truth import available_tracks

        for track in available_tracks():
            _run_analysis(app, window, track.path)
            window.nav.set_current("Tempo")
            stem = os.path.splitext(track.filename)[0]
            shot(f"gate-{stem}")

        window.close()
        app.processEvents()
    finally:
        for path in temp_wavs:
            try:
                os.unlink(path)
            except OSError:
                pass

    print(f"wrote {len(saved)} shots to {outdir}:")
    for path in saved:
        print(f"  {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
