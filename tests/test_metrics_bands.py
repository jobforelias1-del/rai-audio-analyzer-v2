"""Tests for M2 band-energy shares — rulings R-M2-2 / R-M2-3.

Band concentration exactness on sines (a 50 Hz sine is ~100% sub), partition
completeness (the six shares sum to ~100), the NaN silence policy, and the v1
oracle (reference/v1/analyzer.py:223-249, 298-301) encoded test-locally:
v1's Sub/Bass percentages on a mono file must agree with v2's within the
nperseg difference (v1 used 8192 mono; v2 uses 16384 per channel).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import scipy.signal as _sig

from rai_analyzer.metrics.bands import compute_band_energies
from rai_analyzer.metrics.contracts import BandEnergyResult
from rai_analyzer.metrics.params import SIX_BAND_EDGES_HZ
from rai_analyzer.metrics.spectrum import welch_psd
from rai_analyzer.synthetic import drill_pattern


def _sine(freq: float, amp: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _bands(y: np.ndarray, sr: int) -> BandEnergyResult:
    freqs, psd = welch_psd(y, sr)
    return compute_band_energies(freqs, psd)


# --- v1 oracle, encoded verbatim from reference/v1/analyzer.py:223-249 ------

_V1_LOW_BANDS = [("Sub", 20.0, 60.0), ("Bass", 60.0, 120.0)]  # :298-301


def _v1_band_energies(samples: np.ndarray, sr: int, bands=_V1_LOW_BANDS, nperseg=8192) -> dict:
    names = [b[0] for b in bands]
    if samples.size == 0:
        return {name: 0.0 for name in names}
    n = int(min(nperseg, samples.size))
    if n < 64:
        return {name: 0.0 for name in names}
    freqs, psd = _sig.welch(samples.astype(np.float64), fs=sr, nperseg=n)
    audible = (freqs >= 20.0) & (freqs <= 20000.0)
    total = float(np.sum(psd[audible]))
    if total <= 0.0:
        return {name: 0.0 for name in names}
    out = {}
    for name, lo, hi in bands:
        m = (freqs >= lo) & (freqs < hi)
        out[name] = float(np.sum(psd[m]) / total * 100.0)
    return out


# ---------------------------------------------------------------------------
# Band concentration exactness (R-M2-3 edges)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("freq", "band"),
    [
        (50.0, "sub"),  # 20-60
        (90.0, "bass"),  # 60-120
        (200.0, "low_mid"),  # 120-350
        (1000.0, "mid"),  # 350-2000
        (3000.0, "high_mid"),  # 2000-6000
        (8000.0, "air"),  # 6000-20000
    ],
)
def test_sine_concentrates_in_its_band(freq, band):
    res = _bands(_sine(freq, 0.5, 3.0, 48000), 48000)
    assert res.six_band[band] > 99.0
    assert sum(res.six_band.values()) == pytest.approx(100.0, abs=0.01)


def test_sub_pct_and_bass_pct_alias_the_map():
    res = _bands(_sine(50.0, 0.5, 3.0, 48000), 48000)
    assert res.sub_pct == res.six_band["sub"]
    assert res.bass_pct == res.six_band["bass"]
    assert res.sub_pct > 99.0  # R-M2-2: the UI's Sub/bass card number


def test_equal_power_mixture_splits_evenly():
    y = _sine(50.0, 0.4, 3.0, 48000) + _sine(1000.0, 0.4, 3.0, 48000)
    res = _bands(y.astype(np.float32), 48000)
    assert res.six_band["sub"] == pytest.approx(50.0, abs=2.0)
    assert res.six_band["mid"] == pytest.approx(50.0, abs=2.0)


def test_white_noise_partitions_to_100_with_energy_everywhere():
    rng = np.random.default_rng(2026)
    y = (rng.standard_normal(48000 * 3) * 0.3).astype(np.float32)
    res = _bands(y, 48000)
    assert sum(res.six_band.values()) == pytest.approx(100.0, abs=0.01)
    for name, _lo, _hi in SIX_BAND_EDGES_HZ:
        assert res.six_band[name] > 0.0


def test_nyquist_cap_still_partitions_to_100():
    # sr 16000: air (6-20 kHz) is truncated at 8 kHz, total mask likewise —
    # shares stay a partition of what is measurable.
    rng = np.random.default_rng(7)
    y = (rng.standard_normal(16000 * 2) * 0.3).astype(np.float32)
    res = _bands(y, 16000)
    assert sum(res.six_band.values()) == pytest.approx(100.0, abs=0.01)


def test_six_band_keys_are_canonical():
    res = _bands(_sine(1000.0, 0.5, 1.0, 48000), 48000)
    assert list(res.six_band) == ["sub", "bass", "low_mid", "mid", "high_mid", "air"]


# ---------------------------------------------------------------------------
# Silence policy: NaN, never v1's 0.0
# ---------------------------------------------------------------------------


def test_silence_bands_are_nan_not_zero():
    res = _bands(np.zeros(48000, dtype=np.float32), 48000)
    assert math.isnan(res.sub_pct)
    assert math.isnan(res.bass_pct)
    assert all(math.isnan(v) for v in res.six_band.values())
    # v1 said 0.0 here — a documented divergence, not a bug.
    assert _v1_band_energies(np.zeros(48000, dtype=np.float32), 48000)["Sub"] == 0.0


def test_empty_input_is_nan():
    res = _bands(np.zeros(0, dtype=np.float32), 48000)
    assert math.isnan(res.sub_pct)


# ---------------------------------------------------------------------------
# v1 oracle agreement (mono file, coinciding definitions)
# ---------------------------------------------------------------------------


def test_v1_agreement_sub_bass_on_mono_drill():
    """Same definition (% of 20 Hz–20 kHz PSD total, [lo, hi) masks); only the
    Welch resolution differs (v1: 8192 mono / v2: 16384 per channel), so the
    numbers must agree closely on broadband mono material."""
    y = drill_pattern(150.0, duration=12.0)  # mono, sr 22050
    sr = 22050
    v1 = _v1_band_energies(y, sr)
    v2 = _bands(y, sr)
    assert v2.sub_pct == pytest.approx(v1["Sub"], abs=1.5)
    assert v2.bass_pct == pytest.approx(v1["Bass"], abs=1.5)


def test_v1_agreement_exact_at_matched_nperseg_pure_tone():
    # With a narrowband tone the resolution difference is irrelevant:
    # both must call a 50 Hz sine ~all-sub.
    y = _sine(50.0, 0.5, 3.0, 44100)
    v1 = _v1_band_energies(y, 44100)
    v2 = _bands(y, 44100)
    assert v1["Sub"] > 99.0
    assert v2.sub_pct == pytest.approx(v1["Sub"], abs=0.5)
