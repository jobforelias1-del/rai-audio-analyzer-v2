"""RAI v3 main window: chrome, section stack, drag-drop, and analysis wiring.

Composition (M0, normal titled window — no native chrome integration):

    HeaderBar                                  (48px, C-01)
    NavRail | QStackedWidget                   (72px rail, C-03)
    StatusBar                                  (28px, C-04)

Stack pages: 0 = first-run hero (no nav button — unreachable after the first
result), then Overview/Tempo/Signal/Compare placeholders, then the Report
section, in nav order.

Analysis flow: ``open_path`` -> SessionState.begin -> AnalysisWorker on a
QThread -> generation-gated completion -> SessionState.finish/fail -> UI
slots react to session signals. The generation counter is the whole
concurrency story for M0: rapid re-drops simply orphan the older worker and
its result is dropped on arrival.
"""

from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QThread, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rai_ui.sections.placeholder import PlaceholderSection
from rai_ui.sections.report import ReportSection
from rai_ui.services import recent_files
from rai_ui.services.worker import AnalysisWorker
from rai_ui.state.session import SessionState
from rai_ui.widgets.empty_state import EmptyStateHero
from rai_ui.widgets.header import HeaderBar, format_file_meta
from rai_ui.widgets.nav_rail import SECTIONS, NavRail
from rai_ui.widgets.status_bar import StatusBar
from rai_ui.widgets.toast import Toast

WINDOW_TITLE = "RAI v3"

AUDIO_SUFFIXES = (".wav", ".aiff", ".aif", ".flac", ".mp3")
FILE_DIALOG_FILTER = "Audio files (*.wav *.aiff *.aif *.flac *.mp3)"

# Stack layout: hero first, then sections in nav order.
HERO_PAGE = 0
REPORT_PAGE = 1 + SECTIONS.index("Report")

# Placeholder titles per the approved C-18 copy — honest milestone promises.
_PLACEHOLDER_TITLES = {
    "Overview": "Metric cards arrive in M1",
    "Tempo": "Tempogram + candidates arrive in M1",
    "Signal": "Spectrum · stereo · dynamics arrive in M2",
    "Compare": "A/B compare arrives in M4",
}


def _local_audio_paths(urls: list[QUrl]) -> list[str]:
    """Local file paths from a drop payload, filtered to supported audio."""
    paths = []
    for url in urls:
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if path.lower().endswith(AUDIO_SUFFIXES):
            paths.append(path)
    return paths


class MainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1100, 720)

        self.session = SessionState(self)
        self._generation = 0
        self._threads: list[tuple[QThread, AnalysisWorker]] = []

        # -- chrome + stack ---------------------------------------------------
        self.header = HeaderBar(self)
        self.nav = NavRail(self)
        self.status = StatusBar(self)

        self.stack = QStackedWidget(self)
        self.hero = EmptyStateHero(self)
        self.stack.addWidget(self.hero)  # HERO_PAGE
        self._placeholders = {}
        for name in SECTIONS:
            if name == "Report":
                self.report_section = ReportSection(self)
                self.stack.addWidget(self.report_section)
            else:
                page = PlaceholderSection(_PLACEHOLDER_TITLES[name], parent=self)
                self._placeholders[name] = page
                self.stack.addWidget(page)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self.nav)
        middle.addWidget(self.stack, 1)
        outer.addLayout(middle, 1)
        outer.addWidget(self.status)
        self.setCentralWidget(central)

        self.toast = Toast(self)

        # -- wiring -----------------------------------------------------------
        self.nav.section_selected.connect(self._on_section_selected)
        self.header.browse_requested.connect(self._browse)
        self.hero.browse_requested.connect(self._browse)
        self.hero.open_recent.connect(self.open_path)

        self.session.working.connect(self.status.set_working)
        self.session.result_ready.connect(self._on_result_ready)
        self.session.analysis_failed.connect(self._on_analysis_failed)

        # Drag-drop init is a plain flag set, but the status bar promises the
        # capability, so report honestly if the platform refuses it.
        try:
            self.setAcceptDrops(True)
            dnd_ok = True
        except Exception:
            dnd_ok = False
        self.status.set_dnd(dnd_ok)

    # -- opening files ----------------------------------------------------------

    def open_path(self, path: str) -> None:
        """Start (or restart) analysis of ``path`` on a background thread."""
        self.session.begin(path)
        self._start_analysis(path)

    def _browse(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Open audio file", "", FILE_DIALOG_FILTER
        )
        if path:
            self.open_path(path)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and _local_audio_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _local_audio_paths(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            self.open_path(paths[0])

    # -- worker lifecycle ---------------------------------------------------------

    def _start_analysis(self, path: str) -> None:
        self._generation += 1
        self._prune_finished_threads()

        thread = QThread(self)
        worker = AnalysisWorker()  # no parent: moveToThread requires it
        # The generation tag rides on the worker itself; completion handlers
        # read it back via sender(). Bound-method connections + invokeMethod
        # are used deliberately: PySide6 functor connections (partial/lambda)
        # resolve their thread context unreliably across threads.
        worker._generation = self._generation
        worker.moveToThread(thread)
        worker.finished.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        self._threads.append((thread, worker))
        thread.start()
        QMetaObject.invokeMethod(
            worker, "run", Qt.ConnectionType.QueuedConnection, Q_ARG(str, path)
        )

    def _sender_is_current(self) -> bool:
        worker = self.sender()
        return worker is not None and getattr(worker, "_generation", None) == self._generation

    def _on_worker_finished(self, result, features, signal_obj, seconds) -> None:
        if not self._sender_is_current():
            return  # stale: a newer analysis superseded this one
        self.session.finish(result, features, signal_obj, seconds)

    def _on_worker_failed(self, message: str) -> None:
        if not self._sender_is_current():
            return
        self.session.fail(message)

    def _prune_finished_threads(self) -> None:
        self._threads = [(t, w) for (t, w) in self._threads if t.isRunning() or not t.isFinished()]

    def closeEvent(self, event) -> None:
        for thread, _worker in self._threads:
            thread.quit()
            thread.wait(2000)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.toast.isVisible():
            self.toast.reposition()

    # -- session reactions ---------------------------------------------------------

    def _on_section_selected(self, index: int) -> None:
        self.stack.setCurrentIndex(index + 1)  # +1: hero occupies page 0

    def _on_result_ready(self, result) -> None:
        import os

        self.header.show_file(
            os.path.basename(result.path),
            format_file_meta(result.duration, result.sr, result.channels),
        )
        self.status.set_analysis_seconds(self.session.analysis_seconds)
        self.report_section.set_result(result)
        recent_files.add_recent(result.path)
        self.hero.refresh_recent()
        # Report is M0's only data view — always land there on a fresh result.
        self.nav.set_current("Report")

    def _on_analysis_failed(self, message: str) -> None:
        self.status.set_failed()
        self.toast.show_message(f"Analysis failed — {message}")
