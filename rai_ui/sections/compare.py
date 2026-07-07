"""Compare section (M4, 04:445–501): chip row / Δ table card / spectrum overlay.

Stack page 4. Three stacked children inside the standard section frame
(padding 14px 16px, gap 12 — 04:447): the identity chip row (flex:none), the
Δ table card (flex:none), and the spectrum overlay well taking every
remaining pixel (flex:1).

Data flow is one-way and view-model-only (the M2 section doctrine):
MainWindow builds ONE ``CompareViewModel``
(:func:`rai_ui.state.compare_view.build_compare_view` — fed from the session
A-state under the M3 blank doctrine plus the persistent
:class:`~rai_ui.services.compare_slot.CompareSlot` B-state) and pushes it
through ``set_view``; the section fans it out verbatim and derives nothing.

``set_view(None)`` is the R-M4-13 nav gate: with no file loaded the Compare
screen renders NOTHING (04:834 — the nav item exists in the empty state but
the screen stays blank until a file lands), exactly the placeholder-era
visibility. The section's user intents bubble up as signals — the B-empty
chip's Browse click and the loaded chip's ✕ — and the shell owns what they
do (file dialog / slot clear).

``set_working`` mirrors the session's A-side working flag onto the overlay's
shared C-17 sweep; B's in-flight state is chip-only by ruling (R-M4-3) and
arrives through the view-model, never through this flag.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from rai_ui.plots.compare_overlay import CompareOverlayPane
from rai_ui.state.compare_view import CompareViewModel
from rai_ui.widgets.compare_chips import CompareChipRow
from rai_ui.widgets.compare_table import CompareTable

# Section frame per the approved Console (04:447): padding 14px 16px, gap 12.
SECTION_MARGIN_H = 16
SECTION_MARGIN_V = 14
SECTION_GAP = 12


class CompareSection(QWidget):
    """The Compare page: one ``set_view`` truth, chips + table + overlay."""

    browse_b_requested = Signal()
    clear_b_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compareSection")
        self._vm: Optional[CompareViewModel] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SECTION_MARGIN_H, SECTION_MARGIN_V, SECTION_MARGIN_H, SECTION_MARGIN_V
        )
        layout.setSpacing(SECTION_GAP)

        self.chips = CompareChipRow(self)
        self.chips.browse_b_requested.connect(self.browse_b_requested)
        self.chips.clear_b_requested.connect(self.clear_b_requested)
        layout.addWidget(self.chips)

        self.table = CompareTable(self)
        layout.addWidget(self.table)

        # The overlay well is the one flexible zone (04:479 flex:1).
        self.overlay = CompareOverlayPane(self)
        layout.addWidget(self.overlay, 1)

        self.set_view(None)

    # -- public API (widget contract) ------------------------------------------

    def set_view(self, vm: Optional[CompareViewModel]) -> None:
        """Fan one view-model out to all three children. ``None`` = the
        R-M4-13 no-file gate: everything hides, the page renders nothing."""
        self._vm = vm
        visible = vm is not None
        self.chips.setVisible(visible)
        self.table.setVisible(visible)
        self.overlay.setVisible(visible)
        if vm is None:
            return
        self.chips.set_view(vm)
        self.table.set_rows(vm.rows)
        self.overlay.set_view(vm)

    def set_working(self, active: bool) -> None:
        """A-side C-17 sweep on the overlay well (B is chip-only, R-M4-3)."""
        self.overlay.set_working(active)

    def view(self) -> Optional[CompareViewModel]:
        """The last-rendered view-model (None = the no-file gate)."""
        return self._vm
