"""Compare identity chips (M4, C-12 / 04:448–460): A, vs, B, hint, note.

The hue-lock is LAW (C-12 verbatim, 05:246): "A is always cyan (data-a), B
always rose (data-b) — chip, table column, and spectrum curve share the hue."
Every hex here is the tokens' ``plot.data-a`` / ``plot.data-b`` family so the
chips, the Δ-table headers and the overlay curves can never drift apart.

Chip anatomy per the approved screen (binding):

* **A chip** — pill h26, padding 0 12, bg ``accent.bg`` #11333B, border 1px
  ``data-a`` cyan, mono 12 cyan text ``A · <filename>`` (04:449).
* **B chip, loaded** — same pill in ``data-b-fill`` #3A1B2B / rose, mono 12
  rose ``B · <filename>`` plus a trailing ``✕`` glyph (mono 11, 65% rose,
  full rose on hover, ``title="Clear reference"``) that emits the clear
  request (04:452). ✕ is in the vendored Plex cmap, so it is text.
* **B chip, analyzing** — the R-M4-3 gap fill: the SAME loaded pill treatment
  carrying ``B · analyzing…``, no ✕ (in-flight indication is confined to
  this chip; nothing else in Compare moves).
* **B chip, empty** — pill h26, padding 0 14, DASHED rose border, sans 11
  rose, ``B · drop a reference WAV — or Browse…`` (04:456 verbatim); the
  WHOLE chip is the Browse click target and emits the browse request.
* **hint chip** — pill h26, dashed ``border.strong``, sans 11 muted, ``drop a
  WAV to replace B`` (04:453 verbatim), non-interactive, loaded-B only.
* **row chrome** — ``vs`` (sans 12 muted) between the chips; right-aligned
  static profile note ``same profile · drill 140–170`` (sans 11 muted,
  04:459). All copy arrives prebuilt on the ``CompareViewModel`` — this
  module renders it verbatim and derives nothing.

Every designed label is ``setFont`` + ``type_pin``-pinned (landmine 8). The
✕'s hover opacity ride is decorative and skipped (static 65% rose — flagged
in the M4 report); pill radius is height/2 per the "radius:999" convention.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from rai_ui.state.compare_view import BStatus, CompareViewModel, EMPTY_COMPARE_VIEW
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BG,
    COLOR_BORDER_STRONG,
    COLOR_PLOT_DATA_A,
    COLOR_PLOT_DATA_B,
    COLOR_PLOT_DATA_B_FILL,
    COLOR_TEXT_MUTED,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.verdict_block import type_pin

CHIP_HEIGHT = 26  # pill height (04:449)
_CHIP_RADIUS = CHIP_HEIGHT // 2  # "radius:999" convention: height/2
_CHIP_PAD_X = 12  # A / loaded-B / hint padding (04:449)
_EMPTY_PAD_X = 14  # B-empty padding (04:456)
CLEAR_GLYPH = "✕"
CLEAR_TOOLTIP = "Clear reference"
# 65% rose (04:452 opacity:0.65) — alpha byte 166/255.
_CLEAR_RGBA = "rgba(232, 123, 175, 166)"
VS_TEXT = "vs"


def _pill_style(border: str, text_hex: str, font: QFont, bg: str | None, dashed: bool) -> str:
    style = "dashed" if dashed else "solid"
    background = f" background: {bg};" if bg else " background: transparent;"
    return (
        f"border: 1px {style} {border}; border-radius: {_CHIP_RADIUS}px;"
        f"{background} color: {text_hex};{type_pin(font)}"
    )


class _ClearGlyph(QLabel):
    """The loaded-B chip's trailing ✕ — a click target, text glyph only."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(CLEAR_GLYPH, parent)
        font = mono_font(11)  # 11px inside the mono-12 chip (04:452)
        self.setFont(font)
        self.setStyleSheet(
            f"border: none; background: transparent; padding: 0 2px;"
            f" color: {_CLEAR_RGBA};{type_pin(font)}"  # token: color.plot.data-b @65%
        )
        self.setToolTip(CLEAR_TOOLTIP)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class BChip(QFrame):
    """The B identity chip — one widget, three designed states.

    ``set_state(status, text)`` restyles the pill per :class:`BStatus`;
    the EMPTY chip is the Browse affordance (whole chip clickable →
    ``browse_clicked``), the LOADED chip carries the ✕ (``clear_clicked``).
    """

    browse_clicked = Signal()
    clear_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("compareBChip")
        self.setFixedHeight(CHIP_HEIGHT)
        self._status: BStatus = BStatus.EMPTY

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_EMPTY_PAD_X, 0, _EMPTY_PAD_X, 0)
        layout.setSpacing(8)  # text-to-✕ gap (04:452)
        self._layout = layout

        self.text_label = QLabel(self)
        self.text_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self.text_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.clear_glyph = _ClearGlyph(self)
        self.clear_glyph.clicked.connect(self.clear_clicked)
        self.clear_glyph.hide()
        layout.addWidget(self.clear_glyph, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_state(BStatus.EMPTY, EMPTY_COMPARE_VIEW.b_chip_text)

    @property
    def status(self) -> BStatus:
        return self._status

    def set_state(self, status: BStatus, text: str) -> None:
        self._status = status
        self.text_label.setText(text)

        if status is BStatus.EMPTY:
            # Dashed rose browse chip (04:456): sans 11 rose, whole-chip target.
            font = ui_font(11)
            pad, bg, dashed = _EMPTY_PAD_X, None, True
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.clear_glyph.hide()
        else:
            # Loaded/working pill (04:452): rose fill, mono 12 rose.
            font = mono_font(12)
            pad, bg, dashed = _CHIP_PAD_X, COLOR_PLOT_DATA_B_FILL, False  # token: color.plot.data-b-fill
            self.setCursor(Qt.CursorShape.ArrowCursor)
            # The ✕ shows on a LOADED reference only — an in-flight B has no
            # designed cancel affordance (R-M4-3 minimal fill).
            self.clear_glyph.setVisible(status is BStatus.LOADED)

        self._layout.setContentsMargins(pad, 0, pad, 0)
        # token: color.plot.data-b — the hue-lock law (C-12).
        self.setStyleSheet(
            "QFrame#compareBChip { "
            + _pill_style(COLOR_PLOT_DATA_B, COLOR_PLOT_DATA_B, font, bg, dashed)
            + " }"
        )
        self.text_label.setFont(font)
        self.text_label.setStyleSheet(
            f"border: none; background: transparent;"
            f" color: {COLOR_PLOT_DATA_B};{type_pin(font)}"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton and self._status is BStatus.EMPTY:
            self.browse_clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class CompareChipRow(QWidget):
    """The Compare chip row (04:448–460): A · vs · B [· hint] ··· note."""

    browse_b_requested = Signal()
    clear_b_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)  # row gap (04:448)

        # A chip — fixed cyan treatment, only the filename changes.
        self.a_chip = QLabel(self)
        a_font = mono_font(12)
        self.a_chip.setFont(a_font)
        self.a_chip.setFixedHeight(CHIP_HEIGHT)
        self.a_chip.setStyleSheet(
            f"border: 1px solid {COLOR_PLOT_DATA_A};"  # token: color.plot.data-a
            f" border-radius: {_CHIP_RADIUS}px; padding: 0 {_CHIP_PAD_X}px;"
            f" background: {COLOR_ACCENT_BG};"  # token: color.accent.bg
            f" color: {COLOR_PLOT_DATA_A};{type_pin(a_font)}"
        )
        layout.addWidget(self.a_chip)

        self.vs_label = QLabel(VS_TEXT, self)
        vs_font = ui_font(12)
        self.vs_label.setFont(vs_font)
        self.vs_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};{type_pin(vs_font)}")  # token: color.text.muted
        layout.addWidget(self.vs_label)

        self.b_chip = BChip(self)
        self.b_chip.browse_clicked.connect(self.browse_b_requested)
        self.b_chip.clear_clicked.connect(self.clear_b_requested)
        layout.addWidget(self.b_chip)

        # Drop-to-replace hint (04:453) — non-interactive, loaded-B only.
        self.hint_chip = QLabel(self)
        hint_font = ui_font(11)
        self.hint_chip.setFont(hint_font)
        self.hint_chip.setFixedHeight(CHIP_HEIGHT)
        self.hint_chip.setStyleSheet(
            f"border: 1px dashed {COLOR_BORDER_STRONG};"  # token: color.border.strong
            f" border-radius: {_CHIP_RADIUS}px; padding: 0 {_CHIP_PAD_X}px;"
            f" color: {COLOR_TEXT_MUTED};{type_pin(hint_font)}"  # token: color.text.muted
        )
        self.hint_chip.hide()
        layout.addWidget(self.hint_chip)

        layout.addStretch(1)

        self.note_label = QLabel(self)
        note_font = ui_font(11)
        self.note_label.setFont(note_font)
        self.note_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};{type_pin(note_font)}")  # token: color.text.muted
        layout.addWidget(self.note_label)

        self.set_view(EMPTY_COMPARE_VIEW)

    def set_view(self, vm: CompareViewModel) -> None:
        """Render the chip states verbatim from the view-model. Idempotent."""
        self.a_chip.setText(vm.a_chip_text)
        self.b_chip.set_state(vm.b_status, vm.b_chip_text)
        self.hint_chip.setText(vm.hint_chip_text)
        self.hint_chip.setVisible(vm.show_hint_chip)
        self.note_label.setText(vm.profile_note)
