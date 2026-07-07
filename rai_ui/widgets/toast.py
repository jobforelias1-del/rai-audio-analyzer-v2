"""Toast (component C-19): transient bottom-right notice, never a modal.

Failure UX contract for the shell: analysis errors surface as a toast plus a
status-bar note. A modal would interrupt a producer mid-flow for something
the shell already recovered from, so this widget is deliberately passive —
it shows, waits, fades, and never takes focus.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel

from rai_ui.widgets import token, ui_font

TOAST_VISIBLE_MS = 2400
TOAST_FADE_MS = 180
_MARGIN = 16
# Keep clear of the 28px status bar plus a small gap.
_BOTTOM_OFFSET = int(token("size.statusbar")) + 12


class Toast(QFrame):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setObjectName("toast")
        # role="toast" matches the theme QSS (QFrame[role="toast"]).
        self.setProperty("role", "toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        self.label = QLabel(self)
        self.label.setFont(ui_font(int(token("type.scale.body.size"))))
        layout.addWidget(self.label)

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(TOAST_VISIBLE_MS)
        self._timer.timeout.connect(self._start_fade)
        self._animation: QPropertyAnimation | None = None
        self.hide()

    def show_message(self, message: str) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self.label.setText(message)
        self._effect.setOpacity(1.0)
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._timer.start()

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.move(
            parent.width() - self.width() - _MARGIN,
            parent.height() - self.height() - _BOTTOM_OFFSET,
        )

    def _start_fade(self) -> None:
        animation = QPropertyAnimation(self._effect, b"opacity", self)
        animation.setDuration(TOAST_FADE_MS)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.finished.connect(self.hide)
        self._animation = animation
        animation.start()
