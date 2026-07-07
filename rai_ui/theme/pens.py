"""Turn token pen/brush specs into Qt objects at the Qt boundary.

_tokens_gen.py stays Qt-free so the engine CI job can import it; this module
is where the plain-tuple specs (hex, width_px, style, dash_pattern) become
QPen/QBrush. Qt is imported lazily inside the functions so merely importing
rai_ui.theme.pens never drags in PySide6 (test collection without Qt).
"""

from __future__ import annotations

_STYLES = ("solid", "dash")


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
