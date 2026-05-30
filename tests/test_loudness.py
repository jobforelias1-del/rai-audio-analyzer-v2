"""Tests for Tier-1 loudness measurement (LUFS + true peak + sample peak).

These assert *relationships and physical sanity* (e.g. true peak >= sample
peak, monotonicity of LUFS with gain), not pyloudnorm's exact numeric output,
so they stay robust across pyloudnorm/scipy versions.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rai_analyzer.contracts import LoudnessResult
from rai_analyzer.io_audio import AudioSignal
from rai_analyzer.loudness import measure_loudness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal(data: np.ndarray, sr_native: int) -> AudioSignal:
    """Build an AudioSignal for loudness tests.

    Only ``y_native`` / ``sr_native`` / ``channels`` matter to the loudness
    code; ``y`` / ``sr`` are filled with a throwaway mono view so the dataclass
    is well-formed.
    """
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


# ---------------------------------------------------------------------------
# Core reference case: 1 kHz sine, amp 0.5, 3 s @ 48 kHz
# ---------------------------------------------------------------------------


def test_reference_sine_levels():
    sr = 48000
    x = _sine(1000.0, 0.5, 3.0, sr)
    res = measure_loudness(_signal(x, sr))

    assert isinstance(res, LoudnessResult)

    # amp 0.5 -> 20*log10(0.5) = -6.0206 dBFS
    assert res.sample_peak_dbfs == pytest.approx(-6.0206, abs=0.1)

    # True peak is >= sample peak by construction.
    assert res.true_peak_dbtp >= res.sample_peak_dbfs
    # For a clean 1 kHz tone well below Nyquist, the inter-sample overshoot is
    # tiny — true peak should sit just above the sample peak, not wildly off.
    assert res.true_peak_dbtp <= res.sample_peak_dbfs + 1.0

    # Integrated LUFS must be finite and in a sane musical range.
    assert math.isfinite(res.lufs_i)
    assert -20.0 <= res.lufs_i <= 0.0


def test_to_dict_is_rounded_floats():
    sr = 48000
    x = _sine(1000.0, 0.5, 3.0, sr)
    d = measure_loudness(_signal(x, sr)).to_dict()
    assert set(d) == {"lufs_i", "true_peak_dbtp", "sample_peak_dbfs"}
    for v in d.values():
        assert isinstance(v, float)


# ---------------------------------------------------------------------------
# Monotonicity: louder reads higher LUFS (and higher peaks)
# ---------------------------------------------------------------------------


def test_louder_reads_higher_lufs():
    sr = 48000
    quiet = measure_loudness(_signal(_sine(1000.0, 0.1, 3.0, sr), sr))
    loud = measure_loudness(_signal(_sine(1000.0, 0.5, 3.0, sr), sr))

    assert math.isfinite(quiet.lufs_i)
    assert math.isfinite(loud.lufs_i)
    assert loud.lufs_i > quiet.lufs_i

    # A 5x amplitude bump is ~+13.98 dB; LUFS is a dB-domain measure, so the
    # gap should track that gain closely.
    assert loud.lufs_i - quiet.lufs_i == pytest.approx(20.0 * math.log10(5.0), abs=0.3)

    # Peaks scale the same way.
    assert loud.sample_peak_dbfs > quiet.sample_peak_dbfs
    assert loud.true_peak_dbtp > quiet.true_peak_dbtp


def test_gain_shifts_lufs_by_gain_db():
    # Doubling amplitude should raise LUFS by ~+6.02 dB.
    sr = 48000
    base = _sine(997.0, 0.25, 4.0, sr)
    a = measure_loudness(_signal(base, sr))
    b = measure_loudness(_signal(base * 2.0, sr))
    assert b.lufs_i - a.lufs_i == pytest.approx(6.0206, abs=0.2)


# ---------------------------------------------------------------------------
# Inter-sample / true peak: near-clip tone near Nyquist/4 overshoots 0 dBTP
# ---------------------------------------------------------------------------


def test_true_peak_exceeds_sample_peak_near_clipping():
    sr = 48000
    # A tone at sr/4 sampled with a phase offset puts true inter-sample peaks
    # between samples. Scale to ~full-scale so the reconstructed peak pushes
    # above 0 dBTP while the sample peak stays at/under 0 dBFS.
    n = int(0.5 * sr)
    t = np.arange(n) / float(sr)
    x = np.cos(2.0 * np.pi * (sr / 4.0) * t + np.pi / 4.0).astype(np.float32)
    # Normalise so the worst sample is ~just under full scale.
    x = (x / np.max(np.abs(x))) * 0.98
    x = x.astype(np.float32)

    res = measure_loudness(_signal(x, sr))

    # True peak strictly exceeds the sample peak here (inter-sample energy).
    assert res.true_peak_dbtp > res.sample_peak_dbfs + 0.1
    # Sample peak stays at/under 0 dBFS...
    assert res.sample_peak_dbfs <= 0.05
    # ...but the true peak overshoots above 0 dBTP.
    assert res.true_peak_dbtp > 0.0


def test_true_peak_never_below_sample_peak_random():
    rng = np.random.default_rng(1770)
    sr = 44100
    for _ in range(5):
        x = (rng.standard_normal(sr) * 0.3).astype(np.float32)
        res = measure_loudness(_signal(x, sr))
        assert res.true_peak_dbtp >= res.sample_peak_dbfs - 1e-9


# ---------------------------------------------------------------------------
# Mono vs stereo
# ---------------------------------------------------------------------------


def test_mono_and_stereo_both_work():
    sr = 48000
    mono = _sine(1000.0, 0.5, 3.0, sr)
    stereo = np.stack([mono, mono], axis=1)  # (n, 2)

    rm = measure_loudness(_signal(mono, sr))
    rs = measure_loudness(_signal(stereo, sr))

    assert mono.ndim == 1
    assert stereo.shape == (mono.shape[0], 2)

    # Identical content in both channels: peaks match the mono case exactly.
    assert rs.sample_peak_dbfs == pytest.approx(rm.sample_peak_dbfs, abs=1e-6)
    assert rs.true_peak_dbtp == pytest.approx(rm.true_peak_dbtp, abs=1e-6)

    # Both finite, both in a sane range.
    assert math.isfinite(rs.lufs_i)
    assert -20.0 <= rs.lufs_i <= 0.0


def test_stereo_peak_takes_loudest_channel():
    sr = 48000
    left = _sine(1000.0, 0.2, 3.0, sr)
    right = _sine(1000.0, 0.5, 3.0, sr)  # louder channel
    stereo = np.stack([left, right], axis=1)

    res = measure_loudness(_signal(stereo, sr))
    # Sample peak reflects the louder (0.5) channel, ~-6.02 dBFS.
    assert res.sample_peak_dbfs == pytest.approx(-6.0206, abs=0.1)
    assert res.true_peak_dbtp >= res.sample_peak_dbfs


# ---------------------------------------------------------------------------
# Silence
# ---------------------------------------------------------------------------


def test_silence_peaks_are_neg_inf():
    sr = 48000
    sil = np.zeros(int(3.0 * sr), dtype=np.float32)
    res = measure_loudness(_signal(sil, sr))

    assert res.sample_peak_dbfs == float("-inf")
    assert res.true_peak_dbtp == float("-inf")
    # pyloudnorm reports digital silence as -inf LUFS; we pass that through.
    assert res.lufs_i == float("-inf")


def test_stereo_silence_is_neg_inf():
    sr = 48000
    sil = np.zeros((int(2.0 * sr), 2), dtype=np.float32)
    res = measure_loudness(_signal(sil, sr))
    assert res.sample_peak_dbfs == float("-inf")
    assert res.true_peak_dbtp == float("-inf")
    assert res.lufs_i == float("-inf")


# ---------------------------------------------------------------------------
# Very short clips: no gating block -> nan LUFS, but peaks still valid
# ---------------------------------------------------------------------------


def test_short_clip_lufs_is_nan_peaks_valid():
    sr = 48000
    # 0.2 s is shorter than the BS.1770 ~0.4 s gating block.
    x = _sine(1000.0, 0.5, 0.2, sr)
    res = measure_loudness(_signal(x, sr))

    assert math.isnan(res.lufs_i)
    # Peaks are still well-defined for a short clip.
    assert res.sample_peak_dbfs == pytest.approx(-6.0206, abs=0.1)
    assert res.true_peak_dbtp >= res.sample_peak_dbfs


def test_does_not_raise_on_tiny_and_empty_inputs():
    sr = 48000
    for data in (
        np.zeros(0, dtype=np.float32),  # empty
        np.array([0.5], dtype=np.float32),  # single sample
        np.array([[0.1, 0.2]], dtype=np.float32),  # single stereo frame
        np.zeros((0, 2), dtype=np.float32),  # empty stereo
    ):
        res = measure_loudness(_signal(data, sr))
        assert isinstance(res, LoudnessResult)
        # LUFS is nan (too short to gate); peaks are finite-or-(-inf), never nan.
        assert math.isnan(res.lufs_i)
        assert not math.isnan(res.sample_peak_dbfs)
        assert not math.isnan(res.true_peak_dbtp)
        assert res.true_peak_dbtp >= res.sample_peak_dbfs - 1e-9


def test_native_rate_is_used_not_analysis_rate():
    # sample_peak depends only on y_native amplitude; full-scale -> ~0 dBFS at
    # the native rate regardless of the (different) analysis-view sr.
    sr_native = 96000
    x = _sine(1000.0, 1.0, 1.0, sr_native)
    sig = _signal(x, sr_native)
    # Sanity: the analysis-view sr differs from native.
    assert sig.sr != sig.sr_native
    res = measure_loudness(sig)
    assert res.sample_peak_dbfs == pytest.approx(0.0, abs=0.1)
    assert math.isfinite(res.lufs_i)
