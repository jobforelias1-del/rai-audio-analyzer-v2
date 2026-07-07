"""Compare spectrum overlay (M4, R-M4-6): A and B on one log-x well.

The pane-well anatomy is the C-16 idiom the tempogram/spectrum panes proved:
a 34px label row, the pyqtgraph bed with both native axes hidden, and a 28px
custom-painted axis row. Geometry, the locked log-x domain, the normalized-dB
y-domain and the ≤2048-point min/max decimation (R-M3-15) are IMPORTED from
:mod:`rai_ui.plots.spectrum` — one truth, no re-derivation.

Where this pane deliberately differs from the single-file SpectrumPane
(design 04:479–499, binding):

* **Two curves, no fills** — A ``data-a`` cyan, B ``data-b`` rose, both 2px
  cosmetic strokes with NO area fill (the Signal pane's A-fill would bury the
  overlay). **B draws on top of A** (04 emits A first, B second).
* **The ONE sanctioned plot legend** — the label row carries ``SPECTRUM
  OVERLAY`` plus inline 10×2px line swatches with mono-11 hue-locked ``A`` /
  ``B`` letters (the approved screen keeps a legend here, unlike the
  tempogram where the table is the legend).
* **Three axis labels** — ``20 Hz`` / ``1 k`` / ``20 kHz`` at their TRUE log
  positions (R-M4-6; the mock's space-between spacing was the same shortcut
  the Signal pane's five labels corrected).
* **No gridlines** — the approved Compare well draws none (04:479–499).
* **Joint normalization happens upstream** — the view-model
  (:mod:`rai_ui.state.compare_view`) normalizes both curves to ONE shared dB
  reference; this pane renders the arrays verbatim (decimation is the only
  display transform), so the on-screen level difference stays honest.
* **B-empty pill** (04:489–493 verbatim): ``reference (B) not loaded — A
  shown alone`` centered over the bed while the slot is empty.

The working overlay is the shared :class:`WorkingOverlay`
(rai_ui.plots.overlay — the landmine-16 promotion; this pane is the fourth
importer that triggered it). All plot items are created once in ``__init__``
and only mutated in ``set_view`` (idempotency doctrine).

**No mouse, no menu** (C-16) — the legend here is designed, not a pyqtgraph
LegendItem.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rai_ui.plots.overlay import WorkingOverlay
from rai_ui.plots.spectrum import (
    AXIS_ROW_H,
    LABEL_ROW_H,
    Y_VIEW_BOTTOM_DB,
    Y_VIEW_TOP_DB,
    _LOG_MAX,
    _LOG_MIN,
    decimate_curve,
    log_x_fraction,
)
from rai_ui.state.compare_view import EMPTY_COMPARE_VIEW, CompareViewModel
from rai_ui.theme._tokens_gen import (
    COLOR_BORDER_HAIRLINE,
    COLOR_BORDER_STRONG,
    COLOR_PLOT_AXIS_TEXT,
    COLOR_PLOT_DATA_A,
    COLOR_PLOT_DATA_B,
    COLOR_PLOT_GRID,
    COLOR_SURFACE_INSET,
    COLOR_SURFACE_PANEL,
    COLOR_TEXT_MUTED,
    PEN_DATA_A,
    PEN_DATA_B,
    TYPE_FAMILY_NUMERIC,
    TYPE_FAMILY_UI,
)
from rai_ui.theme.pens import qpen
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.verdict_block import type_pin

_FRAME_INSET = 1  # keep the pane's hairline border visible under children

# --- label row copy (04:481, verbatim — rendered uppercase like the design) ----
PANE_TITLE = "Spectrum overlay"

# The three axis labels (04:494–498 verbatim) at TRUE log positions (R-M4-6).
AXIS_TICKS: tuple[tuple[float, str], ...] = (
    (20.0, "20 Hz"),
    (1000.0, "1 k"),
    (20000.0, "20 kHz"),
)
AXIS_LABEL_MARGIN = 2

# Legend swatch geometry (04:482–483): 10×2px line swatch, 5px gap to letter.
_SWATCH_W = 10
_SWATCH_H = 2

# B-empty pill geometry (04:489–493): h24, padding 0 12px, radius = h/2.
_PILL_HEIGHT = 24
_PILL_PAD_X = 12


class _CompareAxisRow(QWidget):
    """28px axis strip: top hairline + the three labels at true log positions,
    edge labels clamped inward (the _SpectrumAxisRow recipe, 3 ticks)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(AXIS_ROW_H)
        self._font = QFont(TYPE_FAMILY_NUMERIC)  # Plex Mono 11 (design axis text)
        self._font.setPixelSize(11)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        width = self.width()
        painter.fillRect(QRectF(0, 0, width, 1), QColor(COLOR_PLOT_GRID))  # token: color.plot.grid

        painter.setFont(self._font)
        painter.setPen(QColor(COLOR_PLOT_AXIS_TEXT))  # token: color.plot.axis-text
        metrics = QFontMetricsF(self._font)
        for freq, label in AXIS_TICKS:
            text_w = metrics.horizontalAdvance(label)
            x = log_x_fraction(freq) * width - text_w / 2
            x = max(AXIS_LABEL_MARGIN, min(x, width - text_w - AXIS_LABEL_MARGIN))
            painter.drawText(
                QRectF(x, 1, text_w, self.height() - 1),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )


def _legend_entry(parent: QWidget, letter: str, hex_color: str) -> tuple[QWidget, QLabel]:
    """One inline legend entry: 10×2 line swatch + hue-locked mono-11 letter."""
    entry = QWidget(parent)
    layout = QHBoxLayout(entry)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)  # swatch-to-letter gap (04:482)
    swatch = QFrame(entry)
    swatch.setFixedSize(_SWATCH_W, _SWATCH_H)
    swatch.setStyleSheet(f"background: {hex_color}; border: none;")
    layout.addWidget(swatch, 0, Qt.AlignmentFlag.AlignVCenter)
    label = QLabel(letter, entry)
    font = mono_font(11)
    label.setFont(font)
    label.setStyleSheet(f"color: {hex_color}; background: transparent;{type_pin(font)}")
    layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
    return entry, label


class CompareOverlayPane(QFrame):
    """The framed overlay well: label row + legend / two-curve bed / axis row.

    Single data entry point ``set_view(vm: CompareViewModel)`` — arrays arrive
    jointly normalized from the view-model and render verbatim.
    ``set_working(active)`` toggles the shared C-17 sweep overlay.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compareOverlayPane")
        # The well chrome (04:479): inset surface, hairline border, radius 12.
        # Self-skinned — the theme QSS has no rule for this id.
        self.setStyleSheet(
            "QFrame#compareOverlayPane {"
            f" background: {COLOR_SURFACE_INSET};"  # token: color.surface.inset
            f" border: 1px solid {COLOR_BORDER_HAIRLINE};"  # token: color.border.hairline
            " border-radius: 12px; }"
        )

        self._vm: CompareViewModel = EMPTY_COMPARE_VIEW

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FRAME_INSET, _FRAME_INSET, _FRAME_INSET, _FRAME_INSET)
        layout.setSpacing(0)

        layout.addWidget(self._build_label_row())

        # --- plot bed (the SpectrumPane recipe: locked log-x, no interaction) ---
        self._plot = pg.PlotWidget(background=COLOR_SURFACE_INSET)  # token: color.surface.inset
        plot_item = self._plot.getPlotItem()
        plot_item.hideAxis("left")
        plot_item.hideAxis("bottom")
        plot_item.hideButtons()
        plot_item.setMenuEnabled(False)
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

        self._axis = _CompareAxisRow(self)
        layout.addWidget(self._axis)

        # --- the two curves (created once; set_view only mutates) --------------
        # No fills — and B's higher z draws it ON TOP of A (04:486–487).
        self.curve_a = pg.PlotDataItem(pen=qpen(PEN_DATA_A))  # token: color.plot.data-a
        self.curve_a.setZValue(-10)
        self._plot.addItem(self.curve_a)
        self.curve_b = pg.PlotDataItem(pen=qpen(PEN_DATA_B))  # token: color.plot.data-b
        self.curve_b.setZValue(-5)
        self._plot.addItem(self.curve_b)

        # --- floating children --------------------------------------------------
        # B-empty pill (04:489–493 verbatim copy arrives on the view-model).
        self.pill_label = QLabel(self)
        pill_font = ui_font(12)
        self.pill_label.setFont(pill_font)
        self.pill_label.setFixedHeight(_PILL_HEIGHT)
        self.pill_label.setStyleSheet(
            f"border: 1px solid {COLOR_BORDER_STRONG};"  # token: color.border.strong
            f" border-radius: {_PILL_HEIGHT // 2}px;"
            f" padding: 0 {_PILL_PAD_X}px;"
            f" background: {COLOR_SURFACE_PANEL};"  # token: color.surface.panel
            f" color: {COLOR_TEXT_MUTED};{type_pin(pill_font)}"  # token: color.text.muted
        )
        self.pill_label.hide()

        self._overlay = WorkingOverlay(self)
        self._overlay.hide()

        self.set_view(EMPTY_COMPARE_VIEW)

    # -- public API -------------------------------------------------------------

    def set_view(self, vm: CompareViewModel) -> None:
        """Render a view-model. Idempotent — items are mutated, never created."""
        self._vm = vm

        for curve, freqs, db in (
            (self.curve_a, vm.a_freqs, vm.a_db),
            (self.curve_b, vm.b_freqs, vm.b_db),
        ):
            if freqs is not None and db is not None and len(freqs):
                x = np.log10(np.asarray(freqs, dtype=np.float64))
                y = np.asarray(db, dtype=np.float64)
                x, y = decimate_curve(x, y)  # ≤2048 drawn points (R-M3-15)
                curve.setData(x, y)
                curve.setVisible(True)
            else:
                curve.setData([], [])
                curve.setVisible(False)

        self.pill_label.setText(vm.b_empty_pill_text or "")
        self.pill_label.adjustSize()
        self.pill_label.setVisible(bool(vm.b_empty_pill_text))

        self._reposition_floats()

    def set_working(self, active: bool) -> None:
        """Toggle the shared C-17 sweep (A-side WORKING; B in-flight is
        chip-only per R-M4-3, so B never drives this)."""
        if active:
            self._overlay.setGeometry(self._overlay_rect())
            self._overlay.raise_()
        self._overlay.setVisible(active)

    def sweep_running(self) -> bool:
        return self._overlay.sweep_running()

    def view(self) -> CompareViewModel:
        """The last-rendered view-model (test/introspection hook)."""
        return self._vm

    # -- internals ---------------------------------------------------------------

    def _build_label_row(self) -> QWidget:
        row = QWidget(self)
        row.setFixedHeight(LABEL_ROW_H)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(16, 0, 16, 0)
        row_layout.setSpacing(10)  # label/legend gap (04:480)

        title = QLabel(PANE_TITLE.upper(), row)
        title_font = ui_font(11, QFont.Weight.Medium)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)  # 0.07em
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;{type_pin(title_font)}"  # token: color.text.muted
        )
        self._title = title
        row_layout.addWidget(title)

        # The one sanctioned plot legend: hue-locked A/B letter swatches.
        entry_a, self.legend_a_label = _legend_entry(row, "A", COLOR_PLOT_DATA_A)  # token: color.plot.data-a
        row_layout.addWidget(entry_a)
        entry_b, self.legend_b_label = _legend_entry(row, "B", COLOR_PLOT_DATA_B)  # token: color.plot.data-b
        row_layout.addWidget(entry_b)

        row_layout.addStretch(1)
        return row

    def _overlay_rect(self):
        return self.rect().adjusted(_FRAME_INSET, _FRAME_INSET, -_FRAME_INSET, -_FRAME_INSET)

    def _reposition_floats(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.activate()

        plot_rect = self._plot.geometry()
        self.pill_label.move(
            round(plot_rect.center().x() - self.pill_label.width() / 2),
            round(plot_rect.center().y() - self.pill_label.height() / 2),
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
