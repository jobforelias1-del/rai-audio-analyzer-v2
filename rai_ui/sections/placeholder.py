"""Quiet placeholder section (C-18 language) for not-yet-built milestones.

A placeholder is a promise, not a failure: body-lg secondary title stating
when the pane arrives, plus one muted hint line. Deliberately no icon, no
border, no semantic color — semantic colors never decorate, and an absent
feature is not an error.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from rai_ui.widgets import token, ui_font

DEFAULT_HINT = "The Report section carries the full analysis until then."


class PlaceholderSection(QWidget):
    def __init__(self, title: str, hint: str = DEFAULT_HINT, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("placeholderSection")

        layout = QVBoxLayout(self)
        layout.addStretch(2)

        # role="empty-title"/"empty-hint": same quiet C-18 styling as the hero,
        # via the theme QSS — deliberately nothing stronger for an absent pane.
        self.title_label = QLabel(title, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setProperty("role", "empty-title")
        self.title_label.setFont(ui_font(int(token("type.scale.body-lg.size"))))
        layout.addWidget(self.title_label)

        self.hint_label = QLabel(hint, self)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setProperty("role", "empty-hint")
        self.hint_label.setFont(ui_font(int(token("type.scale.body.size"))))
        layout.addWidget(self.hint_label)

        layout.addStretch(3)
