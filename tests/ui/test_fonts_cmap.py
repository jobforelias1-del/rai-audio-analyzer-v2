"""Glyph-coverage gate for the bundled numeric font.

The UI renders measurements with typographic characters — multiplication
sign, middle dot, em dash, true minus, infinity, check mark, not-equal,
plus-minus, vulgar fractions, increment — straight from code. If the bundled
IBM Plex Mono ever lacks one, Qt silently substitutes a system font and the
metric readouts go visually off-grid, so the cmap is pinned here.

Pure fontTools — no Qt. fontTools is a UI-venv dependency only, so it is
importorskip'd to keep the Qt-less engine CI job collecting cleanly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fontTools")

from fontTools.ttLib import TTFont  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FONT_PATH = REPO_ROOT / "rai_ui" / "resources" / "fonts" / "IBMPlexMono-Regular.ttf"

REQUIRED_GLYPHS = "×·—−∞✓≠±⅓⅔¼½¾⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞∆" + "0123456789"


def test_plex_mono_covers_required_glyphs():
    font = TTFont(str(FONT_PATH), lazy=True)
    try:
        cmap = font.getBestCmap()
        missing = [(ch, f"U+{ord(ch):04X}") for ch in REQUIRED_GLYPHS if ord(ch) not in cmap]
        assert not missing, f"IBMPlexMono-Regular.ttf cmap is missing: {missing}"
    finally:
        font.close()
