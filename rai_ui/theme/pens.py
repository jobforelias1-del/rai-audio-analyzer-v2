"""Turn token pen/brush specs into Qt objects at the Qt boundary.

_tokens_gen.py stays Qt-free so the engine CI job can import it; this module
is where the plain-tuple specs (hex, width_px, style, dash_pattern) become
QPen/QBrush. Qt is imported lazily inside the functions so merely importing
rai_ui.theme.pens never drags in PySide6 (test collection without Qt).
"""

from __future__ import annotations

from rai_ui.theme._tokens_gen import (
    COLOR_PLOT_BAND_EDGE,
    COLOR_PLOT_GRID,
    COLOR_PLOT_WAVEFORM,
    LINE_HAIRLINE,
)

_STYLES = ("solid", "dash")

# The acceptance band's left/right 1px edge lines (C-16). Defined here rather
# than in the generated module because the generator's pen table is reserved
# for data/marker pens; the color still traces to the tokens by constant so it
# cannot drift. Cosmetic like every plot pen (see qpen).
# token: color.plot.band-edge · line.hairline
PEN_BAND_EDGE = (COLOR_PLOT_BAND_EDGE, float(LINE_HAIRLINE), "solid", None)

# The Overview waveform envelope stroke (R-M2-9): the approved screens draw
# it at 1.2px in a dedicated context-dim hue (04:391) so a dense min/max
# envelope reads as context, not data emphasis. The 1.2 width is an
# approved-screen literal — no line token carries it — queued with tokens
# v0.1.3 for design reconciliation.
# token: color.plot.waveform (v0.1.3) · width literal 1.2 (04:391)
PEN_WAVEFORM = (COLOR_PLOT_WAVEFORM, 1.2, "solid", None)

# The waveform well's center zero-line (04:392) — grid hue at hairline width.
# token: color.plot.grid · line.hairline
PEN_ZERO_LINE = (COLOR_PLOT_GRID, float(LINE_HAIRLINE), "solid", None)


def qpen(spec: tuple):
    """Build a QPen from a PEN_* spec tuple: (hex, width_px, style, dash).

    Pens are cosmetic so plot lines keep their designed pixel width under
    pyqtgraph zoom/resize transforms.
    """
    from PySide6.QtGui import QColor, QPen

    color, width, style, dash = spec
    if style not in _STYLES:
        raise ValueError(f"unknown pen style {style!r}; expected one of {_STYLES}")
    pen = QPen(QColor(color))
    pen.setWidthF(float(width))
    pen.setCosmetic(True)
    if style == "dash":
        # setDashPattern implies Qt.CustomDashLine; pattern units are pen widths.
        pen.setDashPattern([float(v) for v in (dash or ())])
    return pen


def qbrush(hex_color: str):
    """Build a solid QBrush from a BRUSH_* spec (a plain hex string)."""
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(hex_color))
