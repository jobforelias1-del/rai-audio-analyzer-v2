"""Shell tests: window construction, nav, drag-drop, and session-driven UI.

Qt-dependent — the engine CI job has no Qt, so PySide6 is importorskip'd
before anything Qt-flavoured is touched. The theme package is built by a
parallel agent; the stylesheet test skips with a reason while it is absent
(everything else runs unstyled against a bare QApplication).
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QDragEnterEvent, QDropEvent

REPORT_PAGE = 5  # hero=0, Overview..Compare=1..4, Report=5


def _theme_ready() -> bool:
    """True once the parallel-built theme package (load_qss) has landed."""
    try:
        import rai_ui.theme as theme
    except ImportError:
        return False
    return callable(getattr(theme, "load_qss", None))


def make_fake_result(path="/tmp/beat.wav", bpm=150.0):
    from rai_analyzer.contracts import AnalysisResult, Candidate, Relationship, TempoResult

    tempo = TempoResult(
        primary_bpm=bpm,
        felt_bpm=bpm / 2,
        candidates=[
            Candidate(bpm=bpm, score=0.91, salience=1.0),
            Candidate(
                bpm=bpm / 2, score=0.62, salience=0.8, relationship=Relationship.OCTAVE_DOWN
            ),
        ],
        ambiguous=False,
    )
    return AnalysisResult(path=path, duration=6.0, sr=44100, channels=2, tempo=tempo)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    # Keep recent-files writes out of the user's real preferences.
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    from rai_ui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def test_stylesheet_applies_with_zero_parse_warnings(qapp, window):
    if not _theme_ready():
        pytest.skip("rai_ui.theme not present yet (built by a parallel agent)")
    from rai_ui.theme import load_qss

    messages = []
    old_handler = qInstallMessageHandler(lambda mode, ctx, msg: messages.append(msg))
    try:
        qapp.setStyleSheet(load_qss())
        window.show()
        qapp.processEvents()
    finally:
        qInstallMessageHandler(old_handler)
        qapp.setStyleSheet("")
    parse_warnings = [m for m in messages if "parse" in m.lower() and "stylesheet" in m.lower()]
    assert parse_warnings == []


def test_window_constructs(window):
    assert window.windowTitle() == "RAI v3"
    assert window.stack.currentIndex() == 0  # first-run hero
    assert window.session.last_result is None


def test_nav_switches_stack_pages(window, qtbot):
    for offset, name in enumerate(["Overview", "Tempo", "Signal", "Compare", "Report"]):
        window.nav.button(name).click()
        assert window.stack.currentIndex() == offset + 1, name


def test_study_button_is_ghost_and_disabled(window):
    study = window.nav.study_button
    assert not study.isEnabled()
    assert study.property("ghost") is True
    assert study.text() == "Study · soon"


def test_accept_drops_enabled(window):
    assert window.acceptDrops()
    assert window.status.right_label.text() == "drag-drop ready"


def test_drop_of_audio_file_calls_open_path(window, monkeypatch):
    opened = []
    monkeypatch.setattr(window, "open_path", lambda p: opened.append(p))

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/beat.wav")])
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dragEnterEvent(enter)
    assert enter.isAccepted()

    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(drop)
    assert opened == ["/tmp/beat.wav"]


def test_drag_of_non_audio_is_rejected(window):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/tmp/notes.txt")])
    enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    enter.ignore()  # events start accepted by default; handler must decide
    window.dragEnterEvent(enter)
    assert not enter.isAccepted()


def test_result_updates_chrome_and_switches_to_report(window, qtbot):
    result = make_fake_result()
    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(result, None, None, 1.23)

    assert window.stack.currentIndex() == REPORT_PAGE
    assert window.session.analysis_seconds == pytest.approx(1.23)
    assert window.header.file_name_label.text() == "beat.wav"
    assert "44.1 kHz" in window.header.file_meta_label.text()
    assert "stereo" in window.header.file_meta_label.text()
    assert "analysis 1.2 s" in window.status.left_label.text()
    assert window.report_section.text_edit.toPlainText() == result.to_report()


def test_failure_shows_toast_not_modal(window, qtbot):
    window.show()  # toast visibility requires a visible parent chain
    with qtbot.waitSignal(window.session.analysis_failed):
        window.session.fail("could not read file")
    assert window.toast.isVisible()
    assert "could not read file" in window.toast.label.text()
    assert "analysis failed" in window.status.left_label.text()


def test_recent_files_deduped_and_capped(window):
    from rai_ui.services import recent_files

    for path in ("/a.wav", "/b.wav", "/a.wav", "/c.wav", "/d.wav"):
        recent_files.add_recent(path)
    assert recent_files.recent_paths() == ["/d.wav", "/c.wav", "/a.wav"]
