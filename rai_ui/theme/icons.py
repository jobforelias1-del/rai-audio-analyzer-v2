"""Minimal QPainter-drawn monochrome icons for the M0 nav rail.

No SVG assets: six tiny geometric glyphs drawn in code keep the icon set a
single source of truth alongside the tokens (color is a parameter, exactly
like CSS currentColor) and avoid a resource-compile step. All icons live on a
17px grid with a 1.5px stroke per the design spec; each is rendered at 1x and
2x device pixel ratio so they stay crisp on Retina.

Qt is imported lazily so importing this module never requires PySide6.
"""

from __future__ import annotations

ICON_SIZE_PX = 17
STROKE_WIDTH_PX = 1.5
_DPRS = (1.0, 2.0)


def nav_icon(name: str, color: str):
    """Build the named monochrome nav QIcon in the given hex color.

    Names: grid, bars, wave, columns, doc, book.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

    try:
        draw = _DRAWERS[name]
    except KeyError:
        raise KeyError(f"unknown nav icon {name!r}; have {sorted(_DRAWERS)}") from None

    icon = QIcon()
    for dpr in _DPRS:
        pixmap = QPixmap(round(ICON_SIZE_PX * dpr), round(ICON_SIZE_PX * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(color))
        pen.setWidthF(STROKE_WIDTH_PX)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        draw(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


# Each drawer paints in the 17x17 logical coordinate space with ~2px margins.


def _draw_grid(p) -> None:
    from PySide6.QtCore import QRectF

    for x, y in ((2.5, 2.5), (10.0, 2.5), (2.5, 10.0), (10.0, 10.0)):
        p.drawRoundedRect(QRectF(x, y, 4.5, 4.5), 1.0, 1.0)


def _draw_bars(p) -> None:
    from PySide6.QtCore import QPointF

    for y, x_end in ((4.5, 14.5), (8.5, 11.0), (12.5, 8.0)):
        p.drawLine(QPointF(2.5, y), QPointF(x_end, y))


def _draw_wave(p) -> None:
    import math

    from PySide6.QtCore import QPointF

    points = []
    for i in range(25):
        x = 2.0 + 13.0 * i / 24.0
        points.append(QPointF(x, 8.5 - 4.0 * math.sin(2.0 * math.pi * i / 24.0)))
    p.drawPolyline(points)


def _draw_columns(p) -> None:
    from PySide6.QtCore import QPointF

    for x, height in ((4.0, 6.0), (8.5, 10.0), (13.0, 4.0)):
        p.drawLine(QPointF(x, 14.5), QPointF(x, 14.5 - height))


def _draw_doc(p) -> None:
    from PySide6.QtCore import QPointF, QRectF

    p.drawRoundedRect(QRectF(4.0, 2.5, 9.0, 12.0), 1.5, 1.5)
    p.drawLine(QPointF(6.5, 7.0), QPointF(10.5, 7.0))
    p.drawLine(QPointF(6.5, 10.0), QPointF(10.5, 10.0))


def _draw_book(p) -> None:
    from PySide6.QtCore import QPointF, QRectF

    p.drawRoundedRect(QRectF(3.5, 2.5, 10.0, 12.0), 1.5, 1.5)
    p.drawLine(QPointF(6.0, 2.5), QPointF(6.0, 14.5))


_DRAWERS = {
    "grid": _draw_grid,
    "bars": _draw_bars,
    "wave": _draw_wave,
    "columns": _draw_columns,
    "doc": _draw_doc,
    "book": _draw_book,
}
