"""Tests for beat-phase estimation — ruling R-M2-14.

The calibration pin: synthetic click tracks place their first click exactly
at t=0, so after the calibrated ``ONSET_LAG_SECONDS`` correction the detected
phase must sit within ±10 ms of the grid (circularly, modulo the beat
period). This is now enforced across FIVE transient shapes — 40 ms hat, 5 ms
burst, 2 ms click, 1-sample impulse, synthetic snare — at 90 / 120 / 153.85 /
166.01 BPM, because the previous estimator (a circular energy centroid) was
click-shape-dependent and placed sharp transients ~18-26 ms early. The
leading-edge locator that replaced it tracks the attack START for every
shape.

Confidence is now null-normalized (target sharpness vs the same envelope
re-folded at detuned tempos), so grooveless material — white noise, a
constant envelope — scores near zero even on short files, where raw fold
sharpness used to read 0.5-0.8.

Plus the documented degenerate policy: silence -> confidence 0.0 (never NaN);
garbage bpm -> ValueError.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from rai_analyzer.beatgrid import ONSET_LAG_SECONDS, BeatGrid, estimate_beat_phase
from rai_analyzer.config import ANALYSIS_SR, DEFAULT_CONFIG
from rai_analyzer.synthetic import (
    _normalize,
    as_signal,
    click_track,
    drill_pattern,
    synth_hat,
    synth_snare,
)
from rai_analyzer.tempogram import build_features

_CLICK_BPMS = (90.0, 120.0, 153.85, 166.01)
_SR = ANALYSIS_SR

# Features are the expensive step; build each fixture once per module.
_FEATURES_CACHE: dict[float, object] = {}
_SHAPE_FEATURES_CACHE: dict[tuple[str, float], object] = {}


def _click_features(bpm: float):
    if bpm not in _FEATURES_CACHE:
        _FEATURES_CACHE[bpm] = build_features(
            as_signal(click_track(bpm, duration=18.0)), DEFAULT_CONFIG
        )
    return _FEATURES_CACHE[bpm]


def _circular_error(phase: float, period: float) -> float:
    """Distance from phase to the true click grid (t=0, mod period)."""
    return min(phase, period - phase)


# ---------------------------------------------------------------------------
# Multi-shape click fixtures — the shape-robustness pin (root cause of DEFECT 1)
# ---------------------------------------------------------------------------


def _click_shape(name: str) -> np.ndarray:
    """One transient of a given shape (all begin at sample 0)."""
    if name == "hat40ms":  # 40 ms noise burst w/ 20 ms decay (the old fixture)
        return synth_hat(_SR, dur=0.04, rng=np.random.default_rng(0))
    if name == "burst5ms":
        return np.random.default_rng(11).standard_normal(int(0.005 * _SR)).astype(np.float32)
    if name == "click2ms":
        return np.random.default_rng(7).standard_normal(int(0.002 * _SR)).astype(np.float32)
    if name == "impulse1smp":
        return np.array([1.0], dtype=np.float32)
    if name == "snare":
        return synth_snare(_SR, rng=np.random.default_rng(3))
    raise ValueError(name)


def _shape_click_track(name: str, bpm: float, duration: float = 18.0) -> np.ndarray:
    """A metronome of ``_click_shape(name)`` with the first click at t=0."""
    click = _click_shape(name)
    n = int(duration * _SR)
    out = np.zeros(n, dtype=np.float32)
    beat = 60.0 / bpm
    t = 0.0
    while t < duration:
        idx = int(t * _SR)
        end = min(idx + click.size, n)
        if idx < n:
            out[idx:end] += click[: end - idx]
        t += beat
    return _normalize(out)


def _shape_features(name: str, bpm: float):
    key = (name, bpm)
    if key not in _SHAPE_FEATURES_CACHE:
        _SHAPE_FEATURES_CACHE[key] = build_features(
            as_signal(_shape_click_track(name, bpm)), DEFAULT_CONFIG
        )
    return _SHAPE_FEATURES_CACHE[key]


_CLICK_SHAPES = ("hat40ms", "burst5ms", "click2ms", "impulse1smp", "snare")


def _constant_envelope_features(duration: float = 8.0):
    """Features whose band envelopes are perfectly flat (no groove at all)."""
    base = build_features(
        as_signal(np.zeros(int(_SR * duration), dtype=np.float32)), DEFAULT_CONFIG
    )
    flat = np.ones(base.bands.times.size, dtype=np.float64)
    bands = dataclasses.replace(base.bands, low=flat, mid=flat, high=flat, full=flat)
    return dataclasses.replace(base, bands=bands)


def _noise_features(duration: float, seed: int):
    rng = np.random.default_rng(seed)
    y = (0.5 * rng.standard_normal(int(duration * _SR))).astype(np.float32)
    return build_features(as_signal(y), DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# The ±10 ms calibration pin (R-M2-14) — every click shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bpm", _CLICK_BPMS)
def test_click_track_phase_within_10ms(bpm):
    grid = estimate_beat_phase(_click_features(bpm), bpm)
    period = 60.0 / bpm
    assert grid.period_seconds == pytest.approx(period, rel=1e-12)
    assert 0.0 <= grid.phase_seconds < period
    assert _circular_error(grid.phase_seconds, period) <= 0.010
    # A clean metronome must fold sharply.
    assert grid.confidence > 0.5


@pytest.mark.parametrize("shape", _CLICK_SHAPES)
@pytest.mark.parametrize("bpm", _CLICK_BPMS)
def test_phase_within_10ms_for_every_click_shape(shape, bpm):
    # Shape-robustness pin (DEFECT 1 root cause): the leading-edge locator
    # tracks the attack START, so a 1-sample impulse and a 40 ms hat land in
    # the same place. The old energy-centroid put sharp transients 18-26 ms
    # early — outside this budget.
    grid = estimate_beat_phase(_shape_features(shape, bpm), bpm)
    period = 60.0 / bpm
    assert 0.0 <= grid.phase_seconds < period
    assert _circular_error(grid.phase_seconds, period) <= 0.010
    assert 0.0 <= grid.confidence <= 1.0
    assert not math.isnan(grid.confidence)


@pytest.mark.parametrize("bpm", [120.0, 166.01])
def test_phase_tracks_a_shifted_grid(bpm):
    # Shift the whole click track by a known offset: the detected phase must
    # move with it (still within the ±10 ms budget).
    shift_s = 0.130
    sr = 22050
    y = click_track(bpm, duration=18.0)
    shifted = np.concatenate([np.zeros(int(shift_s * sr), dtype=np.float32), y])
    feats = build_features(as_signal(shifted), DEFAULT_CONFIG)
    grid = estimate_beat_phase(feats, bpm)
    period = 60.0 / bpm
    err = abs(grid.phase_seconds - (shift_s % period))
    err = min(err, period - err)
    assert err <= 0.010


def test_beats_per_bar_one_agrees_with_four():
    bpm = 120.0
    g4 = estimate_beat_phase(_click_features(bpm), bpm, beats_per_bar=4)
    g1 = estimate_beat_phase(_click_features(bpm), bpm, beats_per_bar=1)
    period = 60.0 / bpm
    d = abs(g4.phase_seconds - g1.phase_seconds)
    assert min(d, period - d) <= 0.010


def test_drill_pattern_locks_with_confidence():
    # Content sanity (not a calibration pin): a synthetic drill groove at its
    # notated tempo folds sharply and yields a phase inside one period.
    feats = build_features(as_signal(drill_pattern(150.0, duration=24.0)), DEFAULT_CONFIG)
    grid = estimate_beat_phase(feats, 150.0)
    assert 0.0 <= grid.phase_seconds < grid.period_seconds
    assert grid.confidence > 0.5


# ---------------------------------------------------------------------------
# Confidence: null-normalized, so grooveless material scores low (DEFECT 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bpm", _CLICK_BPMS)
def test_clean_click_confidence_high(bpm):
    grid = estimate_beat_phase(_click_features(bpm), bpm)
    assert grid.confidence > 0.6


@pytest.mark.parametrize("duration", [4.0, 8.0])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
@pytest.mark.parametrize("bpm", [120.0, 97.3])
def test_white_noise_confidence_low(duration, seed, bpm):
    # Grooveless: raw fold sharpness read 0.5-0.8 here (max-over-phase +
    # bin-count aliasing on few frames). The detuned null cancels that bias.
    grid = estimate_beat_phase(_noise_features(duration, seed), bpm)
    assert 0.0 <= grid.confidence <= 1.0
    assert not math.isnan(grid.confidence)
    assert grid.confidence < 0.35


@pytest.mark.parametrize("bpm", [120.0, 97.3])
def test_constant_envelope_confidence_low(bpm):
    grid = estimate_beat_phase(_constant_envelope_features(), bpm)
    assert 0.0 <= grid.confidence < 0.2
    assert not math.isnan(grid.confidence)


# ---------------------------------------------------------------------------
# Degenerate policy (documented choices)
# ---------------------------------------------------------------------------


def test_silence_confidence_zero_never_nan():
    feats = build_features(
        as_signal(np.zeros(22050 * 10, dtype=np.float32)), DEFAULT_CONFIG
    )
    grid = estimate_beat_phase(feats, 120.0)
    assert grid.confidence == 0.0
    assert grid.phase_seconds == 0.0
    assert grid.period_seconds == pytest.approx(0.5)
    assert not math.isnan(grid.phase_seconds)
    assert not math.isnan(grid.confidence)


@pytest.mark.parametrize("bad_bpm", [0.0, -5.0, float("nan"), float("inf")])
def test_degenerate_bpm_raises_value_error(bad_bpm):
    # Documented choice per the brief: a resolved tempo is the precondition,
    # so a garbage bpm is a ValueError, not a confidence-0 result.
    with pytest.raises(ValueError):
        estimate_beat_phase(_click_features(120.0), bad_bpm)


def test_degenerate_beats_per_bar_raises_value_error():
    with pytest.raises(ValueError):
        estimate_beat_phase(_click_features(120.0), 120.0, beats_per_bar=0)


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def test_beatgrid_is_frozen_and_bounded():
    grid = estimate_beat_phase(_click_features(120.0), 120.0)
    assert isinstance(grid, BeatGrid)
    assert 0.0 <= grid.confidence <= 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        grid.confidence = 1.0  # type: ignore[misc]


def test_lag_constant_is_a_small_residual_bias():
    # The leading-edge locator's residual bias, calibrated on 1-sample-impulse
    # click tracks, is near zero — librosa's centered STFT frames smear energy
    # symmetrically about each transient, so the half-rise crossing sits
    # almost on the onset (see beatgrid docstring). This REPLACES the old
    # 0.0433 s centroid constant (which was an estimator artifact: ~17.5 ms
    # flux-chain response + ~26 ms energy-centroid pull of the 40 ms fixture's
    # decay tail), so the pinned magnitude legitimately changed.
    assert abs(ONSET_LAG_SECONDS) < 0.010
