"""Soft tempo prior (evidence term + the engine's ambiguity fuel).

A log-normal bump over BPM, fit from the ground-truth set. It favours the
region where the target genre is *notated* (full-time) over the half-time feel
region. The shape is right but the shoulders were tightened for drill (a
narrower default sigma / clamp): the old broad tails handed a genre-implausible
peak like ~132 BPM almost as much prior weight as the 140-170 notated band, so
the prior never had to *fight* it and the divergence trigger stayed silent. It
remains SOFT — a non-zero floor, never zeroing a candidate — so it nudges
scoring rather than dictating it.

Its most important job is not scoring at all: it powers the most reliable
ambiguity trigger. The resolver compares ``argmax(tempogram)`` against
``argmax(tempogram x prior)``; when the prior has to *fight* the raw signal to
move the answer, that disagreement is surfaced as ambiguity. For that to be
meaningful the prior must be a genuine, smooth preference — which is what
``prior_weight`` provides.
"""

from __future__ import annotations

import numpy as np

from ..config import PriorParams
from ..contracts import Features, TermScore


def prior_weight(bpm: float, params: PriorParams) -> float:
    """Soft log-normal prior weight at ``bpm``, in ``[params.floor, 1.0]``."""
    if bpm <= 0:
        return params.floor
    z = (np.log(bpm) - np.log(params.center_bpm)) / params.sigma
    bump = float(np.exp(-0.5 * z * z))
    return params.floor + (1.0 - params.floor) * bump


def prior_weight_array(bpms: np.ndarray, params: PriorParams) -> np.ndarray:
    """Vectorised :func:`prior_weight` for the whole BPM grid (used by the
    resolver's raw-vs-priored divergence trigger)."""
    bpms = np.asarray(bpms, dtype=np.float64)
    with np.errstate(divide="ignore"):
        z = (np.log(np.maximum(bpms, 1e-9)) - np.log(params.center_bpm)) / params.sigma
    bump = np.exp(-0.5 * z * z)
    return params.floor + (1.0 - params.floor) * bump


def score_prior(bpm: float, features: Features, params: PriorParams) -> TermScore:
    """Evidence term: how well ``bpm`` fits the genre tempo prior."""
    w = prior_weight(bpm, params)
    return TermScore(value=w, detail={"weight": w, "center_bpm": params.center_bpm})


def fit_prior(bpms: list[float], floor: float = 0.10, min_sigma: float = 0.14) -> PriorParams:
    """Fit a soft log-normal prior to a set of ground-truth tempos.

    ``center_bpm`` is the geometric mean; ``sigma`` is the std of log-BPM,
    clamped to ``min_sigma`` so a tiny ground-truth set cannot produce an
    over-confident (narrow) prior. The ``min_sigma`` floor was tightened from
    0.18 to 0.14 alongside the drill re-tune: the three-track ground-truth set
    clusters in 150-166, and the old clamp re-inflated the shoulders the re-tune
    set out to trim.
    """
    arr = np.asarray([b for b in bpms if b and b > 0], dtype=np.float64)
    if arr.size == 0:
        return PriorParams(floor=floor)
    logs = np.log(arr)
    center = float(np.exp(np.mean(logs)))
    sigma = float(np.std(logs)) if arr.size > 1 else min_sigma
    sigma = max(sigma, min_sigma)
    return PriorParams(center_bpm=center, sigma=sigma, floor=floor)
