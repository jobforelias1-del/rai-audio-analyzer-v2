"""Relationship chips and the ✓ HUMAN pill (components C-09 / C-13).

The candidate table paints its chips inside a delegate while other surfaces
(the rail's felt chip, future M3 tiebreak cards) want standalone widgets. Both
must render one truth, so the pill geometry and palette live in module-level
paint helpers — ``paint_chip`` / ``paint_human_pill`` — and the QWidget
classes are thin shells over the same functions. A delegate and a widget can
never drift apart because neither owns any drawing of its own.

Design contract (C-09, Console CO:283-290):

* Relation chip: pill h20, padding 0 9px, IBM Plex Mono 11. Border/text by
  kind — the primary row's chip wears the amber marker colors (the table IS
  the plot legend), unrelated mutes, every other relation is neutral.
* ``✓ HUMAN`` tag: pill h20, padding 0 8px, 10px/600, confident-green family.
  The ✓ glyph is covered by the vendored Plex Mono cmap (P3:65), so it is
  text — only ◆ ⚠ ▶ ⏸ ▾ must be drawn icons.
* Chip *labels* are computed in ``rai_ui.state.formatters`` (never here,
  never hand-authored) and arrive pre-built on ``ChipView`` — this module is
  presentation only.

"radius: 999" in the design is symbolic; a painted pill's real radius is
height / 2 (the QSS generator applies the same cap, see Landmine 6).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPaintEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from rai_ui.state.tempo_view import ChipView
from rai_ui.theme._tokens_gen import (
    COLOR_BORDER_HAIRLINE,
    COLOR_BORDER_STRONG,
    COLOR_SEMANTIC_CONFIDENT_BG,
    COLOR_SEMANTIC_CONFIDENT_BORDER,
    COLOR_SEMANTIC_CONFIDENT_TEXT,
    COLOR_SEMANTIC_MARKER_PRIMARY_BASE,
    COLOR_SEMANTIC_MARKER_PRIMARY_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
)
from rai_ui.widgets import mono_font

CHIP_HEIGHT = 20
_CHIP_PAD_X = 9  # design: padding 0 9px
_CHIP_FONT_PX = 11

HUMAN_PILL_TEXT = "✓ HUMAN"
_PILL_PAD_X = 8  # design: padding 0 8px
_PILL_FONT_PX = 10

# kind -> (border hex, text hex). Fixed vocabulary — an unknown kind raises
# rather than silently rendering an unstyled pill (same policy as icons.py).
_CHIP_PALETTE: dict[str, tuple[str, str]] = {
    # token: color.semantic.marker-primary.base / .text — the amber pair that
    # makes the primary row double as the plot legend (C-08 marker-coded pair)
    "primary": (COLOR_SEMANTIC_MARKER_PRIMARY_BASE, COLOR_SEMANTIC_MARKER_PRIMARY_TEXT),
    # token: color.border.strong / color.text.primary
    "related": (COLOR_BORDER_STRONG, COLOR_TEXT_PRIMARY),
    # token: color.border.hairline / color.text.muted
    "unrelated": (COLOR_BORDER_HAIRLINE, COLOR_TEXT_MUTED),
}


def chip_palette(kind: str) -> tuple[str, str]:
    """(border hex, text hex) for a ``ChipView.kind``. Unknown kinds raise."""
    try:
        return _CHIP_PALETTE[kind]
    except KeyError:
        raise KeyError(
            f"unknown chip kind {kind!r}; have {sorted(_CHIP_PALETTE)}"
        ) from None


def chip_font() -> QFont:
    """The relation chip's type: IBM Plex Mono 11 (C-09)."""
    return mono_font(_CHIP_FONT_PX)


def human_pill_font() -> QFont:
    """The ✓ HUMAN tag's type: 10px/600 (Console CO:285)."""
    return mono_font(_PILL_FONT_PX, QFont.Weight.DemiBold)


def chip_width(chip: ChipView) -> int:
    """Rendered pill width in px for ``chip`` (text + 2 × 9px padding)."""
    fm = QFontMetrics(chip_font())
    return fm.horizontalAdvance(chip.text) + 2 * _CHIP_PAD_X


def human_pill_width() -> int:
    """Rendered ✓ HUMAN pill width in px."""
    fm = QFontMetrics(human_pill_font())
    return fm.horizontalAdvance(HUMAN_PILL_TEXT) + 2 * _PILL_PAD_X


def _paint_pill(
    painter: QPainter,
    x: float,
    y: float,
    width: int,
    text: str,
    font: QFont,
    border_hex: str,
    text_hex: str,
    bg_hex: str | None,
) -> int:
    """Draw one pill at (x, y); returns its width so callers can flow layout.

    The stroke rect is inset by 0.5px so the 1px border lands on whole pixels
    (crisp hairline instead of a 2px antialiased smear).
    """
    rect = QRectF(x + 0.5, y + 0.5, width - 1, CHIP_HEIGHT - 1)
    radius = rect.height() / 2  # pill: computed radius, see module docstring
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(border_hex))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.setBrush(QColor(bg_hex) if bg_hex else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setFont(font)
    painter.setPen(QColor(text_hex))
    painter.drawText(
        QRectF(x, y, width, CHIP_HEIGHT), Qt.AlignmentFlag.AlignCenter, text
    )
    painter.restore()
    return width


def paint_chip(painter: QPainter, x: float, y: float, chip: ChipView) -> int:
    """Paint a relation chip with its top-left corner at (x, y).

    Returns the painted width. Shared by ``RelationshipChip.paintEvent`` and
    the candidate table's delegate — the single rendering truth.
    """
    border_hex, text_hex = chip_palette(chip.kind)
    return _paint_pill(
        painter, x, y, chip_width(chip), chip.text, chip_font(),
        border_hex, text_hex, bg_hex=None,  # C-09 chips are outline-only
    )


def paint_human_pill(painter: QPainter, x: float, y: float) -> int:
    """Paint the ✓ HUMAN tag with its top-left corner at (x, y); returns width."""
    return _paint_pill(
        painter, x, y, human_pill_width(), HUMAN_PILL_TEXT, human_pill_font(),
        # token: color.semantic.confident.border / .text / .bg — human ground
        # truth is a confident-family state, not a marker color
        COLOR_SEMANTIC_CONFIDENT_BORDER,
        COLOR_SEMANTIC_CONFIDENT_TEXT,
        COLOR_SEMANTIC_CONFIDENT_BG,
    )


class RelationshipChip(QWidget):
    """Standalone relation chip (h20 pill, mono 11) for non-table surfaces.

    Starts empty (paints nothing, zero width) until ``set_chip`` supplies a
    ``ChipView``; the rail hides/shows it around the felt chip's presence.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chip: ChipView | None = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(CHIP_HEIGHT)

    @property
    def chip(self) -> ChipView | None:
        """The currently rendered ChipView (None before the first set_chip)."""
        return self._chip

    def set_chip(self, chip: ChipView) -> None:
        if chip == self._chip:
            return
        self._chip = chip
        self.setFixedWidth(chip_width(chip))
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt naming
        width = chip_width(self._chip) if self._chip is not None else 0
        return QSize(width, CHIP_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt naming
        if self._chip is None:
            return
        painter = QPainter(self)
        paint_chip(painter, 0, 0, self._chip)
        painter.end()


class HumanPill(QWidget):
    """The ``✓ HUMAN`` tag (C-13): fixed copy, confident-green pill.

    Built and tested in M1; the tiebreak flow that surfaces it ships in M3.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(human_pill_width(), CHIP_HEIGHT)

    def sizeHint(self) -> QSize:  # noqa: N802 — Qt naming
        return QSize(human_pill_width(), CHIP_HEIGHT)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        paint_human_pill(painter, 0, 0)
        painter.end()
