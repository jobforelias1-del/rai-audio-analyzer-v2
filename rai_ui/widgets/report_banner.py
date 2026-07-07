"""The Report screen's confirmed-truth banner (M4, R-M4-11).

04's report TEXT carries a confirmed reason line inside ``to_report()``'s
output — but the copyable/exported report is byte-frozen shared output (the
M0 verbatim guarantee; the shared-output doctrine wins, divergence logged in
the M4 rulings). So the confirmed truth lives in screen CHROME instead: this
slim banner mounts between the Report toolbar and the text edit, ONLY while
the verdict is CONFIRMED · HUMAN, and never touches the text edit's bytes.

Copy (single line, R-M4-11 verbatim):

    ✓ CONFIRMED · HUMAN — human tiebreak · {bpm} saved as ground truth

``{bpm}`` renders through ``fmt_bpm`` (two decimals — the same figure every
other confirmed surface shows). Treatment is the verdict-block confirmed
palette: ``semantic.confident`` bg/border/text, mono 12/500, type-pinned
(landmine 8). The banner is a passive label — no buttons, no links; undo
lives on the rail/bridge/candidates surfaces (R-M3-18).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from rai_ui.state.formatters import fmt_bpm
from rai_ui.theme._tokens_gen import (
    COLOR_SEMANTIC_CONFIDENT_BG,
    COLOR_SEMANTIC_CONFIDENT_BORDER,
    COLOR_SEMANTIC_CONFIDENT_TEXT,
)
from rai_ui.widgets import mono_font
from rai_ui.widgets.verdict_block import type_pin

BANNER_TEXT_FMT = "✓ CONFIRMED · HUMAN — human tiebreak · {bpm} saved as ground truth"

_MARGINS = (12, 6, 12, 6)  # slim banner: l, t, r, b
_RADIUS = 7  # the report toolbar's control radius


def banner_text(bpm: float) -> str:
    """The banner's verbatim copy for a confirmed ``bpm`` (fmt_bpm, 2 dp)."""
    return BANNER_TEXT_FMT.format(bpm=fmt_bpm(bpm))


class ReportBanner(QFrame):
    """Confirmed-truth chrome: shown iff the verdict is CONFIRMED · HUMAN.

    ``set_state(bpm_or_none)`` is the whole API — the shell passes the
    verdict state's ``confirmed_bpm`` when the kind is CONFIRMED_HUMAN and
    ``None`` otherwise; the banner shows/hides and formats accordingly.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("reportBanner")
        # token: color.semantic.confident.bg / .border — the verdict-block
        # confirmed treatment (R-M4-11).
        self.setStyleSheet(
            "QFrame#reportBanner {"
            f" background: {COLOR_SEMANTIC_CONFIDENT_BG};"
            f" border: 1px solid {COLOR_SEMANTIC_CONFIDENT_BORDER};"
            f" border-radius: {_RADIUS}px; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(*_MARGINS)
        self.label = QLabel(self)
        font = mono_font(12, QFont.Weight.Medium)
        self.label.setFont(font)
        # token: color.semantic.confident.text — ✓ is cmap-covered text (P3).
        self.label.setStyleSheet(
            f"color: {COLOR_SEMANTIC_CONFIDENT_TEXT};"
            f" background: transparent;{type_pin(font)}"
        )
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.set_state(None)

    def set_state(self, confirmed_bpm: Optional[float]) -> None:
        """Show the verbatim confirmed line for ``confirmed_bpm``, or hide."""
        if confirmed_bpm is None:
            self.label.setText("")
            self.hide()
            return
        self.label.setText(banner_text(float(confirmed_bpm)))
        self.show()
