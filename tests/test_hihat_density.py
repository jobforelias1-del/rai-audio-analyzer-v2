"""Tests for the hi-hat subdivision-density evidence term.

The whole point of this term is to break tempo-octave ambiguity in drill/trap:
a busy high-band stream that only parses as constant 32nds/64ths under the
slower candidate is evidence that the candidate is too slow and should be
DOUBLED. These tests pin that behaviour down on synthetic signals with a known
tatum, plus the robustness guarantees from the contract:

* the term favours the correct (doubled) octave for straight-16th drill hats;
* a sparse click track yields a finite, non-extreme score and does not crash;
* silence / an empty high band returns a neutral-low, finite score (never NaN);
* the sustained-density guard prevents a one-section roll/fill from being
  treated as evidence to double.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rai_analyzer.config import DEFAULT_CONFIG as C
from rai_analyzer.evidence.hihat_density import score_hihat_density
from rai_analyzer.synthetic import (
    _normalize,
    _place,
    as_signal,
    click_track,
    drill_pattern,
    synth_hat,
    synth_kick,
    synth_snare,
)
from rai_analyzer.tempogram import build_features

# BPMs at which the correct-octave preference must hold (the spec's self-check
# set: straight 16ths at the full tempo, constant 32nds at the half tempo).
_DRILL_BPMS = (150.0, 154.0, 166.0)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _features_for_drill(bpm: float, duration: float = 24.0):
    return build_features(as_signal(drill_pattern(bpm, duration=duration)), C)


def _partial_hat_drill(hat_fraction: float, bpm: float = 150.0, duration: float = 24.0):
    """Drill beat whose straight-16th hats are present only in the first
    ``hat_fraction`` of the track (a transient roll), with kick+snare throughout.

    Used to exercise the sustained-density guard: the fast subdivision exists but
    is NOT sustained, so it must not be taken as evidence to double the tempo.
    """
    from rai_analyzer.config import ANALYSIS_SR

    sr = ANALYSIS_SR
    rng = np.random.default_rng(0)
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float32)
    kick = synth_kick(sr)
    snare = synth_snare(sr, rng=rng)
    hat = synth_hat(sr, rng=rng)
    sixteenth = 60.0 / bpm / 4.0
    bar = 16 * sixteenth
    n_bars = int(duration / bar) + 1
    for b in range(n_bars):
        bar_t = b * bar
        for s in (0, 3, 6, 10):
            _place(out, kick, int((bar_t + s * sixteenth) * sr), rng.uniform(0.9, 1.0))
        for s in (4, 12):
            _place(out, snare, int((bar_t + s * sixteenth) * sr), 1.4 * rng.uniform(0.9, 1.0))
        if bar_t < duration * hat_fraction:  # hats only in the first slice
            for s in range(16):
                _place(out, hat, int((bar_t + s * sixteenth) * sr), rng.uniform(0.3, 0.55))
    out += 0.002 * rng.standard_normal(n).astype(np.float32)
    return _normalize(out)


# --------------------------------------------------------------------------- #
# Core contract: favour the correct (doubled) octave
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bpm", _DRILL_BPMS)
def test_prefers_full_over_half_time(bpm):
    """The straight-16th hat stream must score the notated tempo strictly above
    the half-time tempo (the spec's primary self-verification)."""
    feats = _features_for_drill(bpm)
    full = score_hihat_density(bpm, feats, C.hihat)
    half = score_hihat_density(bpm / 2.0, feats, C.hihat)
    assert full.value > half.value, (
        f"bpm={bpm}: full {full.value:.4f} !> half {half.value:.4f}"
    )


@pytest.mark.parametrize("bpm", _DRILL_BPMS)
def test_full_above_half_threshold_half_below(bpm):
    """Sharper than > : the correct octave clears 0.5 while the half-time octave
    falls below it, so the term is a decisive vote, not a coin-flip."""
    feats = _features_for_drill(bpm)
    full = score_hihat_density(bpm, feats, C.hihat).value
    half = score_hihat_density(bpm / 2.0, feats, C.hihat).value
    assert half < 0.5 < full, f"bpm={bpm}: expected half<0.5<full, got half={half:.4f} full={full:.4f}"


@pytest.mark.parametrize("bpm", _DRILL_BPMS)
def test_detail_fields_present_and_sane(bpm):
    """The contract requires detail to carry tatum_bpm / ratio / active_fraction.
    Check they exist, are finite, and report a dense, sustained, ~4x stream."""
    feats = _features_for_drill(bpm)
    ts = score_hihat_density(bpm, feats, C.hihat)
    for key in ("tatum_bpm", "ratio", "active_fraction"):
        assert key in ts.detail, f"missing detail[{key!r}]"
    assert ts.detail["tatum_bpm"] is not None and math.isfinite(ts.detail["tatum_bpm"])
    assert math.isfinite(ts.detail["ratio"])
    # Straight 16ths -> tatum ~ 4x beat (allow a wide band: the onset rate
    # slightly undercounts at the envelope's frame resolution).
    assert 3.2 < ts.detail["ratio"] < 4.6, f"ratio {ts.detail['ratio']} not near 4 (16ths)"
    # Sustained across the whole track.
    assert ts.detail["active_fraction"] >= C.hihat.min_active_sections


@pytest.mark.parametrize("bpm", _DRILL_BPMS)
def test_half_time_is_implausibly_fine(bpm):
    """At the half-time candidate the hats parse as ~32nds (ratio >= the
    implausible threshold) and the term scores it low — the 'should be doubled'
    signal."""
    feats = _features_for_drill(bpm)
    half = score_hihat_density(bpm / 2.0, feats, C.hihat)
    assert half.detail["ratio"] >= C.hihat.implausible_ratio
    assert half.value < 0.4


# --------------------------------------------------------------------------- #
# Output validity / clamping
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bpm", [37.5, 75.0, 150.0, 200.0, 300.0])
def test_output_in_unit_interval_and_finite(bpm):
    """Every score is a finite value in [0, 1] regardless of candidate."""
    feats = _features_for_drill(150.0)
    ts = score_hihat_density(bpm, feats, C.hihat)
    assert math.isfinite(ts.value)
    assert 0.0 <= ts.value <= 1.0


def test_non_positive_bpm_is_neutral_not_crash():
    """A zero / negative candidate must not raise and must return a valid score."""
    feats = _features_for_drill(150.0)
    for bad in (0.0, -10.0):
        ts = score_hihat_density(bad, feats, C.hihat)
        assert math.isfinite(ts.value)
        assert 0.0 <= ts.value <= 1.0


# --------------------------------------------------------------------------- #
# Robustness: silence, empty high band, sparse click track
# --------------------------------------------------------------------------- #


def test_silence_returns_neutral_low_and_does_not_crash():
    """Pure silence has no high-band evidence: a finite, neutral-low score."""
    from rai_analyzer.config import ANALYSIS_SR

    silence = np.zeros(int(18 * ANALYSIS_SR), dtype=np.float32)
    feats = build_features(as_signal(silence), C)
    ts = score_hihat_density(120.0, feats, C.hihat)
    assert math.isfinite(ts.value)
    assert 0.0 <= ts.value < 0.5  # neutral-low, never a confident vote
    assert ts.detail.get("tatum_bpm") is None


def test_empty_high_band_array_is_neutral():
    """If the high band is all-zero (silent stream) the term is neutral-low and
    does not divide by zero or emit NaN."""
    feats = _features_for_drill(150.0)
    # Build a sibling Features whose high band is zeroed, reusing everything else.
    import dataclasses

    zero_high = np.zeros_like(feats.bands.high)
    bands = dataclasses.replace(feats.bands, high=zero_high)
    feats0 = dataclasses.replace(feats, bands=bands)
    ts = score_hihat_density(150.0, feats0, C.hihat)
    assert math.isfinite(ts.value)
    assert 0.0 <= ts.value < 0.5


@pytest.mark.parametrize("cand", [120.0, 60.0, 240.0])
def test_click_track_non_extreme_and_finite(cand):
    """A plain metronome (sparse high band, one click per beat) must not crash
    and must not produce an extreme verdict — there is no fast subdivision to
    argue an octave from."""
    feats = build_features(as_signal(click_track(120.0, duration=18.0)), C)
    ts = score_hihat_density(cand, feats, C.hihat)
    assert math.isfinite(ts.value)
    assert 0.0 <= ts.value <= 1.0
    # "Non-extreme": never pinned to the rails.
    assert 0.02 < ts.value < 0.98


def test_click_does_not_get_doubling_evidence():
    """For a click, the beat-rate and half-rate candidates should land close
    together (no strong push toward either octave), unlike a drill beat."""
    feats = build_features(as_signal(click_track(120.0, duration=18.0)), C)
    at_beat = score_hihat_density(120.0, feats, C.hihat).value
    at_half = score_hihat_density(60.0, feats, C.hihat).value
    # Both parse as clean musical ratios (~1 and ~2); the term must not strongly
    # prefer doubling the way it does for a real 16th-note hat stream.
    assert abs(at_beat - at_half) < 0.25


# --------------------------------------------------------------------------- #
# Sustained-density guard
# --------------------------------------------------------------------------- #


def test_transient_burst_does_not_flip_octave_verdict():
    """A drill whose fast hats appear in only one section is a transient roll,
    not a sustained subdivision. The guard must keep that burst from delivering
    the confident 'double it' verdict a sustained hat stream produces."""
    burst_feats = build_features(as_signal(_partial_hat_drill(hat_fraction=1 / 6)), C)
    full_feats = _features_for_drill(150.0)

    burst_full = score_hihat_density(150.0, burst_feats, C.hihat)
    burst_half = score_hihat_density(75.0, burst_feats, C.hihat)
    drill_full = score_hihat_density(150.0, full_feats, C.hihat).value
    drill_half = score_hihat_density(75.0, full_feats, C.hihat).value

    burst_margin = burst_full.value - burst_half.value
    drill_margin = drill_full - drill_half

    # The sustained drill must show a large pro-doubling margin...
    assert drill_margin > 0.3
    # ...while the transient burst's margin is heavily suppressed (the guard
    # gates the doubling evidence): well under half the sustained margin.
    assert burst_margin < 0.5 * drill_margin
    # And the guard's own bookkeeping reflects "not sustained".
    assert burst_full.detail["active_fraction"] < C.hihat.min_active_sections
    assert burst_full.detail["sustained"] is False


def test_sustained_drill_is_marked_sustained():
    """The positive control for the guard: a full-length straight-16th hat
    stream is active in (nearly) every section."""
    feats = _features_for_drill(150.0)
    ts = score_hihat_density(150.0, feats, C.hihat)
    assert ts.detail["sustained"] is True
    assert ts.detail["active_fraction"] >= C.hihat.min_active_sections
