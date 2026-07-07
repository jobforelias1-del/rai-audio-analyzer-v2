"""First-run hero page (C-18 language): the pre-first-analysis landing view.

Lives as page 0 of the section stack. The nav rail has no button for it, so
after the first result it becomes unreachable — the shell never returns to
the empty state once there is data to show.

Recent-file chips come from the QSettings-backed recent list; clicking one
re-analyzes that path. Everything here is invitation, never error styling.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rai_ui.services import recent_files
from rai_ui.widgets import mono_font, token, ui_font

HERO_TITLE = "Drop a WAV to analyze"
HERO_HINT = "anywhere in this window · or"


class EmptyStateHero(QWidget):
    browse_requested = Signal()
    open_recent = Signal(str)  # full path of a recent-file chip

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")

        outer = QVBoxLayout(self)
        outer.addStretch(3)

        # role="empty-title"/"empty-hint" match the theme QSS empty-state rules.
        self.title_label = QLabel(HERO_TITLE, self)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setProperty("role", "empty-title")
        self.title_label.setFont(ui_font(int(token("type.scale.body-lg.size"))))
        outer.addWidget(self.title_label)

        self.hint_label = QLabel(HERO_HINT, self)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setProperty("role", "empty-hint")
        self.hint_label.setFont(ui_font(int(token("type.scale.body.size"))))
        outer.addWidget(self.hint_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.browse_button = QPushButton("Browse…", self)
        self.browse_button.setProperty("variant", "secondary")
        self.browse_button.setProperty("size", "m")
        self.browse_button.clicked.connect(self.browse_requested.emit)
        button_row.addWidget(self.browse_button)
        button_row.addStretch(1)
        outer.addSpacing(int(token("space.scale.4")))
        outer.addLayout(button_row)

        self._recent_row = QHBoxLayout()
        self._recent_row.setSpacing(int(token("space.scale.2")))
        self._recent_row.addStretch(1)
        self._recent_row.addStretch(1)
        outer.addSpacing(int(token("space.scale.6")))
        outer.addLayout(self._recent_row)
        self._chips: list[QPushButton] = []

        outer.addStretch(4)
        self.refresh_recent()

    def refresh_recent(self) -> None:
        """Rebuild the recent-file chip row from the persisted list."""
        for chip in self._chips:
            self._recent_row.removeWidget(chip)
            chip.deleteLater()
        self._chips = []
        for path in recent_files.recent_paths():
            chip = QPushButton(os.path.basename(path), self)
            chip.setToolTip(path)
            chip.setFont(mono_font(12))
            chip.setProperty("variant", "ghost")
            chip.setProperty("size", "s")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                f"QPushButton {{ color: {token('color.text.secondary')};"
                f" border: 1px solid {token('color.border.hairline')};"
                f" border-radius: {token('radius.sm')}px; padding: 3px 10px; }}"
            )
            chip.clicked.connect(lambda _=False, p=path: self.open_recent.emit(p))
            # Insert before the trailing stretch so chips stay centered.
            self._recent_row.insertWidget(self._recent_row.count() - 1, chip)
            self._chips.append(chip)
