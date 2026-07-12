"""RAI v3 main window: chrome, section stack, drag-drop, and analysis wiring.

Composition (M1/M2, normal titled window — no native chrome integration):

    HeaderBar                                  (48px, C-01)
    MeterBridge                                (76px, C-02 — collapsed mode only)
    NavRail | QStackedWidget | MetricRail      (72px nav C-03 · 236px rail C-07)
    StatusBar                                  (28px, C-04)

Stack pages: 0 = first-run hero (no nav button — unreachable after the first
result), then the real Overview (M2), Tempo (M1), Signal (M2), Compare (M4)
and Report sections, in nav order.

M4 — Compare A/B: drops route by ACTIVE page (R-M4-1 — Compare = B,
anywhere else = A), the B lane lives in :class:`CompareSlot` (persistent
reference, R-M4-2; mutually-exclusive with A/relearn, R-M4-3), and
``_refresh_compare`` joins session A-state with the slot's B-state into ONE
``build_compare_view`` pass. The Report confirmed-truth line is GUI chrome
(``ReportBanner``, R-M4-11) — the copyable ``to_report()`` bytes stay frozen.

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
* ``hear_requested`` toggles the clicked ROW's click-grid premix through the
  ONE shared :class:`ClickPreview` engine (R-M3-10/21: clicking the playing
  row STOPS it, any other row switches the preview — ``toggle`` is the
  service's own same-bpm semantics) and fires the verbatim design toast ONLY
  when playback actually starts (never on stop, never on a dead device); the
  overlay's preview buttons drive the same engine. The table's ⏸ stop cell
  follows the SERVICE: it is set from post-toggle ``playing_bpm``, cleared by
  the engine's ``stopped`` signal, and cleared when a tiebreak-card preview
  takes the engine over (a pointer swap keeps playing and never emits
  ``stopped`` by contract, so that takeover is cleared explicitly at the one
  card-preview entry point);
* overlay ``confirm_requested`` -> ``session.confirm(bpm)`` (reducer + journal
  append) + a toast that BRANCHES on the returned :class:`ConfirmOutcome`
  (persistence honesty — the design toast only fires when a journal record
  actually landed; an accepted-but-unpersisted confirm/undo gets the RC
  "session only" copy, a refused one gets no toast); ``undo_requested``
  (candidates header ghost / rail / bridge inline links) -> ``session.undo()``
  with the same outcome branching — the session owns the transitions
  (R-M3-17/20). Undo additionally CLEARS the tiebreak selection (04:862
  ``chosenIdx:null`` — confirm KEEPS it, undo is the one clearing transition);
* the header genre chip opens the profile popover (R-M3-11); its relearn /
  revert signals drive the :class:`RelearnController` (progress on the status
  bar, one terminal ``finished(ok, message)`` toast per R-M3-16);
* mutual exclusion (adversarial-review fix): while a relearn is running every
  analysis entry point (drop/browse/recents/``open_path``) refuses with a
  toast, and while an analysis is in flight (WORKING) relearn refuses with a
  toast — the engine's fingerprint load cache is path-keyed and content-blind,
  so letting the two overlap can tear a resolve mid-flight (these gates are
  load-bearing, not cosmetic);
* click-preview lifecycle: ``begin``/``fail`` clear the engine (stale premixes
  from the previous file must never keep playing), a fresh result re-arms it
  with the new Features/PCM; closing the overlay stops playback (R-M3-8). The
  engine's ``stopped`` signal (natural EOF, device death, external stop) feeds
  back into the overlay AND the candidate table so a card can never keep
  pulsing "previewing" — and a hear cell can never keep saying "stop" — over
  silence.
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

from rai_ui.sections.compare import CompareSection
from rai_ui.sections.overview import OverviewSection
from rai_ui.sections.placeholder import PlaceholderSection
from rai_ui.sections.report import ReportSection
from rai_ui.sections.signal import SignalSection
from rai_ui.sections.tempo import TempoSection
from rai_ui.services import recent_files
from rai_ui.services.click_preview import ClickPreview
from rai_ui.services.compare_slot import CompareSlot
from rai_ui.services.relearn import (
    RELEARN_DONE_MESSAGE_FMT,
    RelearnController,
    RelearnError,
    profile_state,
    revert_profile,
    sweep_orphan_tmp_profiles,
)
from rai_ui.services.worker import AnalysisWorker
from rai_ui.state.compare_view import build_compare_view
from rai_ui.state.session import SessionState
from rai_ui.state.verdict import VerdictKind
from rai_ui.state.signal_view import build_overview_view, build_signal_view
from rai_ui.state.tempo_view import build_tempo_view
from rai_ui.widgets.empty_state import EmptyStateHero
from rai_ui.widgets.header import HeaderBar, format_file_meta
from rai_ui.widgets.meter_bridge import MeterBridge
from rai_ui.widgets.metric_readout import MetricRail
from rai_ui.widgets.nav_rail import SECTIONS, NavRail
from rai_ui.widgets.profile_popover import (
    POPOVER_GAP,
    ProfilePopover,
    anchor_position,
)
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
COMPARE_PAGE = 1 + SECTIONS.index("Compare")
REPORT_PAGE = 1 + SECTIONS.index("Report")

# Placeholder titles per the approved C-18 copy — honest milestone promises.
# Every nav section is a real page as of M4 (Tempo M1, Overview/Signal M2,
# Compare M4); the machinery stays so a future section fails loudly here.
_PLACEHOLDER_TITLES: dict[str, str] = {}

# M3 toast copy — verbatim design copy on the single always-neutral slot
# (R-M3-16; the verdict block is the semantic voice, toasts only confirm).
# The design toasts fire ONLY when the journal record actually landed
# (ConfirmOutcome.persisted); a confirm/undo the reducer accepted but the
# store could not persist (no file hash, or the append raised) gets the
# honest RC "session only" copy instead — the UI never asserts a persistence
# that never happened (adversarial-review finding, persistence honesty).
TOAST_CONFIRM = "Ground truth saved — the engine learns from this"
TOAST_UNDO = "Reverted — verdict back to AMBIGUOUS"
TOAST_CONFIRM_SESSION_ONLY = "Confirmed — session only (couldn't save to disk)"
TOAST_UNDO_SESSION_ONLY = "Reverted — session only (couldn't save to disk)"
# Relearn has no designed surface — RC copy of record (R-M3-16). The success
# message aliases the controller's own terminal copy so they cannot diverge.
TOAST_RELEARN_DONE_FMT = RELEARN_DONE_MESSAGE_FMT
TOAST_PROFILE_REVERTED = "Reverted to previous profile"
# Analysis ⇄ relearn mutual exclusion (RC copy — no designed surface). The
# gates are load-bearing: the engine's fingerprint load cache is path-keyed
# and content-blind, so an analysis racing a relearn's profile publish can
# score one verdict against two different profiles (review finding 18).
TOAST_RELEARN_BLOCKED_BY_ANALYSIS = "Analysis running — relearn once it finishes"
TOAST_ANALYSIS_BLOCKED_BY_RELEARN = "Relearning — drop ignored until it finishes"
# M4 Compare lane (R-M4-1/3). The loaded toast is design copy VERBATIM
# (04:875: '{name} analyzed — reference loaded'); the rest is RC copy in the
# M3 mutual-exclusion tone (the B-side refusals live in compare_slot). The
# vice-versa gates below are as load-bearing as the relearn pair: a B worker
# reads the same path-keyed fingerprint cache (review finding 18).
TOAST_REFERENCE_LOADED_FMT = "{name} analyzed — reference loaded"
TOAST_REFERENCE_FAILED_FMT = "Reference analysis failed — {message}"
TOAST_ANALYSIS_BLOCKED_BY_REFERENCE = "Reference analyzing — drop ignored until it finishes"
TOAST_RELEARN_BLOCKED_BY_REFERENCE = "Reference analyzing — relearn once it finishes"


def hear_toast(bpm: float) -> str:
    """The table ▶ hear toast — ``bpm.toFixed(2)`` verbatim (04:738)."""
    return f"▶ click-grid preview · {bpm:.2f} BPM — audible in the app"

# QSettings key for the rail⇄bridge choice (ruling R10).
_RAIL_COLLAPSED_KEY = "ui/rail_collapsed"

# A-lane stragglers that outlive closeEvent's bounded wait are detached from
# the window's destruction chain and parked here until process exit —
# destroying a running QThread is a Qt qFatal hard abort, and letting GC do
# it is heap corruption (the compare_slot/relearn recipe, retrofitted here
# 2026-07-12 after the CI ui-offscreen SIGSEGV).
_ORPHANED_THREADS: list[tuple[QThread, AnalysisWorker]] = []


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
        # M5 hygiene: sweep any relearn staging temp (*.tmp-<pid>) stranded by
        # a hard kill. Startup is the one provably-safe moment — no relearn
        # can be running before the window exists — and this is the sweep's
        # ONLY call site (see the service docstring; pinned by tests).
        sweep_orphan_tmp_profiles()
        # M4: the persistent Compare B lane (R-M4-2) — its own workers and
        # generation counter; refuses while A works or a relearn runs
        # (R-M4-3). The gates are same-thread callables; the relearn probe is
        # a closure over the attribute so tests can swap the controller.
        self.compare_slot = CompareSlot(
            self,
            a_working=self._analysis_in_flight,
            relearn_running=lambda: self.relearn.is_running(),
        )

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
            elif name == "Compare":
                self.compare_section = CompareSection(self)
                self.stack.addWidget(self.compare_section)
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
        self.session.working.connect(self.compare_section.set_working)
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

        # M4 Compare wiring (R-M4-1/2): the section's user intents resolve
        # here; the slot's lifecycle feeds the compare refresh + toasts. All
        # bound-method connections (landmine 2 discipline).
        self.compare_section.browse_b_requested.connect(self._browse_reference)
        self.compare_section.clear_b_requested.connect(self._on_clear_reference)
        self.compare_slot.changed.connect(self._refresh_compare)
        self.compare_slot.loaded.connect(self._on_reference_loaded)
        self.compare_slot.failed.connect(self._on_reference_failed)
        self.compare_slot.profile_fallback.connect(self.toast.show_message)

        # Profile popover + relearn (R-M3-11/16).
        self.header.profile_chip_clicked.connect(self._open_profile_popover)
        self.profile_popover.relearn_requested.connect(self._on_relearn_requested)
        self.profile_popover.revert_requested.connect(self._on_revert_requested)
        self.relearn.progress.connect(self._on_relearn_progress)
        # The controller's single terminal signal: finished(ok, message) for
        # success, failure AND cancellation — there is no failed signal.
        self.relearn.finished.connect(self._on_relearn_finished)

        # Playback-state honesty (findings 7/10/15 + R-M3-21): the engine's
        # ``stopped`` signal — natural EOF, device death, or an external stop
        # — resets the tiebreak card's ▶/⏸ state AND the candidate table's
        # ⏸ stop cell so neither claims playback over silence and the next
        # click starts fresh instead of dead-toggling. Bound-method
        # connection (landmine 2 discipline), main-thread by the service's
        # contract (the audio callback never emits).
        self.click_preview.stopped.connect(self._on_preview_stopped)

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
        """Start (or restart) analysis of ``path`` on a background thread.

        EVERY analysis entry point funnels through here (drop, browse, hero
        recents, tests), so this is where the relearn⇄analysis mutual
        exclusion gates the analysis side: a relearn's atomic profile publish
        plus the engine's path-keyed, content-blind fingerprint cache means a
        concurrent analysis could score one verdict against two profiles
        (review finding 18) — refuse honestly with a toast instead.
        """
        if self.relearn.is_running():
            self.toast.show_message(TOAST_ANALYSIS_BLOCKED_BY_RELEARN)
            return
        # M4 vice-versa gate (R-M4-3): the lanes are mutually exclusive —
        # an A analysis racing a B worker shares the same content-blind
        # fingerprint cache the relearn gate protects against.
        if self.compare_slot.is_working():
            self.toast.show_message(TOAST_ANALYSIS_BLOCKED_BY_REFERENCE)
            return
        self.session.begin(path)
        self._start_analysis(path)

    def open_reference(self, path: str) -> None:
        """Load (or replace) the Compare reference B with ``path`` (R-M4-1).

        The slot owns the R-M4-3 refusal gates and returns toast-ready copy
        when it declines; a ``None`` return means the B analysis started.
        """
        refusal = self.compare_slot.start(path)
        if refusal is not None:
            self.toast.show_message(refusal)

    def _analysis_in_flight(self) -> bool:
        """The A lane's WORKING truth (the slot's injected gate probe).

        Reads the reduced verdict rather than thread state — the M3
        postscript rule (gates flip before terminal relays) makes this safe
        from completion handlers.
        """
        return self.session.verdict_state.kind is VerdictKind.WORKING

    def _browse(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "Open audio file", "", FILE_DIALOG_FILTER
        )
        if path:
            self.open_path(path)

    def _browse_reference(self) -> None:
        # The B-empty chip IS the browse affordance (04:456, R-M4-1).
        path, _selected = QFileDialog.getOpenFileName(
            self, "Open reference audio file", "", FILE_DIALOG_FILTER
        )
        if path:
            self.open_reference(path)

    def _on_clear_reference(self) -> None:
        # The chip's ✕ — the ONE clearing act (R-M4-2). Toast-less like the
        # approved demo's clearB; the refresh rides the slot's changed signal.
        self.compare_slot.clear()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and _local_audio_paths(event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = _local_audio_paths(event.mimeData().urls())
        if paths:
            event.acceptProposedAction()
            # R-M4-1 drop routing: a WAV dropped while Compare is the ACTIVE
            # page loads/replaces B; anywhere else it is A (untouched M0
            # behavior). With no file loaded the Compare screen renders
            # nothing (R-M4-13), so the drop falls through to A rather than
            # feeding an invisible B analysis (authored guard, flagged).
            on_compare = (
                self.stack.currentIndex() == COMPARE_PAGE
                and self.session.verdict_state.kind is not VerdictKind.NO_FILE
            )
            if on_compare:
                self.open_reference(paths[0])
            else:
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
        # RelearnController.close() = cancel() + a BOUNDED wait (2 s, never
        # the old unbounded-in-N 10 s freeze); a straggler is detached and
        # leaked deliberately rather than qFatal-ing (landmine 1 / review 11).
        self.relearn.close()
        self.compare_slot.close()  # M4: the B lane's own bounded teardown
        # A-lane bounded teardown, SAME recipe as compare_slot/relearn: a
        # compute-bound analysis worker that outlives the wait (quit() cannot
        # interrupt resolve_tempo mid-flight) is detached and parked —
        # dropping the wrappers instead lets a later GC pass destroy a
        # RUNNING QThread (Qt hard abort / heap corruption; this was the
        # 2026-07-12 CI ui-offscreen SIGSEGV, reproducing on slow runners
        # where fingerprint scoring exceeds the 2 s grace).
        for thread, worker in self._threads:
            thread.quit()
            if not thread.wait(2000):
                thread.setParent(None)  # out of the destruction chain
                _ORPHANED_THREADS.append((thread, worker))
        self._threads = [
            pair for pair in self._threads if pair not in _ORPHANED_THREADS
        ]
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
        # M4: the Compare view rides the same fan-out (plus the slot's own
        # changed signal), and the Report banner mirrors the verdict truth
        # (R-M4-11 — chrome only; to_report() bytes are never touched).
        self._refresh_compare()
        state = session.verdict_state
        self.report_section.banner.set_state(
            state.confirmed_bpm
            if state.kind is VerdictKind.CONFIRMED_HUMAN
            else None
        )

    def _refresh_compare(self) -> None:
        """Rebuild the Compare view-model from session A-state + the B slot.

        The R-M4-13 nav gate: before any file has loaded (NO_FILE) the
        section renders nothing at all. The M3 blank doctrine is applied to
        the A side HERE (WORKING/ERROR pass ``None`` — the exact
        BLANK_VERDICT_KINDS rule the other builders apply internally); the B
        side comes from the persistent slot and is never blanked by A's
        lifecycle (R-M4-2).
        """
        kind = self.session.verdict_state.kind
        if kind is VerdictKind.NO_FILE:
            self.compare_section.set_view(None)
            return
        blank_a = kind in (VerdictKind.WORKING, VerdictKind.ERROR)
        self.compare_section.set_view(
            build_compare_view(
                None if blank_a else self.session.last_result,
                None if blank_a else self.session.last_signal_result,
                self.compare_slot.result,
                self.compare_slot.signal_result,
                self.compare_slot.status,
            )
        )

    def _on_reference_loaded(self, result) -> None:
        import os

        # Design toast verbatim (04:875) — fires only for a CURRENT B
        # completion (the slot's generation gate already dropped stale ones).
        self.toast.show_message(
            TOAST_REFERENCE_LOADED_FMT.format(name=os.path.basename(result.path))
        )

    def _on_reference_failed(self, message: str) -> None:
        # RC copy — the design never drew a failing B; the slot has already
        # restored the previous reference (or EMPTY), honestly.
        self.toast.show_message(TOAST_REFERENCE_FAILED_FMT.format(message=message))

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
        """▶ hear is a truthful toggle on the clicked ROW's bpm (R-M3-10/21).

        Clicking the playing row STOPS it; any other row switches the preview
        (``ClickPreview.toggle`` — the service's own same-bpm semantics, so a
        stale cell can never fork the truth). The design toast (04:738) fires
        ONLY when playback actually starts — never on the stop leg, and never
        when a missing/failed audio device made the start a no-op (the
        service degrades with a log; the toast must not announce audio that
        isn't audible). Start truth is read back from the SERVICE
        (``playing_bpm`` after the toggle), and the same float — exact
        equality with the service's cache keys, the documented comparison —
        drives the table's ⏸ stop cell.
        """
        self.click_preview.toggle(bpm)
        playing = self.click_preview.playing_bpm
        started = playing is not None and playing == float(bpm)
        self.tempo_section.set_playing_bpm(float(bpm) if started else None)
        if started:
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
        """session.undo() owns the transition (R-M3-17/20); outcome-branched
        toast, and the tiebreak selection is CLEARED.

        The reducer's guard is the truth: if nothing was undoable (a stale
        click racing a state change), the state is unchanged and no toast
        fires — "Reverted" must never announce a revert that didn't happen.
        An accepted undo whose retraction record could not be journaled gets
        the honest "session only" copy (the confirmation will resurrect on
        the next boot — the design toast must not promise otherwise).

        Design truth (04:862, recon §2.4): undo sets ``chosenIdx:null`` —
        confirm KEEPS the selection, dismiss keeps it, undo is the ONE
        transition that clears it. Without the clear, reopening the overlay
        after an undo shows the retracted card still selected with the
        confirm footer armed — one stray Space away from re-saving the very
        ground truth the user just deliberately retracted.
        """
        outcome = self.session.undo()
        if not outcome.accepted:
            return
        self.tempo_section.candidates.tiebreak.clear_selection()
        self.toast.show_message(
            TOAST_UNDO if outcome.persisted else TOAST_UNDO_SESSION_ONLY
        )

    def _on_confirm_requested(self, bpm: float) -> None:
        """Overlay confirm -> session.confirm(bpm) + the outcome-branched toast.

        Confirm stops playback (design §3.3): the overlay already emitted its
        own preview stop, but a table-originated ▶ hear may still be running —
        stop the shared engine outright (idempotent).

        Toast honesty: the design's "Ground truth saved" fires only when the
        journal append actually landed (``ConfirmOutcome.persisted``); an
        accepted confirm without a file hash or with a failed write keeps the
        in-session state (losing the click over a disk hiccup would be worse)
        but says so — "session only". A refused confirm stays silent.
        """
        self.click_preview.stop()
        outcome = self.session.confirm(bpm)
        if not outcome.accepted:
            return
        self.toast.show_message(
            TOAST_CONFIRM if outcome.persisted else TOAST_CONFIRM_SESSION_ONLY
        )

    def _on_preview_requested(self, bpm: float) -> None:
        # Tiebreak card preview: same engine as ▶ hear; starting one stops the
        # previous (pointer-swap when already playing, D3). No toast — only
        # the table's hear cell has designed toast copy (recon §5).
        self.click_preview.preview(bpm)
        # The takeover ends any table-originated preview, but a pointer swap
        # keeps the stream playing and therefore never emits ``stopped`` (the
        # service's documented contract) — so the table's ⏸ stop cell is
        # cleared HERE, at the one entry point every card preview funnels
        # through (button click and the overlay's Space key alike). R-M3-21:
        # the cell must not claim a preview the overlay now owns, even when
        # the card's bpm equals the row's.
        self.tempo_section.set_playing_bpm(None)

    def _on_preview_stop_requested(self) -> None:
        self.click_preview.stop()

    def _on_preview_stopped(self) -> None:
        # The service says playback ended (natural EOF, a device that died,
        # or an explicit stop that ended live playback): reset the overlay's
        # card to '▶ preview click grid' AND the table's hear cell to
        # '▶ hear' (R-M3-21 — the cell follows the service, not click
        # bookkeeping) WITHOUT re-emitting a stop into the already-stopped
        # engine. Idempotent — a stop the overlay or the hear toggle itself
        # initiated finds its slot already cleared.
        self.tempo_section.candidates.tiebreak.preview_ended()
        self.tempo_section.set_playing_bpm(None)

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
        # Placement (M5 backlog item 2): chip-aligned but occlusion-free —
        # below the header hairline, dodging the rail / clearing the bridge.
        # The math lives in anchor_position (pure, unit-tested); this site
        # only gathers the global coordinates of whatever is visible.
        chip = self.header.genre_chip
        self.profile_popover.open_at(
            anchor_position(
                chip_right_x=chip.mapToGlobal(QPoint(chip.width(), 0)).x(),
                header_bottom_y=self.header.mapToGlobal(
                    QPoint(0, self.header.height())
                ).y(),
                popover_width=self.profile_popover.width(),
                rail_left_x=(
                    self.rail.mapToGlobal(QPoint(0, 0)).x()
                    if self.rail.isVisible()
                    else None
                ),
                bridge_bottom_y=(
                    self.bridge.mapToGlobal(QPoint(0, self.bridge.height())).y()
                    if self.bridge.isVisible()
                    else None
                ),
                min_x=self.mapToGlobal(QPoint(0, 0)).x() + POPOVER_GAP,
                # Screen-bottom clamp (review finding 07-12): a Qt.Popup gets
                # no automatic screen-fitting — without this, a low-dragged
                # window leaves the popover's lower rows unreachable.
                screen_bottom_y=(
                    self.screen().availableGeometry().y()
                    + self.screen().availableGeometry().height()
                    if self.screen() is not None
                    else None
                ),
                popover_height=self.profile_popover.sizeHint().height(),
            )
        )

    def _on_relearn_requested(self) -> None:
        self.profile_popover.hide()
        # Mutual exclusion, relearn side (review finding 18): while an
        # analysis is in flight (the session's WORKING truth) a relearn's
        # profile publish + cache clear could land mid-resolve — candidates
        # scored before the clear use the old profile, candidates after use
        # the new one, presented as ONE measurement. Refuse with a toast.
        if self.session.verdict_state.kind is VerdictKind.WORKING:
            self.toast.show_message(TOAST_RELEARN_BLOCKED_BY_ANALYSIS)
            return
        # M4 (R-M4-3): a B worker resolves against the same path-keyed
        # fingerprint cache — the relearn gate covers both analysis lanes.
        if self.compare_slot.is_working():
            self.toast.show_message(TOAST_RELEARN_BLOCKED_BY_REFERENCE)
            return
        if self.relearn.start():
            # A determinate count arrives with the first progress signal.
            self.status.set_relearn_progress("relearning…")

    def _on_relearn_progress(self, done: int, total: int) -> None:
        self.status.set_relearn_progress(f"relearning {done}/{total}")

    def _on_relearn_finished(self, ok: bool, message: str) -> None:
        # The single terminal path — success ("Profile relearned from N
        # confirmed tracks"), failure (human RelearnError text verbatim) and
        # cancellation all arrive here with a toast-ready message.
        del ok  # the message already carries the outcome, worded for humans
        self.status.set_relearn_progress(None)
        self.toast.show_message(message)

    def _on_revert_requested(self) -> None:
        self.profile_popover.hide()
        try:
            revert_profile()
        except RelearnError as exc:
            self.toast.show_message(str(exc))
            return
        self.toast.show_message(TOAST_PROFILE_REVERTED)
