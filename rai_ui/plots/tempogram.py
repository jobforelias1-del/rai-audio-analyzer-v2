"""Tempogram pane (component C-16): the 1-D combined salience curve over BPM.

Layer order, bottom to top, exactly as the approved Console draws it:
vertical grid hairlines (every 20 BPM) → solid acceptance-band region with
1px edge lines → the salience curve (2px cosmetic data pen, solid fill to
the baseline) → candidate ticks (drawn by the custom axis row) → full-height
primary/felt markers → their label chips. **No legend widget — ever**
(CL:345): the candidate table is the legend, and each marker carries its own
label chip instead.

Frame anatomy: a 34px label row ("TEMPOGRAM" + subtitle), the plot bed, and
a 28px custom-painted axis row. pyqtgraph's own axes are hidden — the design
wants ticks at true data positions with only the last tick carrying the
"BPM" unit, plus 2×10px candidate ticks on the axis row's top edge, none of
which AxisItem gives us. The x-domain is locked to 40–240 BPM (the engine's
grid) with zero padding and all mouse interaction disabled, so the linear
map ``x(bpm) = (bpm − 40)/200`` holds for every layer (CO:644).

Marker label chips are child QWidgets (C-08 "marker-coded pair"), custom
painted so QSS cannot drift them, repositioned on resize and on set_view.
They stagger vertically (primary top 40px, felt 70px) and flip to the
marker's left past 72% of the span — the side is decided upstream in the
view-model (``plots.helpers.marker_label_side``), never re-derived here.

The working sweep (C-17) is a solid overlay with a 2px accent line sweeping
left→right on a 1200ms loop. The animation runs only while the overlay is
effectively visible: it starts in showEvent and stops in hideEvent, so
switching sections or closing the window can never leak a running timer.
Motion is decorative — with the animation stopped the overlay still reads
"WORKING…" (TK motion policy).

No-tempo is a neutral state, never error styling (ruling R14): a flat 1px
baseline at plot mid-height plus the computed "no periodicity — …" line.

This module imports pyqtgraph at the top (widget layer); the pure placement
math it relies on lives in ``rai_ui.plots.helpers`` per the package doctrine.
"""

from __future__ import annotations

from typing import Optional

import pyqtgraph as pg
from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rai_ui.state.tempo_view import (
    BPM_AXIS_MAX,
    BPM_AXIS_MIN,
    EMPTY_VIEW,
    MarkerView,
    TempoViewModel,
)
from rai_ui.theme._tokens_gen import (
    BRUSH_BAND,
    BRUSH_DATA_A_FILL,
    COLOR_ACCENT_BASE,
    COLOR_BORDER_STRONG,
    COLOR_PLOT_AXIS_TEXT,
    COLOR_PLOT_GRID,
    COLOR_SEMANTIC_MARKER_FELT_BASE,
    COLOR_SEMANTIC_MARKER_FELT_BG,
    COLOR_SEMANTIC_MARKER_FELT_TEXT,
    COLOR_SEMANTIC_MARKER_PRIMARY_BASE,
    COLOR_SEMANTIC_MARKER_PRIMARY_BG,
    COLOR_SEMANTIC_MARKER_PRIMARY_TEXT,
    COLOR_SURFACE_INSET,
    COLOR_SURFACE_PANEL,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
    MOTION_WORKING_SWEEP_MS,
    PEN_DATA_A,
    PEN_GRID,
    PEN_MARKER_FELT,
    PEN_MARKER_PRIMARY,
    RADIUS_SM,
    TYPE_FAMILY_NUMERIC,
    TYPE_FAMILY_UI,
)
from rai_ui.theme.pens import PEN_BAND_EDGE, qbrush, qpen

# --- frame geometry (approved Console, CO:208-257) ---------------------------
LABEL_ROW_H = 34  # pane label strip
AXIS_ROW_H = 28  # custom axis strip
PANE_MIN_H = 190  # design: min-height:190px inside the Tempo column
_FRAME_INSET = 1  # keep the pane's QSS hairline border visible under children

# The plot's fixed window: x locked to the engine's BPM grid, y headroom so a
# salience of 1.0 does not kiss the label row.
Y_MAX = 1.05
GRID_STEP_BPM = 20.0  # vertical hairline every 20 BPM = every 10% of width

# --- marker label chips (C-08, CO:226-234) -----------------------------------
CHIP_H = 22
CHIP_PAD_X = 8
CHIP_SWATCH_W = 8
CHIP_SWATCH_H = 3
CHIP_GAP = 6  # swatch → text
CHIP_TOP_PRIMARY = 40  # vertical stagger, measured from the pane's top
CHIP_TOP_FELT = 70
CHIP_MARKER_GAP = 8  # horizontal gap between marker line and chip edge

# --- axis row (CO:250-257) ----------------------------------------------------
CANDIDATE_TICK_W = 2
CANDIDATE_TICK_H = 10
AXIS_LABEL_MARGIN = 2  # keep edge tick labels off the frame border
AXIS_UNIT_SUFFIX = " BPM"  # only the last tick carries the unit

# --- band label / no-tempo (CO:215, CO:236-240, C-17) -------------------------
BAND_LABEL_GAP = 6  # px above the axis row

# --- working sweep (C-17, CO:241-249) ------------------------------------------
SWEEP_START_FRAC = -0.04  # mock keyframes: left:-4% → 102%
SWEEP_END_FRAC = 1.02
SWEEP_LINE_W = 2
WORKING_WORD = "WORKING…"
WORKING_SUB = "full-track analysis · ~1 s"


def axis_tick_label(tick: float, is_last: bool) -> str:
    """The axis row's label for one tick — only the last carries the unit."""
    text = f"{tick:g}"
    return text + AXIS_UNIT_SUFFIX if is_last else text


class _MarkerChip(QWidget):
    """One marker label chip (C-08): swatch + mono label on a panel pill.

    Custom painted so the design's exact geometry (h22, pad 8, radius 4,
    swatch 8px, gap 6) cannot be nudged by QSS. The swatch mirrors the
    marker's pen identity: primary = filled amber bar, felt = dashed violet.
    """

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if kind == "primary":
            # token: color.semantic.marker-primary.{base,bg,text}
            self._swatch = QColor(COLOR_SEMANTIC_MARKER_PRIMARY_BASE)
            self._border = QColor(COLOR_SEMANTIC_MARKER_PRIMARY_BG)
            self._text_color = QColor(COLOR_SEMANTIC_MARKER_PRIMARY_TEXT)
        elif kind == "felt":
            # token: color.semantic.marker-felt.{base,bg,text}
            self._swatch = QColor(COLOR_SEMANTIC_MARKER_FELT_BASE)
            self._border = QColor(COLOR_SEMANTIC_MARKER_FELT_BG)
            self._text_color = QColor(COLOR_SEMANTIC_MARKER_FELT_TEXT)
        else:
            raise ValueError(f"unknown marker kind {kind!r}")
        self.kind = kind
        self._dashed_swatch = kind == "felt"
        self._label = ""
        # Plex Mono 12/600 (design C-08); painter font, immune to app QSS.
        self._font = QFont(TYPE_FAMILY_NUMERIC)
        self._font.setPixelSize(12)
        self._font.setWeight(QFont.Weight.DemiBold)
        self.setFixedHeight(CHIP_H)

    def label(self) -> str:
        return self._label

    def set_label(self, label: str) -> None:
        self._label = label
        text_w = QFontMetricsF(self._font).horizontalAdvance(label)
        self.setFixedWidth(
            round(CHIP_PAD_X + CHIP_SWATCH_W + CHIP_GAP + text_w + CHIP_PAD_X)
        )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(self._border, 1.0))
        painter.setBrush(QColor(COLOR_SURFACE_PANEL))  # token: color.surface.panel
        painter.drawRoundedRect(rect, RADIUS_SM, RADIUS_SM)

        swatch_y = (CHIP_H - CHIP_SWATCH_H) / 2
        if self._dashed_swatch:
            # 8px dashed stroke, dash 4-3 (on 0–4, off 4–7, on 7–8).
            painter.fillRect(QRectF(CHIP_PAD_X, swatch_y, 4, CHIP_SWATCH_H), self._swatch)
            painter.fillRect(QRectF(CHIP_PAD_X + 7, swatch_y, 1, CHIP_SWATCH_H), self._swatch)
        else:
            painter.fillRect(
                QRectF(CHIP_PAD_X, swatch_y, CHIP_SWATCH_W, CHIP_SWATCH_H), self._swatch
            )

        painter.setFont(self._font)
        painter.setPen(self._text_color)
        text_rect = QRectF(
            CHIP_PAD_X + CHIP_SWATCH_W + CHIP_GAP, 0, self.width(), CHIP_H
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._label,
        )


class _TempoAxisRow(QWidget):
    """The 28px custom axis strip: top rule, true-position tick labels, and
    2×10px candidate ticks on its top edge.

    pyqtgraph's AxisItem is bypassed because the design's axis is not an
    axis widget: labels sit at true data positions with only the final one
    unit-suffixed, and the candidate ticks belong to this strip, not the
    plot. The linear map matches the plot above (same width, same 40–240
    domain, zero padding), so everything stays column-aligned.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(AXIS_ROW_H)
        self._ticks: tuple[float, ...] = ()
        self._candidate_bpms: tuple[float, ...] = ()
        self._span: tuple[float, float] = (0.0, 1.0)
        # Plex Mono 11 (design axis text); painter font, immune to app QSS.
        self._font = QFont(TYPE_FAMILY_NUMERIC)
        self._font.setPixelSize(11)

    def set_data(
        self,
        ticks: tuple[float, ...],
        candidate_bpms: tuple[float, ...],
        span: tuple[float, float],
    ) -> None:
        self._ticks = ticks
        self._candidate_bpms = candidate_bpms
        self._span = span
        self.update()

    def candidate_bpms(self) -> tuple[float, ...]:
        return self._candidate_bpms

    def _x_for(self, bpm: float) -> float:
        lo, hi = self._span
        if hi <= lo:
            return 0.0
        return (bpm - lo) / (hi - lo) * self.width()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        width = self.width()
        # Top rule — the axis line (design: border-top 1px plot.grid).
        painter.fillRect(QRectF(0, 0, width, 1), QColor(COLOR_PLOT_GRID))  # token: color.plot.grid

        # Candidate ticks, sitting on the axis line (2×10px).
        # token: color.border.strong — the design's candidate-tick #333D49
        tick_color = QColor(COLOR_BORDER_STRONG)
        for bpm in self._candidate_bpms:
            x = self._x_for(bpm)
            painter.fillRect(
                QRectF(round(x) - CANDIDATE_TICK_W / 2, 0, CANDIDATE_TICK_W, CANDIDATE_TICK_H),
                tick_color,
            )

        # Tick labels at true data positions; edge labels clamped inward.
        painter.setFont(self._font)
        painter.setPen(QColor(COLOR_PLOT_AXIS_TEXT))  # token: color.plot.axis-text
        metrics = QFontMetricsF(self._font)
        for i, tick in enumerate(self._ticks):
            label = axis_tick_label(tick, i == len(self._ticks) - 1)
            text_w = metrics.horizontalAdvance(label)
            x = self._x_for(tick) - text_w / 2
            x = max(AXIS_LABEL_MARGIN, min(x, width - text_w - AXIS_LABEL_MARGIN))
            painter.drawText(
                QRectF(x, 1, text_w, self.height() - 1),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )


class _WorkingOverlay(QWidget):
    """The C-17 working state: solid cover, sweeping accent line, quiet copy.

    The sweep animation is owned here and tied to *effective* visibility:
    started in showEvent, stopped in hideEvent. Hiding the pane (or any
    ancestor — e.g. switching sections) delivers a hide event to this child,
    so the animation can never keep ticking off-screen. With motion disabled
    or stopped the overlay still communicates via its static text.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction = SWEEP_START_FRAC

        # 1200ms infinite sweep on the design's standard easing curve
        # (cubic-bezier(0.2, 0, 0, 1) — token: motion.easing).
        easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
        easing.addCubicBezierSegment(QPointF(0.2, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(SWEEP_START_FRAC)
        self._animation.setEndValue(SWEEP_END_FRAC)
        self._animation.setDuration(MOTION_WORKING_SWEEP_MS)  # token: motion.working-sweep
        self._animation.setEasingCurve(easing)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._on_fraction)

        # Plex Mono 12/600 word + Plex Sans 12 sub (painter fonts).
        self._word_font = QFont(TYPE_FAMILY_NUMERIC)
        self._word_font.setPixelSize(12)
        self._word_font.setWeight(QFont.Weight.DemiBold)
        self._sub_font = QFont(TYPE_FAMILY_UI)
        self._sub_font.setPixelSize(12)

    def sweep_running(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    def _on_fraction(self, value) -> None:
        self._fraction = float(value)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._animation.state() != QVariantAnimation.State.Running:
            self._animation.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLOR_SURFACE_INSET))  # token: color.surface.inset

        sweep_x = self._fraction * self.width()
        painter.fillRect(
            QRectF(sweep_x, 0, SWEEP_LINE_W, self.height()),
            QColor(COLOR_ACCENT_BASE),  # token: color.accent.base
        )

        center_y = self.height() / 2
        painter.setFont(self._word_font)
        painter.setPen(QColor(COLOR_TEXT_SECONDARY))  # token: color.text.secondary
        painter.drawText(
            QRectF(0, center_y - 24, self.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            WORKING_WORD,
        )
        painter.setFont(self._sub_font)
        painter.setPen(QColor(COLOR_TEXT_MUTED))  # token: color.text.muted
        painter.drawText(
            QRectF(0, center_y + 4, self.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            WORKING_SUB,
        )


class TempogramPane(QFrame):
    """The framed tempogram well: label row / pyqtgraph bed / custom axis row.

    Single data entry point ``set_view(vm)`` — everything on screen derives
    from the ``TempoViewModel``, never from engine objects directly.
    ``set_working(active)`` toggles the C-17 sweep overlay.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # "tempogramPane" matches the theme QSS (QFrame#tempogramPane).
        self.setObjectName("tempogramPane")
        self.setMinimumHeight(PANE_MIN_H)

        self._vm: TempoViewModel = EMPTY_VIEW

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FRAME_INSET, _FRAME_INSET, _FRAME_INSET, _FRAME_INSET)
        layout.setSpacing(0)

        layout.addWidget(self._build_label_row())

        # --- plot bed ---------------------------------------------------------
        self._plot = pg.PlotWidget(background=COLOR_SURFACE_INSET)  # token: color.surface.inset
        plot_item = self._plot.getPlotItem()
        plot_item.hideAxis("left")
        plot_item.hideAxis("bottom")
        plot_item.hideButtons()
        plot_item.setMenuEnabled(False)  # no context menu (and no legend, ever)
        plot_item.setContentsMargins(0, 0, 0, 0)
        plot_item.layout.setContentsMargins(0, 0, 0, 0)
        plot_item.layout.setSpacing(0)
        viewbox = plot_item.getViewBox()
        viewbox.setMouseEnabled(x=False, y=False)
        viewbox.setDefaultPadding(0.0)
        viewbox.disableAutoRange()
        self._span = (BPM_AXIS_MIN, BPM_AXIS_MAX)
        viewbox.setXRange(BPM_AXIS_MIN, BPM_AXIS_MAX, padding=0)
        viewbox.setYRange(0.0, Y_MAX, padding=0)
        layout.addWidget(self._plot, 1)

        self._axis = _TempoAxisRow(self)
        layout.addWidget(self._axis)

        # --- static plot items (created once — set_view only mutates them) ----
        # Grid: vertical hairlines every 20 BPM, interior only (the frame's
        # edges stand in for 40 and 240).
        bpm = BPM_AXIS_MIN + GRID_STEP_BPM
        while bpm < BPM_AXIS_MAX:
            line = pg.InfiniteLine(pos=bpm, angle=90, movable=False, pen=qpen(PEN_GRID))
            line.setZValue(-30)
            self._plot.addItem(line)
            bpm += GRID_STEP_BPM

        # Acceptance band with its 1px edge lines (C-16; ruling R11 token).
        self._band = pg.LinearRegionItem(
            values=EMPTY_VIEW.band,
            orientation="vertical",
            movable=False,
            brush=qbrush(BRUSH_BAND),  # token: color.plot.band
            pen=qpen(PEN_BAND_EDGE),  # token: color.plot.band-edge
        )
        self._band.setZValue(-20)
        self._plot.addItem(self._band)

        # Salience curve: 2px cosmetic data pen, solid fill to the baseline.
        self._curve = pg.PlotDataItem(
            pen=qpen(PEN_DATA_A),  # token: color.plot.data-a
            fillLevel=0.0,
            brush=qbrush(BRUSH_DATA_A_FILL),  # token: color.plot.data-a-fill
        )
        self._curve.setZValue(-10)
        self._plot.addItem(self._curve)

        # No-tempo flat baseline at plot mid-height (ruling R14).
        self._baseline = pg.InfiniteLine(
            pos=Y_MAX / 2, angle=0, movable=False, pen=qpen(PEN_GRID)
        )
        self._baseline.setZValue(-10)
        self._baseline.setVisible(False)
        self._plot.addItem(self._baseline)

        # Full-height markers — persistent, shown per view-model.
        self._marker_lines: dict[str, pg.InfiniteLine] = {
            "primary": pg.InfiniteLine(
                pos=0.0, angle=90, movable=False, pen=qpen(PEN_MARKER_PRIMARY)
            ),  # token: color.semantic.marker-primary.base
            "felt": pg.InfiniteLine(
                pos=0.0, angle=90, movable=False, pen=qpen(PEN_MARKER_FELT)
            ),  # token: color.semantic.marker-felt.base (dash 4-3 per tokens/C-08)
        }
        for line in self._marker_lines.values():
            line.setZValue(10)
            line.setVisible(False)
            self._plot.addItem(line)

        # --- floating children (manual geometry, above the plot) --------------
        self._chips: dict[str, _MarkerChip] = {
            "primary": _MarkerChip("primary", self),
            "felt": _MarkerChip("felt", self),
        }
        for chip in self._chips.values():
            chip.hide()

        self._band_label = QLabel(self)
        # Mono 11 muted, pinned widget-level (app QSS would restyle a bare QLabel).
        self._band_label.setStyleSheet(
            f'font-family: "{TYPE_FAMILY_NUMERIC}"; font-size: 11px;'
            f" color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
        )
        self._band_label.hide()

        self._no_tempo_label = QLabel(self)
        self._no_tempo_label.setStyleSheet(
            f'font-family: "{TYPE_FAMILY_UI}"; font-size: 13px;'
            f" color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
        )
        self._no_tempo_label.hide()

        self._overlay = _WorkingOverlay(self)
        self._overlay.hide()

        self.set_view(EMPTY_VIEW)

    # -- public API -------------------------------------------------------------

    def set_view(self, vm: TempoViewModel) -> None:
        """Render a view-model. Idempotent: no plot items or child widgets are
        created here, only mutated, so calling twice changes nothing."""
        self._vm = vm

        self._band.setRegion(vm.band)
        band_lo, band_hi = vm.band
        self._band_label.setText(f"BAND {band_lo:g}–{band_hi:g}")
        self._band_label.adjustSize()
        self._band_label.setVisible(True)

        if vm.curve_bpms is not None and vm.curve_salience is not None and not vm.no_tempo:
            self._curve.setData(vm.curve_bpms, vm.curve_salience)
            self._curve.setVisible(True)
        else:
            self._curve.setData([], [])
            self._curve.setVisible(False)

        self._baseline.setVisible(vm.no_tempo)
        self._no_tempo_label.setText(vm.no_tempo_text or "")
        self._no_tempo_label.adjustSize()
        self._no_tempo_label.setVisible(vm.no_tempo)

        markers_by_kind = {m.kind: m for m in vm.markers}
        for kind, line in self._marker_lines.items():
            marker = markers_by_kind.get(kind)
            chip = self._chips[kind]
            if marker is None:
                line.setVisible(False)
                chip.hide()
            else:
                line.setValue(marker.bpm)
                line.setVisible(True)
                chip.set_label(marker.label)
                chip.setVisible(True)

        self._axis.set_data(
            vm.axis_ticks, tuple(c.bpm for c in vm.candidates), self._span
        )
        self._reposition_floats()

    def set_working(self, active: bool) -> None:
        """Toggle the C-17 sweep overlay (animation follows visibility)."""
        if active:
            self._overlay.setGeometry(self._overlay_rect())
            self._overlay.raise_()
        self._overlay.setVisible(active)

    def sweep_running(self) -> bool:
        """True while the working sweep animation is actually ticking."""
        return self._overlay.sweep_running()

    def bpm_to_x(self, bpm: float) -> float:
        """Map a BPM to this pane's x pixel through the locked 40–240 domain.

        The viewbox fills the plot widget (axes hidden, zero margins, zero
        padding), so the linear map over the plot's geometry is the same map
        every layer uses. Public because tests and the section assert
        alignment through it.
        """
        rect = self._plot.geometry()
        lo, hi = self._span
        return rect.x() + (bpm - lo) / (hi - lo) * rect.width()

    # -- internals ---------------------------------------------------------------

    def _build_label_row(self) -> QWidget:
        row = QWidget(self)
        row.setFixedHeight(LABEL_ROW_H)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(10)

        title = QLabel("TEMPOGRAM", row)
        title_font = QFont(TYPE_FAMILY_UI)
        title_font.setPixelSize(11)
        title_font.setWeight(QFont.Weight.Medium)
        # Label style tracking 0.07em (design "Label" style).
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)
        title.setFont(title_font)
        title.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {COLOR_TEXT_MUTED};"
            " background: transparent;"  # token: color.text.muted
        )
        row_layout.addWidget(title)

        subtitle = QLabel("combined salience over BPM · drill band shaded", row)
        subtitle.setStyleSheet(
            f'font-family: "{TYPE_FAMILY_UI}"; font-size: 11px;'
            f" color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
        )
        row_layout.addWidget(subtitle)
        row_layout.addStretch(1)
        return row

    def _overlay_rect(self):
        return self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)

    def _place_chip(self, chip: _MarkerChip, marker: MarkerView) -> None:
        x = self.bpm_to_x(marker.bpm)
        if marker.side == "left":
            left = round(x - CHIP_MARKER_GAP - chip.width())
        else:
            left = round(x + CHIP_MARKER_GAP)
        # Never clipped (C-08): clamp inside the pane whatever the side says.
        left = max(_FRAME_INSET, min(left, self.width() - chip.width() - _FRAME_INSET))
        top = CHIP_TOP_PRIMARY if marker.kind == "primary" else CHIP_TOP_FELT
        chip.move(left, top)
        chip.raise_()

    def _reposition_floats(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()  # geometry must be current before mapping BPM → px

        markers_by_kind = {m.kind: m for m in self._vm.markers}
        for kind, chip in self._chips.items():
            marker = markers_by_kind.get(kind)
            if marker is not None:
                self._place_chip(chip, marker)

        plot_rect = self._plot.geometry()

        band_lo, band_hi = self._vm.band
        band_center_x = self.bpm_to_x((band_lo + band_hi) / 2)
        self._band_label.move(
            round(band_center_x - self._band_label.width() / 2),
            plot_rect.bottom() - BAND_LABEL_GAP - self._band_label.height(),
        )

        self._no_tempo_label.move(
            round(plot_rect.center().x() - self._no_tempo_label.width() / 2),
            round(plot_rect.center().y() - self._no_tempo_label.height() / 2),
        )

        if self._overlay.isVisible():
            self._overlay.setGeometry(self._overlay_rect())
            self._overlay.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._overlay.setGeometry(self._overlay_rect())
        self._reposition_floats()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._reposition_floats()
