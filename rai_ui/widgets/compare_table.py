"""The Compare Δ table (M4, R-M4-4 / C-15 / 04:461–478): a fixed 6-row grid.

Card chrome rides the shared ``QFrame#metricCard`` theme rule (panel surface,
hairline border, radius 12 — the exact 04:461 values). Inside it:

* **Header row** (04:463–469): 11px/500/0.07em uppercase — ``Metric`` muted ·
  ``A`` **cyan** ``data-a`` · ``B`` **rose** ``data-b`` (the hue-lock law) ·
  ``Δ B−A`` muted (U+0394 / U+2212 — the sign convention is stated IN the
  header) · ``Reading`` muted; hairline ``border.strong`` bottom rule.
* **Six metric rows exactly** (the set is closed, 04:804–811): column widths
  ``150/120/120/90/1fr`` gap 12 (04:462, matches C-15). Cells: metric sans 13
  ``text.secondary`` · A/B values mono 14/**500** ``text.primary`` · Δ mono
  14/**600** ``text.primary`` · Reading sans 12 ``text.secondary``.

**Δ is NEVER semantically tinted** (C-15 law: "Δ never uses verdict colors —
a louder track isn't 'bad'"): every cell color is set ONCE at construction
and no ``set_rows`` path touches a stylesheet — weight 600 is the only
emphasis the delta gets. All strings arrive prebuilt on ``CompareRowView``
(the pure view-model, one truth); this widget renders them verbatim.

Blessed literals / floors: the design's 12.5px reading type is
unrepresentable in integer QFont pixel sizes — floored to 12 (the C-06 chip
10.5→10 precedent, queued for design reconciliation). The row hover
``surface.hover`` wash and per-row 9px vertical padding are decorative
row-chrome the fixed QGridLayout replaces with its uniform 12px gap —
documented divergence, flagged in the M4 report.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout

from rai_ui.state.compare_view import EMPTY_COMPARE_VIEW, CompareRowView
from rai_ui.theme._tokens_gen import (
    COLOR_BORDER_STRONG,
    COLOR_PLOT_DATA_A,
    COLOR_PLOT_DATA_B,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.verdict_block import type_pin

# Header strings, verbatim (04:463–469): Δ = U+0394, − = U+2212. Rendered
# uppercase (text-transform) like every design label.
HEADERS: tuple[str, ...] = ("Metric", "A", "B", "Δ B−A", "Reading")

# Grid geometry (04:462 = C-15): 150/120/120/90/1fr, gap 12.
COLUMN_WIDTHS: tuple[int, ...] = (150, 120, 120, 90)
GRID_GAP = 12
ROW_COUNT = 6

# Header column hues — the ONLY tinted text in the table (hue-lock law C-12;
# Δ and every value stay untinted forever, C-15).
_HEADER_COLORS: tuple[str, ...] = (
    COLOR_TEXT_MUTED,  # token: color.text.muted
    COLOR_PLOT_DATA_A,  # token: color.plot.data-a
    COLOR_PLOT_DATA_B,  # token: color.plot.data-b
    COLOR_TEXT_MUTED,
    COLOR_TEXT_MUTED,
)

# Card padding 14px 16px (04:461) — contents margins are (l, t, r, b).
_CARD_MARGINS = (16, 14, 16, 14)
# Header grid padding 0 10px 8px 10px (04:463) — the rows' 10px side padding
# is baked into the same grid margins so the columns stay aligned.
_GRID_SIDE_PAD = 10
_HEADER_BOTTOM_PAD = 8


def _header_label(text: str, color_hex: str, parent) -> QLabel:
    """One 11px/500/0.07em uppercase header cell, per-column hue."""
    label = QLabel(text.upper(), parent)
    font = ui_font(11, QFont.Weight.Medium)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)  # 0.07em
    label.setFont(font)
    label.setStyleSheet(f"color: {color_hex}; background: transparent;{type_pin(font)}")
    return label


class CompareTable(QFrame):
    """The Δ table card: header + exactly six prebuilt rows, strings verbatim.

    ``set_rows`` accepts the view-model's 6-tuple of :class:`CompareRowView`
    and swaps texts only — no widget is created or restyled after
    construction (idempotency + the never-tinted-Δ law by structure).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")  # shared card chrome (theme QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*_CARD_MARGINS)
        outer.setSpacing(_HEADER_BOTTOM_PAD)

        # -- header (own grid + bottom rule) ------------------------------------
        header = QFrame(self)
        header.setObjectName("compareTableHeader")
        header.setStyleSheet(
            "QFrame#compareTableHeader {"
            f" border: none; border-bottom: 1px solid {COLOR_BORDER_STRONG};"  # token: color.border.strong
            " background: transparent; }"
        )
        header_grid = QGridLayout(header)
        header_grid.setContentsMargins(_GRID_SIDE_PAD, 0, _GRID_SIDE_PAD, _HEADER_BOTTOM_PAD)
        header_grid.setHorizontalSpacing(GRID_GAP)
        header_grid.setVerticalSpacing(0)
        self.header_labels: list[QLabel] = []
        for col, (text, color) in enumerate(zip(HEADERS, _HEADER_COLORS)):
            label = _header_label(text, color, header)
            header_grid.addWidget(label, 0, col)
            self.header_labels.append(label)
        self._fix_columns(header_grid)
        outer.addWidget(header)

        # -- the six rows (one grid, built once) ---------------------------------
        body = QFrame(self)
        body.setStyleSheet("border: none; background: transparent;")
        grid = QGridLayout(body)
        grid.setContentsMargins(_GRID_SIDE_PAD, 0, _GRID_SIDE_PAD, 0)
        grid.setHorizontalSpacing(GRID_GAP)
        grid.setVerticalSpacing(GRID_GAP)

        metric_font = ui_font(13)
        value_font = mono_font(14, QFont.Weight.Medium)  # A/B values 14/500
        delta_font = mono_font(14, QFont.Weight.DemiBold)  # Δ 14/600 — its ONLY emphasis
        reading_font = ui_font(12)  # design 12.5 — floored, see module docstring

        self.metric_labels: list[QLabel] = []
        self.a_value_labels: list[QLabel] = []
        self.b_value_labels: list[QLabel] = []
        self.delta_labels: list[QLabel] = []
        self.reading_labels: list[QLabel] = []

        def _cell(font: QFont, color_hex: str) -> QLabel:
            label = QLabel(body)
            label.setFont(font)
            # Color fixed at construction — set_rows never restyles (C-15 law).
            label.setStyleSheet(
                f"color: {color_hex}; background: transparent;{type_pin(font)}"
            )
            return label

        for row in range(ROW_COUNT):
            metric = _cell(metric_font, COLOR_TEXT_SECONDARY)  # token: color.text.secondary
            a_value = _cell(value_font, COLOR_TEXT_PRIMARY)  # token: color.text.primary
            b_value = _cell(value_font, COLOR_TEXT_PRIMARY)
            delta = _cell(delta_font, COLOR_TEXT_PRIMARY)  # NEVER tinted (C-15)
            reading = _cell(reading_font, COLOR_TEXT_SECONDARY)
            for col, label in enumerate((metric, a_value, b_value, delta, reading)):
                grid.addWidget(label, row, col, Qt.AlignmentFlag.AlignVCenter)
            self.metric_labels.append(metric)
            self.a_value_labels.append(a_value)
            self.b_value_labels.append(b_value)
            self.delta_labels.append(delta)
            self.reading_labels.append(reading)
        self._fix_columns(grid)
        outer.addWidget(body)

        self._rows: tuple[CompareRowView, ...] = ()
        self.set_rows(EMPTY_COMPARE_VIEW.rows)

    @staticmethod
    def _fix_columns(grid: QGridLayout) -> None:
        """The designed track sizes: fixed 150/120/120/90, Reading takes 1fr."""
        for col, width in enumerate(COLUMN_WIDTHS):
            grid.setColumnMinimumWidth(col, width)
            grid.setColumnStretch(col, 0)
        grid.setColumnStretch(len(COLUMN_WIDTHS), 1)

    # -- API ------------------------------------------------------------------

    def set_rows(self, rows: tuple[CompareRowView, ...]) -> None:
        """Render the six rows verbatim. Text swaps only — never a restyle."""
        if len(rows) != ROW_COUNT:
            raise ValueError(f"Compare table is a fixed {ROW_COUNT}-row grid, got {len(rows)}")
        self._rows = tuple(rows)
        for row_view, metric, a_value, b_value, delta, reading in zip(
            rows,
            self.metric_labels,
            self.a_value_labels,
            self.b_value_labels,
            self.delta_labels,
            self.reading_labels,
        ):
            metric.setText(row_view.metric)
            a_value.setText(row_view.a_text)
            b_value.setText(row_view.b_text)
            delta.setText(row_view.delta_text)
            reading.setText(row_view.reading)

    def rows(self) -> tuple[CompareRowView, ...]:
        """The last-rendered rows (test/introspection hook)."""
        return self._rows
