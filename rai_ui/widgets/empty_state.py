"""First-run hero page (C-18 language): the pre-first-analysis landing view.

Lives as page 0 of the section stack. The nav rail has no button for it, so
after the first result it becomes unreachable — the shell never returns to
the empty state once there is data to show.

Recent-file chips come from the QSettings-backed recent list; clicking one
re-analyzes that path. Per the approved Console (CO:194-199) the row reads
``RECENT`` (label style) followed by one pill chip per file — h24 pills on
the panel surface with the hover wash, mono 11. The pill skin lives in the
theme QSS (``QPushButton#recentPill``); only the content-box height is
pinned here (Landmine 6). Everything here is invitation, never error styling.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rai_ui.services import recent_files
from rai_ui.widgets import mono_font, token, ui_font

HERO_TITLE = "Drop a WAV to analyze"
HERO_HINT = "anywhere in this window · or"
RECENT_LABEL_TEXT = "RECENT"  # design renders the label uppercase (CO:195)
RECENT_PILL_HEIGHT = 24  # h24 content-box, pinned widget-level (Landmine 6)


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
        # The "RECENT" label leads the pill row (label style: 11/500/0.07em,
        # uppercase, muted); hidden while there is nothing recent to show.
        self.recent_label = QLabel(RECENT_LABEL_TEXT, self)
        label_font = ui_font(11, QFont.Weight.Medium)
        label_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107.0)
        self.recent_label.setFont(label_font)
        self.recent_label.setStyleSheet(
            # Pin type widget-level (app QSS outranks QFont — Landmine 6).
            f"color: {token('color.text.muted')};"
            ' font-family: "IBM Plex Sans"; font-size: 11px; font-weight: 500;'
        )
        self.recent_label.hide()
        self._recent_row.addWidget(self.recent_label)
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
            # "recentPill" matches the theme QSS (QPushButton#recentPill):
            # panel bg, hairline border, pill radius, mono 11, hover wash.
            chip.setObjectName("recentPill")
            chip.setToolTip(path)
            chip.setFont(mono_font(11))
            chip.setFixedHeight(RECENT_PILL_HEIGHT)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, p=path: self.open_recent.emit(p))
            # Insert before the trailing stretch so chips stay centered.
            self._recent_row.insertWidget(self._recent_row.count() - 1, chip)
            self._chips.append(chip)
        self.recent_label.setVisible(bool(self._chips))
