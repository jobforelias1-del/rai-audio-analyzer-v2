"""Frequency-spectrum pane (Signal section): the Welch PSD curve over log-x.

Mirrors the tempogram pane's proven anatomy (C-16 idiom): a 34px label row
("FREQUENCY SPECTRUM" + caption), the pyqtgraph plot bed with both native
axes hidden, and a 28px custom-painted axis row. All plot items are created
once in ``__init__`` and only mutated in ``set_view`` — never re-created —
so a repeated call is a no-op (idempotency is test-pinned).

The x-domain is LOG frequency (R-M2-7): data is plotted at ``log10(freq)``
with the viewbox locked to ``log10(20)..log10(20000)`` and zero padding, so
the linear map over the plot's geometry IS the log-frequency map and every
layer (curve, axis labels) shares it. The design's five axis labels sit at
their TRUE log positions — the approved mock's even spacing was a shortcut;
the caption "log frequency" is the binding intent (design recon §1a) — and
only the end labels carry units (``20 Hz`` … ``20 kHz``). The drawn curve is
min/max-decimated to ≤ 2048 points (R-M3-15, paint-cost fix — visually
identical, every PSD bin provably contained); antialiasing stays ON for this
diagonal curve, unlike the waveform's AA-off vertical columns.

The y-domain is the display-normalized dB range from
:mod:`rai_ui.state.signal_view` (curve max at the 0 dB top, −90 dB floor —
the normalization itself happens in the view-model builder, one truth), plus
the same 5% headroom the tempogram gives its curve so a 0 dB peak does not
kiss the label row. The design renders NO y-axis labels (R-M2-7) — the grid
is three horizontal hairlines at 25% steps of the bed (04:410; the Signal
plot deliberately flips the tempogram's vertical-grid orientation).

Silence (R-M2-8): no curve — the well shows the authored copy
(``vm.silent_text``) centered on the bed, C-17 neutral styling, exactly the
tempogram's no-tempo pattern. The UNMEASURABLE state (non-silent file, no
finite spectrum bins — e.g. pure DC) rides the same label with
``vm.unmeasurable_text``: the view-model owns both copies, the pane just
shows whichever one is set. C-17's "flat baseline" is already on screen:
the persistent 50% gridline is a 1px ``plot.grid`` horizontal — drawing a
second grid-colored line at the same place would be a no-op, so no separate
baseline item exists here (documented divergence from the tempogram, whose
grid is vertical and therefore needed a dedicated baseline).

The working overlay is the tempogram's ``_WorkingOverlay`` imported directly
— C-17 authored exactly one working state and re-implementing it would only
create drift (same-package reuse; its animation start/stop already follows
effective visibility, so no timer can leak).

**No mouse, no menu, no legend — ever** (C-16, CL:345).
"""

from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rai_ui.plots.decimate import minmax_decimate
from rai_ui.plots.tempogram import _WorkingOverlay
from rai_ui.state.signal_view import (
    EMPTY_SIGNAL_VIEW,
    SPECTRUM_FLOOR_DB,
    SPECTRUM_TOP_DB,
    SignalViewModel,
)
from rai_ui.theme._tokens_gen import (
    BRUSH_DATA_A_FILL,
    COLOR_PLOT_AXIS_TEXT,
    COLOR_PLOT_GRID,
    COLOR_SURFACE_INSET,
    COLOR_TEXT_MUTED,
    PEN_DATA_A,
    PEN_GRID,
    TYPE_FAMILY_NUMERIC,
    TYPE_FAMILY_UI,
)
from rai_ui.theme.pens import qbrush, qpen
from rai_ui.widgets.verdict_block import type_pin

# --- frame geometry (C-16 idiom, same strips as the tempogram) ----------------
LABEL_ROW_H = 34  # pane label strip
AXIS_ROW_H = 28  # custom axis strip
_FRAME_INSET = 1  # keep the pane's QSS hairline border visible under children

# --- label row copy (design recon §7, verbatim) --------------------------------
PANE_TITLE = "FREQUENCY SPECTRUM"
PANE_CAPTION = "average magnitude · log frequency"

# --- x-domain: log frequency 20 Hz → 20 kHz (R-M2-7) ---------------------------
FREQ_MIN_HZ = 20.0
FREQ_MAX_HZ = 20000.0
_LOG_MIN = math.log10(FREQ_MIN_HZ)
_LOG_MAX = math.log10(FREQ_MAX_HZ)

# The five axis labels (04:415–421 verbatim) — only the ends carry units.
AXIS_TICKS: tuple[tuple[float, str], ...] = (
    (20.0, "20 Hz"),
    (100.0, "100"),
    (1000.0, "1 k"),
    (10000.0, "10 k"),
    (20000.0, "20 kHz"),
)
AXIS_LABEL_MARGIN = 2  # keep edge tick labels off the frame border

# --- y-domain: normalized display dB (view-model truth) + curve headroom -------
# The tempogram gives its 0..1 curve 5% headroom (Y_MAX = 1.05) so a full-
# scale value does not kiss the label row; the same 5% of the 90 dB display
# range is 4.5 dB. The data itself stays max-at-0 dB (R-M2-7).
Y_HEADROOM_DB = 0.05 * (SPECTRUM_TOP_DB - SPECTRUM_FLOOR_DB)
Y_VIEW_BOTTOM_DB = SPECTRUM_FLOOR_DB
Y_VIEW_TOP_DB = SPECTRUM_TOP_DB + Y_HEADROOM_DB

# Horizontal gridlines at 25% steps of the bed, interior only — the label and
# axis rows' rules stand in for the edges (04:410).
GRID_FRACS = (0.25, 0.5, 0.75)

# R-M3-15: the drawn curve is capped at this many points. A real file's Welch
# grid is ~8k bins — an order of magnitude past any plausible bed width — and
# stroking all of them under the 2.0px antialiased data pen cost ~67 ms per
# paint (recon-measured; ~17 ms decimated). Min/max decimation keeps both
# extremes per bin, so the drawn curve provably contains every PSD bin and a
# single-bin spike stays visible. Antialiasing itself is KEPT: unlike the
# waveform's vertical columns, this curve is diagonal and DOES alias.
SPECTRUM_MAX_POINTS = 2048


def log_x_fraction(freq_hz: float) -> float:
    """A frequency's fractional position on the locked log-x span (0..1)."""
    return (math.log10(freq_hz) - _LOG_MIN) / (_LOG_MAX - _LOG_MIN)


def decimate_curve(
    x: np.ndarray, y: np.ndarray, max_points: int = SPECTRUM_MAX_POINTS
) -> tuple[np.ndarray, np.ndarray]:
    """Min/max-decimate a dense ``(x, y)`` curve to at most ``max_points``.

    Display-only (R-M3-15): each of ``max_points // 2`` contiguous bins
    contributes two drawn points — its y-minimum at the bin's first x and its
    y-maximum at the bin's last x — so the drawn polyline contains every
    sample's y (the ``minmax_decimate`` doctrine: never drop a transient) and
    the curve's x endpoints are preserved exactly. Within a bin the two
    extremes ride the bin's edge x-positions rather than their true ones —
    sub-pixel at any plausible bed width, and the pairing is monotonic in x.

    A curve already at or below ``max_points`` passes through unchanged —
    decimating would fabricate nothing and lose nothing, so it is skipped.
    Pure numpy, exposed for tests. Bin geometry (linspace edges) is exactly
    ``rai_ui.plots.decimate.minmax_decimate``'s, which computes the y
    extremes.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    n = y.size
    if n <= max_points:
        return x, y
    bins = max_points // 2
    mins, maxs = minmax_decimate(y, bins)
    # The same edge geometry minmax_decimate used (n > bins holds because
    # n > max_points >= 2 * bins), re-derived here for the x positions.
    edges = np.linspace(0, n, bins + 1).astype(np.intp)
    xs = np.empty(2 * bins, dtype=np.float64)
    ys = np.empty(2 * bins, dtype=np.float64)
    xs[0::2] = x[edges[:-1]]  # bin's first sample x
    xs[1::2] = x[edges[1:] - 1]  # bin's last sample x — keeps the endpoints
    ys[0::2] = mins
    ys[1::2] = maxs
    return xs, ys


class _SpectrumAxisRow(QWidget):
    """The 28px custom axis strip: top rule + the five fixed frequency labels
    at TRUE log positions, edge labels clamped inward.

    pyqtgraph's AxisItem is bypassed for the same reason as the tempogram's:
    the design's axis is not an axis widget — five fixed labels, units only
    at the ends, no ticks. The log map matches the plot above (same width,
    same 20–20k domain, zero padding), so everything stays column-aligned.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(AXIS_ROW_H)
        # Plex Mono 11 (design axis text); painter font, immune to app QSS.
        self._font = QFont(TYPE_FAMILY_NUMERIC)
        self._font.setPixelSize(11)

    def _x_for(self, freq_hz: float) -> float:
        return log_x_fraction(freq_hz) * self.width()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        width = self.width()
        # Top rule — the axis line (design: border-top 1px plot.grid).
        painter.fillRect(QRectF(0, 0, width, 1), QColor(COLOR_PLOT_GRID))  # token: color.plot.grid

        painter.setFont(self._font)
        painter.setPen(QColor(COLOR_PLOT_AXIS_TEXT))  # token: color.plot.axis-text
        metrics = QFontMetricsF(self._font)
        for freq, label in AXIS_TICKS:
            text_w = metrics.horizontalAdvance(label)
            x = self._x_for(freq) - text_w / 2
            x = max(AXIS_LABEL_MARGIN, min(x, width - text_w - AXIS_LABEL_MARGIN))
            painter.drawText(
                QRectF(x, 1, text_w, self.height() - 1),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )


class SpectrumPane(QFrame):
    """The framed spectrum well: label row / pyqtgraph bed / custom axis row.

    Single data entry point ``set_view(vm)`` — everything on screen derives
    from the ``SignalViewModel``, never from engine objects directly.
    ``set_working(active)`` toggles the C-17 sweep overlay.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # "spectrumPane" matches the theme QSS (QFrame#spectrumPane).
        self.setObjectName("spectrumPane")

        self._vm: SignalViewModel = EMPTY_SIGNAL_VIEW

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
        viewbox.setXRange(_LOG_MIN, _LOG_MAX, padding=0)
        viewbox.setYRange(Y_VIEW_BOTTOM_DB, Y_VIEW_TOP_DB, padding=0)
        layout.addWidget(self._plot, 1)

        self._axis = _SpectrumAxisRow(self)
        layout.addWidget(self._axis)

        # --- static plot items (created once — set_view only mutates them) ----
        # Grid: horizontal hairlines at 25% steps of the bed, interior only.
        self._grid_lines: list[pg.InfiniteLine] = []
        span = Y_VIEW_TOP_DB - Y_VIEW_BOTTOM_DB
        for frac in GRID_FRACS:
            line = pg.InfiniteLine(
                pos=Y_VIEW_BOTTOM_DB + frac * span,
                angle=0,
                movable=False,
                pen=qpen(PEN_GRID),  # token: color.plot.grid
            )
            line.setZValue(-30)
            self._plot.addItem(line)
            self._grid_lines.append(line)

        # The PSD curve: 2px cosmetic data pen, solid fill to the −90 dB floor.
        self._curve = pg.PlotDataItem(
            pen=qpen(PEN_DATA_A),  # token: color.plot.data-a
            fillLevel=SPECTRUM_FLOOR_DB,
            brush=qbrush(BRUSH_DATA_A_FILL),  # token: color.plot.data-a-fill
        )
        self._curve.setZValue(-10)
        self._plot.addItem(self._curve)

        # --- floating children (manual geometry, above the plot) --------------
        # The well's copy label — carries BOTH the silent-file copy (R-M2-8)
        # and the unmeasurable copy, one C-17 neutral treatment; the exact
        # no-tempo-label idiom from the tempogram.
        self._silent_label = QLabel(self)
        silent_font = QFont(TYPE_FAMILY_UI)
        silent_font.setPixelSize(13)
        self._silent_label.setFont(silent_font)
        self._silent_label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
            f"{type_pin(silent_font)}"
        )
        self._silent_label.hide()

        self._overlay = _WorkingOverlay(self)
        self._overlay.hide()

        self.set_view(EMPTY_SIGNAL_VIEW)

    # -- public API -------------------------------------------------------------

    def set_view(self, vm: SignalViewModel) -> None:
        """Render a view-model. Idempotent: no plot items or child widgets are
        created here, only mutated, so calling twice changes nothing."""
        self._vm = vm

        if vm.spectrum_freqs is not None and vm.spectrum_db is not None:
            # The view-model's arrays are display-normalized (max 0 dB, −90
            # floor) and masked ≥ 20 Hz — plotting at log10(f) puts them on
            # the locked log-x domain. Dense curves are min/max-decimated to
            # ≤ SPECTRUM_MAX_POINTS drawn points (R-M3-15) — the paint cost
            # fix; the view-model itself stays full-resolution.
            x = np.log10(np.asarray(vm.spectrum_freqs, dtype=np.float64))
            y = np.asarray(vm.spectrum_db, dtype=np.float64)
            x, y = decimate_curve(x, y)
            self._curve.setData(x, y)
            self._curve.setVisible(True)
        else:
            self._curve.setData([], [])
            self._curve.setVisible(False)

        # Silent and unmeasurable share one label; the view-model owns the
        # copy (silence wins by construction — the builder never sets both).
        # WORKING/ERROR blank both texts, so the label blanks with the rest.
        well_text = vm.silent_text or vm.unmeasurable_text or ""
        self._silent_label.setText(well_text)
        self._silent_label.adjustSize()
        self._silent_label.setVisible(bool(well_text))

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

    def freq_to_x(self, freq_hz: float) -> float:
        """Map a frequency to this pane's x pixel through the locked log-x
        domain.

        The viewbox fills the plot widget (axes hidden, zero margins, zero
        padding), so the log-fraction map over the plot's geometry is the
        same map every layer uses. Public because tests assert alignment
        through it.
        """
        rect = self._plot.geometry()
        return rect.x() + log_x_fraction(freq_hz) * rect.width()

    # -- internals ---------------------------------------------------------------

    def _build_label_row(self) -> QWidget:
        row = QWidget(self)
        row.setFixedHeight(LABEL_ROW_H)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(10)

        title = QLabel(PANE_TITLE, row)
        title_font = QFont(TYPE_FAMILY_UI)
        title_font.setPixelSize(11)
        title_font.setWeight(QFont.Weight.Medium)
        # Label style tracking 0.07em (design "Label" style).
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
            f"{type_pin(title_font)}"
        )
        self._title = title
        row_layout.addWidget(title)

        caption = QLabel(PANE_CAPTION, row)
        caption_font = QFont(TYPE_FAMILY_UI)
        caption_font.setPixelSize(11)
        caption.setFont(caption_font)
        caption.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
            f"{type_pin(caption_font)}"
        )
        self._caption = caption
        row_layout.addWidget(caption)
        row_layout.addStretch(1)
        return row

    def _overlay_rect(self):
        return self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)

    def _reposition_floats(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()  # geometry must be current before centering

        plot_rect = self._plot.geometry()
        self._silent_label.move(
            round(plot_rect.center().x() - self._silent_label.width() / 2),
            round(plot_rect.center().y() - self._silent_label.height() / 2),
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
