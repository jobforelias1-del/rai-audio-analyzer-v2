"""Unit tests for the resolver's ambiguity triggers (rai_analyzer.resolver).

These exercise :func:`rai_analyzer.resolver._detect_ambiguity` directly with
hand-built candidate sets. Driving the detector with synthesised candidates
(rather than synthesising audio that happens to mis-lock) lets us pin the exact
score/salience/relationship geometry each trigger is supposed to react to —
which is the whole point of having the triggers be a small, pure function.

Coverage:
  * Trigger 2 (competitor-score clustering) still fires — regression guard.
  * Trigger 3 (genre-band) fires for a single dominant peak parked below the
    drill band with a salient in-band partner, and NO strong score competitor —
    the confidently-wrong failure mode Triggers 1 & 2 both miss.
  * Trigger 3 stays silent for a confident in-band primary, and for a clean
    out-of-band primary whose only in-band candidates are zero-salience ghosts
    (a 120 BPM metronome) — so it never reflexively flags non-drill material.
"""

from __future__ import annotations

from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.contracts import Candidate, Relationship
from rai_analyzer.resolver import _detect_ambiguity


def _cand(bpm, score, salience, rel) -> Candidate:
    return Candidate(bpm=bpm, score=score, salience=salience, relationship=rel)


# ---------------------------------------------------------------------------
# Trigger 2: a strong octave/fractional runner-up (regression).
# ---------------------------------------------------------------------------


def test_competitor_score_trigger_still_fires():
    """An octave runner-up within score_close_frac of the winner => ambiguous."""
    cands = [
        _cand(150.0, score=2.00, salience=1.00, rel=Relationship.SELF),
        _cand(75.0, score=1.85, salience=0.95, rel=Relationship.OCTAVE_DOWN),
    ]
    # raw == priored so Trigger 1 cannot fire; 150 is in-band so Trigger 3 cannot
    # fire. Only the competitor-score trigger is left to explain a flag.
    ambiguous, reason = _detect_ambiguity(cands, DEFAULT_CONFIG, raw_best=150.0, priored_best=150.0)
    assert ambiguous is True
    assert reason and "within" in reason
    assert "outside the drill band" not in reason  # it was Trigger 2, not Trigger 3


def test_competitor_trigger_silent_when_runner_is_weak():
    """A runner-up well below score_close_frac leaves an in-band primary confident."""
    cands = [
        _cand(155.0, score=2.00, salience=1.00, rel=Relationship.SELF),
        _cand(77.5, score=0.50, salience=0.90, rel=Relationship.OCTAVE_DOWN),
    ]
    ambiguous, reason = _detect_ambiguity(cands, DEFAULT_CONFIG, raw_best=155.0, priored_best=155.0)
    assert ambiguous is False
    assert reason is None


# ---------------------------------------------------------------------------
# Trigger 3: genre-band — the confidently-wrong catch.
# ---------------------------------------------------------------------------


def test_out_of_band_primary_with_salient_in_band_partner_is_flagged():
    """Primary ~132 (below the drill band), salient truth in-band, no competitor.

    Mirrors the variant Ledger/Mathematics failure: one dominant peak in a
    genre-implausible place that the old engine reported as a confident wrong
    number because nothing competed with it on score.
    """
    cands = [
        _cand(132.05, score=2.00, salience=0.92, rel=Relationship.SELF),
        _cand(165.06, score=1.20, salience=0.55, rel=Relationship.FRACTIONAL),
        _cand(66.02, score=0.80, salience=0.40, rel=Relationship.OCTAVE_DOWN),
    ]
    # Runner-up is only 60% of the winner's score (< score_close_frac), and
    # raw == priored, so Triggers 1 & 2 are both silent — Trigger 3 must catch it.
    ambiguous, reason = _detect_ambiguity(
        cands, DEFAULT_CONFIG, raw_best=132.05, priored_best=132.05
    )
    assert ambiguous is True
    assert reason is not None
    assert "outside the drill band" in reason  # the out-of-band condition is named
    assert "132" in reason and "165" in reason


def test_in_band_confident_primary_is_not_flagged():
    """A primary squarely inside the drill band with weak competition stays confident."""
    cands = [
        _cand(155.0, score=2.00, salience=1.00, rel=Relationship.SELF),
        _cand(77.5, score=0.45, salience=0.90, rel=Relationship.OCTAVE_DOWN),
    ]
    ambiguous, reason = _detect_ambiguity(cands, DEFAULT_CONFIG, raw_best=155.0, priored_best=155.0)
    assert ambiguous is False
    assert reason is None


def test_out_of_band_without_salient_in_band_evidence_is_not_flagged():
    """A clean 120 BPM metronome must NOT trip Trigger 3.

    Its in-band candidates (e.g. 150 = 120*5/4) are zero-salience multiplier
    ghosts, so there is no real in-band evidence the primary 'missed'. Flagging
    here would be the over-eager failure the salience floor exists to prevent.
    """
    cands = [
        _cand(120.0, score=2.00, salience=1.00, rel=Relationship.SELF),
        _cand(150.0, score=1.40, salience=0.00, rel=Relationship.FRACTIONAL),
        _cand(160.0, score=1.10, salience=0.00, rel=Relationship.FRACTIONAL),
        _cand(60.0, score=0.80, salience=0.02, rel=Relationship.OCTAVE_DOWN),
    ]
    ambiguous, reason = _detect_ambiguity(cands, DEFAULT_CONFIG, raw_best=120.0, priored_best=120.0)
    assert ambiguous is False
    assert reason is None
