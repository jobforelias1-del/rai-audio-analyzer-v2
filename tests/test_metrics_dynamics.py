"""Tests for M2 dynamics (peak / RMS / crest) — ruling R-M2-5.

Three layers of assurance:

* synthetic exactness — sines and squares have closed-form peak/RMS/crest;
* the **D2 cross-check** — ``dynamics.peak_dbfs`` must equal
  ``loudness.sample_peak_dbfs`` on every synthetic AND every disk fixture
  (same formula by construction; this test makes the construction law);
* the **v1 oracle** — v1's formulas (reference/v1/analyzer.py:52-67, 193-200)
  encoded test-locally: agreement where definitions coincide (mono files),
  documented divergence where they don't (v1 measured the MONO DOWNMIX, so
  anti-phase stereo content cancelled and v1 under-read the peak).
"""

from __future__ import annotations

import glob
import math
import os

import numpy as np
import pytest

from rai_analyzer.io_audio import AudioSignal, load_audio
from rai_analyzer.loudness import measure_loudness
from rai_analyzer.metrics.contracts import DynamicsResult
from rai_analyzer.metrics.dynamics import compute_dynamics

_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "..", "validation", "fixtures")
_FIXTURE_WAVS = sorted(glob.glob(os.path.join(_FIXTURE_DIR, "*.wav")))


# ---------------------------------------------------------------------------
# Helpers (local by design — conftest.py is not touched in M2)
# ---------------------------------------------------------------------------


def _signal(data: np.ndarray, sr_native: int = 48000) -> AudioSignal:
    """Wrap raw native-rate samples as an AudioSignal (loudness-test pattern)."""
    data = np.asarray(data, dtype=np.float32)
    channels = 1 if data.ndim == 1 else data.shape[1]
    n = data.shape[0]
    return AudioSignal(
        path="<test>",
        y=data.reshape(-1)[: max(n, 1)].astype(np.float32, copy=False),
        sr=22050,
        y_native=data,
        sr_native=sr_native,
        channels=channels,
        duration=n / float(sr_native),
    )


def _sine(freq: float, amp: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


# --- v1 oracle, encoded verbatim from reference/v1/analyzer.py -------------


def _v1_peak_dbfs(samples: np.ndarray) -> float:
    """v1 compute_peak_dbfs (reference/v1/analyzer.py:52-57)."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * np.log10(peak)


def _v1_rms_dbfs(samples: np.ndarray) -> float:
    """v1 compute_rms_dbfs (reference/v1/analyzer.py:60-67)."""
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * np.log10(rms)


def _v1_dynamic_range(peak_db: float, rms_db: float) -> float:
    """v1 compute_dynamic_range (reference/v1/analyzer.py:193-200)."""
    if not np.isfinite(peak_db) or not np.isfinite(rms_db):
        return 0.0
    return float(peak_db - rms_db)


def _v1_mono(data: np.ndarray) -> np.ndarray:
    """v1's intake downmix: mean of channels (reference/v1/analyzer.py:45-46)."""
    if data.ndim > 1:
        return data.mean(axis=1)
    return data


# ---------------------------------------------------------------------------
# Synthetic exactness
# ---------------------------------------------------------------------------


def test_sine_peak_rms_crest():
    # amp 0.5 sine: peak -6.0206 dBFS, RMS = peak - 3.0103 dB (crest of a sine).
    res = compute_dynamics(_sine(1000.0, 0.5, 3.0, 48000))
    assert isinstance(res, DynamicsResult)
    assert res.peak_dbfs == pytest.approx(-6.0206, abs=0.1)
    assert res.rms_dbfs == pytest.approx(-9.0309, abs=0.1)
    assert res.crest_db == pytest.approx(3.0103, abs=0.1)


def test_square_wave_crest_is_zero():
    # A full-on square has peak == RMS -> crest 0 dB exactly.
    sq = np.sign(_sine(500.0, 1.0, 2.0, 48000)).astype(np.float32) * 0.5
    sq[sq == 0.0] = 0.5  # sign(0) -> keep full scale
    res = compute_dynamics(sq)
    assert res.crest_db == pytest.approx(0.0, abs=1e-6)
    assert res.peak_dbfs == pytest.approx(res.rms_dbfs, abs=1e-6)


def test_gain_shifts_both_levels_by_gain_db():
    base = _sine(997.0, 0.25, 2.0, 48000)
    a = compute_dynamics(base)
    b = compute_dynamics(base * 2.0)
    assert b.peak_dbfs - a.peak_dbfs == pytest.approx(6.0206, abs=1e-6)
    assert b.rms_dbfs - a.rms_dbfs == pytest.approx(6.0206, abs=1e-6)
    # Crest is gain-invariant.
    assert b.crest_db == pytest.approx(a.crest_db, abs=1e-9)


def test_stereo_peak_takes_loudest_channel_rms_pools_all():
    quiet = _sine(1000.0, 0.2, 2.0, 48000)
    loud = _sine(1000.0, 0.5, 2.0, 48000)
    res = compute_dynamics(np.stack([quiet, loud], axis=1))
    # Peak is the max over ALL channels -> the 0.5 channel.
    assert res.peak_dbfs == pytest.approx(-6.0206, abs=0.1)
    # RMS pools every sample of every channel: mean square = (0.2^2 + 0.5^2)/2 / 2.
    expected_rms = 20.0 * math.log10(math.sqrt((0.2**2 + 0.5**2) / 2.0 / 2.0))
    assert res.rms_dbfs == pytest.approx(expected_rms, abs=0.1)


# ---------------------------------------------------------------------------
# Silence / degenerate — NaN policy (never v1's lying 0.0)
# ---------------------------------------------------------------------------


def test_silence_is_neg_inf_peaks_and_nan_crest():
    for shape in ((48000,), (48000, 2)):
        res = compute_dynamics(np.zeros(shape, dtype=np.float32))
        assert res.peak_dbfs == float("-inf")
        assert res.rms_dbfs == float("-inf")
        assert math.isnan(res.crest_db)
        # Explicitly: NOT v1's 0.0 (ruling R-M2-5).
        assert res.crest_db != 0.0


def test_empty_input_never_raises():
    for shape in ((0,), (0, 2)):
        res = compute_dynamics(np.zeros(shape, dtype=np.float32))
        assert res.peak_dbfs == float("-inf")
        assert res.rms_dbfs == float("-inf")
        assert math.isnan(res.crest_db)


# ---------------------------------------------------------------------------
# D2 cross-check: dynamics peak ≡ loudness sample peak
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        _sine(1000.0, 0.5, 2.0, 48000),
        _sine(50.0, 0.9, 2.0, 44100),
        np.stack([_sine(1000.0, 0.2, 2.0, 48000), _sine(1000.0, 0.5, 2.0, 48000)], axis=1),
        np.stack([_sine(440.0, 0.7, 1.0, 48000), -_sine(440.0, 0.7, 1.0, 48000)], axis=1),
        np.zeros(4800, dtype=np.float32),
        np.zeros((4800, 2), dtype=np.float32),
    ],
    ids=["mono-sine", "sub-sine", "stereo-unequal", "stereo-antiphase", "silence", "silence-2ch"],
)
def test_d2_peak_equals_loudness_sample_peak_synthetic(data):
    sig = _signal(data, 48000)
    assert compute_dynamics(sig.y_native).peak_dbfs == measure_loudness(sig).sample_peak_dbfs


@pytest.mark.skipif(not _FIXTURE_WAVS, reason="drop-in fixture WAVs not present")
@pytest.mark.parametrize("path", _FIXTURE_WAVS, ids=[os.path.basename(p) for p in _FIXTURE_WAVS])
def test_d2_peak_equals_loudness_sample_peak_disk(path):
    sig = load_audio(path)
    assert compute_dynamics(sig.y_native).peak_dbfs == measure_loudness(sig).sample_peak_dbfs


# ---------------------------------------------------------------------------
# v1 oracle: agreement on mono, documented divergence on stereo
# ---------------------------------------------------------------------------


def test_v1_agreement_on_mono_dynamics():
    # Mono file: v1's downmix is the identity, so every definition coincides.
    y = _sine(180.0, 0.6, 3.0, 44100)
    res = compute_dynamics(y)
    assert res.peak_dbfs == pytest.approx(_v1_peak_dbfs(y), abs=1e-9)
    assert res.rms_dbfs == pytest.approx(_v1_rms_dbfs(y), abs=1e-9)
    assert res.crest_db == pytest.approx(
        _v1_dynamic_range(_v1_peak_dbfs(y), _v1_rms_dbfs(y)), abs=1e-9
    )


def test_v1_divergence_stereo_downmix_cancellation():
    """DOCUMENTED DIVERGENCE: v1 measured the mono downmix, so anti-phase
    stereo cancels and v1's peak collapses; v2 measures all channels and
    reports the real level (and agrees with loudness — the D2 identity)."""
    mono = _sine(440.0, 0.7, 2.0, 48000)
    stereo = np.stack([mono, -mono], axis=1)  # perfect anti-phase

    v1_peak = _v1_peak_dbfs(_v1_mono(stereo))
    v2 = compute_dynamics(stereo)

    assert v1_peak == float("-inf")  # v1: total cancellation
    assert v2.peak_dbfs == pytest.approx(20.0 * math.log10(0.7), abs=0.1)  # v2: the truth
    sig = _signal(stereo, 48000)
    assert v2.peak_dbfs == measure_loudness(sig).sample_peak_dbfs


def test_v1_divergence_silence_crest():
    """DOCUMENTED DIVERGENCE: v1 reported crest 0.0 for silence; v2 says NaN
    (nothing to measure is not 'no dynamics')."""
    sil = np.zeros(48000, dtype=np.float32)
    assert _v1_dynamic_range(_v1_peak_dbfs(sil), _v1_rms_dbfs(sil)) == 0.0
    assert math.isnan(compute_dynamics(sil).crest_db)
