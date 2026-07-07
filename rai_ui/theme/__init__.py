"""RAI v3 theme package: the single source of visual truth for the UI.

Design tokens live in rai.tokens.json; tools/gen_theme.py compiles them into
the committed artifacts _tokens_gen.py (flat constants) and app.qss (the
stylesheet). This package stays importable WITHOUT Qt on purpose — the engine
CI job has no PySide6, and the anti-drift tests need the constants and QSS
text alone. Qt-touching helpers live in the fonts/pens/icons submodules and
import Qt lazily or are only imported by Qt-side code.
"""

from __future__ import annotations

from pathlib import Path

from . import _tokens_gen as tokens  # noqa: F401  (re-export: theme.tokens.COLOR_*)

_QSS_PATH = Path(__file__).resolve().parent / "app.qss"


def load_qss() -> str:
    """Return the committed stylesheet text (generated from the tokens)."""
    return _QSS_PATH.read_text(encoding="utf-8")


__all__ = ["load_qss", "tokens"]
