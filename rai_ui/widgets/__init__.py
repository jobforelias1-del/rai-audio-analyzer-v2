"""Shell chrome widgets for RAI v3 + the design-token accessor.

Tokens are law: every color / size / type value a widget needs comes from
``rai_ui/theme/rai.tokens.json``. The theme package (built in parallel) also
generates constants from the same file, but widgets read the JSON directly so
the shell renders faithfully even while the theme package is still landing —
same source of truth either way, no cross-agent naming coupling.

``token("color.text.muted")`` walks the dotted path and unwraps ``{"value": x}``
leaves, so callers get the bare hex / px number.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from PySide6.QtGui import QFont

_TOKENS_PATH = Path(__file__).resolve().parent.parent / "theme" / "rai.tokens.json"


@lru_cache(maxsize=1)
def _tokens() -> dict:
    with open(_TOKENS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def token(path: str) -> Any:
    """Resolve a dotted token path, e.g. ``token("size.header") -> 48``."""
    node: Any = _tokens()
    for part in path.split("."):
        node = node[part]
    if isinstance(node, dict) and "value" in node:
        return node["value"]
    return node


def ui_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """The UI family (IBM Plex Sans) at an exact pixel size."""
    font = QFont(str(token("type.family.ui")))
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font


def mono_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """The numeric family (IBM Plex Mono) — every measurement renders in this."""
    font = QFont(str(token("type.family.numeric")))
    font.setPixelSize(pixel_size)
    font.setWeight(weight)
    return font
