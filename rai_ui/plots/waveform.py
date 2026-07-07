"""Waveform pane: the Overview section's full-width context waveform well.

Anatomy mirrors the tempogram pane (C-16 idiom, approved Console 04:388-398):
a 34px label row ("WAVEFORM", no subtitle — the design draws the label alone),
the pyqtgraph bed, and a 28px custom-painted axis row whose only labels are
the endpoints — ``0:00`` on the left and the file length (mm:ss, from the
view-model) on the right, mono 11 axis text over a 1px top rule.

Rendering (R-M2-9): the min/max envelope arrives pre-decimated in the
``OverviewViewModel`` (2048 bins over a display-only channel mean — this
widget derives NOTHING). It is drawn exactly the way the approved mock's
``wave()`` generator draws it — **per-column vertical strokes**, one
``M x ymin L x ymax`` segment per bin (04:666-674) — as a single
``PlotDataItem`` with ``connect="pairs"`` under the 1.2px cosmetic
``PEN_WAVEFORM`` (#3E97AB — the deliberate context-dim hue, tokens v0.1.3).
A second polyline (the "spine") runs through the envelope midpoints with the
same pen: for dense audio it vanishes inside the columns, but it is what
makes sparse and silent renders honest — a passthrough envelope
(clip ≤ 2048 samples, mins == maxs) becomes a connected sample polyline
instead of disconnected dots, and a digitally silent file renders the mock's
exact ``'flat'`` path: a continuous #3E97AB line on the center — an honest
flat line, **no copy** (R-M2-8; the silent-file prose belongs to the
spectrum well only).

The center zero-line (#1B2129 hairline, ``PEN_ZERO_LINE``) paints *above*
the envelope — the mock draws it second (04:391-392) so the axis stays
legible over dense columns — and is always visible, file or no file.

The frame is amplitude-honest: y is locked to ±1.05 full scale (same 1.05
headroom doctrine as the tempogram's salience axis) so a quiet file renders
small and silence renders flat — the instrument never autoscales noise into
a waveform. x is locked 0..1 (fraction of file); bin i of n sits at
``i/(n-1)`` so the first and last columns touch the well edges, matching the
mock's ``i*5`` over a 1000-unit viewBox. All mouse interaction is disabled
and there is no legend, ever.

The C-17 working overlay is the tempogram's own ``_WorkingOverlay`` —
imported, not copied, so the sweep/typography/visibility rules have exactly
one truth.

This module imports pyqtgraph at the top (widget layer, same as
``tempogram.py``); the pure decimation math lives in
``rai_ui.plots.decimate`` per the package doctrine.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rai_ui.plots.tempogram import _WorkingOverlay
from rai_ui.state.signal_view import EMPTY_OVERVIEW_VIEW, OverviewViewModel
from rai_ui.theme._tokens_gen import (
    COLOR_PLOT_AXIS_TEXT,
    COLOR_PLOT_GRID,
    COLOR_SURFACE_INSET,
    COLOR_TEXT_MUTED,
    TYPE_FAMILY_NUMERIC,
    TYPE_FAMILY_UI,
)
from rai_ui.theme.pens import PEN_WAVEFORM, PEN_ZERO_LINE, qpen
from rai_ui.widgets.verdict_block import type_pin

# --- frame geometry (approved Console, 04:388-398) ----------------------------
LABEL_ROW_H = 34  # pane label strip (mock: SVG bed starts at top:34)
AXIS_ROW_H = 28  # endpoint axis strip (mock: bottom:28, border-top 1px)
AXIS_PAD_X = 16  # mock axis row: padding:0 16px
_FRAME_INSET = 1  # keep the pane's QSS hairline border visible under children

# The locked window: x is the file as a 0..1 fraction, y is full-scale
# amplitude with the tempogram's 1.05 headroom so a 0 dBFS peak does not
# kiss the label/axis rows.
X_MIN, X_MAX = 0.0, 1.0
AMP_LIMIT = 1.05

# The left axis endpoint is fixed copy (04:395); the right endpoint is the
# view-model's mm:ss length.
AXIS_START_TEXT = "0:00"

WAVEFORM_TITLE = "WAVEFORM"


def envelope_xy(
    mins: np.ndarray, maxs: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map an envelope to plot arrays: ``(x, xs_pairs, ys_pairs)``.

    ``x`` is one 0..1 position per bin (bin i of n at ``i/(n-1)``, endpoints
    on the well edges like the mock's columns; a single bin sits at 0).
    ``xs_pairs``/``ys_pairs`` are the ``connect="pairs"`` arrays — each bin
    contributes one vertical ``(x, min) → (x, max)`` stroke. Pure numpy,
    exposed for tests.
    """
    mins = np.asarray(mins, dtype=np.float64)
    maxs = np.asarray(maxs, dtype=np.float64)
    n = mins.size
    if n > 1:
        x = np.linspace(X_MIN, X_MAX, n)
    else:
        x = np.zeros(n, dtype=np.float64)
    xs = np.repeat(x, 2)
    ys = np.empty(2 * n, dtype=np.float64)
    ys[0::2] = mins
    ys[1::2] = maxs
    return x, xs, ys


class _WaveAxisRow(QWidget):
    """The 28px endpoint axis strip: 1px top rule, ``0:00`` left, length right.

    Custom painted like the tempogram's axis row — painter fonts are immune
    to the app QSS, and an axis of exactly two endpoint labels is not an
    AxisItem job. Padding matches the mock's ``0 16px``.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(AXIS_ROW_H)
        self._length_text = EMPTY_OVERVIEW_VIEW.wave_len_text
        # Plex Mono 11 (design axis text); painter font, immune to app QSS.
        self._font = QFont(TYPE_FAMILY_NUMERIC)
        self._font.setPixelSize(11)

    def set_length_text(self, text: str) -> None:
        self._length_text = text
        self.update()

    def length_text(self) -> str:
        return self._length_text

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        width = self.width()
        # Top rule — the axis line (design: border-top 1px plot.grid).
        painter.fillRect(QRectF(0, 0, width, 1), QColor(COLOR_PLOT_GRID))  # token: color.plot.grid

        painter.setFont(self._font)
        painter.setPen(QColor(COLOR_PLOT_AXIS_TEXT))  # token: color.plot.axis-text
        text_rect = QRectF(AXIS_PAD_X, 1, width - 2 * AXIS_PAD_X, self.height() - 1)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            AXIS_START_TEXT,
        )
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self._length_text,
        )


class WaveformPane(QFrame):
    """The framed waveform well: label row / pyqtgraph bed / endpoint axis row.

    Single data entry point ``set_view(vm)`` — everything on screen derives
    from the ``OverviewViewModel``, never from engine objects directly.
    ``set_working(active)`` toggles the shared C-17 sweep overlay. Idempotent:
    plot items and children are created once in ``__init__`` and only mutated.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # "waveformPane" matches the theme QSS (QFrame#waveformPane).
        self.setObjectName("waveformPane")
        # No minimum height: the design gives this well flex:1 with
        # min-height:0 (04:388) — the Overview section owns sizing.

        self._vm: OverviewViewModel = EMPTY_OVERVIEW_VIEW

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
        viewbox.setXRange(X_MIN, X_MAX, padding=0)
        viewbox.setYRange(-AMP_LIMIT, AMP_LIMIT, padding=0)
        layout.addWidget(self._plot, 1)

        self._axis = _WaveAxisRow(self)
        layout.addWidget(self._axis)

        # --- static plot items (created once — set_view only mutates them) ----
        # Envelope columns: one vertical min→max stroke per bin, exactly the
        # mock's wave() path geometry (04:666-674), 1.2px cosmetic pen.
        self._envelope = pg.PlotDataItem(
            pen=qpen(PEN_WAVEFORM),  # token: color.plot.waveform (v0.1.3)
            connect="pairs",
        )
        self._envelope.setZValue(-10)
        self._plot.addItem(self._envelope)

        # Envelope spine: a connected polyline through the bin midpoints with
        # the same pen. Inside dense columns it is invisible; on a silent file
        # it IS the mock's 'flat' render (a continuous line on the center),
        # and on a passthrough envelope it connects the raw samples.
        self._spine = pg.PlotDataItem(pen=qpen(PEN_WAVEFORM))  # token: color.plot.waveform
        self._spine.setZValue(-10)
        self._plot.addItem(self._spine)

        # Center zero-line, painted ABOVE the envelope — the mock draws it
        # second (04:392) so the center stays legible over dense columns.
        self._zero_line = pg.InfiniteLine(
            pos=0.0, angle=0, movable=False, pen=qpen(PEN_ZERO_LINE)
        )  # token: color.plot.grid · line.hairline
        self._zero_line.setZValue(-5)
        self._plot.addItem(self._zero_line)

        # --- shared C-17 working overlay (one truth, owned by tempogram.py) ---
        self._overlay = _WorkingOverlay(self)
        self._overlay.hide()

        self.set_view(EMPTY_OVERVIEW_VIEW)

    # -- public API -------------------------------------------------------------

    def set_view(self, vm: OverviewViewModel) -> None:
        """Render a view-model. Idempotent: no plot items or child widgets are
        created here, only mutated, so calling twice changes nothing."""
        self._vm = vm

        mins, maxs = vm.wave_mins, vm.wave_maxs
        if mins is None or maxs is None:
            self._envelope.setData([], [], connect="pairs")
            self._spine.setData([], [])
            self._envelope.setVisible(False)
            self._spine.setVisible(False)
        else:
            x, xs, ys = envelope_xy(mins, maxs)
            self._envelope.setData(xs, ys, connect="pairs")
            self._spine.setData(x, (ys[0::2] + ys[1::2]) / 2.0)
            self._envelope.setVisible(True)
            self._spine.setVisible(True)

        self._axis.set_length_text(vm.wave_len_text)

    def set_working(self, active: bool) -> None:
        """Toggle the C-17 sweep overlay (animation follows visibility)."""
        if active:
            self._overlay.setGeometry(self._overlay_rect())
            self._overlay.raise_()
        self._overlay.setVisible(active)

    def sweep_running(self) -> bool:
        """True while the working sweep animation is actually ticking."""
        return self._overlay.sweep_running()

    # -- internals ---------------------------------------------------------------

    def _build_label_row(self) -> QWidget:
        row = QWidget(self)
        row.setFixedHeight(LABEL_ROW_H)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(10)

        # Pane label, design "Label" style: 11px/500, 0.07em tracking,
        # uppercase, muted. setFont + type_pin pair (M1 landmine 8).
        self._title = QLabel(WAVEFORM_TITLE, row)
        title_font = QFont(TYPE_FAMILY_UI)
        title_font.setPixelSize(11)
        title_font.setWeight(QFont.Weight.Medium)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)
        self._title.setFont(title_font)
        self._title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;"  # token: color.text.muted
            + type_pin(title_font)
        )
        row_layout.addWidget(self._title)
        row_layout.addStretch(1)
        return row

    def _overlay_rect(self):
        return self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self._overlay_rect())
            self._overlay.raise_()
