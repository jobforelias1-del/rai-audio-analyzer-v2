"""Navigation rail (component C-03): fixed 72px, exclusive section buttons.

Buttons carry the ``nav=true`` property so the theme QSS can style them as one
family. Icons come from ``rai_ui.theme.icons`` (a parallel-built black box);
while that module is absent the rail degrades to text-only buttons rather than
failing to construct — the shell must stay runnable during parallel builds.

The rail intentionally has NO button for the first-run hero page: once you
navigate anywhere you can't get "back" to the empty state, by design.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QFrame, QSizePolicy, QToolButton, QVBoxLayout

from rai_ui.widgets import token, ui_font

RAIL_WIDTH = 72  # px, per approved C-03 spec
SECTIONS: tuple[str, ...] = ("Overview", "Tempo", "Signal", "Compare", "Report")
STUDY_TEXT = "Study · soon"

# Section -> glyph name in rai_ui.theme.icons (grid/bars/wave/columns/doc/book).
_ICON_GLYPHS = {
    "overview": "grid",
    "tempo": "bars",
    "signal": "wave",
    "compare": "columns",
    "report": "doc",
    "study": "book",
}


def _load_icon(name: str) -> QIcon:
    """Fetch a themed icon; empty icon if the theme package hasn't landed."""
    try:
        from rai_ui.theme import icons
    except ImportError:
        return QIcon()
    try:
        return icons.nav_icon(_ICON_GLYPHS[name], str(token("color.text.secondary")))
    except Exception:
        return QIcon()


class NavRail(QFrame):
    """Emits ``section_selected(index)`` — index into ``SECTIONS``."""

    section_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("navRail")
        self.setFixedWidth(RAIL_WIDTH)
        self.setStyleSheet(
            f"QFrame#navRail {{ background: {token('color.surface.panel')};"
            f" border-right: 1px solid {token('color.border.hairline')}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, int(token("space.scale.2")), 0, int(token("space.scale.2")))
        layout.setSpacing(int(token("space.scale.1")))

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QToolButton] = {}

        for index, name in enumerate(SECTIONS):
            button = QToolButton(self)
            button.setText(name)
            button.setIcon(_load_icon(name.lower()))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setCheckable(True)
            button.setProperty("nav", True)
            button.setFont(ui_font(11))
            # The app-wide QSS sets 13px text and 12px side padding, which
            # elides "Overview" inside the 72px rail; pin caption size and a
            # narrower padding at widget level (widget QSS outranks app QSS).
            button.setStyleSheet("font-size: 11px; padding: 8px 2px;")
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(52)
            button.toggled.connect(partial(self._on_toggled, index))
            self._group.addButton(button, index)
            self._buttons[name] = button
            layout.addWidget(button)

        layout.addStretch(1)

        self.study_button = QToolButton(self)
        self.study_button.setText(STUDY_TEXT)
        self.study_button.setIcon(_load_icon("study"))
        self.study_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.study_button.setEnabled(False)
        # nav=true too so the theme's [nav][ghost]:disabled dim rule matches.
        self.study_button.setProperty("nav", True)
        self.study_button.setProperty("ghost", True)
        self.study_button.setFont(ui_font(11))
        self.study_button.setStyleSheet("font-size: 11px; padding: 8px 2px;")
        self.study_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.study_button)

    def _on_toggled(self, index: int, checked: bool) -> None:
        if checked:
            self.section_selected.emit(index)

    def button(self, name: str) -> QToolButton:
        return self._buttons[name]

    def set_current(self, name: str) -> None:
        """Programmatic navigation (e.g. auto-jump to Report on first result)."""
        self._buttons[name].setChecked(True)
