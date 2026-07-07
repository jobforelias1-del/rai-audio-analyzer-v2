"""Load the bundled IBM Plex faces into the application font database.

The design renders every numeral in IBM Plex Mono and all UI text in IBM
Plex Sans, so the six TTFs ship inside rai_ui/resources/fonts and are
registered at startup — never resolved from the host system. Paths handed to
QFontDatabase.addApplicationFont must be ABSOLUTE: with a relative path the
lookup silently depends on the process CWD (app bundles launch with CWD=/),
so we anchor on this module's own location.

Failure policy: in development a missing/unloadable face raises RuntimeError
immediately — a silently substituted font would invalidate every design
review. In a frozen release build (PyInstaller sets sys.frozen) we degrade
instead of crashing: the QSS font-family chain falls back to system faces and
whatever did load is returned.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FONTS_DIR = Path(__file__).resolve().parent.parent / "resources" / "fonts"

FONT_FILES = (
    "IBMPlexSans-Regular.ttf",
    "IBMPlexSans-Medium.ttf",
    "IBMPlexSans-SemiBold.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Medium.ttf",
    "IBMPlexMono-SemiBold.ttf",
)

REQUIRED_FAMILIES = ("IBM Plex Sans", "IBM Plex Mono")


def _is_release() -> bool:
    return bool(getattr(sys, "frozen", False))


def load_fonts() -> list[str]:
    """Register the bundled TTFs; return the loaded family names.

    Requires a QGuiApplication/QApplication to exist. Raises RuntimeError in
    development if any file fails to load or a required family is absent.
    """
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    failed: list[str] = []
    for filename in FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(str(_FONTS_DIR / filename))
        if font_id == -1:
            failed.append(filename)
            continue
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in families:
                families.append(family)

    missing = [f for f in REQUIRED_FAMILIES if f not in families]
    if (failed or missing) and not _is_release():
        raise RuntimeError(
            f"font load failed: files={failed or 'ok'} missing_families={missing or 'ok'} "
            f"(dir: {_FONTS_DIR})"
        )
    return families
