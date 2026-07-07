"""RAI v3 main window: chrome, section stack, drag-drop, and analysis wiring.

Composition (M1/M2, normal titled window — no native chrome integration):

    HeaderBar                                  (48px, C-01)
    MeterBridge                                (76px, C-02 — collapsed mode only)
    NavRail | QStackedWidget | MetricRail      (72px nav C-03 · 236px rail C-07)
    StatusBar                                  (28px, C-04)

Stack pages: 0 = first-run hero (no nav button — unreachable after the first
result), then the real Overview (M2), Tempo (M1), and Signal (M2) sections,
the Compare placeholder, then the Report section, in nav order.

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
Tempo, Overview, and Signal view-models from the session in one fan-out
(``_refresh_views`` — the payload fields, including ``last_signal_result``
and ``last_signal_obj``, are already stored when it fires: the session's
documented ordering contract) and pushes them to the three sections, the
rail, and the bridge, so no two surfaces can ever disagree.

M3 — the flagship is live (the R6 inert toasts are gone). MainWindow is the
one place the widget signals meet the services:

* ``tiebreak_requested`` (candidates header / rail / bridge) opens the C-14
  overlay over the candidates pane — ambiguous verdicts only (R-M3-6, tested
  through the view-model's ``show_tiebreak`` flag, never a verdict-kind
  branch);
* ``hear_requested`` plays the clicked ROW's click-grid premix through the
  ONE shared :class:`ClickPreview` engine and fires the verbatim design toast
  (R-M3-10); the overlay's preview buttons drive the same engine;
* overlay ``confirm_requested`` -> ``session.confirm(bpm)`` (reducer + journal
  append) + the design toast; ``undo_requested`` (candidates header ghost /
  rail / bridge inline links) -> ``session.undo()`` + the design toast — the
  session owns the transitions (R-M3-17/20);
* the header genre chip opens the profile popover (R-M3-11); its relearn /
  revert signals drive the :class:`RelearnController` (progress on the status
  bar, completion toasts per R-M3-16);
* click-preview lifecycle: ``begin``/``fail`` clear the engine (stale premixes
  from the previous file must never keep playing), a fresh result re-arms it
  with the new Features/PCM; closing the overlay stops playback (R-M3-8).
"""

from __future__ import annotations

from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, QSettings, Qt, QThread, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from rai_ui.sections.overview import OverviewSection
from rai_ui.sections.placeholder import PlaceholderSection
from rai_ui.sections.report import ReportSection
from rai_ui.sections.signal import SignalSection
from rai_ui.sections.tempo import TempoSection
from rai_ui.services import recent_files
from rai_ui.services.click_preview import ClickPreview
from rai_ui.services.relearn import (
    RelearnController,
    RelearnError,
    profile_state,
    revert_profile,
)
from rai_ui.services.worker import AnalysisWorker
from rai_ui.state.session import SessionState
from rai_ui.state.signal_view import build_overview_view, build_signal_view
from rai_ui.state.tempo_view import build_tempo_view
from rai_ui.widgets.empty_state import EmptyStateHero
from rai_ui.widgets.header import HeaderBar, format_file_meta
from rai_ui.widgets.meter_bridge import MeterBridge
from rai_ui.widgets.metric_readout import MetricRail
from rai_ui.widgets.nav_rail import SECTIONS, NavRail
from rai_ui.widgets.profile_popover import ProfilePopover
from rai_ui.widgets.status_bar import StatusBar
from rai_ui.widgets.toast import Toast

WINDOW_TITLE = "RAI v3"

AUDIO_SUFFIXES = (".wav", ".aiff", ".aif", ".flac", ".mp3")
FILE_DIALOG_FILTER = "Audio files (*.wav *.aiff *.aif *.flac *.mp3)"

# Stack layout: hero first, then sections in nav order.
HERO_PAGE = 0
OVERVIEW_PAGE = 1 + SECTIONS.index("Overview")
TEMPO_PAGE = 1 + SECTIONS.index("Tempo")
SIGNAL_PAGE = 1 + SECTIONS.index("Signal")
REPORT_PAGE = 1 + SECTIONS.index("Report")

# Placeholder titles per the approved C-18 copy — honest milestone promises.
# Tempo shipped in M1, Overview/Signal in M2; all three are constructed as
# real sections below.
_PLACEHOLDER_TITLES = {
    "Compare": "A/B compare arrives in M4",
}

# M3 toast copy — verbatim design copy on the single always-neutral slot
# (R-M3-16; the verdict block is the semantic voice, toasts only confirm).
TOAST_CONFIRM = "Ground truth saved — the engine learns from this"
TOAST_UNDO = "Reverted — verdict back to AMBIGUOUS"
# Relearn has no designed surface — RC copy of record (R-M3-16).
TOAST_RELEARN_DONE_FMT = "Profile relearned from {n} confirmed tracks"
TOAST_PROFILE_REVERTED = "Reverted to previous profile"


def hear_toast(bpm: float) -> str:
    """The table ▶ hear toast — ``bpm.toFixed(2)`` verbatim (04:738)."""
    return f"▶ click-grid preview · {bpm:.2f} BPM — audible in the app"

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

        # -- M3 services -------------------------------------------------------
        # ONE shared click-grid engine for the table's ▶ hear AND the tiebreak
        # cards (R-M3-8); plain Python (no QObject) — every call site below is
        # same-thread UI code, and tests swap the attribute for a fake.
        self.click_preview = ClickPreview()
        # Relearn runs on its own QThread via the controller (R-M3-11).
        self.relearn = RelearnController(self)

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
            elif name == "Overview":
                self.overview_section = OverviewSection(self)
                self.stack.addWidget(self.overview_section)
            elif name == "Signal":
                self.signal_section = SignalSection(self)
                self.stack.addWidget(self.signal_section)
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
        # The R-M3-11 profile popover (a Qt popup — outside clicks dismiss it).
        self.profile_popover = ProfilePopover(self)

        # -- wiring -----------------------------------------------------------
        self.nav.section_selected.connect(self._on_section_selected)
        self.stack.currentChanged.connect(self._on_stack_page_changed)
        self.header.browse_requested.connect(self._browse)
        self.header.rail_toggle.clicked.connect(self._toggle_rail_mode)
        self.hero.browse_requested.connect(self._browse)
        self.hero.open_recent.connect(self.open_path)

        self.session.working.connect(self.status.set_working)
        self.session.working.connect(self.tempo_section.set_working)
        self.session.working.connect(self.overview_section.set_working)
        self.session.working.connect(self.signal_section.set_working)
        self.session.working.connect(self._on_working)
        self.session.verdict_changed.connect(self._on_verdict_changed)
        self.session.result_ready.connect(self._on_result_ready)
        self.session.analysis_failed.connect(self._on_analysis_failed)

        # M3 flagship wiring: every entry point resolves to the real flow.
        self.tempo_section.hear_requested.connect(self._on_hear_requested)
        self.tempo_section.tiebreak_requested.connect(self._on_tiebreak_requested)
        self.tempo_section.undo_requested.connect(self._on_undo_requested)
        # The overlay's own signals, bubbled up through the section (R-M3-17
        # cut the seam; this is the Stage-3 sink side).
        self.tempo_section.preview_requested.connect(self._on_preview_requested)
        self.tempo_section.preview_stop_requested.connect(self._on_preview_stop_requested)
        self.tempo_section.confirm_requested.connect(self._on_confirm_requested)
        self.tempo_section.tiebreak_closed.connect(self._on_tiebreak_closed)
        for surface in (self.rail, self.bridge):
            surface.tiebreak_requested.connect(self._on_tiebreak_requested)
            surface.undo_requested.connect(self._on_undo_requested)

        # Profile popover + relearn (R-M3-11/16).
        self.header.profile_chip_clicked.connect(self._open_profile_popover)
        self.profile_popover.relearn_requested.connect(self._on_relearn_requested)
        self.profile_popover.revert_requested.connect(self._on_revert_requested)
        self.relearn.progress.connect(self._on_relearn_progress)
        self.relearn.finished.connect(self._on_relearn_finished)
        self.relearn.failed.connect(self._on_relearn_failed)

        # Rail⇄bridge mode: restore the persisted choice (R10), then apply it
        # for the current (hero) page — both surfaces start hidden.
        self._rail_collapsed = bool(
            _ui_settings().value(_RAIL_COLLAPSED_KEY, False, type=bool)
        )
        self._apply_rail_mode()

        # First paint of every section surface from the (empty) session.
        self._refresh_views()

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
        # R-M3-12: the one-shot "user profile unreadable" notice (bound-method
        # connection — cross-thread functor connections misdeliver, landmine 2).
        worker.profile_fallback.connect(self._on_profile_fallback)
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

    def _on_worker_finished(
        self, result, features, signal_obj, seconds, signal_result=None, md5=None
    ) -> None:
        if not self._sender_is_current():
            return  # stale: a newer analysis superseded this one
        self.session.finish(
            result,
            features,
            signal_obj,
            seconds,
            signal_result=signal_result,
            md5=md5,  # M3: worker-computed whole-file hash (additive, sixth)
        )

    def _on_worker_failed(self, message: str) -> None:
        if not self._sender_is_current():
            return
        self.session.fail(message)

    def _on_profile_fallback(self, message: str) -> None:
        # Only the CURRENT analysis may toast — a stale worker's fallback
        # notice would attribute the wrong run's profile state to this one.
        if self._sender_is_current():
            self.toast.show_message(message)

    def _prune_finished_threads(self) -> None:
        self._threads = [(t, w) for (t, w) in self._threads if t.isRunning() or not t.isFinished()]

    def closeEvent(self, event) -> None:
        self.click_preview.stop()  # release the audio stream before teardown
        self.relearn.close()  # quit+wait the relearn thread (landmine 1)
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

    def _refresh_views(self) -> None:
        """Rebuild all three section view-models and fan them out.

        One derivation point per section (build_tempo_view /
        build_overview_view / build_signal_view), all fed from the same
        session snapshot in one pass, so the Tempo surfaces, the Overview
        cards, the Signal cards, the rail, and the bridge can never show
        different numbers for the same measurement.
        """
        session = self.session
        tempo_vm = build_tempo_view(
            session.last_result,
            session.last_features,
            session.verdict_state,
            session.last_signal_result,
        )
        self.tempo_section.set_view(tempo_vm)
        self.rail.set_view(tempo_vm.readout)
        self.bridge.set_view(tempo_vm.readout)

        self.overview_section.set_view(
            build_overview_view(
                session.last_result,
                session.last_signal_obj,
                session.last_signal_result,
                session.verdict_state,
            )
        )
        self.signal_section.set_view(
            build_signal_view(
                session.last_result,
                session.last_signal_result,
                session.verdict_state,
            )
        )

    def _on_verdict_changed(self, _state) -> None:
        # The session stores payload fields BEFORE reducing (its documented
        # ordering contract), so rebuilding here always sees fresh data.
        self._refresh_views()

    def _on_working(self, active: bool) -> None:
        if active:
            # A new analysis is in flight: stop playback and drop every premix
            # built from the PREVIOUS file's PCM (R-M3-8 — a pointer-swap
            # buffer must never keep playing under the new file's name).
            self.click_preview.clear()
        # The file chip names the file being analyzed from the moment work
        # starts — "no file loaded" (or the previous file's metadata) over a
        # live analysis would be dishonest. Real duration/rate/channels meta
        # replaces "analyzing…" on finish.
        if active and self.session.path:
            import os

            self.header.show_file(os.path.basename(self.session.path), "analyzing…")

    def _on_result_ready(self, result) -> None:
        import os

        # Arm the click engine with the fresh payload (the session's ordering
        # contract guarantees last_features/last_signal_obj are already set).
        self.click_preview.set_source(
            self.session.last_features, self.session.last_signal_obj
        )
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
        # begin() already cleared the engine; clearing again keeps the fail
        # path self-sufficient (no source, no playback, empty cache).
        self.click_preview.clear()
        self.status.set_failed()
        if self.session.path:
            import os

            self.header.show_file(
                os.path.basename(self.session.path), "analysis failed"
            )
        self.toast.show_message(f"Analysis failed — {message}")

    # -- M3 flagship: tiebreak / hear / undo / confirm --------------------------------

    def _on_hear_requested(self, bpm: float) -> None:
        """▶ hear previews the clicked ROW's bpm (R-M3-10) + the design toast.

        The toast fires unconditionally — verbatim demo behavior (04:738);
        a missing audio device degrades inside the service with a log, never
        a crash and never a dead click.
        """
        self.click_preview.preview(bpm)
        self.toast.show_message(hear_toast(bpm))

    def _on_tiebreak_requested(self) -> None:
        """Open the C-14 overlay — ambiguous verdicts only (R-M3-6).

        The gate reads the view-model's ``show_tiebreak`` flag (the derived
        "this verdict has a tiebreak entry point" truth) rather than
        branching on verdict kinds here. In confirmed state there is no
        entry point — undo first (R-M3-6/18). The rail/bridge buttons are
        visible on any section, so land on Tempo where the overlay lives.
        """
        if not self.tempo_section.view().readout.verdict.show_tiebreak:
            return
        self.nav.set_current("Tempo")
        self.tempo_section.open_tiebreak()

    def _on_undo_requested(self) -> None:
        """session.undo() owns the transition (R-M3-17/20); toast on success.

        The reducer's guard is the truth: if nothing was undoable (a stale
        click racing a state change), the state is unchanged and no toast
        fires — "Reverted" must never announce a revert that didn't happen.
        """
        before = self.session.verdict_state
        self.session.undo()
        if self.session.verdict_state is not before:
            self.toast.show_message(TOAST_UNDO)

    def _on_confirm_requested(self, bpm: float) -> None:
        """Overlay confirm -> session.confirm(bpm) + the design toast.

        Confirm stops playback (design §3.3): the overlay already emitted its
        own preview stop, but a table-originated ▶ hear may still be running —
        stop the shared engine outright (idempotent).
        """
        self.click_preview.stop()
        before = self.session.verdict_state
        self.session.confirm(bpm)
        if self.session.verdict_state is not before:
            self.toast.show_message(TOAST_CONFIRM)

    def _on_preview_requested(self, bpm: float) -> None:
        # Tiebreak card preview: same engine as ▶ hear; starting one stops the
        # previous (pointer-swap when already playing, D3). No toast — only
        # the table's hear cell has designed toast copy (recon §5).
        self.click_preview.preview(bpm)

    def _on_preview_stop_requested(self) -> None:
        self.click_preview.stop()

    def _on_tiebreak_closed(self) -> None:
        # Overlay close stops playback (R-M3-8) — including a table-originated
        # preview; the overlay's own stop signal only covers its cards.
        self.click_preview.stop()

    # -- M3 flagship: profile popover + relearn (R-M3-11) ------------------------------

    def _open_profile_popover(self) -> None:
        """Render fresh profile truth into the popover and pop it on the chip."""
        state = profile_state()
        self.profile_popover.set_state(
            profile_kind=state.kind,
            relearned_date=state.relearned_at,
            confirmed_count=state.confirmed_count,
            backup_exists=state.backup_exists,
        )
        chip = self.header.genre_chip
        corner = chip.mapToGlobal(QPoint(chip.width(), chip.height() + 6))
        self.profile_popover.open_at(
            QPoint(corner.x() - self.profile_popover.width(), corner.y())
        )

    def _on_relearn_requested(self) -> None:
        self.profile_popover.hide()
        if self.relearn.start():
            # A determinate count arrives with the first progress signal.
            self.status.set_relearn_progress("relearning…")

    def _on_relearn_progress(self, done: int, total: int) -> None:
        self.status.set_relearn_progress(f"relearning {done}/{total}")

    def _on_relearn_finished(self, report) -> None:
        self.status.set_relearn_progress(None)
        self.toast.show_message(TOAST_RELEARN_DONE_FMT.format(n=report.learned))

    def _on_relearn_failed(self, message: str) -> None:
        self.status.set_relearn_progress(None)
        # RelearnError messages are written for humans and pass verbatim.
        self.toast.show_message(message)

    def _on_revert_requested(self) -> None:
        self.profile_popover.hide()
        try:
            revert_profile()
        except RelearnError as exc:
            self.toast.show_message(str(exc))
            return
        self.toast.show_message(TOAST_PROFILE_REVERTED)
