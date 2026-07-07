"""Minimal QPainter-drawn monochrome icons for the v3 UI.

No SVG assets: tiny geometric glyphs drawn in code keep the icon set a
single source of truth alongside the tokens (color is a parameter, exactly
like CSS currentColor) and avoid a resource-compile step. All icons live on a
17px grid with a 1.5px stroke per the design spec; each is rendered at 1x and
2x device pixel ratio so they stay crisp on Retina.

Two registries share that machinery:

* ``nav_icon`` — the six M0 nav-rail glyphs.
* ``glyph_icon`` — the M1 UI symbols (diamond ◆, warning ⚠, play ▶, pause ⏸,
  chevron-down ▾, plus the header's collapse/expand rail-toggle pair). The
  symbol characters are NOT covered by the vendored IBM Plex faces, so
  rendering them as text would fall back to OS emoji glyphs — the design
  forbids that (P3 drawn-icons rule): they must always be drawn.

Qt is imported lazily so importing this module never requires PySide6.
"""

from __future__ import annotations

ICON_SIZE_PX = 17
STROKE_WIDTH_PX = 1.5
_DPRS = (1.0, 2.0)


def _build_icon(draw, color: str):
    """Render ``draw`` at 1x and 2x into a QIcon in the given hex color.

    The painter arrives with the standard 1.5px round-capped pen set and no
    brush; drawers for solid glyphs opt into a fill themselves.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

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


def nav_icon(name: str, color: str):
    """Build the named monochrome nav QIcon in the given hex color.

    Names: grid, bars, wave, columns, doc, book.
    """
    try:
        draw = _DRAWERS[name]
    except KeyError:
        raise KeyError(f"unknown nav icon {name!r}; have {sorted(_DRAWERS)}") from None
    return _build_icon(draw, color)


def glyph_icon(name: str, color: str):
    """Build the named monochrome UI-symbol QIcon in the given hex color.

    Names: diamond, warning, play, pause, chevron-down, collapse, expand.
    Fixed vocabulary — an unknown name raises ``KeyError`` rather than
    silently degrading.
    """
    try:
        draw = _GLYPH_DRAWERS[name]
    except KeyError:
        raise KeyError(
            f"unknown glyph icon {name!r}; have {sorted(_GLYPH_DRAWERS)}"
        ) from None
    return _build_icon(draw, color)


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


# --- M1 UI symbols (drawn, never font glyphs — P3 rule) ----------------------


def _draw_diamond(p) -> None:
    # ◆ — the Ambiguous verdict mark. Solid fill so it reads at 12px.
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF

    p.setBrush(p.pen().color())
    p.drawPolygon(
        QPolygonF(
            [QPointF(8.5, 3.0), QPointF(14.0, 8.5), QPointF(8.5, 14.0), QPointF(3.0, 8.5)]
        )
    )


def _draw_warning(p) -> None:
    # ⚠ — outlined triangle with an exclamation stem and dot.
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF

    p.drawPolygon(
        QPolygonF([QPointF(8.5, 3.0), QPointF(15.0, 13.8), QPointF(2.0, 13.8)])
    )
    p.drawLine(QPointF(8.5, 7.0), QPointF(8.5, 9.8))
    p.drawPoint(QPointF(8.5, 11.9))


def _draw_play(p) -> None:
    # ▶ — solid right-pointing triangle (hear / preview affordances).
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF

    p.setBrush(p.pen().color())
    p.drawPolygon(
        QPolygonF([QPointF(5.5, 3.5), QPointF(14.0, 8.5), QPointF(5.5, 13.5)])
    )


def _draw_pause(p) -> None:
    # ⏸ — two solid vertical bars.
    from PySide6.QtCore import QRectF

    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(4.5, 3.5, 2.6, 10.0), 1.0, 1.0)
    p.drawRoundedRect(QRectF(9.9, 3.5, 2.6, 10.0), 1.0, 1.0)


def _draw_chevron_down(p) -> None:
    # ▾ — open chevron (disclosure affordance).
    from PySide6.QtCore import QPointF

    p.drawPolyline([QPointF(4.5, 6.5), QPointF(8.5, 10.5), QPointF(12.5, 6.5)])


_DRAWERS = {
    "grid": _draw_grid,
    "bars": _draw_bars,
    "wave": _draw_wave,
    "columns": _draw_columns,
    "doc": _draw_doc,
    "book": _draw_book,
}

def _draw_collapse(p) -> None:
    # Rail visible (right column filled): clicking collapses it to the bridge.
    from PySide6.QtCore import QRectF, Qt

    p.drawRoundedRect(QRectF(2.5, 3.5, 12.0, 10.0), 1.5, 1.5)
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(10.5, 5.0, 2.5, 7.0), 0.8, 0.8)
    p.setBrush(Qt.BrushStyle.NoBrush)


def _draw_expand(p) -> None:
    # Bridge visible (top strip filled): clicking expands back to the rail.
    from PySide6.QtCore import QRectF, Qt

    p.drawRoundedRect(QRectF(2.5, 3.5, 12.0, 10.0), 1.5, 1.5)
    p.setBrush(p.pen().color())
    p.drawRoundedRect(QRectF(4.0, 5.0, 9.0, 2.5), 0.8, 0.8)
    p.setBrush(Qt.BrushStyle.NoBrush)


_GLYPH_DRAWERS = {
    "diamond": _draw_diamond,
    "warning": _draw_warning,
    "play": _draw_play,
    "pause": _draw_pause,
    "chevron-down": _draw_chevron_down,
    "collapse": _draw_collapse,
    "expand": _draw_expand,
}
