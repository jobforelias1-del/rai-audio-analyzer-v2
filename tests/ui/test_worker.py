"""Worker tests: real analysis on a synthetic drill WAV + stale-drop semantics.

The real-worker test exercises the full engine pipeline (load -> features ->
resolve -> loudness) on a QThread, exactly as the shell runs it. The
stale-generation test swaps in a manually-driven fake worker so the ordering
is deterministic — no sleeps, no races.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("soundfile")  # write_wav dependency

from PySide6.QtCore import Q_ARG, QMetaObject, QObject, QSettings, Qt, QThread, Signal, Slot

from rai_analyzer.synthetic import drill_pattern, write_wav

ANALYSIS_TIMEOUT_MS = 120_000


def make_fake_result(path, bpm=150.0):
    from rai_analyzer.contracts import AnalysisResult, Candidate, TempoResult

    tempo = TempoResult(
        primary_bpm=bpm,
        felt_bpm=None,
        candidates=[Candidate(bpm=bpm, score=0.9, salience=1.0)],
        ambiguous=False,
    )
    return AnalysisResult(path=path, duration=6.0, sr=22050, channels=1, tempo=tempo)


@pytest.fixture
def drill_wav(tmp_path):
    y = drill_pattern(150.0, duration=6.0)
    return write_wav(str(tmp_path / "drill150.wav"), y)


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )


def test_worker_analyzes_real_wav_on_thread(qtbot, drill_wav):
    from rai_ui.services.worker import AnalysisWorker

    worker = AnalysisWorker()
    thread = QThread()
    worker.moveToThread(thread)

    received = []
    worker.finished.connect(
        lambda r, f, s, secs, sig, md5: received.append((r, f, s, secs, sig, md5))
    )
    try:
        with qtbot.waitSignal(worker.finished, timeout=ANALYSIS_TIMEOUT_MS):
            thread.start()
            QMetaObject.invokeMethod(
                worker, "run", Qt.ConnectionType.QueuedConnection, Q_ARG(str, drill_wav)
            )
    finally:
        thread.quit()
        thread.wait(10_000)

    result, features, signal_obj, seconds, signal_result, md5 = received[0]
    assert result.path == drill_wav
    assert result.duration == pytest.approx(6.0, abs=0.25)
    # Plausible tempo: the 150 BPM drill may honestly resolve to an octave
    # partner, but never outside the musical range.
    assert 40.0 <= result.tempo.primary_bpm <= 320.0
    assert result.tempo.candidates, "candidate set must never be empty"
    assert seconds > 0.0
    assert features is not None
    assert signal_obj is not None and signal_obj.duration == pytest.approx(6.0, abs=0.25)
    # M2: the composed SignalResult rides fifth (R-M2-15) with sane physics —
    # a real drill pattern has positive crest and a mono width of exactly 0.
    assert signal_result is not None
    assert signal_result.dynamics.crest_db > 0.0
    assert signal_result.dynamics.peak_dbfs >= signal_result.dynamics.rms_dbfs
    assert signal_result.stereo.width_pct == 0.0  # synthetic drill WAV is mono
    assert 0.0 <= signal_result.bands.sub_pct <= 100.0
    assert signal_result.spectrum.freqs.size > 0
    # M3: the whole-file md5 rides sixth (same additive rule) and matches the
    # store helper's chunked-whole-file recipe exactly.
    from rai_ui.services import ground_truth_store

    assert md5 == ground_truth_store.file_md5(drill_wav)


def test_worker_metrics_failure_degrades_to_none(qtbot, drill_wav, monkeypatch):
    """R-M2-15: a metrics exception must NOT kill the analysis — the worker
    logs, degrades signal_result to None, and still emits finished."""
    import rai_analyzer.metrics.compute as metrics_compute

    from rai_ui.services.worker import AnalysisWorker

    def _boom(_signal):
        raise RuntimeError("metrics exploded")

    monkeypatch.setattr(metrics_compute, "compute_signal_result", _boom)

    worker = AnalysisWorker()
    received = []
    worker.finished.connect(
        lambda r, f, s, secs, sig, md5: received.append((r, f, s, secs, sig, md5))
    )
    with qtbot.waitSignal(worker.finished, timeout=ANALYSIS_TIMEOUT_MS):
        worker.run(drill_wav)  # direct call — same thread, deterministic

    result, features, signal_obj, seconds, signal_result, md5 = received[0]
    assert result is not None and result.tempo.candidates
    assert signal_result is None  # degraded, not fatal
    assert md5 is not None  # the md5 lane is independent of the metrics lane


def test_worker_failure_emits_last_traceback_line(qtbot, tmp_path):
    from rai_ui.services.worker import AnalysisWorker

    worker = AnalysisWorker()
    with qtbot.waitSignal(worker.failed, timeout=30_000) as blocker:
        worker.run(str(tmp_path / "does-not-exist.wav"))
    message = blocker.args[0]
    assert message
    assert "\n" not in message  # last line only, toast-sized


def test_open_path_end_to_end_populates_session(qtbot, drill_wav, isolated_settings):
    from rai_ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_path(drill_wav)

    session = window.session
    assert session.path == drill_wav
    assert session.last_result is not None
    assert 40.0 <= session.last_result.tempo.primary_bpm <= 320.0
    assert session.analysis_seconds is not None and session.analysis_seconds > 0.0
    assert session.last_features is not None
    assert session.last_signal_obj is not None
    # M2 plumbing proof: worker → MainWindow → session, fifth position intact.
    assert session.last_signal_result is not None
    assert session.last_signal_result.dynamics.crest_db > 0.0
    # M3 plumbing proof: the md5 rode sixth through MainWindow into the session.
    from rai_ui.services import ground_truth_store

    assert session.last_md5 == ground_truth_store.file_md5(drill_wav)


class _ManualWorker(QObject):
    """Never completes on its own; the test emits completions in a chosen order.

    Mirrors the real worker's M3 signature (5th ``object`` = SignalResult |
    None per R-M2-15, 6th ``object`` = md5 | None per R-M3-3, plus the
    ``profile_fallback`` notice MainWindow connects) so the stale-drop path
    is tested against the live contract.
    """

    finished = Signal(object, object, object, float, object, object)
    failed = Signal(str)
    profile_fallback = Signal(str)
    created: list = []

    def __init__(self):
        super().__init__()
        _ManualWorker.created.append(self)

    @Slot(str)
    def run(self, path):  # pragma: no cover - trivial
        self._path = path


def test_stale_generation_result_is_dropped(qtbot, monkeypatch, isolated_settings):
    import rai_ui.main_window as mw

    _ManualWorker.created = []
    monkeypatch.setattr(mw, "AnalysisWorker", _ManualWorker)

    window = mw.MainWindow()
    qtbot.addWidget(window)

    window.open_path("/tmp/first.wav")
    window.open_path("/tmp/second.wav")
    assert len(_ManualWorker.created) == 2
    first_worker, second_worker = _ManualWorker.created

    newer = make_fake_result("/tmp/second.wav", bpm=140.0)
    older = make_fake_result("/tmp/first.wav", bpm=90.0)

    with qtbot.waitSignal(window.session.result_ready):
        second_worker.finished.emit(newer, None, None, 0.5, None, None)

    results_after = []
    window.session.result_ready.connect(lambda r: results_after.append(r))
    first_worker.finished.emit(older, None, None, 2.0, None, None)  # stale — must be dropped
    qtbot.wait(50)

    assert results_after == []
    assert window.session.last_result is newer
    assert window.session.analysis_seconds == pytest.approx(0.5)
