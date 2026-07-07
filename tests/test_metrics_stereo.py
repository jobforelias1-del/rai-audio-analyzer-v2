"""Tests for M2 stereo width + correlation — ruling R-M2-4.

Synthetic exactness (identical channels -> width 0 / corr 1; anti-phase ->
width 100 / corr -1; uncorrelated noise -> width ~50 / corr ~0), the mono and
silence policies, and the v1 oracle (reference/v1/analyzer.py:252-287): v1's
ratio is v2's width/100, so v1's classification words must be reproducible
from v2's number.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rai_analyzer.metrics.contracts import StereoResult
from rai_analyzer.metrics.stereo import compute_stereo


def _sine(freq: float, amp: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


# --- v1 oracle, encoded verbatim from reference/v1/analyzer.py:252-287 ------


def _v1_stereo_width_word(raw_channels) -> str:
    if raw_channels is None or raw_channels.ndim < 2 or raw_channels.shape[1] < 2:
        return "Mono"
    L = raw_channels[:, 0].astype(np.float64)
    R = raw_channels[:, 1].astype(np.float64)
    mid = 0.5 * (L + R)
    side = 0.5 * (L - R)
    mid_e = float(np.sum(mid * mid))
    side_e = float(np.sum(side * side))
    if mid_e + side_e <= 0.0:
        return "Mono"
    ratio = side_e / (mid_e + side_e)
    if ratio < 0.02:
        return "Mono"
    if ratio < 0.10:
        return "Narrow"
    if ratio < 0.30:
        return "Balanced"
    return "Wide"


def _word_from_v2_width(res: StereoResult) -> str:
    """v1's classification thresholds applied to v2's width (ratio*100)."""
    if not math.isfinite(res.width_pct):
        return "Mono"
    if res.width_pct < 2.0:
        return "Mono"
    if res.width_pct < 10.0:
        return "Narrow"
    if res.width_pct < 30.0:
        return "Balanced"
    return "Wide"


# ---------------------------------------------------------------------------
# Synthetic exactness
# ---------------------------------------------------------------------------


def test_identical_channels_width_zero_corr_one():
    mono = _sine(1000.0, 0.5, 2.0, 48000)
    res = compute_stereo(np.stack([mono, mono], axis=1))
    assert res.width_pct == pytest.approx(0.0, abs=1e-9)
    assert res.correlation == pytest.approx(1.0, abs=1e-9)


def test_antiphase_width_100_corr_minus_one():
    mono = _sine(1000.0, 0.5, 2.0, 48000)
    res = compute_stereo(np.stack([mono, -mono], axis=1))
    assert res.width_pct == pytest.approx(100.0, abs=1e-9)
    assert res.correlation == pytest.approx(-1.0, abs=1e-9)


def test_uncorrelated_noise_width_50_corr_0():
    rng = np.random.default_rng(1770)
    left = (rng.standard_normal(48000 * 2) * 0.3).astype(np.float32)
    right = (rng.standard_normal(48000 * 2) * 0.3).astype(np.float32)
    res = compute_stereo(np.stack([left, right], axis=1))
    assert res.width_pct == pytest.approx(50.0, abs=3.0)
    assert res.correlation == pytest.approx(0.0, abs=0.05)


def test_one_silent_channel_width_50_corr_none():
    # L = tone, R = digital zero: mid == side energy exactly -> width 50;
    # Pearson r is undefined against a zero-variance channel.
    left = _sine(1000.0, 0.5, 2.0, 48000)
    right = np.zeros_like(left)
    res = compute_stereo(np.stack([left, right], axis=1))
    assert res.width_pct == pytest.approx(50.0, abs=1e-9)
    assert res.correlation is None


def test_width_is_gain_invariant():
    rng = np.random.default_rng(9)
    left = (rng.standard_normal(48000) * 0.3).astype(np.float32)
    right = (rng.standard_normal(48000) * 0.3).astype(np.float32)
    stereo = np.stack([left, right], axis=1)
    a = compute_stereo(stereo)
    b = compute_stereo(stereo * 0.1)
    assert b.width_pct == pytest.approx(a.width_pct, abs=1e-6)


# ---------------------------------------------------------------------------
# Mono / silence / channel-count policies
# ---------------------------------------------------------------------------


def test_mono_file_width_zero_is_a_measurement_corr_none():
    res = compute_stereo(_sine(1000.0, 0.5, 2.0, 48000))
    assert res.width_pct == 0.0  # exactly: the demo's "0 %" (R-M2-4)
    assert res.correlation is None


def test_silent_stereo_width_nan_corr_none():
    res = compute_stereo(np.zeros((48000, 2), dtype=np.float32))
    assert math.isnan(res.width_pct)
    assert res.correlation is None


def test_empty_input_never_raises():
    for shape in ((0,), (0, 2)):
        res = compute_stereo(np.zeros(shape, dtype=np.float32))
        assert isinstance(res, StereoResult)


def test_more_than_two_channels_uses_first_two():
    mono = _sine(1000.0, 0.5, 2.0, 48000)
    loud_third = _sine(50.0, 0.9, 2.0, 48000)
    res = compute_stereo(np.stack([mono, mono, loud_third], axis=1))
    assert res.width_pct == pytest.approx(0.0, abs=1e-9)
    assert res.correlation == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# v1 oracle: same ratio, so v1's words are reproducible from v2's number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side_gain", [0.0, 0.05, 0.2, 0.5, 1.0])
def test_v1_word_matches_v2_width(side_gain):
    rng = np.random.default_rng(int(side_gain * 100) + 1)
    common = (rng.standard_normal(48000) * 0.3).astype(np.float32)
    diff = (rng.standard_normal(48000) * 0.3 * side_gain).astype(np.float32)
    stereo = np.stack([common + diff, common - diff], axis=1)
    assert _word_from_v2_width(compute_stereo(stereo)) == _v1_stereo_width_word(stereo)


def test_v1_word_matches_v2_on_mono_and_silence():
    mono = _sine(440.0, 0.5, 1.0, 48000)
    assert _word_from_v2_width(compute_stereo(mono)) == "Mono"
    sil = np.zeros((48000, 2), dtype=np.float32)
    assert _word_from_v2_width(compute_stereo(sil)) == _v1_stereo_width_word(sil) == "Mono"
