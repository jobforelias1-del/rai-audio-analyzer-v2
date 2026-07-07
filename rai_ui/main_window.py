"""RAI v3 main window: chrome, section stack, drag-drop, and analysis wiring.

Composition (M1, normal titled window — no native chrome integration):

    HeaderBar                                  (48px, C-01)
    MeterBridge                                (76px, C-02 — collapsed mode only)
    NavRail | QStackedWidget | MetricRail      (72px nav C-03 · 236px rail C-07)
    StatusBar                                  (28px, C-04)

Stack pages: 0 = first-run hero (no nav button — unreachable after the first
result), then Overview placeholder, the real Tempo section (M1), the
Signal/Compare placeholders, then the Report section, in nav order.

The readout rail and the meter bridge are MainWindow-level chrome (ruling
R10): the rail persists across sections and hides only on the hero page; the
header's rail toggle folds it into the full-width bridge strip under the
header, and that choice persists via QSettings (``_ui_settings`` mirrors the
``recent_files._settings`` pattern so tests can monkeypatch it).

Analysis flow: ``open_path`` -> SessionState.begin -> AnalysisWorker on a
QThread -> generation-gated completion -> SessionState.finish/fail -> UI
slots react to session signals. The generation counter is the whole
concurrency story for M0/M1: rapid re-drops simply orphan the older worker
and its result is dropped on arrival. Every ``verdict_changed`` rebuilds the
Tempo view-model from the session (the payload fields are already stored
when it fires — the session's documented ordering contract) and pushes it to
the Tempo section, the rail, and the bridge, so the three surfaces can never
disagree.

M3 seams (ruling R6): hear / tiebreak / undo render live-looking and always
answer — MainWindow resolves their signals to the "arrives in M3" toasts.
"""

from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, QSettings, Qt, QThread, QUrl
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
from rai_ui.sections.tempo import TempoSection
from rai_ui.services import recent_files
from rai_ui.services.worker import AnalysisWorker
from rai_ui.state.session import SessionState
from rai_ui.state.tempo_view import build_tempo_view
from rai_ui.widgets.empty_state import EmptyStateHero
from rai_ui.widgets.header import HeaderBar, format_file_meta
from rai_ui.widgets.meter_bridge import MeterBridge
from rai_ui.widgets.metric_readout import MetricRail
from rai_ui.widgets.nav_rail import SECTIONS, NavRail
from rai_ui.widgets.status_bar import StatusBar
from rai_ui.widgets.toast import Toast

WINDOW_TITLE = "RAI v3"

AUDIO_SUFFIXES = (".wav", ".aiff", ".aif", ".flac", ".mp3")
FILE_DIALOG_FILTER = "Audio files (*.wav *.aiff *.aif *.flac *.mp3)"

# Stack layout: hero first, then sections in nav order.
HERO_PAGE = 0
TEMPO_PAGE = 1 + SECTIONS.index("Tempo")
REPORT_PAGE = 1 + SECTIONS.index("Report")

# Placeholder titles per the approved C-18 copy — honest milestone promises.
# Tempo shipped in M1 and is constructed as a real section below.
_PLACEHOLDER_TITLES = {
    "Overview": "Metric cards arrive in M1",
    "Signal": "Spectrum · stereo · dynamics arrive in M2",
    "Compare": "A/B compare arrives in M4",
}

# R6 toast copy — verbatim from the M1 architecture brief.
TOAST_TIEBREAK_M3 = "Tiebreak flow arrives in M3"
TOAST_HEAR_M3 = "Audio preview arrives in M3"

# QSettings key for the rail⇄bridge choice (ruling R10).
_RAIL_COLLAPSED_KEY = "ui/rail_collapsed"


def _ui_settings() -> QSettings:
    """QSettings for shell UI preferences (rail⇄bridge mode).

    Module-level and explicitly constructed with the app identity — the
    ``recent_files._settings`` pattern — so it works under pytest's bare
    QApplication and tests can monkeypatch it to a throwaway INI.
    """
    return QSettings(recent_files.ORGANIZATION, recent_files.APPLICATION)


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
            elif name == "Tempo":
                self.tempo_section = TempoSection(self)
                self.stack.addWidget(self.tempo_section)
            else:
                page = PlaceholderSection(_PLACEHOLDER_TITLES[name], parent=self)
                self._placeholders[name] = page
                self.stack.addWidget(page)

        # Readout surfaces (R10): rail right of the stack, bridge under the
        # header. Exactly one of them shows outside the hero page.
        self.rail = MetricRail(self)
        self.bridge = MeterBridge(self)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addWidget(self.bridge)
        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self.nav)
        middle.addWidget(self.stack, 1)
        middle.addWidget(self.rail)
        outer.addLayout(middle, 1)
        outer.addWidget(self.status)
        self.setCentralWidget(central)

        self.toast = Toast(self)

        # -- wiring -----------------------------------------------------------
        self.nav.section_selected.connect(self._on_section_selected)
        self.stack.currentChanged.connect(self._on_stack_page_changed)
        self.header.browse_requested.connect(self._browse)
        self.header.rail_toggle.clicked.connect(self._toggle_rail_mode)
        self.hero.browse_requested.connect(self._browse)
        self.hero.open_recent.connect(self.open_path)

        self.session.working.connect(self.status.set_working)
        self.session.working.connect(self.tempo_section.set_working)
        self.session.working.connect(self._on_working)
        self.session.verdict_changed.connect(self._on_verdict_changed)
        self.session.result_ready.connect(self._on_result_ready)
        self.session.analysis_failed.connect(self._on_analysis_failed)

        # M3 seams (R6): every live-looking action answers with a toast.
        self.tempo_section.hear_requested.connect(self._on_hear_requested)
        self.tempo_section.tiebreak_requested.connect(self._on_tiebreak_requested)
        for surface in (self.rail, self.bridge):
            surface.tiebreak_requested.connect(self._on_tiebreak_requested)
            surface.undo_requested.connect(self._on_tiebreak_requested)

        # Rail⇄bridge mode: restore the persisted choice (R10), then apply it
        # for the current (hero) page — both surfaces start hidden.
        self._rail_collapsed = bool(
            _ui_settings().value(_RAIL_COLLAPSED_KEY, False, type=bool)
        )
        self._apply_rail_mode()

        # First paint of the tempo surfaces from the (empty) session.
        self._refresh_tempo_views()

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

    # -- rail ⇄ bridge mode (R10) ---------------------------------------------------

    def _toggle_rail_mode(self) -> None:
        self._set_rail_collapsed(not self._rail_collapsed)

    def _set_rail_collapsed(self, collapsed: bool) -> None:
        self._rail_collapsed = bool(collapsed)
        settings = _ui_settings()
        settings.setValue(_RAIL_COLLAPSED_KEY, self._rail_collapsed)
        settings.sync()
        self._apply_rail_mode()

    def _apply_rail_mode(self) -> None:
        """Show exactly one readout surface — none on the hero page (R10)."""
        on_hero = self.stack.currentIndex() == HERO_PAGE
        self.rail.setVisible(not on_hero and not self._rail_collapsed)
        self.bridge.setVisible(not on_hero and self._rail_collapsed)
        self.header.set_rail_collapsed(self._rail_collapsed)

    def _on_stack_page_changed(self, _index: int) -> None:
        self._apply_rail_mode()

    # -- session reactions ---------------------------------------------------------

    def _on_section_selected(self, index: int) -> None:
        self.stack.setCurrentIndex(index + 1)  # +1: hero occupies page 0

    def _refresh_tempo_views(self) -> None:
        """Rebuild the one Tempo view-model and fan it out to all surfaces."""
        vm = build_tempo_view(
            self.session.last_result,
            self.session.last_features,
            self.session.verdict_state,
        )
        self.tempo_section.set_view(vm)
        self.rail.set_view(vm.readout)
        self.bridge.set_view(vm.readout)

    def _on_verdict_changed(self, _state) -> None:
        # The session stores payload fields BEFORE reducing (its documented
        # ordering contract), so rebuilding here always sees fresh data.
        self._refresh_tempo_views()

    def _on_working(self, active: bool) -> None:
        # The file chip names the file being analyzed from the moment work
        # starts — "no file loaded" (or the previous file's metadata) over a
        # live analysis would be dishonest. Real duration/rate/channels meta
        # replaces "analyzing…" on finish.
        if active and self.session.path:
            import os

            self.header.show_file(os.path.basename(self.session.path), "analyzing…")

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
        # Land on Tempo after a successful analysis (ruling R7); Report stays
        # one click away and renders the same result byte-verbatim.
        self.nav.set_current("Tempo")

    def _on_analysis_failed(self, message: str) -> None:
        self.status.set_failed()
        if self.session.path:
            import os

            self.header.show_file(
                os.path.basename(self.session.path), "analysis failed"
            )
        self.toast.show_message(f"Analysis failed — {message}")

    # -- M3 seams (R6): present-but-inert actions, never a dead click ---------------

    def _on_hear_requested(self, _bpm: float) -> None:
        self.toast.show_message(TOAST_HEAR_M3)

    def _on_tiebreak_requested(self) -> None:
        self.toast.show_message(TOAST_TIEBREAK_M3)
