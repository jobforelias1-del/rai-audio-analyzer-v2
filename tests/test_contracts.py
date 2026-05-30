"""Unit tests for the data contracts (rai_analyzer.contracts).

These cover the *stable* parts of the foundation: relationship classification,
the TermScore defensive clamp, the dict round-trips, the human report, and the
stability of the Relationship enum string values. None of this depends on any
evidence-term implementation, so it is safe to assert exactly.
"""

from __future__ import annotations

import math

import pytest

from rai_analyzer.contracts import (
    AnalysisResult,
    Candidate,
    Relationship,
    TempoResult,
    TermScore,
    classify_relationship,
)


# ---------------------------------------------------------------------------
# classify_relationship
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ratio,expected",
    [
        (1.0, Relationship.SELF),
        (2.0, Relationship.OCTAVE_UP),
        (0.5, Relationship.OCTAVE_DOWN),
        (3.0, Relationship.TRIPLE),
        (1.0 / 3.0, Relationship.THIRD),
        (3.0 / 2.0, Relationship.DOTTED_UP),
        (2.0 / 3.0, Relationship.DOTTED_DOWN),
        (8.0 / 5.0, Relationship.FRACTIONAL),  # ~1.6 tresillo alias
    ],
)
def test_classify_relationship_canonical_ratios(ratio, expected):
    reference = 120.0
    assert classify_relationship(reference * ratio, reference) == expected


def test_classify_relationship_unrelated():
    # 1.78 lands ~11% from the nearest tabled ratio (1.6 / 2.0) -> unrelated.
    # NB: 1.27 is NOT a good "unrelated" probe — the table includes 5/4 (1.25),
    # so 1.27 is within tolerance and correctly classifies as FRACTIONAL.
    assert classify_relationship(120.0 * 1.78, 120.0) == Relationship.UNRELATED


def test_classify_relationship_approx_eight_fifths():
    # ~1.6 hit slightly off-exact should still classify as FRACTIONAL (8/5).
    assert classify_relationship(192.5, 120.0) == Relationship.FRACTIONAL


def test_classify_relationship_respects_tolerance():
    # A ratio 3% above the octave is OCTAVE_UP under default 4% tolerance.
    near_octave = 120.0 * 2.0 * 1.03
    assert classify_relationship(near_octave, 120.0) == Relationship.OCTAVE_UP
    # But with a tight 1% tolerance the same ratio is no longer close enough.
    assert classify_relationship(near_octave, 120.0, tol=0.01) == Relationship.UNRELATED


def test_classify_relationship_nonpositive_inputs():
    assert classify_relationship(0.0, 120.0) == Relationship.UNRELATED
    assert classify_relationship(120.0, 0.0) == Relationship.UNRELATED
    assert classify_relationship(-150.0, 120.0) == Relationship.UNRELATED


# ---------------------------------------------------------------------------
# TermScore defensive clamp
# ---------------------------------------------------------------------------


def test_termscore_clamps_above_one():
    assert TermScore(value=1.5).value == 1.0


def test_termscore_clamps_below_zero():
    assert TermScore(value=-0.2).value == 0.0


def test_termscore_clamps_nan_to_zero():
    assert TermScore(value=float("nan")).value == 0.0


def test_termscore_clamps_inf_to_one():
    # +inf is non-finite -> coerced to 0.0 per the contract (not clamped to 1.0).
    assert TermScore(value=float("inf")).value == 0.0
    assert TermScore(value=float("-inf")).value == 0.0


def test_termscore_in_range_passes_through():
    ts = TermScore(value=0.42, detail={"k": 1})
    assert ts.value == pytest.approx(0.42)
    assert ts.detail == {"k": 1}


# ---------------------------------------------------------------------------
# Candidate.to_dict
# ---------------------------------------------------------------------------


def test_candidate_to_dict_keys_and_values():
    c = Candidate(
        bpm=150.123,
        score=0.87654,
        salience=0.555,
        relationship=Relationship.OCTAVE_UP,
        terms={"prior": TermScore(value=0.3333), "tempogram": TermScore(value=0.9)},
    )
    d = c.to_dict()
    assert set(d.keys()) == {"bpm", "salience", "score", "relationship", "terms"}
    assert d["bpm"] == pytest.approx(150.12)
    assert d["salience"] == pytest.approx(0.555)
    assert d["score"] == pytest.approx(0.8765)
    assert d["relationship"] == "octave_up"
    # terms become plain rounded floats keyed by term name.
    assert d["terms"]["prior"] == pytest.approx(0.333)
    assert d["terms"]["tempogram"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# TempoResult.to_dict
# ---------------------------------------------------------------------------


def _sample_tempo_result(ambiguous: bool = True) -> TempoResult:
    cands = [
        Candidate(bpm=150.0, score=1.2, salience=0.9, relationship=Relationship.SELF),
        Candidate(bpm=75.0, score=1.0, salience=0.8, relationship=Relationship.OCTAVE_DOWN),
    ]
    return TempoResult(
        primary_bpm=150.0,
        felt_bpm=75.0,
        candidates=cands,
        ambiguous=ambiguous,
        ambiguity_reason="raw tempogram peaks at 75, prior favors 150" if ambiguous else None,
        raw_best_bpm=75.0,
        priored_best_bpm=150.0,
    )


def test_temporesult_to_dict_keys():
    d = _sample_tempo_result().to_dict()
    assert set(d.keys()) == {
        "primary_bpm",
        "felt_bpm",
        "ambiguous",
        "ambiguity_reason",
        "raw_best_bpm",
        "priored_best_bpm",
        "candidates",
    }
    assert d["primary_bpm"] == pytest.approx(150.0)
    assert d["felt_bpm"] == pytest.approx(75.0)
    assert d["ambiguous"] is True
    assert d["raw_best_bpm"] == pytest.approx(75.0)
    assert d["priored_best_bpm"] == pytest.approx(150.0)
    assert isinstance(d["candidates"], list) and len(d["candidates"]) == 2
    assert d["candidates"][0]["relationship"] == "self"


def test_temporesult_to_dict_handles_none_felt_and_peaks():
    tr = TempoResult(
        primary_bpm=0.0,
        felt_bpm=None,
        candidates=[],
        ambiguous=True,
        ambiguity_reason="No tempo detected.",
    )
    d = tr.to_dict()
    assert d["felt_bpm"] is None
    assert d["raw_best_bpm"] is None
    assert d["priored_best_bpm"] is None
    assert d["candidates"] == []


# ---------------------------------------------------------------------------
# AnalysisResult.to_report
# ---------------------------------------------------------------------------


def _sample_analysis(ambiguous: bool = True) -> AnalysisResult:
    return AnalysisResult(
        path="/tmp/some/track.wav",
        duration=24.0,
        sr=44100,
        channels=2,
        tempo=_sample_tempo_result(ambiguous=ambiguous),
        loudness=None,
    )


def test_to_report_ambiguous_banner_and_sections():
    report = _sample_analysis(ambiguous=True).to_report()
    assert isinstance(report, str) and report
    assert "TEMPO" in report
    assert "CANDIDATES" in report
    assert "AMBIGUOUS" in report
    # The basename, not the full path, is shown.
    assert "track.wav" in report


def test_to_report_reliable_banner():
    report = _sample_analysis(ambiguous=False).to_report()
    assert "TEMPO" in report
    assert "CANDIDATES" in report
    # Reliable verdict -> the confident banner, not the ambiguous one.
    assert "confident" in report
    assert "AMBIGUOUS" not in report


# ---------------------------------------------------------------------------
# Relationship enum string stability
# ---------------------------------------------------------------------------


def test_relationship_enum_string_values_are_stable():
    assert Relationship.SELF.value == "self"
    assert Relationship.OCTAVE_UP.value == "octave_up"
    assert Relationship.OCTAVE_DOWN.value == "octave_down"
    assert Relationship.TRIPLE.value == "triple"
    assert Relationship.THIRD.value == "third"
    assert Relationship.DOTTED_UP.value == "dotted_up"
    assert Relationship.DOTTED_DOWN.value == "dotted_down"
    assert Relationship.FRACTIONAL.value == "fractional"
    assert Relationship.UNRELATED.value == "unrelated"


def test_relationship_is_str_enum():
    # Relationship subclasses str, so members compare equal to their value.
    assert Relationship.OCTAVE_DOWN == "octave_down"
