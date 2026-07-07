"""Pure placement math for plot annotations (no Qt, no pyqtgraph).

Kept out of the widget modules so the decisions that determine what a user
actually sees on a plot — e.g. which side of a marker its label hangs on —
are unit-testable without a QApplication.
"""

from __future__ import annotations

# Fraction of the visible x-span past which a marker's label flips to the
# left of the marker line. 0.72 leaves room for the widest label class
# ("205.15 BPM" plus padding) before the plot's right edge would clip it.
DEFAULT_FLIP_FRACTION = 0.72


def marker_label_side(
    bpm: float, xmin: float, xmax: float, flip_frac: float = DEFAULT_FLIP_FRACTION
) -> str:
    """Which side of a vertical BPM marker its text label should hang on.

    Labels hang to the ``"right"`` of the marker line by default (reading
    direction); once the marker sits at or past ``flip_frac`` of the visible
    span, the label would clip the plot's right edge, so it flips to
    ``"left"``. The boundary itself flips left (``>=``) so behaviour at the
    exact threshold is deterministic.

    A degenerate or inverted range (``xmax <= xmin``) returns ``"right"`` —
    there is no span to measure against, so keep the default.
    """
    span = xmax - xmin
    if span <= 0:
        return "right"
    frac = (bpm - xmin) / span
    return "left" if frac >= flip_frac else "right"
