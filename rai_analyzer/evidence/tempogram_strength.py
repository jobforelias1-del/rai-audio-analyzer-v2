"""Product-tempogram salience evidence term.

The base octave-resistant evidence: how strong is the (already octave-resistant)
product tempogram at this candidate? Kept as its own term so its weight is
tunable independently of the genre-specific terms.
"""

from __future__ import annotations

from ..config import TempogramTermParams
from ..contracts import Features, TermScore


def score_tempogram(bpm: float, features: Features, params: TempogramTermParams) -> TermScore:
    """Evidence term: product-tempogram salience at ``bpm`` (optionally sharpened)."""
    sal = features.tempo_curve.value_at(bpm)
    value = float(sal**params.sharpen) if params.sharpen != 1.0 else float(sal)
    return TermScore(value=value, detail={"salience": sal})
