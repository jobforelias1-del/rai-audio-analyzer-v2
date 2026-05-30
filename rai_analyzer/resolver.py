"""Tempo resolver — combines evidence terms and decides confident vs. ambiguous.

This is the integration heart of the engine and the home of the signature
feature: *never silently pick an octave.* It scores every candidate as a
weighted sum of independently-testable evidence terms, then applies two
ambiguity triggers. When either fires, the result is flagged for a human
tiebreak and the full candidate set is surfaced with explanations — rather than
emitting a confident wrong number, which is the exact failure mode that
triggered this rebuild.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .candidates import generate_candidates
from .config import TempoConfig
from .contracts import Candidate, Features, Relationship, TempoResult, classify_relationship
from .evidence import (
    prior_weight_array,
    score_fingerprint,
    score_hihat_density,
    score_prior,
    score_tempogram,
)
from .tempogram import build_combined_envelope, refine_bpm

# Relationships that, on a near-equal-scoring runner-up, make the verdict
# ambiguous. The octave/fractional family is the classic octave trap. SELF is
# the "Fixette shape": a *distinct* in-band tempo only a few percent from the
# primary (e.g. truth 141 vs primary 146, both inside the drill band) — it
# survives candidate de-dup yet classifies as near-unison, so the
# octave/fractional-only gate used to let a confident-but-wrong primary through
# unflagged. Counting SELF closes that hole without disturbing the octave logic.
_AMBIGUOUS_RELATIONS = frozenset(
    {
        Relationship.SELF,
        Relationship.OCTAVE_UP,
        Relationship.OCTAVE_DOWN,
        Relationship.TRIPLE,
        Relationship.THIRD,
        Relationship.DOTTED_UP,
        Relationship.DOTTED_DOWN,
        Relationship.FRACTIONAL,
    }
)

# Relationships that make a candidate a plausible "felt" (tapped) tempo of primary.
_FELT_RELATIONS = frozenset(
    {Relationship.OCTAVE_DOWN, Relationship.DOTTED_DOWN, Relationship.THIRD, Relationship.SELF}
)

# Simple musical ratios used to snap octave/fractional partners onto an exact
# multiple of the precisely-refined anchor pulse (inherits its precision).
_SIMPLE_RATIOS = (
    1 / 3, 1 / 2, 5 / 8, 2 / 3, 3 / 4, 4 / 5, 5 / 6, 1.0,
    6 / 5, 5 / 4, 4 / 3, 3 / 2, 8 / 5, 2.0, 3.0,
)


def _snap_to_ratio(bpm: float, base: float, tol: float = 0.04) -> Optional[float]:
    """Snap ``bpm`` to ``ratio * base`` if it lands near a simple musical ratio."""
    if base <= 0 or bpm <= 0:
        return None
    r = bpm / base
    best: Optional[float] = None
    best_err = tol
    for s in _SIMPLE_RATIOS:
        err = abs(r - s) / s
        if err < best_err:
            best_err, best = err, s
    return best * base if best is not None else None


def resolve_tempo(features: Features, cfg: TempoConfig) -> TempoResult:
    """Resolve the tempo of a track into a confident or ambiguous verdict."""
    bpms = generate_candidates(features, cfg)
    if not bpms:
        return TempoResult(
            primary_bpm=0.0,
            felt_bpm=None,
            candidates=[],
            ambiguous=True,
            ambiguity_reason="No tempo detected (signal too quiet or too short).",
        )

    # --- Score every candidate as a weighted sum of evidence terms. ---
    w = cfg.weights
    candidates: list[Candidate] = []
    for bpm in bpms:
        terms = {
            "fingerprint": score_fingerprint(bpm, features, cfg.fingerprint),
            "hihat_density": score_hihat_density(bpm, features, cfg.hihat),
            "tempogram": score_tempogram(bpm, features, cfg.tempogram_term),
            "prior": score_prior(bpm, features, cfg.prior),
        }
        score = (
            w.fingerprint * terms["fingerprint"].value
            + w.hihat_density * terms["hihat_density"].value
            + w.tempogram * terms["tempogram"].value
            + w.prior * terms["prior"].value
        )
        candidates.append(
            Candidate(
                bpm=bpm,
                score=score,
                salience=features.tempo_curve.value_at(bpm),
                terms=terms,
            )
        )

    candidates.sort(key=lambda c: -c.score)
    primary = candidates[0]

    # --- Raw-vs-priored divergence (computed before refinement; also the most
    #     reliable ambiguity trigger). ---
    raw_best, priored_best = _raw_vs_priored(features, cfg)

    # --- Refine the headline number to DAW-marker precision. ---
    # Anchor on the single most-salient pulse (cleanest to refine — in drill the
    # backbeat), then snap octave/fractional partners to exact ratios of it so
    # primary == 2x felt and every number inherits the anchor's precision.
    combined = build_combined_envelope(features.bands, cfg)
    base_bpm = refine_bpm(combined, features.sr, features.hop_length, raw_best) if raw_best > 0 else 0.0

    def finalize(bpm: float) -> float:
        snapped = _snap_to_ratio(bpm, base_bpm)
        if snapped is not None:
            return snapped
        return refine_bpm(combined, features.sr, features.hop_length, bpm)

    refined_primary = finalize(primary.bpm)
    primary.bpm = refined_primary

    # --- Relationships of every candidate to the chosen primary. ---
    for c in candidates:
        c.relationship = (
            Relationship.SELF
            if c is primary
            else classify_relationship(c.bpm, refined_primary)
        )

    # --- Felt (tapped) tempo. ---
    felt_bpm = _felt_tempo(refined_primary, candidates, finalize, cfg)

    ambiguous, reason = _detect_ambiguity(candidates, cfg, raw_best, priored_best)

    return TempoResult(
        primary_bpm=refined_primary,
        felt_bpm=felt_bpm,
        candidates=candidates,
        ambiguous=ambiguous,
        ambiguity_reason=reason,
        raw_best_bpm=raw_best,
        priored_best_bpm=priored_best,
    )


def _raw_vs_priored(features: Features, cfg: TempoConfig) -> tuple[float, float]:
    """Argmax of the raw product tempogram vs. the prior-weighted tempogram."""
    curve = features.tempo_curve
    grid, sal = curve.bpms, curve.salience
    if sal.size == 0 or float(np.max(sal)) <= 0:
        return 0.0, 0.0
    raw_best = float(grid[int(np.argmax(sal))])
    priored = sal * prior_weight_array(grid, cfg.prior)
    priored_best = float(grid[int(np.argmax(priored))])
    return raw_best, priored_best


def _felt_tempo(
    primary_bpm: float, candidates: list[Candidate], finalize, cfg: TempoConfig
) -> Optional[float]:
    """Derive the tempo a human would tap their foot to.

    If the primary already sits in the tappable band, that is the felt tempo.
    Otherwise the strongest octave/dotted-down candidate inside the band is the
    felt tempo (e.g. 154 -> 77). Never fabricated: if nothing qualifies, None.
    ``finalize`` applies the same base-anchored precision refinement used for
    the primary.
    """
    amb = cfg.ambiguity
    if amb.felt_min <= primary_bpm <= amb.felt_max:
        return primary_bpm
    in_band = [
        c
        for c in candidates
        if amb.felt_min <= c.bpm <= amb.felt_max and c.relationship in _FELT_RELATIONS
    ]
    if not in_band:
        return None
    best = max(in_band, key=lambda c: c.salience)
    return finalize(best.bpm)


def _detect_ambiguity(
    candidates: list[Candidate], cfg: TempoConfig, raw_best: float, priored_best: float
) -> tuple[bool, Optional[str]]:
    """Apply the two ambiguity triggers; return (ambiguous, human-readable reason)."""
    amb = cfg.ambiguity
    reasons: list[str] = []

    # Trigger 1: the prior is actively fighting the raw signal.
    if raw_best > 0 and priored_best > 0:
        rel = classify_relationship(priored_best, raw_best)
        if (
            abs(priored_best - raw_best) / raw_best > amb.divergence_tol
            and rel != Relationship.SELF
        ):
            reasons.append(
                f"raw tempogram peaks at {raw_best:.0f}, prior favors "
                f"{priored_best:.0f} ({rel.value})"
            )

    # Trigger 2 (score clustering): a strong runner-up — an octave/fractional
    # partner OR a near-unison in-band alternate (the Fixette shape) — scores
    # within score_close_frac of the winner, so the engine declines to force a
    # confident pick between two near-tied tempos.
    if len(candidates) >= 2:
        top, runner = candidates[0], candidates[1]
        if (
            top.score > 0
            and runner.score / top.score >= amb.score_close_frac
            and runner.relationship in _AMBIGUOUS_RELATIONS
        ):
            pct = 100.0 * runner.score / top.score
            reasons.append(
                f"{runner.bpm:.0f} ({runner.relationship.value}) scores within "
                f"{pct:.0f}% of {top.bpm:.0f}"
            )

    return (bool(reasons), "; ".join(reasons) if reasons else None)
