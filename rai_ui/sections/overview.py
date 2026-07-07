"""Overview section (M2): four summary cards over the full-width waveform.

Stack page 1. Assembles the approved Console's Overview screen (04:352–400):
a top card row — the wide Tempo card (1.35fr), Loudness, Dynamics, and the
File card (1fr each), gap 12 — that keeps its natural height (flex:none),
above the waveform well that takes every remaining pixel (flex:1), all inside
the section's 14px/16px padding with a 12px gap. Qt stretch factors are
integers, so the fr ratios are scaled ×100 (the TempoSection convention).

Data flow is one-way and view-model-only: MainWindow builds an
``OverviewViewModel`` (``rai_ui.state.signal_view.build_overview_view`` — the
single derivation point) and pushes it through ``set_view``; the section fans
it out verbatim to the four cards and the waveform pane and never touches
engine objects itself. ``set_working`` mirrors the session's working flag
onto the C-17 surface — the waveform sweep; the cards need no working state
because the blanked view-model already dashes every value (R-M1-3/R-M2-16,
enforced in the builder, not here).

The persistent readout rail and the meter bridge are NOT part of this
section: they are MainWindow-level chrome (ruling R10). The rail repeats
Tempo/Loudness/Dynamics beside this page by design ("numbers never leave the
screen"); Overview adds the File card and the waveform.
"""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from rai_ui.plots.waveform import WaveformPane
from rai_ui.state.signal_view import EMPTY_OVERVIEW_VIEW, OverviewViewModel
from rai_ui.widgets.metric_cards import RowsCard, TempoCard

# Section frame per the approved Console (04:352): padding 14px 16px, gap 12.
SECTION_MARGIN_H = 16
SECTION_MARGIN_V = 14
SECTION_GAP = 12

# Card row grid ``1.35fr 1fr 1fr 1fr; gap:12px`` (04:354) — fr ratios ×100.
CARD_ROW_GAP = 12
TEMPO_CARD_STRETCH = 135
CARD_STRETCH = 100

# The File card's compact value type: mono 12px/500 (04:382).
FILE_VALUE_PX = 12


class OverviewSection(QWidget):
    """The Overview page: one ``set_view`` truth, four cards, one waveform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("overviewSection")
        self._vm: OverviewViewModel = EMPTY_OVERVIEW_VIEW

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SECTION_MARGIN_H, SECTION_MARGIN_V, SECTION_MARGIN_H, SECTION_MARGIN_V
        )
        layout.setSpacing(SECTION_GAP)

        # -- card row (flex:none — natural height, waveform takes the rest) ----
        card_row = QHBoxLayout()
        card_row.setSpacing(CARD_ROW_GAP)
        self.tempo_card = TempoCard(self)
        self.loudness_card = RowsCard(parent=self)
        self.dynamics_card = RowsCard(parent=self)
        # File card variant: compact mono 12/500 values (constructor state —
        # the card never changes shape, only numbers; CARDS contract).
        self.file_card = RowsCard(
            value_px=FILE_VALUE_PX, value_weight=QFont.Weight.Medium, parent=self
        )
        card_row.addWidget(self.tempo_card, TEMPO_CARD_STRETCH)
        card_row.addWidget(self.loudness_card, CARD_STRETCH)
        card_row.addWidget(self.dynamics_card, CARD_STRETCH)
        card_row.addWidget(self.file_card, CARD_STRETCH)
        layout.addLayout(card_row, 0)

        # -- waveform well (flex:1) ---------------------------------------------
        self.waveform = WaveformPane(self)
        layout.addWidget(self.waveform, 1)

        self.set_view(EMPTY_OVERVIEW_VIEW)

    # -- public API (widget contract) ------------------------------------------

    def set_view(self, vm: OverviewViewModel) -> None:
        """Fan one view-model out to every card + the waveform. Idempotent."""
        self._vm = vm
        self.tempo_card.set_view(vm.tempo_card)
        self.loudness_card.set_view(vm.loudness_card)
        self.dynamics_card.set_view(vm.dynamics_card)
        self.file_card.set_view(vm.file_card)
        self.waveform.set_view(vm)

    def set_working(self, active: bool) -> None:
        """Toggle the C-17 working surface (the waveform sweep). The cards
        carry no skeleton: the blanked WORKING view-model dashes them."""
        self.waveform.set_working(active)

    def view(self) -> OverviewViewModel:
        """The last-rendered view-model (smoke/test introspection hook)."""
        return self._vm
