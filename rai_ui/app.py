"""Application factory for the RAI v3 shell.

``create_app`` is the one place process-wide Qt state is configured: app
identity (which QSettings keys off), the Plex font families, the global
stylesheet, and the default UI font. MainWindow never assumes any of this —
tests construct it against a bare QApplication — but the shipped app always
boots through here.

The theme package is imported lazily inside ``create_app`` so that importing
``rai_ui.app`` (and MainWindow) works even while the theme is being built in
parallel; starting the real app without a theme fails loudly instead of
rendering off-spec.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

APP_NAME = "RAI Audio Analyzer"
ORG_NAME = "SiliconClick"

DEFAULT_FONT_FAMILY = "IBM Plex Sans"
DEFAULT_FONT_PT = 13


def create_app(argv: Optional[list] = None) -> QApplication:
    """Build the styled QApplication (fonts loaded, QSS applied, identity set)."""
    try:
        from rai_ui.theme import load_qss
        from rai_ui.theme.fonts import load_fonts
    except ImportError as exc:
        raise ImportError(
            "rai_ui.theme is not available (load_qss / fonts.load_fonts missing). "
            "The theme package is built alongside the shell; the app cannot start "
            "unstyled — tokens are law."
        ) from exc

    app = QApplication(argv if argv is not None else [])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)

    load_fonts()  # raises RuntimeError in dev if the Plex faces are missing
    app.setFont(QFont(DEFAULT_FONT_FAMILY, DEFAULT_FONT_PT))
    app.setStyleSheet(load_qss())
    return app
