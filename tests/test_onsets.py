"""Unit tests for rai_analyzer.onsets.compute_band_envelopes.

Covers the three core guarantees of the multiband onset layer (spec section 1):

* the returned :class:`BandEnvelopes` is well-formed (aligned, finite,
  non-negative, all envelopes the same length as ``times``),
* the bands are frequency-selective (a low tone's onset energy lands in
  ``.low`` rather than ``.high``; a high tone's lands in ``.high`` rather than
  ``.low``), and
* a metronome click train produces clear, periodic peaks in the broadband
  ``.full`` envelope.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import find_peaks

from rai_analyzer.config import ANALYSIS_SR, HOP_LENGTH
from rai_analyzer.contracts import BandEnvelopes
from rai_analyzer.onsets import compute_band_envelopes


def _am_burst_tone(freq: float, sr: int = ANALYSIS_SR, dur: float = 6.0, rate: float = 4.0):
    """A gated (amplitude-modulated) sine: a single frequency that switches on
    and off ``rate`` times a second, so it generates repeated, well-localised
    onsets while keeping (almost) all of its spectral energy at ``freq``."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    tone = np.sin(2 * np.pi * freq * t)
    gate = ((t * rate) % 1.0 < 0.5).astype(np.float64)  # 50% duty cycle
    return (tone * gate).astype(np.float32)


def test_band_envelopes_wellformed():
    """All envelopes + times share one length and are finite & non-negative."""
    y = _am_burst_tone(440.0)
    be = compute_band_envelopes(y, ANALYSIS_SR, hop_length=HOP_LENGTH)

    assert isinstance(be, BandEnvelopes)
    assert be.sr == ANALYSIS_SR
    assert be.hop_length == HOP_LENGTH

    T = len(be.times)
    assert T > 0
    for name in ("low", "mid", "high", "full"):
        arr = be.band(name)
        assert len(arr) == T, f"{name} length {len(arr)} != times length {T}"
        assert np.all(np.isfinite(arr)), f"{name} has non-finite values"
        assert np.all(arr >= 0.0), f"{name} has negative values"

    # frame_rate is the documented SR / hop relationship.
    assert be.frame_rate == pytest.approx(ANALYSIS_SR / HOP_LENGTH)


def test_low_tone_energy_lands_in_low_band():
    """A ~60 Hz gated tone deposits its onset energy in .low, not .high."""
    y = _am_burst_tone(60.0)
    be = compute_band_envelopes(y, ANALYSIS_SR, hop_length=HOP_LENGTH)

    low_e = float(be.low.sum())
    high_e = float(be.high.sum())

    assert low_e > 0.0
    # A 60 Hz tone has essentially nothing above the 8 kHz mid/high cut, so the
    # low band must dominate the high band by a wide margin.
    assert low_e > high_e
    assert low_e > 2.0 * (high_e + 1e-9)


def test_high_tone_energy_lands_in_high_band():
    """A ~10 kHz gated tone (below the 11025 Hz Nyquist) favours .high over .low."""
    freq = 10000.0
    assert freq < ANALYSIS_SR / 2.0  # genuinely below Nyquist
    y = _am_burst_tone(freq)
    be = compute_band_envelopes(y, ANALYSIS_SR, hop_length=HOP_LENGTH)

    low_e = float(be.low.sum())
    high_e = float(be.high.sum())

    assert high_e > 0.0
    # The high band carries more onset energy than the low band, and is the
    # strongest of the three perceptual bands for a 10 kHz source.
    assert high_e > low_e
    assert high_e >= float(be.mid.sum())


def test_click_track_produces_clear_broadband_peaks(make_click):
    """A 120 BPM metronome yields periodic, well-separated peaks in .full."""
    bpm, dur = 120.0, 8.0
    sig = make_click(bpm, duration=dur)
    be = compute_band_envelopes(sig.y, sig.sr, hop_length=HOP_LENGTH)

    full = be.full
    assert float(full.max()) > 0.0

    fps = be.frame_rate
    beat_period = 60.0 / bpm
    # Peaks at least ~half a beat apart, prominent vs the envelope max.
    height = 0.3 * float(full.max())
    distance = max(1, int(round(0.5 * beat_period * fps)))
    peaks, _ = find_peaks(full, height=height, distance=distance)

    expected_beats = int(dur / beat_period)
    # Should recover most of the beats (allow a little edge slack), but never a
    # smeared blob with only one or two peaks.
    assert len(peaks) >= expected_beats - 2
    assert len(peaks) <= expected_beats + 2

    # The recovered peaks are spaced at roughly one beat (median inter-peak gap).
    if len(peaks) >= 2:
        gaps = np.diff(be.times[peaks])
        assert np.median(gaps) == pytest.approx(beat_period, rel=0.15)
