"""Unit tests for the tempo resolver (rai_analyzer.resolver.resolve_tempo).

CONCURRENCY: the fingerprint, hi-hat-density, and loudness evidence terms are
being implemented in parallel and currently return neutral stubs. These tests
therefore assert ONLY invariants that are driven by the prior + product
tempogram + divergence/relationship logic, which are stable regardless of how
those terms land:

  * structural shape of the TempoResult,
  * octave-consistency (primary ~= 2 * felt; felt inside the felt band),
  * recall (the true tempo AND its half are present in the candidate set),
  * the ambiguity verdict for the half-time drill synthetic and the clean click,
  * graceful handling of a silent signal.

It does NOT assert exact evidence-term values or exact total scores.
"""

from __future__ import annotations

import numpy as np
import pytest

from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.contracts import Relationship, TempoResult
from rai_analyzer.resolver import resolve_tempo
from rai_analyzer.synthetic import as_signal
from rai_analyzer.tempogram import build_features


def _build(signal):
    return build_features(signal, DEFAULT_CONFIG)


def _has_member_within(candidates, target, frac):
    return any(abs(c.bpm - target) / target <= frac for c in candidates)


# ---------------------------------------------------------------------------
# Clean click track: unambiguous, accurate.
# ---------------------------------------------------------------------------


def test_click_track_is_confident_and_accurate(features_click_120):
    r = resolve_tempo(features_click_120, DEFAULT_CONFIG)
    assert isinstance(r, TempoResult)
    assert r.ambiguous is False
    assert r.ambiguity_reason is None
    # Primary within 1% of the true 120 BPM click.
    assert abs(r.primary_bpm - 120.0) / 120.0 <= 0.01


def test_click_track_via_factory(make_click):
    feats = _build(make_click(100.0, duration=18.0))
    r = resolve_tempo(feats, DEFAULT_CONFIG)
    assert r.ambiguous is False
    assert abs(r.primary_bpm - 100.0) / 100.0 <= 0.01


# ---------------------------------------------------------------------------
# Half-time drill: true tempo surfaced, octave-consistent, flagged ambiguous.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_drill_surfaces_true_tempo_and_half(make_drill, true_bpm):
    feats = _build(make_drill(true_bpm, duration=24.0))
    r = resolve_tempo(feats, DEFAULT_CONFIG)

    # Recall: the candidate set must contain the TRUE bpm and its half-time
    # partner (within 3%). This is the "do not lose the truth" guarantee.
    assert _has_member_within(r.candidates, true_bpm, 0.03), (
        f"true {true_bpm} not in candidates {[round(c.bpm, 2) for c in r.candidates]}"
    )
    assert _has_member_within(r.candidates, true_bpm / 2.0, 0.03), (
        f"half {true_bpm / 2} not in candidates {[round(c.bpm, 2) for c in r.candidates]}"
    )


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_drill_is_flagged_ambiguous(make_drill, true_bpm):
    # The strong half-time backbeat triggers raw-vs-priored divergence, so the
    # engine must decline to silently force-pick an octave.
    feats = _build(make_drill(true_bpm, duration=24.0))
    r = resolve_tempo(feats, DEFAULT_CONFIG)
    assert r.ambiguous is True
    assert r.ambiguity_reason  # a non-empty human-readable explanation
    # The divergence trigger fires: raw peak and priored peak are an octave apart.
    assert r.raw_best_bpm is not None and r.priored_best_bpm is not None


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_drill_octave_consistent_primary_and_felt(make_drill, true_bpm):
    feats = _build(make_drill(true_bpm, duration=24.0))
    r = resolve_tempo(feats, DEFAULT_CONFIG)

    # The truth must be surfaced as the primary (NOT the wrong-octave half).
    assert abs(r.primary_bpm - true_bpm) / true_bpm <= 0.03, (
        f"primary {r.primary_bpm} is not the true {true_bpm}"
    )

    # Octave-consistency: when a felt tempo is reported, primary is ~2x it.
    if r.felt_bpm is not None:
        assert abs(r.primary_bpm - 2.0 * r.felt_bpm) / r.primary_bpm <= 0.04


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_drill_felt_inside_felt_band(make_drill, true_bpm):
    amb = DEFAULT_CONFIG.ambiguity
    feats = _build(make_drill(true_bpm, duration=24.0))
    r = resolve_tempo(feats, DEFAULT_CONFIG)
    if r.felt_bpm is not None:
        assert amb.felt_min <= r.felt_bpm <= amb.felt_max


# ---------------------------------------------------------------------------
# Relationship bookkeeping invariants.
# ---------------------------------------------------------------------------


def test_every_candidate_has_a_relationship(features_drill_150):
    r = resolve_tempo(features_drill_150, DEFAULT_CONFIG)
    assert r.candidates  # the drill must produce candidates
    for c in r.candidates:
        assert c.relationship is not None
        assert isinstance(c.relationship, Relationship)


def test_exactly_one_self_relationship_is_the_primary(features_drill_150):
    r = resolve_tempo(features_drill_150, DEFAULT_CONFIG)
    selves = [c for c in r.candidates if c.relationship == Relationship.SELF]
    assert len(selves) == 1
    # The SELF candidate carries the primary bpm.
    assert selves[0].bpm == pytest.approx(r.primary_bpm)


def test_candidates_sorted_by_descending_score(features_drill_150):
    r = resolve_tempo(features_drill_150, DEFAULT_CONFIG)
    scores = [c.score for c in r.candidates]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Degenerate signal: must not crash; declares ambiguity.
# ---------------------------------------------------------------------------


def test_silent_signal_resolves_without_crashing():
    silent = np.zeros(22050 * 5, dtype=np.float32)
    feats = _build(as_signal(silent))
    r = resolve_tempo(feats, DEFAULT_CONFIG)
    assert isinstance(r, TempoResult)
    # Nothing to detect -> ambiguous, with an empty (or at most minimal) set.
    assert r.ambiguous is True
    assert len(r.candidates) == 0
    assert r.primary_bpm == pytest.approx(0.0)
    assert r.felt_bpm is None
    # The dict round-trip still works on the degenerate result.
    assert r.to_dict()["ambiguous"] is True
