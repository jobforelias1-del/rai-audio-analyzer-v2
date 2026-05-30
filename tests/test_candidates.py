"""Unit tests for rai_analyzer.candidates.generate_candidates.

Candidate generation's only job is to guarantee the truth is *present* in a
de-duplicated, range-filtered hypothesis set (scoring decides between them).
For a synthetic drill at 150 BPM (whose felt/half-time pulse is 75) we check:

* both octaves surface (a candidate within 3% of 150 AND one within 3% of 75),
* every candidate lies within the configured [bpm_min, bpm_max] band,
* no two candidates sit within ``dedup_tol`` of each other, and
* the set is not a single multiplier ladder off one base — the independent
  octave pair is genuinely present.
"""

from __future__ import annotations

import numpy as np

from rai_analyzer.candidates import generate_candidates


def _within(cands, target, rel=0.03) -> bool:
    return any(abs(c - target) / target <= rel for c in cands)


def test_both_octaves_surface(features_drill_150, cfg):
    """A 150 BPM drill yields a candidate near 150 AND one near its half (75)."""
    cands = generate_candidates(features_drill_150, cfg)
    assert cands, "expected a non-empty candidate set"
    assert _within(cands, 150.0, 0.03), f"no candidate within 3% of 150: {cands}"
    assert _within(cands, 75.0, 0.03), f"no candidate within 3% of 75: {cands}"


def test_all_candidates_in_configured_range(features_drill_150, cfg):
    """Every candidate respects [candidates.bpm_min, candidates.bpm_max]."""
    cp = cfg.candidates
    cands = generate_candidates(features_drill_150, cfg)
    assert cands
    for c in cands:
        assert cp.bpm_min <= c <= cp.bpm_max, f"{c} outside [{cp.bpm_min}, {cp.bpm_max}]"


def test_candidates_are_deduplicated(features_drill_150, cfg):
    """No two returned candidates fall within dedup_tol (relative) of each other."""
    cp = cfg.candidates
    cands = sorted(generate_candidates(features_drill_150, cfg))
    assert cands
    for a, b in zip(cands, cands[1:]):
        rel_gap = abs(b - a) / min(a, b)
        assert rel_gap > cp.dedup_tol, f"{a} and {b} are within dedup_tol={cp.dedup_tol}"


def test_independent_octave_pair_present(features_drill_150, cfg):
    """The set surfaces independent peaks, not just one multiplier ladder.

    The injected octave pair (~75 and ~150) is present and the two are a clean
    2:1 apart, which a single multiplier family off one mis-locked base could
    not by itself guarantee — confirming independent peaks are seeded in.
    """
    cands = generate_candidates(features_drill_150, cfg)
    assert cands

    near_75 = [c for c in cands if abs(c - 75.0) / 75.0 <= 0.03]
    near_150 = [c for c in cands if abs(c - 150.0) / 150.0 <= 0.03]
    assert near_75 and near_150

    # The two representatives are an octave apart (ratio ~2), i.e. a real
    # metrical pair was surfaced rather than collapsed away.
    ratio = max(near_150[0], near_75[0]) / min(near_150[0], near_75[0])
    assert abs(ratio - 2.0) <= 0.06

    # And there is genuine spread: not every candidate is a multiple of a single
    # base (the set spans more than one octave region).
    assert max(cands) / min(cands) >= 1.5


def test_no_candidates_when_curve_is_flat(cfg):
    """A flat (no-peak) tempo curve produces an empty candidate set."""
    from rai_analyzer.contracts import Features, TempoCurve, BandEnvelopes

    grid = np.linspace(40.0, 240.0, 801)
    zeros = np.zeros_like(grid)
    flat = TempoCurve(bpms=grid, salience=zeros, acf=zeros.copy(), dft=zeros.copy())
    t = np.linspace(0.0, 1.0, 16)
    bands = BandEnvelopes(
        sr=22050,
        hop_length=512,
        times=t,
        low=np.zeros_like(t),
        mid=np.zeros_like(t),
        high=np.zeros_like(t),
        full=np.zeros_like(t),
    )
    feats = Features(
        sr=22050,
        hop_length=512,
        duration=1.0,
        bands=bands,
        tempo_curve=flat,
        high_curve=flat,
    )
    assert generate_candidates(feats, cfg) == []
