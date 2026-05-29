"""Hi-hat subdivision-density term.

>>> STATUS: STUB. Returns a neutral score so the pipeline runs end-to-end.
>>> The real implementation is built by a dedicated agent against this contract.

Contract (do not change without updating the resolver and __init__):

    score_hihat_density(candidate_bpm: float, features: Features,
                        params: HihatParams) -> TermScore

Algorithm to implement:
  * Find the dominant high-band tatum from ``features.high_curve`` /
    ``features.bands.high`` and express it as a ratio tatum_bpm / candidate_bpm.
  * A candidate is plausible when its hat stream lands on a musical subdivision
    (``params.musical_ratios``; especially 4 = straight 16ths). A persistent
    high-band stream that only parses as constant 32nds/64ths
    (ratio >= ``params.implausible_ratio``) under the slower candidate is
    evidence to DOUBLE -> score the slow candidate low, the doubled one high.
  * Density must be SUSTAINED: split the track into ``params.n_sections``
    sections and require the density to hold in at least
    ``params.min_active_sections`` of them (guards against transient rolls /
    fills faking a fast subdivision).
"""

from __future__ import annotations

from ..config import HihatParams
from ..contracts import Features, TermScore


def score_hihat_density(bpm: float, features: Features, params: HihatParams) -> TermScore:
    """STUB — neutral score. Real implementation pending (see module docstring)."""
    return TermScore(value=0.5, detail={"stub": True})
