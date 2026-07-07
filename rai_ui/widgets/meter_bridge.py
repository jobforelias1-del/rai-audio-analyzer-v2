"""Collapsed meter bridge (component C-02): the rail folded into a 76px strip.

When the readout rail collapses, this full-width band under the header shows
the SAME data — same ``ReadoutView`` object, so the two surfaces can never
disagree on a digit — as a row of cells on hairline dividers: verdict cell
(196px, widening to 280px when Ambiguous docks its red Tiebreak button), then
Primary BPM 28px / Felt 17px with their marker ticks, then the loudness trio
and DR / Width, then the doctrine caption.

Doctrine enforced here:

* "Verdict cell background/border swap with state; numeral cells never
  change color" (CL:78) — value labels get their color once at construction
  and no ``set_view`` path restyles them.
* Reasons render on ONE line, ellipsized, with the full text in the tooltip
  (the rail owns the full-length treatment).
* The ◆ ambiguous mark is drawn (``rai_ui.theme.icons``), never a font glyph;
  the bridge's ambiguous word reads "◆ AMBIGUOUS — HUMAN TIEBREAK" (CO:105).
* DR and Width show as "—" until M2 computes them (R12); Sub/bass is a
  rail-only row — the bridge subset is intentional (CO:127-146).
* Caption copy is fixed: "dBTP ≠ dBFS — both always shown" (the bridge drops
  the rail footer's ", never collapsed." tail — Console verbatim, CO:148).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rai_ui.state.tempo_view import EMPTY_VIEW, ReadoutView, VerdictView
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_BORDER_HAIRLINE,
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_AMBIGUOUS_BG,
    COLOR_SEMANTIC_AMBIGUOUS_BORDER,
    COLOR_SEMANTIC_CONFIDENT_BG,
    COLOR_SEMANTIC_CONFIDENT_BORDER,
    COLOR_SURFACE_RAISED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    LINE_HAIRLINE,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.metric_readout import TickBar, group_label
from rai_ui.widgets.verdict_block import (
    body_color,
    diamond_pixmap,
    display_word,
    type_pin,
    verdict_qss_property,
    word_color,
)

BRIDGE_HEIGHT = 76  # C-02 strip height (blessed literal, R2)
VERDICT_CELL_WIDTH = 196  # verdict cell (CL:78)
VERDICT_CELL_WIDTH_AMBIGUOUS = 280  # ambiguous variant widens (CL:78)

# Doctrine caption — verbatim (CO:148); the rail's longer form lives in
# metric_readout.py.
BRIDGE_FOOTER = "dBTP ≠ dBFS — both always shown"

# Reasons arrive from the view-model split on the engine's "; " joiner; the
# bridge's single line joins them back the same way.
_REASON_JOINER = "; "

# Verdict-cell skin per QSS-property state: (background, border). The cell's
# right divider uses the SEMANTIC border color (CL:78), not the hairline.
_CELL_SKINS: dict[str, tuple[str, str]] = {
    "confident": (COLOR_SEMANTIC_CONFIDENT_BG, COLOR_SEMANTIC_CONFIDENT_BORDER),
    "confirmed": (COLOR_SEMANTIC_CONFIDENT_BG, COLOR_SEMANTIC_CONFIDENT_BORDER),
    "ambiguous": (COLOR_SEMANTIC_AMBIGUOUS_BG, COLOR_SEMANTIC_AMBIGUOUS_BORDER),
    # neutral / working / error share the raised-neutral surface.
    "neutral": (COLOR_SURFACE_RAISED, COLOR_BORDER_HAIRLINE),
    "working": (COLOR_SURFACE_RAISED, COLOR_BORDER_HAIRLINE),
    "error": (COLOR_SURFACE_RAISED, COLOR_BORDER_HAIRLINE),
}


class ElidedLabel(QLabel):
    """A one-line label that elides right and carries the full text in its
    tooltip — the bridge's reason treatment (CO:93)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        # Let the cell width win; the text yields, never the layout.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._relayout()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(
            metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        )


def _cell(parent: QWidget, divider: bool = True, gap: int = 2) -> tuple[QFrame, QVBoxLayout]:
    """A bridge cell: padding 0 18px, vertically centered, right hairline."""
    cell = QFrame(parent)
    cell.setObjectName("bridgeCell")
    if divider:
        cell.setStyleSheet(
            # token: color.border.hairline — "cells on hairline dividers"
            f"QFrame#bridgeCell {{ border-right: {LINE_HAIRLINE}px solid"
            f" {COLOR_BORDER_HAIRLINE}; }}"
        )
    layout = QVBoxLayout(cell)
    layout.setContentsMargins(18, 0, 18, 0)  # cell padding 0 18px (CO:118)
    layout.setSpacing(gap)
    layout.addStretch(1)
    return cell, layout


def _finish_cell(layout: QVBoxLayout) -> None:
    layout.addStretch(1)


def _value_row(cell: QWidget, size_px: int, weight: QFont.Weight, unit: str | None) -> tuple[QWidget, QLabel]:
    """A numeral (+ optional 10px unit) row for a bridge cell."""
    row = QWidget(cell)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    value_label = QLabel(row)
    value_font = mono_font(size_px, weight)
    value_label.setFont(value_font)
    value_label.setStyleSheet(  # token: color.text.primary
        f"color: {COLOR_TEXT_PRIMARY};{type_pin(value_font)}"
    )
    layout.addWidget(value_label, 0, Qt.AlignmentFlag.AlignBottom)
    if unit is not None:
        unit_label = QLabel(unit, row)
        unit_font = mono_font(10, QFont.Weight.Medium)  # unit 10/500
        unit_label.setFont(unit_font)
        unit_label.setStyleSheet(  # token: color.text.muted
            f"color: {COLOR_TEXT_MUTED};{type_pin(unit_font)}"
        )
        layout.addWidget(unit_label, 0, Qt.AlignmentFlag.AlignBottom)
    layout.addStretch(1)
    return row, value_label


class MeterBridge(QFrame):
    """The 76px collapsed readout strip. One ``set_view(ReadoutView)`` truth."""

    tiebreak_requested = Signal()
    undo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("meterBridge")  # theme QSS: panel bg + bottom hairline
        self.setFixedHeight(BRIDGE_HEIGHT)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 1. Verdict cell — the only cell whose skin swaps with state.
        self.verdict_cell = QFrame(self)
        self.verdict_cell.setObjectName("bridgeVerdictCell")
        self.verdict_cell.setFixedWidth(VERDICT_CELL_WIDTH)
        cell_layout = QHBoxLayout(self.verdict_cell)
        cell_layout.setContentsMargins(16, 0, 16, 0)  # verdict cell padding 0 16px
        cell_layout.setSpacing(12)

        text_column = QWidget(self.verdict_cell)
        text_layout = QVBoxLayout(text_column)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        text_layout.addStretch(1)
        word_row = QHBoxLayout()
        word_row.setSpacing(6)
        self._icon_label = QLabel(text_column)  # the drawn ◆, ambiguous only
        self._icon_label.setFixedSize(12, 12)
        self._icon_label.hide()
        self.word_label = QLabel(text_column)
        word_font = mono_font(12, QFont.Weight.DemiBold)  # word 12/600
        self.word_label.setFont(word_font)
        self._word_pin = type_pin(word_font)  # re-applied on every verdict restyle
        word_row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        word_row.addWidget(self.word_label, 0, Qt.AlignmentFlag.AlignVCenter)
        word_row.addStretch(1)
        text_layout.addLayout(word_row)
        reason_row = QHBoxLayout()
        reason_row.setSpacing(0)
        self.reason_label = ElidedLabel(text_column)
        reason_font = ui_font(11)
        self.reason_label.setFont(reason_font)
        self._reason_pin = type_pin(reason_font)  # re-applied on every verdict restyle
        reason_row.addWidget(self.reason_label, 1)
        # Confirmed's inline undo link sits OUTSIDE the elide so it survives
        # any reason length ("… · undo", CO:99).
        self._undo_link = QLabel(text_column)
        undo_font = ui_font(11)
        self._undo_link.setFont(undo_font)
        self._undo_link.setStyleSheet(type_pin(undo_font))  # colors are inline rich text
        self._undo_link.setTextFormat(Qt.TextFormat.RichText)
        self._undo_link.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._undo_link.linkActivated.connect(lambda _href: self.undo_requested.emit())
        self._undo_link.hide()
        reason_row.addWidget(self._undo_link, 0)
        text_layout.addLayout(reason_row)
        text_layout.addStretch(1)
        cell_layout.addWidget(text_column, 1)

        # The docked red action — ambiguous contexts only (C-10).
        self._tiebreak_button = QPushButton("Tiebreak", self.verdict_cell)
        self._tiebreak_button.setObjectName("tiebreakButton")
        self._tiebreak_button.setFixedHeight(26)  # h26 (CO:108)
        self._tiebreak_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tiebreak_button.clicked.connect(self.tiebreak_requested.emit)
        self._tiebreak_button.hide()
        cell_layout.addWidget(self._tiebreak_button, 0, Qt.AlignmentFlag.AlignVCenter)
        outer.addWidget(self.verdict_cell)

        # 2. Primary BPM: label + 28px numeral + amber 58×3 tick.
        cell, layout = _cell(self, gap=0)
        layout.addWidget(group_label("Primary BPM", cell))
        row, self.primary_value = _value_row(cell, 28, QFont.Weight.DemiBold, None)  # 28/600 (R2)
        layout.addWidget(row)
        layout.addWidget(TickBar("primary", 58, cell))  # 58×3 (CO:120)
        _finish_cell(layout)
        outer.addWidget(cell)

        # 3. Felt: label + 17px numeral + violet dashed 38px tick.
        cell, layout = _cell(self, gap=1)
        layout.addWidget(group_label("Felt", cell))
        row, self.felt_value = _value_row(cell, 17, QFont.Weight.Medium, None)  # 17/500 (R2)
        layout.addWidget(row)
        layout.addWidget(TickBar("felt", 38, cell))  # 38px dashed (CO:125)
        _finish_cell(layout)
        outer.addWidget(cell)

        # 4-8. Numeral cells: loudness trio, DR, Width (Sub/bass is rail-only).
        self.lufs_value = self._metric_cell(outer, "Integrated", "LUFS")
        self.dbtp_value = self._metric_cell(outer, "True pk", "dBTP")
        self.dbfs_value = self._metric_cell(outer, "Sample pk", "dBFS")
        self.dr_value = self._metric_cell(outer, "DR", None)
        self.width_value = self._metric_cell(outer, "Width", None, divider=False)

        outer.addStretch(1)

        # 9. Doctrine caption — exact copy, never reworded.
        self.footer_label = QLabel(BRIDGE_FOOTER, self)
        footer_font = ui_font(11)
        self.footer_label.setFont(footer_font)
        self.footer_label.setStyleSheet(  # token: color.text.muted
            f"color: {COLOR_TEXT_MUTED};{type_pin(footer_font)}"
        )
        self.footer_label.setContentsMargins(16, 0, 16, 0)  # caption padding 0 16 (CO:148)
        outer.addWidget(self.footer_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._view: ReadoutView = EMPTY_VIEW.readout
        self.set_view(self._view)

    def _metric_cell(
        self, outer: QHBoxLayout, name: str, unit: str | None, divider: bool = True
    ) -> QLabel:
        cell, layout = _cell(self, divider=divider)
        layout.addWidget(group_label(name, cell))
        row, value_label = _value_row(cell, 16, QFont.Weight.DemiBold, unit)  # 16/600
        layout.addWidget(row)
        _finish_cell(layout)
        outer.addWidget(cell)
        return value_label

    # -- API ------------------------------------------------------------------

    def set_view(self, view: ReadoutView) -> None:
        """Render ``view`` verbatim. Only the verdict cell ever changes color."""
        self._view = view
        self._render_verdict_cell(view.verdict)
        self.primary_value.setText(view.primary_text)
        self.felt_value.setText(view.felt_text)
        self.lufs_value.setText(view.lufs_text)
        self.dbtp_value.setText(view.dbtp_text)
        self.dbfs_value.setText(view.dbfs_text)
        self.dr_value.setText(view.dr_text)
        self.width_value.setText(view.width_text)

    def view(self) -> ReadoutView:
        """The last-rendered view (test/introspection hook)."""
        return self._view

    # -- internals --------------------------------------------------------------

    def _render_verdict_cell(self, verdict: VerdictView) -> None:
        kind = verdict.kind
        state = verdict_qss_property(kind)
        bg, border = _CELL_SKINS[state]
        self.verdict_cell.setStyleSheet(
            f"QFrame#bridgeVerdictCell {{ background-color: {bg};"
            f" border-right: {LINE_HAIRLINE}px solid {border}; }}"
        )
        self.verdict_cell.setFixedWidth(
            VERDICT_CELL_WIDTH_AMBIGUOUS if kind == "ambiguous" else VERDICT_CELL_WIDTH
        )

        self.word_label.setText(display_word(verdict, bridge=True))
        self.word_label.setStyleSheet(f"color: {word_color(kind)};{self._word_pin}")
        if kind == "ambiguous":
            self._icon_label.setPixmap(diamond_pixmap(12, COLOR_SEMANTIC_AMBIGUOUS_BASE))
            self._icon_label.show()
        else:
            self._icon_label.hide()

        # One line, ellipsized, full text in the tooltip. Confirmed appends
        # " · " + the inline undo link outside the elide.
        if kind in ("confident", "ambiguous", "error"):
            reason = _REASON_JOINER.join(verdict.reasons)
        elif kind == "confirmed_human":
            reason = (verdict.reasons[0] + " · ") if verdict.reasons else ""
        else:
            reason = verdict.sub or ""
        self.reason_label.setStyleSheet(f"color: {body_color(kind)};{self._reason_pin}")
        self.reason_label.set_full_text(reason)
        if verdict.show_undo:
            self._undo_link.setText(
                # token: color.accent.base (undo is an accent link, CO:99)
                f'<a href="undo" style="color:{COLOR_ACCENT_BASE};text-decoration:none">undo</a>'
            )
            self._undo_link.show()
        else:
            self._undo_link.hide()
        self._tiebreak_button.setVisible(verdict.show_tiebreak)
