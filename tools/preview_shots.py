"""Offscreen preview-shot harness for the M1 Tempo lane.

Renders the REAL app (create_app: fonts, theme QSS, pyqtgraph config) at
1280×860 offscreen, drives it through the M1 states with REAL analyses on
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
    gate-<fixture>   one Tempo shot per acceptance-gate WAV present on disk
                     (validation/ground_truth.py paths; the WAVs are
                     .gitignored so this is existence-guarded)

Settings are redirected to a throwaway temp INI so the harness never touches
the user's real recents or rail preference.

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
    """Point recent-files and UI prefs at a throwaway INI (never the user's)."""
    from PySide6.QtCore import QSettings

    import rai_ui.main_window as mw
    from rai_ui.services import recent_files

    ini_dir = tempfile.mkdtemp(prefix="rai_preview_settings_")

    def _tmp_settings(name: str):
        return lambda: QSettings(
            os.path.join(ini_dir, name), QSettings.Format.IniFormat
        )

    recent_files._settings = _tmp_settings("recent.ini")
    mw._ui_settings = _tmp_settings("ui.ini")


def _write_silent_wav() -> str:
    """A silent WAV — the engine's no-tempo shape, end to end."""
    import numpy as np

    from rai_analyzer.synthetic import write_wav

    fd, path = tempfile.mkstemp(prefix="rai_preview_silent_", suffix=".wav")
    os.close(fd)
    write_wav(path, np.zeros(int(SILENT_DURATION_S * SILENT_SR), dtype=np.float32), SILENT_SR)
    return path


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
