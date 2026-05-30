"""Evidence terms for tempo-candidate scoring.

Every evidence term is a pure function with the SAME signature::

    score_<term>(candidate_bpm: float, features: Features, params) -> TermScore

* ``candidate_bpm`` — the BPM hypothesis being scored.
* ``features``      — the immutable, precomputed :class:`Features` bundle.
* ``params``        — this term's own params slice from :class:`TempoConfig`.
* returns a :class:`TermScore` with ``value`` in [0, 1] (higher = the term
  favours this candidate) plus a ``detail`` dict for diagnostics.

This uniform contract is what lets the resolver be a simple weighted sum and
lets each term be built and tested independently (and in parallel). Do not
change these signatures without updating the resolver.
"""

from .fingerprint import score_fingerprint
from .hihat_density import score_hihat_density
from .prior import fit_prior, prior_weight, prior_weight_array, score_prior
from .tempogram_strength import score_tempogram

__all__ = [
    "score_fingerprint",
    "score_hihat_density",
    "score_prior",
    "score_tempogram",
    "prior_weight",
    "prior_weight_array",
    "fit_prior",
]
