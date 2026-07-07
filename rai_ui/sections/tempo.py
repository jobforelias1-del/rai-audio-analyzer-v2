"""Tempo section (M1): the tempogram well over the candidates card.

Stack page 2. Assembles the two Tempo panes exactly as the approved Console
lays them out — the C-16 tempogram (flex 1.55) above the C-13 candidates
card (flex 1), inside the section's 14px/16px padding with a 12px gap
(CO:206-208). The persistent readout rail and the meter bridge are NOT part
of this section: they are MainWindow-level chrome (ruling R10) so they can
survive section switches.

Data flow is one-way and view-model-only: MainWindow builds a
``TempoViewModel`` (``rai_ui.state.tempo_view.build_tempo_view`` — the single
derivation point) and pushes it through ``set_view``; the section fans it out
verbatim to both panes and never touches engine objects itself.
``set_working`` mirrors the session's working flag onto the C-17 surfaces
(sweep overlay on the plot, skeleton rows in the table).

The child panes' actions bubble up here for MainWindow to answer:
``hear_requested`` / ``tiebreak_requested`` / ``undo_requested`` plus the
tiebreak overlay's ``preview_requested`` / ``preview_stop_requested`` /
``confirm_requested`` (M3 — the overlay lives inside the candidates pane;
MainWindow opens it via ``open_tiebreak`` on ambiguous verdicts only and
wires the preview signals to the click-preview service).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from rai_ui.plots.tempogram import TempogramPane
from rai_ui.state.tempo_view import EMPTY_VIEW, TempoViewModel
from rai_ui.widgets.candidate_table import CandidatePane

# Section frame per the approved Console (CO:206): padding 14px 16px, gap 12.
SECTION_MARGIN_H = 16
SECTION_MARGIN_V = 14
SECTION_GAP = 12

# Vertical share: tempogram flex 1.55 over the candidates card flex 1
# (CO:208). Qt stretch factors are integers, so the ratio is scaled ×100.
TEMPOGRAM_STRETCH = 155
CANDIDATES_STRETCH = 100


class TempoSection(QWidget):
    """The Tempo page: one ``set_view`` truth, two panes, two bubbled signals."""

    hear_requested = Signal(float)  # bpm of the clicked candidate row
    tiebreak_requested = Signal()
    undo_requested = Signal()  # candidates-header "Undo tiebreak" ghost (R-M3-17)
    # Tiebreak-overlay signals (M3): bpm previews + the confirm act.
    preview_requested = Signal(float)
    preview_stop_requested = Signal()
    confirm_requested = Signal(float)
    tiebreak_closed = Signal()  # ✕/Esc/auto-dismiss — MainWindow stops audio

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tempoSection")
        self._vm: TempoViewModel = EMPTY_VIEW

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SECTION_MARGIN_H, SECTION_MARGIN_V, SECTION_MARGIN_H, SECTION_MARGIN_V
        )
        layout.setSpacing(SECTION_GAP)

        self.tempogram = TempogramPane(self)
        self.candidates = CandidatePane(self)
        layout.addWidget(self.tempogram, TEMPOGRAM_STRETCH)
        layout.addWidget(self.candidates, CANDIDATES_STRETCH)

        # Signal-to-signal forwarding (same thread — the cross-thread functor
        # landmine does not apply to child-widget wiring).
        self.candidates.hear_requested.connect(self.hear_requested)
        self.candidates.tiebreak_requested.connect(self.tiebreak_requested)
        self.candidates.undo_requested.connect(self.undo_requested)
        self.candidates.preview_requested.connect(self.preview_requested)
        self.candidates.preview_stop_requested.connect(self.preview_stop_requested)
        self.candidates.confirm_requested.connect(self.confirm_requested)
        self.candidates.tiebreak_closed.connect(self.tiebreak_closed)

    # -- public API (widget contract) ------------------------------------------

    def set_view(self, vm: TempoViewModel) -> None:
        """Fan one view-model out to both panes. Idempotent, like the panes."""
        self._vm = vm
        self.tempogram.set_view(vm)
        self.candidates.set_rows(vm)

    def set_working(self, active: bool) -> None:
        """Toggle the C-17 working surfaces (plot sweep + table skeleton)."""
        self.tempogram.set_working(active)
        self.candidates.set_working(active)

    def open_tiebreak(self) -> None:
        """Open the C-14 overlay over the candidates pane (ambiguous only —
        the caller enforces R-M3-6; confirmed state has no entry point)."""
        self.candidates.open_tiebreak()

    def close_tiebreak(self) -> None:
        """Dismiss the overlay if open (preview stops, selection survives)."""
        self.candidates.close_tiebreak()

    def view(self) -> TempoViewModel:
        """The last-rendered view-model (smoke/test introspection hook)."""
        return self._vm
