"""Metrical-profile fingerprint term — the strongest genre-specific weapon.

>>> STATUS: STUB. Returns a neutral score so the pipeline runs end-to-end.
>>> The real implementation is built by a dedicated agent against this contract.

Contract (do not change without updating the resolver and __init__):

    score_fingerprint(candidate_bpm: float, features: Features,
                      params: FingerprintParams) -> TermScore

Algorithm to implement:
  * For ``candidate_bpm``, a bar = ``params.beats_per_bar`` beats; divide the
    bar into ``params.bins_per_bar`` (16) slots = a 16th-note grid.
  * For each band in ``params.bands`` (low/mid/high), fold that band's onset
    energy (``features.bands.<band>`` over ``features.bands.times``) into the
    16-bin grid at the candidate's BEST PHASE (search phase offsets that
    maximise on-grid energy), summing energy per slot across all bars, then
    normalise to a unit profile.
  * Compare the candidate's folded per-band profiles to the learned genre
    fingerprint (cosine similarity / correlation). Higher match -> higher score.
  * The genre fingerprint is learned by averaging the folded profiles of the
    ground-truth tracks (``learn_fingerprint``) and cached to
    ``rai_analyzer/fingerprints/drill.json``; ``params.fingerprint_path``
    overrides the path (None => packaged default). A wrong-octave candidate
    folds the pattern at the wrong resolution and matches poorly — that is how
    this term disambiguates the octave.
"""

from __future__ import annotations

from ..config import FingerprintParams
from ..contracts import Features, TermScore


def score_fingerprint(bpm: float, features: Features, params: FingerprintParams) -> TermScore:
    """STUB — neutral score. Real implementation pending (see module docstring)."""
    return TermScore(value=0.5, detail={"stub": True})
