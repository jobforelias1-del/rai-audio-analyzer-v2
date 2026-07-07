"""Header bar (component C-01): wordmark, file identity chip, genre chip, Browse.

48px raised surface with a hairline bottom edge. M0 keeps a normal titled
window (no native traffic-light integration), so this is a plain widget row —
nothing here touches window chrome.

The file chip has two states: a dashed "no file loaded" placeholder before the
first analysis, and ``name  duration · sr · channels`` after (values straight
off the AnalysisResult). The genre chip is static in M0 (profile selection is
an M1 feature); the rail toggle ships disabled with an honest tooltip.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton

from rai_ui.widgets import mono_font, token

HEADER_HEIGHT = int(token("size.header"))  # 48
_GAP = int(token("space.scale.3"))  # 12

NO_FILE_TEXT = "no file loaded"
RAIL_TOOLTIP = "rail arrives in M1"
GENRE_CHIP_TEXT = "DRILL · 140–170"  # static in M0; profile switching is M1


def _channels_word(channels: int) -> str:
    return {1: "mono", 2: "stereo"}.get(channels, f"{channels} ch")


def format_file_meta(duration: float, sr: int, channels: int) -> str:
    """``194.9 s · 44.1 kHz · stereo`` — the chip's muted half."""
    return f"{duration:.1f} s · {sr / 1000:.4g} kHz · {_channels_word(channels)}"


class HeaderBar(QFrame):
    """Top chrome row. Emits ``browse_requested`` when Browse… is clicked."""

    browse_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # "Header" matches the theme QSS selector (QWidget#Header): background,
        # height and hairline all come from the stylesheet.
        self.setObjectName("Header")
        self.setFixedHeight(HEADER_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(_GAP, 0, _GAP, 0)
        layout.setSpacing(_GAP)

        # Wordmark: Plex Mono semibold 20, letter-spaced, in a bordered box.
        self.wordmark = QLabel("RAI", self)
        self.wordmark.setObjectName("wordmark")
        wm_font = mono_font(20, QFont.Weight.DemiBold)
        wm_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.0)
        self.wordmark.setFont(wm_font)
        self.wordmark.setStyleSheet(
            f"QLabel#wordmark {{ color: {token('color.text.primary')};"
            f" border: 1px solid {token('color.border.strong')};"
            f" border-radius: {token('radius.sm')}px; padding: 1px 7px;"
            # Pin the type here too: the app-wide QSS font rule outranks QFont.
            ' font-family: "IBM Plex Mono"; font-size: 20px; font-weight: 600; }'
        )
        layout.addWidget(self.wordmark)

        self.version_label = QLabel("v3", self)
        self.version_label.setFont(mono_font(12))
        self.version_label.setStyleSheet(
            f"color: {token('color.text.muted')};"
            ' font-family: "IBM Plex Mono"; font-size: 12px;'
        )
        layout.addWidget(self.version_label)

        # File identity chip.
        self.file_chip = QFrame(self)
        self.file_chip.setObjectName("fileChip")
        chip_layout = QHBoxLayout(self.file_chip)
        chip_layout.setContentsMargins(10, 3, 10, 3)
        chip_layout.setSpacing(8)
        self.file_name_label = QLabel(self.file_chip)
        self.file_name_label.setFont(mono_font(12, QFont.Weight.DemiBold))
        self.file_meta_label = QLabel(self.file_chip)
        self.file_meta_label.setFont(mono_font(12))
        # The app-wide QSS sets Plex Sans 13 on every widget; the chip is a
        # measurement surface, so pin mono 12 at the same specificity level.
        _chip_type = 'font-family: "IBM Plex Mono"; font-size: 12px;'
        self._chip_name_type = _chip_type + " font-weight: 600;"
        self._chip_meta_type = _chip_type
        chip_layout.addWidget(self.file_name_label)
        chip_layout.addWidget(self.file_meta_label)
        layout.addWidget(self.file_chip)
        self.show_empty()

        layout.addStretch(1)

        # Genre profile chip (pill, QLabel[role="chip"] in the theme QSS).
        # The amber dot is a marker color, not a verdict color — it identifies
        # the profile, it judges nothing.
        self.genre_chip = QLabel(self)
        self.genre_chip.setProperty("role", "chip")
        self.genre_chip.setTextFormat(Qt.TextFormat.RichText)
        self.genre_chip.setText(
            f'<span style="color: {token("color.semantic.marker-primary.base")};">●</span>'
            f"&nbsp;{GENRE_CHIP_TEXT}"
        )
        layout.addWidget(self.genre_chip)

        self.browse_button = QPushButton("Browse…", self)
        self.browse_button.setProperty("variant", "secondary")
        self.browse_button.setProperty("size", "m")
        self.browse_button.clicked.connect(self.browse_requested.emit)
        layout.addWidget(self.browse_button)

        self.rail_toggle = QToolButton(self)
        self.rail_toggle.setText("▤")
        self.rail_toggle.setEnabled(False)
        self.rail_toggle.setToolTip(RAIL_TOOLTIP)
        self.rail_toggle.setProperty("variant", "ghost")
        # The theme has no QToolButton ghost rule (only nav buttons), so a
        # bare toolbutton renders as a native light box on the dark header.
        self.rail_toggle.setStyleSheet(
            "QToolButton { background: transparent; border: none;"
            f" color: {token('color.text.muted')}; }}"
            f"QToolButton:disabled {{ color: {token('color.text.disabled')}; }}"
        )
        layout.addWidget(self.rail_toggle)

    # -- file chip states ---------------------------------------------------

    def show_empty(self) -> None:
        self.file_name_label.setText(NO_FILE_TEXT)
        self.file_name_label.setStyleSheet(
            f"color: {token('color.text.muted')}; {self._chip_meta_type}"
        )
        self.file_meta_label.setText("")
        self.file_chip.setStyleSheet(
            f"QFrame#fileChip {{ border: 1px dashed {token('color.border.hairline')};"
            f" border-radius: {token('radius.sm')}px; }}"
        )

    def show_file(self, name: str, meta: str) -> None:
        self.file_name_label.setText(name)
        self.file_name_label.setStyleSheet(
            f"color: {token('color.text.primary')}; {self._chip_name_type}"
        )
        self.file_meta_label.setText(meta)
        self.file_meta_label.setStyleSheet(
            f"color: {token('color.text.muted')}; {self._chip_meta_type}"
        )
        self.file_chip.setStyleSheet(
            f"QFrame#fileChip {{ border: 1px solid {token('color.border.hairline')};"
            f" border-radius: {token('radius.sm')}px;"
            f" background: {token('color.surface.panel')}; }}"
        )
