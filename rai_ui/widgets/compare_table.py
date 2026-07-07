"""The Compare Δ table (M4, R-M4-4 / C-15 / 04:461–478): a fixed 6-row grid.

Card chrome rides the shared ``QFrame#metricCard`` theme rule (panel surface,
hairline border, radius 12 — the exact 04:461 values). Inside it:

* **Header row** (04:463–469): 11px/500/0.07em uppercase — ``Metric`` muted ·
  ``A`` **cyan** ``data-a`` · ``B`` **rose** ``data-b`` (the hue-lock law) ·
  ``Δ B−A`` muted (U+0394 / U+2212 — the sign convention is stated IN the
  header) · ``Reading`` muted; hairline ``border.strong`` bottom rule.
* **Six metric rows exactly** (the set is closed, 04:804–811), each its own
  hover-capable ``QFrame#compareRow`` (04:471, BINDING): padding ``9px 10px``
  (grid margins), ``border-radius: 7`` and a ``surface.hover`` wash on
  ``:hover`` — the one affordance that lets the eye trace a row across five
  columns. Rows stack with ZERO layout spacing, so the 9px paddings meet as
  the designed 18px inter-row rhythm; each row carries the same fixed grid
  tracks ``150/120/120/90/1fr`` gap 12 (04:462, matches C-15), so columns
  align across rows by construction. Cells: metric sans 13
  ``text.secondary`` · A/B values mono 14/**500** ``text.primary`` · Δ mono
  14/**600** ``text.primary`` · Reading sans 12 ``text.secondary``.

**Δ is NEVER semantically tinted** (C-15 law: "Δ never uses verdict colors —
a louder track isn't 'bad'"): every cell color is set ONCE at construction
and no ``set_rows`` path touches a stylesheet — weight 600 is the only
emphasis the delta gets. All strings arrive prebuilt on ``CompareRowView``
(the pure view-model, one truth); this widget renders them verbatim.

Blessed literals / floors: the design's 12.5px reading type is
unrepresentable in integer QFont pixel sizes — floored to 12 (the C-06 chip
10.5→10 precedent, queued for design reconciliation). The header rule sits
11px above the first row's text (04:463→471): 2px of container spacing plus
the row's own 9px top padding.
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
    COLOR_SURFACE_HOVER,
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
# Header grid padding 0 10px 8px 10px (04:463) — matches the rows' 10px side
# padding so the columns stay aligned.
_GRID_SIDE_PAD = 10
_HEADER_BOTTOM_PAD = 8

# Row chrome (04:471, BINDING): each row is its own hover container with
# ``padding: 9px 10px; border-radius: 7px`` and the ``surface.hover`` wash on
# :hover. Rows stack with ZERO layout spacing — the meeting 9px paddings ARE
# the 18px inter-row rhythm.
ROW_PAD_V = 9
ROW_PAD_H = _GRID_SIDE_PAD  # 10 — must equal the header's side pad (alignment)
ROW_RADIUS = 7
ROW_QSS = (
    f"QFrame#compareRow {{ border: none; border-radius: {ROW_RADIUS}px;"
    " background: transparent; }"
    f" QFrame#compareRow:hover {{ background: {COLOR_SURFACE_HOVER}; }}"  # token: color.surface.hover
)

# Header rule → first-row text = 11px (04:463→471): 2px of container spacing
# plus the first row's own 9px top padding.
_HEADER_RULE_GAP = 11 - ROW_PAD_V


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
        outer.setSpacing(_HEADER_RULE_GAP)  # rule→row = 2 + the row's 9px pad = 11

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

        # -- the six rows: one hover container each (04:471) ---------------------
        body = QFrame(self)
        body.setObjectName("compareTableBody")
        body.setStyleSheet("QFrame#compareTableBody { border: none; background: transparent; }")
        rows_box = QVBoxLayout(body)
        rows_box.setContentsMargins(0, 0, 0, 0)
        rows_box.setSpacing(0)  # the rows' meeting 9px pads ARE the 18px rhythm

        metric_font = ui_font(13)
        value_font = mono_font(14, QFont.Weight.Medium)  # A/B values 14/500
        delta_font = mono_font(14, QFont.Weight.DemiBold)  # Δ 14/600 — its ONLY emphasis
        reading_font = ui_font(12)  # design 12.5 — floored, see module docstring

        self.row_widgets: list[QFrame] = []
        self.metric_labels: list[QLabel] = []
        self.a_value_labels: list[QLabel] = []
        self.b_value_labels: list[QLabel] = []
        self.delta_labels: list[QLabel] = []
        self.reading_labels: list[QLabel] = []

        def _cell(parent: QFrame, font: QFont, color_hex: str) -> QLabel:
            label = QLabel(parent)
            label.setFont(font)
            # Color fixed at construction — set_rows never restyles (C-15 law).
            label.setStyleSheet(
                f"color: {color_hex}; background: transparent;{type_pin(font)}"
            )
            return label

        for _row in range(ROW_COUNT):
            row_widget = QFrame(body)
            row_widget.setObjectName("compareRow")
            row_widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
            row_widget.setStyleSheet(ROW_QSS)  # radius 7 + surface.hover wash
            row_grid = QGridLayout(row_widget)
            # padding: 9px 10px (04:471) as the row grid's margins.
            row_grid.setContentsMargins(ROW_PAD_H, ROW_PAD_V, ROW_PAD_H, ROW_PAD_V)
            row_grid.setHorizontalSpacing(GRID_GAP)
            row_grid.setVerticalSpacing(0)

            metric = _cell(row_widget, metric_font, COLOR_TEXT_SECONDARY)  # token: color.text.secondary
            a_value = _cell(row_widget, value_font, COLOR_TEXT_PRIMARY)  # token: color.text.primary
            b_value = _cell(row_widget, value_font, COLOR_TEXT_PRIMARY)
            delta = _cell(row_widget, delta_font, COLOR_TEXT_PRIMARY)  # NEVER tinted (C-15)
            reading = _cell(row_widget, reading_font, COLOR_TEXT_SECONDARY)
            for col, label in enumerate((metric, a_value, b_value, delta, reading)):
                row_grid.addWidget(label, 0, col, Qt.AlignmentFlag.AlignVCenter)
            # Same fixed tracks in every row — columns align by construction.
            self._fix_columns(row_grid)

            rows_box.addWidget(row_widget)
            self.row_widgets.append(row_widget)
            self.metric_labels.append(metric)
            self.a_value_labels.append(a_value)
            self.b_value_labels.append(b_value)
            self.delta_labels.append(delta)
            self.reading_labels.append(reading)
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
