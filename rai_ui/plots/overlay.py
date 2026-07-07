"""The shared C-17 working overlay — one truth for every plot pane.

Promoted verbatim from ``rai_ui.plots.tempogram._WorkingOverlay`` in M4
(landmine 16's scheduled cleanup: the module-private class had grown three
importers — tempogram, spectrum, waveform — and Compare's spectrum overlay
would have been the fourth). Zero behavior change: the class body, its
constants, and the visibility-driven animation contract moved unmodified;
only the name went public.

The sweep animation is owned here and tied to *effective* visibility:
started in showEvent, stopped in hideEvent. Hiding the pane (or any
ancestor — e.g. switching sections) delivers a hide event to this child,
so the animation can never keep ticking off-screen. With motion disabled
or stopped the overlay still communicates via its static text.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_SURFACE_INSET,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
    MOTION_WORKING_SWEEP_MS,
    TYPE_FAMILY_NUMERIC,
    TYPE_FAMILY_UI,
)

# --- working sweep (C-17, CO:241-249) ------------------------------------------
SWEEP_START_FRAC = -0.04  # mock keyframes: left:-4% → 102%
SWEEP_END_FRAC = 1.02
SWEEP_LINE_W = 2
WORKING_WORD = "WORKING…"
WORKING_SUB = "full-track analysis · ~1 s"


class WorkingOverlay(QWidget):
    """The C-17 working state: solid cover, sweeping accent line, quiet copy.

    The sweep animation is owned here and tied to *effective* visibility:
    started in showEvent, stopped in hideEvent. Hiding the pane (or any
    ancestor — e.g. switching sections) delivers a hide event to this child,
    so the animation can never keep ticking off-screen. With motion disabled
    or stopped the overlay still communicates via its static text.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction = SWEEP_START_FRAC

        # 1200ms infinite sweep on the design's standard easing curve
        # (cubic-bezier(0.2, 0, 0, 1) — token: motion.easing).
        easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
        easing.addCubicBezierSegment(QPointF(0.2, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(SWEEP_START_FRAC)
        self._animation.setEndValue(SWEEP_END_FRAC)
        self._animation.setDuration(MOTION_WORKING_SWEEP_MS)  # token: motion.working-sweep
        self._animation.setEasingCurve(easing)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._on_fraction)

        # Plex Mono 12/600 word + Plex Sans 12 sub (painter fonts).
        self._word_font = QFont(TYPE_FAMILY_NUMERIC)
        self._word_font.setPixelSize(12)
        self._word_font.setWeight(QFont.Weight.DemiBold)
        self._sub_font = QFont(TYPE_FAMILY_UI)
        self._sub_font.setPixelSize(12)

    def sweep_running(self) -> bool:
        return self._animation.state() == QVariantAnimation.State.Running

    def _on_fraction(self, value) -> None:
        self._fraction = float(value)
        self.update()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._animation.state() != QVariantAnimation.State.Running:
            self._animation.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._animation.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(COLOR_SURFACE_INSET))  # token: color.surface.inset

        sweep_x = self._fraction * self.width()
        painter.fillRect(
            QRectF(sweep_x, 0, SWEEP_LINE_W, self.height()),
            QColor(COLOR_ACCENT_BASE),  # token: color.accent.base
        )

        center_y = self.height() / 2
        painter.setFont(self._word_font)
        painter.setPen(QColor(COLOR_TEXT_SECONDARY))  # token: color.text.secondary
        painter.drawText(
            QRectF(0, center_y - 24, self.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            WORKING_WORD,
        )
        painter.setFont(self._sub_font)
        painter.setPen(QColor(COLOR_TEXT_MUTED))  # token: color.text.muted
        painter.drawText(
            QRectF(0, center_y + 4, self.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            WORKING_SUB,
        )
