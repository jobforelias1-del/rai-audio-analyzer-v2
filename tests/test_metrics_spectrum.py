"""Tests for the M2 Welch spectrum — ruling R-M2-7.

Pins the recipe: nperseg = min(16384, n) at the NATIVE rate, per-channel PSDs
averaged in the POWER domain (never a pre-FFT downmix — v1's cancellation
bug), audible mask 20 Hz .. min(20 kHz, Nyquist), dB values UNNORMALIZED
(the UI owns display normalization).
"""

from __future__ import annotations

import numpy as np
import pytest

from rai_analyzer.metrics.contracts import SpectrumData
from rai_analyzer.metrics.params import SPECTRUM_NPERSEG
from rai_analyzer.metrics.spectrum import audible_mask, build_spectrum_data, welch_psd


def _sine(freq: float, amp: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _spectrum(y: np.ndarray, sr: int) -> SpectrumData:
    freqs, psd = welch_psd(y, sr)
    return build_spectrum_data(freqs, psd)


# ---------------------------------------------------------------------------
# Peak location + masking
# ---------------------------------------------------------------------------


def test_sine_peak_lands_at_its_frequency():
    sr = 48000
    spec = _spectrum(_sine(1000.0, 0.5, 3.0, sr), sr)
    assert spec.freqs.size == spec.psd_db.size > 0
    peak_freq = float(spec.freqs[int(np.argmax(spec.psd_db))])
    # Bin spacing is sr / nperseg ≈ 2.93 Hz at 48 kHz.
    assert peak_freq == pytest.approx(1000.0, abs=2.0 * sr / SPECTRUM_NPERSEG)


def test_mask_is_20hz_to_20khz():
    sr = 48000
    spec = _spectrum(_sine(1000.0, 0.5, 2.0, sr), sr)
    assert float(spec.freqs[0]) >= 20.0
    assert float(spec.freqs[-1]) <= 20000.0


def test_mask_caps_at_nyquist_below_20k():
    sr = 22050
    spec = _spectrum(_sine(1000.0, 0.5, 2.0, sr), sr)
    assert float(spec.freqs[-1]) <= sr / 2.0
    assert spec.freqs.size > 0


def test_bin_spacing_pins_nperseg_16384():
    sr = 48000
    freqs, _ = welch_psd(_sine(1000.0, 0.5, 3.0, sr), sr)  # n = 144000 > 16384
    spacing = float(freqs[1] - freqs[0])
    assert spacing == pytest.approx(sr / SPECTRUM_NPERSEG, rel=1e-9)


def test_short_input_shrinks_nperseg_not_crashes():
    sr = 48000
    y = _sine(1000.0, 0.5, 0.05, sr)  # 2400 samples < 16384
    freqs, psd = welch_psd(y, sr)
    assert freqs.size > 0
    spacing = float(freqs[1] - freqs[0])
    assert spacing == pytest.approx(sr / y.size, rel=1e-9)
    spec = build_spectrum_data(freqs, psd)
    assert spec.freqs.size > 0


# ---------------------------------------------------------------------------
# Power-domain channel averaging (the v1 cancellation-bug fix)
# ---------------------------------------------------------------------------


def test_antiphase_stereo_keeps_its_spectrum():
    """v1 downmixed to mono BEFORE the FFT, so anti-phase content vanished
    from its spectrum. v2 averages per-channel PSDs in the power domain: the
    anti-phase tone must read exactly as strong as the in-phase one."""
    sr = 48000
    mono = _sine(1000.0, 0.5, 3.0, sr)
    in_phase = np.stack([mono, mono], axis=1)
    anti_phase = np.stack([mono, -mono], axis=1)

    spec_in = _spectrum(in_phase, sr)
    spec_anti = _spectrum(anti_phase, sr)

    peak_in = float(np.max(spec_in.psd_db))
    peak_anti = float(np.max(spec_anti.psd_db))
    assert peak_anti == pytest.approx(peak_in, abs=1e-6)

    # And the v1-style downmix-first spectrum really would have lost it —
    # the divergence this recipe exists to fix.
    downmix = anti_phase.mean(axis=1)
    assert float(np.max(np.abs(downmix))) < 1e-6


def test_unnormalized_db_tracks_gain():
    # +6.02 dB of gain moves the (unnormalized) peak bin by +6.02 dB.
    sr = 48000
    a = _spectrum(_sine(1000.0, 0.25, 3.0, sr), sr)
    b = _spectrum(_sine(1000.0, 0.5, 3.0, sr), sr)
    assert float(np.max(b.psd_db)) - float(np.max(a.psd_db)) == pytest.approx(6.0206, abs=0.05)


# ---------------------------------------------------------------------------
# Silence / degenerate
# ---------------------------------------------------------------------------


def test_silence_spectrum_is_neg_inf_everywhere():
    sr = 48000
    spec = _spectrum(np.zeros(sr, dtype=np.float32), sr)
    assert spec.freqs.size > 0
    assert np.all(np.isneginf(spec.psd_db))


def test_empty_and_tiny_input_yield_empty_spectrum():
    for y in (np.zeros(0, dtype=np.float32), np.zeros(1, dtype=np.float32)):
        freqs, psd = welch_psd(y, 48000)
        assert freqs.size == 0 and psd.size == 0
        spec = build_spectrum_data(freqs, psd)
        assert spec.freqs.size == 0 and spec.psd_db.size == 0


def test_audible_mask_is_inclusive_at_both_edges():
    freqs = np.array([19.9, 20.0, 1000.0, 20000.0, 20000.1])
    assert list(audible_mask(freqs)) == [False, True, True, True, False]
