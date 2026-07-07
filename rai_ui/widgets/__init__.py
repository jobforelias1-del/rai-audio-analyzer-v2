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


# --- M1 widget surface (re-exports) -----------------------------------------
# Only the Integrate stage touches package __init__ files (ruling R15). These
# imports sit BELOW the helper definitions on purpose: the widget modules
# import ``mono_font``/``ui_font``/``token`` back from this package, so the
# helpers must already exist on the partially-initialized module when the
# re-exports execute. Deliberately absent: ``rai_ui.plots.tempogram`` — the
# plots package __init__ stays import-free (engine CI imports plot math
# without Qt/pyqtgraph), so the tempogram pane is imported by module path.
from rai_ui.widgets.candidate_table import CandidatePane  # noqa: E402
from rai_ui.widgets.chips import HumanPill, RelationshipChip  # noqa: E402
from rai_ui.widgets.meter_bridge import MeterBridge  # noqa: E402
from rai_ui.widgets.metric_readout import MetricRail  # noqa: E402
from rai_ui.widgets.verdict_block import VerdictBlock  # noqa: E402

__all__ = [
    "token",
    "ui_font",
    "mono_font",
    "CandidatePane",
    "RelationshipChip",
    "HumanPill",
    "MeterBridge",
    "MetricRail",
    "VerdictBlock",
]
