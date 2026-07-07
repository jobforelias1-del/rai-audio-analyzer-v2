"""Recent-files store backed by QSettings.

Keeps the last few analyzed paths so the first-run hero page can offer
one-click re-analysis. QSettings is constructed explicitly with the app's
organization/name so this works even before ``create_app`` has stamped the
application metadata (e.g. under pytest's bare QApplication).

Tests monkeypatch ``_settings`` to point at a throwaway INI file so they never
touch the user's real preferences.
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

ORGANIZATION = "SiliconClick"
APPLICATION = "RAI Audio Analyzer"

MAX_RECENT = 3
_KEY = "recent/files"


def _settings() -> QSettings:
    return QSettings(ORGANIZATION, APPLICATION)


def recent_paths() -> list[str]:
    """Most-recent-first list of previously analyzed paths (at most 3)."""
    raw = _settings().value(_KEY, [])
    if raw is None:
        return []
    # QSettings collapses a one-element list to a plain string on some
    # platforms; normalise both shapes.
    if isinstance(raw, str):
        raw = [raw] if raw else []
    return [str(p) for p in raw][:MAX_RECENT]


def add_recent(path: str) -> list[str]:
    """Push ``path`` to the front, de-duped, capped at ``MAX_RECENT``."""
    paths = [path] + [p for p in recent_paths() if p != path]
    paths = paths[:MAX_RECENT]
    settings = _settings()
    settings.setValue(_KEY, paths)
    settings.sync()
    return paths
