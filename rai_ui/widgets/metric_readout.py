"""Persistent readout rail (component C-07): every number, always visible.

The 236px right-hand rail is the app's measurement column: verdict card on
top, then the marker-coded tempo numerals (primary 40px over its amber 64×3
tick, felt 24px over its violet dashed 44px tick — C-08 pairs), then the
loudness and dynamics/stereo groups, then the doctrine footer. It consumes a
``ReadoutView`` — the SAME object the meter bridge consumes — so the two
surfaces can never disagree on a digit.

Doctrine enforced here:

* Every numeral is IBM Plex Mono and is NEVER tinted by verdict state — the
  value labels' colors are set once at construction and no ``set_view`` path
  touches them (semantic color never tints a numeral, CL:158).
* Absence is an em-dash, −∞ is a measurement (C-06) — but that rendering is
  the view-model's job; this widget displays ``ReadoutView`` strings verbatim.
  DR / Sub-bass / Stereo width arrive as "—" until M2 lands them (R12).
* Type sizes are the approved screens' literal values (R2): primary 40,
  felt 24, metric rows 16 with 10px units — not the token type-ramp's 64.
* The felt chip (``rel(felt, primary)``) is neutral styling always — the
  amber/violet reserved hues mark the plot, not this pill.
* Footer copy is fixed: "dBTP ≠ dBFS — both always shown, never collapsed."
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rai_ui.state.tempo_view import EMPTY_VIEW, ReadoutView
from rai_ui.theme._tokens_gen import (
    COLOR_BORDER_HAIRLINE,
    COLOR_BORDER_STRONG,
    COLOR_SEMANTIC_MARKER_FELT_BASE,
    COLOR_SEMANTIC_MARKER_PRIMARY_BASE,
    COLOR_SURFACE_ACTIVE,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.verdict_block import VerdictBlock, type_pin

RAIL_WIDTH = 236  # approved rail width (C-05 "rail width 236"; blessed literal, R2)

# Doctrine footer — verbatim (Console CO:599). The bridge's shorter variant
# lives in meter_bridge.py.
RAIL_FOOTER = "dBTP ≠ dBFS — both always shown, never collapsed."


def group_label(text: str, parent: QWidget | None = None) -> QLabel:
    """A design "label"-style heading: 11px/500/0.07em, uppercase, muted."""
    label = QLabel(text.upper(), parent)
    font = ui_font(11, QFont.Weight.Medium)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107.0)  # 0.07em
    label.setFont(font)
    # token: color.text.muted — type pinned widget-level (landmine 6); the
    # 0.07em tracking stays on the QFont (letter-spacing is not a QSS prop).
    label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};{type_pin(font)}")
    return label


class TickBar(QWidget):
    """The C-08 marker-identity tick under a tempo numeral.

    ``primary`` = solid amber bar (radius 2); ``felt`` = 3px dashed violet
    rule on the felt marker's 4-on/3-off pixel rhythm. Purely paint — no
    layout children — so rail and bridge reuse it at their own widths.
    """

    HEIGHT = 3

    def __init__(self, kind: str, width_px: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if kind not in ("primary", "felt"):
            raise ValueError(f"unknown tick kind {kind!r}; expected 'primary' or 'felt'")
        self._kind = kind
        self.setFixedSize(width_px, self.HEIGHT)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._kind == "primary":
            painter.setPen(Qt.PenStyle.NoPen)
            # token: color.semantic.marker-primary.base · radius 2 (CO:567)
            painter.setBrush(QColor(COLOR_SEMANTIC_MARKER_PRIMARY_BASE))
            painter.drawRoundedRect(QRectF(self.rect()), 2.0, 2.0)
        else:
            # token: color.semantic.marker-felt.base — dash pattern in pen
            # widths: (4/3, 1) at width 3 = 4px on / 3px off, the felt
            # marker's 4-3 pixel rhythm (C-08 / R3).
            pen = QPen(QColor(COLOR_SEMANTIC_MARKER_FELT_BASE))
            pen.setWidthF(float(self.HEIGHT))
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setDashPattern([4.0 / 3.0, 1.0])
            painter.setPen(pen)
            y = self.HEIGHT // 2
            painter.drawLine(0, y, self.width(), y)
        painter.end()


def metric_row(
    parent: QWidget, name: str, unit: str | None
) -> tuple[QWidget, QLabel]:
    """One readout row: 12px name left, 16px/600 mono value (+10px unit) right.

    Returns ``(row_widget, value_label)`` — the value label is what
    ``set_view`` updates and what tests compare against the bridge.
    """
    row = QWidget(parent)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    name_label = QLabel(name, row)
    name_font = ui_font(12)
    name_label.setFont(name_font)
    name_label.setStyleSheet(  # token: color.text.secondary
        f"color: {COLOR_TEXT_SECONDARY};{type_pin(name_font)}"
    )
    layout.addWidget(name_label)
    layout.addStretch(1)
    value_label = QLabel(row)
    value_font = mono_font(16, QFont.Weight.DemiBold)  # metric row 16/600 (R2)
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
    return row, value_label


def _divider(parent: QWidget) -> QFrame:
    line = QFrame(parent)
    line.setFixedHeight(1)
    # token: color.border.hairline
    line.setStyleSheet(f"background-color: {COLOR_BORDER_HAIRLINE};")
    return line


class MetricRail(QFrame):
    """The persistent 236px readout rail. One ``set_view(ReadoutView)`` truth."""

    tiebreak_requested = Signal()
    undo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricRail")  # theme QSS: panel bg + left hairline
        self.setFixedWidth(RAIL_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # The rail scrolls vertically on short windows (CO:533 overflow-y:auto);
        # the scroll machinery stays transparent so the QSS panel shows through.
        scroll = QScrollArea(self)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            # Quiet scrollbar on the panel surface (design overflow-y:auto has
            # no chrome of its own). token: color.surface.active
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            "QScrollBar::handle:vertical { background: "
            f"{COLOR_SURFACE_ACTIVE}; border-radius: 4px; min-height: 24px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical "
            "{ background: transparent; }"
        )
        # NOTE: any stylesheet set on the viewport must be selector-scoped —
        # a bare declaration cascades to every rail child and strips e.g. the
        # tiebreak button's red skin (bitten during M1 integration).

        content = QWidget()
        content.setAutoFillBackground(False)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 14)  # rail padding 14px 16px
        layout.setSpacing(13)  # rail vertical gap 13

        # 1. Verdict card.
        self.verdict_block = VerdictBlock(content)
        self.verdict_block.tiebreak_requested.connect(self.tiebreak_requested.emit)
        self.verdict_block.undo_requested.connect(self.undo_requested.emit)
        layout.addWidget(self.verdict_block)

        # 2. Primary BPM: label + 40px numeral + amber 64×3 tick (C-08 pair).
        primary_group = QWidget(content)
        primary_layout = QVBoxLayout(primary_group)
        primary_layout.setContentsMargins(0, 0, 0, 0)
        primary_layout.setSpacing(3)
        primary_layout.addWidget(group_label("Primary BPM", primary_group))
        self.primary_value = QLabel(primary_group)
        primary_font = mono_font(40, QFont.Weight.DemiBold)  # rail primary 40/600 (R2)
        self.primary_value.setFont(primary_font)
        self.primary_value.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(primary_font)}"
        )
        primary_layout.addWidget(self.primary_value)
        primary_layout.addSpacing(2)  # tick margin-top 2 (CO:567)
        primary_layout.addWidget(TickBar("primary", 64, primary_group))  # 64×3 (CO:567)
        layout.addWidget(primary_group)

        # 3. Felt: label + 24px numeral + violet dashed 44px tick + optional
        #    right-aligned relationship chip (rel(felt, primary), CO:849).
        felt_row = QWidget(content)
        felt_row_layout = QHBoxLayout(felt_row)
        felt_row_layout.setContentsMargins(0, 0, 0, 0)
        felt_row_layout.setSpacing(8)
        felt_group = QWidget(felt_row)
        felt_layout = QVBoxLayout(felt_group)
        felt_layout.setContentsMargins(0, 0, 0, 0)
        felt_layout.setSpacing(3)
        felt_layout.addWidget(group_label("Felt", felt_group))
        self.felt_value = QLabel(felt_group)
        felt_font = mono_font(24, QFont.Weight.Medium)  # rail felt 24/500 (R2)
        self.felt_value.setFont(felt_font)
        self.felt_value.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(felt_font)}"
        )
        felt_layout.addWidget(self.felt_value)
        felt_layout.addSpacing(2)
        felt_layout.addWidget(TickBar("felt", 44, felt_group))  # 44px dashed (CO:573)
        felt_row_layout.addWidget(felt_group)
        felt_row_layout.addStretch(1)
        self.felt_chip_label = QLabel(felt_row)
        chip_font = mono_font(11)
        self.felt_chip_label.setFont(chip_font)
        self.felt_chip_label.setFixedHeight(20)  # pill h20
        self.felt_chip_label.setStyleSheet(
            # token: color.border.strong / color.text.primary — neutral pill,
            # never the reserved marker hues (radius = half of h20).
            f"border: 1px solid {COLOR_BORDER_STRONG}; border-radius: 10px;"
            f" padding: 0 9px; color: {COLOR_TEXT_PRIMARY};{type_pin(chip_font)}"
        )
        self.felt_chip_label.hide()
        felt_row_layout.addWidget(self.felt_chip_label, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addWidget(felt_row)

        layout.addWidget(_divider(content))

        # 4. Loudness group.
        loudness_group = QWidget(content)
        loudness_layout = QVBoxLayout(loudness_group)
        loudness_layout.setContentsMargins(0, 0, 0, 0)
        loudness_layout.setSpacing(8)
        loudness_layout.addWidget(group_label("Loudness", loudness_group))
        row, self.lufs_value = metric_row(loudness_group, "Integrated", "LUFS")
        loudness_layout.addWidget(row)
        row, self.dbtp_value = metric_row(loudness_group, "True peak", "dBTP")
        loudness_layout.addWidget(row)
        row, self.dbfs_value = metric_row(loudness_group, "Sample peak", "dBFS")
        loudness_layout.addWidget(row)
        layout.addWidget(loudness_group)

        layout.addWidget(_divider(content))

        # 5. Dynamics · stereo group (values are "—" until M2 — R12).
        dynamics_group = QWidget(content)
        dynamics_layout = QVBoxLayout(dynamics_group)
        dynamics_layout.setContentsMargins(0, 0, 0, 0)
        dynamics_layout.setSpacing(8)
        dynamics_layout.addWidget(group_label("Dynamics · stereo", dynamics_group))
        row, self.dr_value = metric_row(dynamics_group, "Dyn range", "dB")
        dynamics_layout.addWidget(row)
        row, self.sub_value = metric_row(dynamics_group, "Sub/bass", None)
        dynamics_layout.addWidget(row)
        row, self.width_value = metric_row(dynamics_group, "Stereo width", None)
        dynamics_layout.addWidget(row)
        layout.addWidget(dynamics_group)

        layout.addStretch(1)

        # 6. Doctrine footer — exact copy, never reworded.
        self.footer_label = QLabel(RAIL_FOOTER, content)
        footer_font = ui_font(11)
        self.footer_label.setFont(footer_font)
        self.footer_label.setWordWrap(True)
        self.footer_label.setStyleSheet(  # token: color.text.muted
            f"color: {COLOR_TEXT_MUTED};{type_pin(footer_font)}"
        )
        layout.addWidget(self.footer_label)

        scroll.setWidget(content)
        # QScrollArea::setWidget re-ENABLES autoFillBackground on the widget
        # it adopts (Qt behavior), which painted the whole rail palette-Base
        # #EFEFEF in the M1 preview shots. Clear it again AFTER setWidget so
        # the #metricRail panel genuinely shows through.
        content.setAutoFillBackground(False)
        outer.addWidget(scroll)

        self._view: ReadoutView = EMPTY_VIEW.readout
        self.set_view(self._view)

    # -- API ------------------------------------------------------------------

    def set_view(self, view: ReadoutView) -> None:
        """Render ``view`` verbatim. Never touches a numeral's color."""
        self._view = view
        self.verdict_block.set_verdict(view.verdict)
        self.primary_value.setText(view.primary_text)
        self.felt_value.setText(view.felt_text)
        if view.felt_chip is None:
            self.felt_chip_label.hide()
        else:
            self.felt_chip_label.setText(view.felt_chip.text)
            self.felt_chip_label.show()
        self.lufs_value.setText(view.lufs_text)
        self.dbtp_value.setText(view.dbtp_text)
        self.dbfs_value.setText(view.dbfs_text)
        self.dr_value.setText(view.dr_text)
        self.sub_value.setText(view.sub_text)
        self.width_value.setText(view.width_text)

    def view(self) -> ReadoutView:
        """The last-rendered view (test/introspection hook)."""
        return self._view
