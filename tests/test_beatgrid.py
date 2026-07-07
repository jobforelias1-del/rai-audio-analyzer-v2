"""Tests for beat-phase estimation — ruling R-M2-14.

The calibration pin: synthetic click tracks place their first click exactly
at t=0, so after the calibrated ``ONSET_LAG_SECONDS`` correction the detected
phase must sit within ±10 ms of the grid (circularly, modulo the beat
period) at 90 / 120 / 153.85 / 166.01 BPM. Plus the documented degenerate
policy: silence -> confidence 0.0 (never NaN); garbage bpm -> ValueError.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from rai_analyzer.beatgrid import ONSET_LAG_SECONDS, BeatGrid, estimate_beat_phase
from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.synthetic import as_signal, click_track, drill_pattern
from rai_analyzer.tempogram import build_features

_CLICK_BPMS = (90.0, 120.0, 153.85, 166.01)

# Features are the expensive step; build each click track once per module.
_FEATURES_CACHE: dict[float, object] = {}


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
# The ±10 ms calibration pin (R-M2-14)
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


def test_lag_constant_is_calibrated_and_positive():
    # The spectral-flux envelope peaks AFTER the transient: the calibrated
    # constant must be a small positive latency (see beatgrid docstring for
    # the measured 42.6–44.5 ms window it centers).
    assert 0.0 < ONSET_LAG_SECONDS < 0.1
