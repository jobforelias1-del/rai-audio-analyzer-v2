"""Overview/Signal metric cards (Console 04:352–441): Gauge / Rows / Tempo.

Three card shells over the shared card chrome (``QFrame#metricCard`` — panel
surface, hairline border, radius 12 from the theme QSS; padding 16px 18px
pinned here because QSS owns surfaces only, Landmine 6):

* ``GaugeCard`` — a Signal metric card (04:423–441): 11px uppercase label,
  30px/500 mono value, optional 8px gauge (track ``surface.active``, fill
  ``plot.data-a``, radius 4), 11px muted caption, optional C-06 absence chip.
  The Dynamic-range variant has NO gauge (``gauge_frac is None``) and an
  inline 14px muted ``dB`` unit instead.
* ``RowsCard`` — an Overview rows card (Loudness / Dynamics / File,
  04:367–386): label over label/value rows (12px secondary name, 16px/600
  mono value, 10px/500 muted unit) plus the optional chip. The File card's
  compact 12px/500 values are a constructor variant.
* ``TempoCard`` — Overview's wide card (04:356–366): 34px/600 mono primary
  over the amber 62×3 tick, 19px/500 felt beside the violet dashed 32px tick
  and its lowercase ``felt`` caption, then the short tinted verdict word.

Doctrine enforced here:

* Widgets render view-models verbatim and derive NOTHING — every string
  arrives prebuilt on ``GaugeCardView`` / ``RowsCardView`` / ``TempoCardView``
  (rai_ui.state.signal_view, the one truth).
* Numerals are IBM Plex Mono, ``text.primary``, and are NEVER tinted by
  state: value-label colors are set once at construction and no ``set_view``
  path touches them (CL:158). The verdict word is the ONLY tinted text on the
  Tempo card (R-M2-20).
* The ◆ before the ambiguous verdict word is a DRAWN icon, never a font
  glyph (P3 rule / R-M2-20) — keyed off
  ``verdict_word == AMBIGUOUS_VERDICT_WORD``, the constant the view-model
  exports for exactly this purpose. ✓ is in the vendored Plex cmap and rides
  inside the word text.
* A C-06 chip renders ONLY when the view-model attached one (R-M2-10 — value
  is ``—`` AND a reason exists); the widget never invents or suppresses one.
* Every designed label is ``setFont`` + ``type_pin``-pinned (Landmine 8: the
  app-wide QSS font rule silently overrides bare ``setFont``; offscreen
  widget tests can't catch it — tests/ui/test_metric_cards.py applies the
  real stylesheet).

Blessed literals (approved-screen values with no token, per the R-M1-2
precedent): the ticks' 62/32px widths, every card-internal gap (6/9/10), the
gauge geometry (h8/r4), and the chip's 10px type — the design's 10.5px is
unrepresentable in integer QFont pixel sizes; floored to 10 so the chip stays
subordinate to the 11px captions (queued for design reconciliation alongside
the v0.1.3 punch list).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from rai_ui.state.formatters import EM_DASH
from rai_ui.state.signal_view import (
    AMBIGUOUS_VERDICT_WORD,
    ChipNote,
    GaugeCardView,
    RowsCardView,
    TempoCardView,
)
from rai_ui.theme._tokens_gen import (
    COLOR_BORDER_STRONG,
    COLOR_PLOT_DATA_A,
    COLOR_SURFACE_ACTIVE,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.metric_readout import TickBar, group_label
from rai_ui.widgets.verdict_block import diamond_pixmap, type_pin

# Card padding 16px 18px (04:356/04:423) — contents margins are (l, t, r, b).
_CARD_MARGINS = (18, 16, 18, 16)

# Chip geometry (C-06 pill, 04:372): h20 · padding 0 9px · radius = h/2.
_CHIP_HEIGHT = 20
_CHIP_PAD_X = 9
_CHIP_FONT_PX = 10  # design 10.5px — floored, see module docstring

# Gauge geometry (04:426): height 8, radius 4.
_GAUGE_HEIGHT = 8
_GAUGE_RADIUS = 4.0

# The empty states every card boots from (no view-model rendered yet): pure
# absence, no chips, no gauge fill — indistinguishable from the WORKING dash.
_EMPTY_GAUGE = GaugeCardView(
    label="", value_text=EM_DASH, gauge_frac=None, caption="", chip=None
)
_EMPTY_ROWS = RowsCardView(label="", rows=(), chip=None)
_EMPTY_TEMPO = TempoCardView(
    primary_text=EM_DASH,
    felt_text=EM_DASH,
    verdict_word=EM_DASH,
    verdict_tint=COLOR_TEXT_MUTED,
)


def _card_frame(widget: QFrame) -> None:
    """Apply the shared card chrome hooks: the theme QSS skins
    ``QFrame#metricCard`` (surface/border/radius); padding is layout-level."""
    widget.setObjectName("metricCard")


def _caption_label(parent: QWidget) -> QLabel:
    """An 11px muted caption line (04:428 idiom), type-pinned."""
    label = QLabel(parent)
    font = ui_font(11)
    label.setFont(font)
    # token: color.text.muted
    label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};{type_pin(font)}")
    return label


class AbsenceChip(QLabel):
    """The C-06 absence chip (04:372): a reason pill riding with a ``—``.

    Presentation only — whether a chip exists is the view-model's call
    (R-M2-10); this label just shows/hides on ``set_note``. Pill: h20,
    padding 0 9px, hairline ``border.strong`` outline, ``text.secondary``
    copy at 10px (design 10.5 — see module docstring).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_CHIP_HEIGHT)
        font = ui_font(_CHIP_FONT_PX)
        self.setFont(font)
        self.setStyleSheet(
            # token: color.border.strong / color.text.secondary — radius is
            # h/2 ("radius: 999" is symbolic, same cap as the QSS generator).
            f"border: 1px solid {COLOR_BORDER_STRONG};"
            f" border-radius: {_CHIP_HEIGHT // 2}px;"
            f" padding: 0 {_CHIP_PAD_X}px;"
            f" color: {COLOR_TEXT_SECONDARY};{type_pin(font)}"
        )
        self.hide()

    def set_note(self, note: ChipNote | None) -> None:
        """Show the chip with ``note.text``, or hide it entirely on None."""
        if note is None:
            self.hide()
            self.setText("")
        else:
            self.setText(note.text)
            self.show()


class GaugeBar(QWidget):
    """The 8px metric gauge (04:426): track ``surface.active``, fill
    ``plot.data-a``, radius 4. Purely paint — no layout children."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_GAUGE_HEIGHT)
        self._fraction = 0.0

    def fraction(self) -> float:
        """The rendered fill fraction (post-clamp)."""
        return self._fraction

    def set_fraction(self, fraction: float) -> None:
        """Set the 0..1 fill. Defensive clamp — the view-model already clamps
        (R-M2-4 measurements are shares), but a paint routine must never
        trust its input into drawing outside the track."""
        value = float(fraction)
        if not math.isfinite(value):
            value = 0.0
        self._fraction = min(1.0, max(0.0, value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # token: color.surface.active — the track (same precedented trick as
        # the M1 salience bars).
        painter.setBrush(QColor(COLOR_SURFACE_ACTIVE))
        painter.drawRoundedRect(QRectF(self.rect()), _GAUGE_RADIUS, _GAUGE_RADIUS)
        if self._fraction > 0.0:
            # token: color.plot.data-a — the fill (04:426).
            painter.setBrush(QColor(COLOR_PLOT_DATA_A))
            painter.drawRoundedRect(
                QRectF(0.0, 0.0, self._fraction * self.width(), float(self.height())),
                _GAUGE_RADIUS,
                _GAUGE_RADIUS,
            )
        painter.end()


class GaugeCard(QFrame):
    """A Signal metric card (04:423–441). Feed it ``GaugeCardView``s.

    ``unit`` is the card's fixed inline unit copy — the Dynamic-range card's
    14px muted ``dB`` (04:438). The design template renders it
    unconditionally (``— dB`` on absence included), so it is construction
    state, not view state; Width/Sub carry their ``%`` inside ``value_text``.
    """

    def __init__(self, unit: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _card_frame(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_CARD_MARGINS)
        layout.setSpacing(10)  # card-internal gap 10 (04:424)

        self.title_label = group_label("", self)
        layout.addWidget(self.title_label)

        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        self.value_label = QLabel(self)
        value_font = mono_font(30, QFont.Weight.Medium)  # metric-m 30/500 (C-07)
        self.value_label.setFont(value_font)
        self.value_label.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(value_font)}"
        )
        value_row.addWidget(self.value_label)
        self.unit_label: QLabel | None = None
        if unit is not None:
            self.unit_label = QLabel(unit, self)
            unit_font = mono_font(14)  # inline unit 14px (04:438)
            self.unit_label.setFont(unit_font)
            self.unit_label.setStyleSheet(  # token: color.text.muted
                f"color: {COLOR_TEXT_MUTED};{type_pin(unit_font)}"
            )
            value_row.addWidget(self.unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch(1)
        layout.addLayout(value_row)

        self.gauge = GaugeBar(self)
        self.gauge.hide()
        layout.addWidget(self.gauge)

        self.caption_label = _caption_label(self)
        layout.addWidget(self.caption_label)

        self.chip_label = AbsenceChip(self)
        layout.addWidget(self.chip_label, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addStretch(1)

        self._view: GaugeCardView = _EMPTY_GAUGE
        self.set_view(self._view)

    # -- API ------------------------------------------------------------------

    def set_view(self, v: GaugeCardView) -> None:
        """Render ``v`` verbatim. Idempotent; never touches a numeral color."""
        self._view = v
        self.title_label.setText(v.label.upper())
        self.value_label.setText(v.value_text)
        if v.gauge_frac is None:
            self.gauge.hide()  # the DR card has no gauge bar (04:436–440)
        else:
            self.gauge.set_fraction(v.gauge_frac)
            self.gauge.show()
        self.caption_label.setText(v.caption)
        self.chip_label.set_note(v.chip)

    def view(self) -> GaugeCardView:
        """The last-rendered view (test/introspection hook)."""
        return self._view


class RowsCard(QFrame):
    """An Overview rows card — Loudness / Dynamics / File (04:367–386).

    ``value_px`` / ``value_weight`` parameterize the value type: the default
    16px/600 is the standard metric row (04:369); the File card's compact
    variant is 12px/500 (04:382) — construction state, because a card never
    changes shape, only numbers.
    """

    def __init__(
        self,
        value_px: int = 16,
        value_weight: QFont.Weight = QFont.Weight.DemiBold,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        _card_frame(self)
        self._value_font = mono_font(value_px, value_weight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_CARD_MARGINS)
        layout.setSpacing(9)  # card-internal gap 9 (04:368)
        self._layout = layout

        self.title_label = group_label("", self)
        layout.addWidget(self.title_label)

        # Rows are (re)built by set_view; the chip stays the last item.
        self._row_widgets: list[QWidget] = []
        self.row_name_labels: list[QLabel] = []
        self.row_value_labels: list[QLabel] = []
        self.row_unit_labels: list[QLabel | None] = []
        self._skeleton: tuple[tuple[str, str | None], ...] = ()

        self.chip_label = AbsenceChip(self)
        layout.addWidget(self.chip_label, 0, Qt.AlignmentFlag.AlignLeft)

        layout.addStretch(1)

        self._view: RowsCardView = _EMPTY_ROWS
        self.set_view(self._view)

    # -- rows -------------------------------------------------------------------

    def _build_row(
        self, name: str, unit: str | None
    ) -> tuple[QWidget, QLabel, QLabel, QLabel | None]:
        """One card row (04:369): 12px secondary name left, mono value
        (+10px/500 muted unit) right, baseline-ish via bottom alignment —
        the same anatomy as the rail's ``metric_row``, re-sized per card."""
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        name_label = QLabel(name, row)
        name_font = ui_font(12)
        name_label.setFont(name_font)
        name_label.setStyleSheet(  # token: color.text.secondary
            f"color: {COLOR_TEXT_SECONDARY};{type_pin(name_font)}"
        )
        row_layout.addWidget(name_label)
        row_layout.addStretch(1)
        value_label = QLabel(row)
        value_label.setFont(self._value_font)
        value_label.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(self._value_font)}"
        )
        row_layout.addWidget(value_label, 0, Qt.AlignmentFlag.AlignBottom)
        unit_label: QLabel | None = None
        if unit is not None:
            unit_label = QLabel(unit, row)
            unit_font = mono_font(10, QFont.Weight.Medium)  # unit 10/500 (04:369)
            unit_label.setFont(unit_font)
            unit_label.setStyleSheet(  # token: color.text.muted
                f"color: {COLOR_TEXT_MUTED};{type_pin(unit_font)}"
            )
            row_layout.addWidget(unit_label, 0, Qt.AlignmentFlag.AlignBottom)
        return row, name_label, value_label, unit_label

    def _rebuild_rows(self, view: RowsCardView) -> None:
        for widget in self._row_widgets:
            self._layout.removeWidget(widget)
            widget.deleteLater()
        self._row_widgets = []
        self.row_name_labels = []
        self.row_value_labels = []
        self.row_unit_labels = []
        # Insert after the title (index 0), before the chip + stretch.
        for i, row_view in enumerate(view.rows):
            row, name_label, value_label, unit_label = self._build_row(
                row_view.label, row_view.unit
            )
            self._layout.insertWidget(1 + i, row)
            self._row_widgets.append(row)
            self.row_name_labels.append(name_label)
            self.row_value_labels.append(value_label)
            self.row_unit_labels.append(unit_label)
        self._skeleton = tuple((r.label, r.unit) for r in view.rows)

    # -- API ------------------------------------------------------------------

    def set_view(self, v: RowsCardView) -> None:
        """Render ``v`` verbatim. Rows are rebuilt only when the (label, unit)
        skeleton changes — the steady-state update just swaps value strings."""
        self._view = v
        self.title_label.setText(v.label.upper())
        skeleton = tuple((r.label, r.unit) for r in v.rows)
        if skeleton != self._skeleton:
            self._rebuild_rows(v)
        for row_view, value_label in zip(v.rows, self.row_value_labels):
            value_label.setText(row_view.value_text)
        self.chip_label.set_note(v.chip)

    def view(self) -> RowsCardView:
        """The last-rendered view (test/introspection hook)."""
        return self._view


class TempoCard(QFrame):
    """Overview's wide Tempo card (04:356–366). Feed it ``TempoCardView``s.

    34px/600 mono primary over the amber 62×3 tick; 19px/500 felt beside the
    violet dashed 32px tick and the lowercase ``felt`` caption; then the
    short verdict word — the ONLY tinted text on the card (R-M2-20). The full
    verdict block with reasons stays rail-only.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _card_frame(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*_CARD_MARGINS)
        layout.setSpacing(6)  # card-internal gap 6 (04:356)

        self.title_label = group_label("Tempo", self)
        layout.addWidget(self.title_label)

        self.primary_value = QLabel(self)
        primary_font = mono_font(34, QFont.Weight.DemiBold)  # primary 34/600 (04:358)
        self.primary_value.setFont(primary_font)
        self.primary_value.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(primary_font)}"
        )
        layout.addWidget(self.primary_value)

        layout.addWidget(TickBar("primary", 62, self))  # amber 62×3 r2 (04:359)

        felt_row = QWidget(self)
        felt_layout = QHBoxLayout(felt_row)
        felt_layout.setContentsMargins(0, 4, 0, 0)  # felt row margin-top 4 (04:360)
        felt_layout.setSpacing(10)  # felt row gap 10
        self.felt_value = QLabel(felt_row)
        felt_font = mono_font(19, QFont.Weight.Medium)  # felt 19/500 (04:361)
        self.felt_value.setFont(felt_font)
        self.felt_value.setStyleSheet(  # token: color.text.primary
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(felt_font)}"
        )
        felt_layout.addWidget(self.felt_value)
        # Baseline alignment approximated bottom-up (design align-items:
        # baseline): the caption's descent tracks the numeral's; the 3px tick
        # rides the same bottom edge.
        felt_layout.addWidget(
            TickBar("felt", 32, felt_row), 0, Qt.AlignmentFlag.AlignBottom
        )  # violet dashed 32px (04:362)
        self.felt_caption = _caption_label(felt_row)
        self.felt_caption.setText("felt")  # lowercase — NOT a group label (04:363)
        felt_layout.addWidget(self.felt_caption, 0, Qt.AlignmentFlag.AlignBottom)
        felt_layout.addStretch(1)
        layout.addWidget(felt_row)

        verdict_row = QWidget(self)
        verdict_layout = QHBoxLayout(verdict_row)
        verdict_layout.setContentsMargins(0, 2, 0, 0)  # verdict margin-top 2 (04:365)
        verdict_layout.setSpacing(6)
        self.diamond_label = QLabel(verdict_row)  # the drawn ◆, ambiguous only
        self.diamond_label.setFixedSize(12, 12)
        self.diamond_label.hide()
        verdict_layout.addWidget(self.diamond_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.word_label = QLabel(verdict_row)
        word_font = ui_font(12)  # verdict summary line 12px (04:365)
        self.word_label.setFont(word_font)
        self._word_pin = type_pin(word_font)  # color re-applied per set_view
        verdict_layout.addWidget(self.word_label, 0, Qt.AlignmentFlag.AlignVCenter)
        verdict_layout.addStretch(1)
        layout.addWidget(verdict_row)

        layout.addStretch(1)

        self._view: TempoCardView = _EMPTY_TEMPO
        self.set_view(self._view)

    # -- API ------------------------------------------------------------------

    def set_view(self, v: TempoCardView) -> None:
        """Render ``v`` verbatim. The tint touches the WORD (and its drawn ◆)
        only — numerals keep their construction color forever."""
        self._view = v
        self.primary_value.setText(v.primary_text)
        self.felt_value.setText(v.felt_text)
        self.word_label.setText(v.verdict_word)
        self.word_label.setStyleSheet(f"color: {v.verdict_tint};{self._word_pin}")
        if v.verdict_word == AMBIGUOUS_VERDICT_WORD:
            # The one word whose glyph is not cmap-covered: drawn ◆ (R-M2-20).
            self.diamond_label.setPixmap(diamond_pixmap(12, v.verdict_tint))
            self.diamond_label.show()
        else:
            self.diamond_label.hide()

    def view(self) -> TempoCardView:
        """The last-rendered view (test/introspection hook)."""
        return self._view
