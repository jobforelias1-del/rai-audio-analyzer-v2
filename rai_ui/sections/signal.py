"""Signal section (M2): the frequency-spectrum well over three metric cards.

Stack page 3. Assembles the approved Console's Signal screen (04:402–443):
the spectrum plot takes the section's flexible space (flex:1.5 in the mock —
the only flexible zone, so it simply gets every remaining pixel here) above a
three-card metric row (``1fr 1fr 1fr; gap:12px``, flex:none) — Stereo width,
Sub/bass energy, Dynamic range — inside the section's 14px/16px padding with
a 12px gap.

Data flow is one-way and view-model-only: MainWindow builds a
``SignalViewModel`` (``rai_ui.state.signal_view.build_signal_view`` — the
single derivation point) and pushes it through ``set_view``; the section fans
it out verbatim to the spectrum pane and the three gauge cards and never
touches engine objects itself. ``set_working`` mirrors the session's working
flag onto the C-17 surface — the spectrum sweep; the cards need no working
state because the blanked view-model already dashes every value
(R-M1-3/R-M2-16, enforced in the builder, not here).

Card construction state per the CARDS contract: the Dynamic-range card is
``GaugeCard(unit="dB")`` — the design renders the inline 14px dB unit
unconditionally (``— dB`` on absence, 04:438) and the card has no gauge bar
(the view-model's ``gauge_frac`` is always None for it); Width and Sub carry
their ``%`` inside ``value_text`` and render the 8px gauge.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from rai_ui.plots.spectrum import SpectrumPane
from rai_ui.state.signal_view import EMPTY_SIGNAL_VIEW, SignalViewModel
from rai_ui.widgets.metric_cards import GaugeCard

# Section frame per the approved Console (04:404): padding 14px 16px, gap 12.
SECTION_MARGIN_H = 16
SECTION_MARGIN_V = 14
SECTION_GAP = 12

# Metric card row ``1fr 1fr 1fr; gap:12px`` (04:423).
CARD_ROW_GAP = 12

# The DR card's fixed inline unit (04:438) — construction state, see CARDS.
DR_UNIT = "dB"


class SignalSection(QWidget):
    """The Signal page: one ``set_view`` truth, one plot, three cards."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("signalSection")
        self._vm: SignalViewModel = EMPTY_SIGNAL_VIEW

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SECTION_MARGIN_H, SECTION_MARGIN_V, SECTION_MARGIN_H, SECTION_MARGIN_V
        )
        layout.setSpacing(SECTION_GAP)

        # -- spectrum well (the flexible zone) ----------------------------------
        self.spectrum = SpectrumPane(self)
        layout.addWidget(self.spectrum, 1)

        # -- metric card row (flex:none — natural height) -----------------------
        card_row = QHBoxLayout()
        card_row.setSpacing(CARD_ROW_GAP)
        self.width_card = GaugeCard(parent=self)
        self.sub_card = GaugeCard(parent=self)
        self.dr_card = GaugeCard(unit=DR_UNIT, parent=self)
        card_row.addWidget(self.width_card, 1)
        card_row.addWidget(self.sub_card, 1)
        card_row.addWidget(self.dr_card, 1)
        layout.addLayout(card_row, 0)

        self.set_view(EMPTY_SIGNAL_VIEW)

    # -- public API (widget contract) ------------------------------------------

    def set_view(self, vm: SignalViewModel) -> None:
        """Fan one view-model out to the plot + all three cards. Idempotent."""
        self._vm = vm
        self.spectrum.set_view(vm)
        self.width_card.set_view(vm.width_card)
        self.sub_card.set_view(vm.sub_card)
        self.dr_card.set_view(vm.dr_card)

    def set_working(self, active: bool) -> None:
        """Toggle the C-17 working surface (the spectrum sweep). The cards
        carry no skeleton: the blanked WORKING view-model dashes them."""
        self.spectrum.set_working(active)

    def view(self) -> SignalViewModel:
        """The last-rendered view-model (smoke/test introspection hook)."""
        return self._vm
