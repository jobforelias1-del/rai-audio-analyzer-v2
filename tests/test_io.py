"""Unit tests for rai_analyzer.io_audio.load_audio.

The IO layer reads a file once and exposes two views: a mono float32 analysis
signal at ANALYSIS_SR, and the native-rate / native-channel signal for
loudness. We verify:

* a round-trip WAV preserves sr_native, channel count and duration, and the
  analysis view is 1-D float32 at ANALYSIS_SR,
* a 48 kHz file is resampled (signal.sr == ANALYSIS_SR) while sr_native stays
  48000, and
* a stereo file reports channels == 2 yet still produces a mono (1-D) analysis
  view.
"""

from __future__ import annotations

import numpy as np
import pytest
import soundfile as sf

from rai_analyzer.config import ANALYSIS_SR
from rai_analyzer.io_audio import load_audio
from rai_analyzer.synthetic import click_track


def test_roundtrip_mono_native_rate(tmp_wav):
    """A mono WAV written at ANALYSIS_SR loads back with matching metadata."""
    dur = 3.0
    y = click_track(120.0, duration=dur, sr=ANALYSIS_SR)
    path = tmp_wav(y, ANALYSIS_SR)

    sig = load_audio(path)

    assert sig.sr_native == ANALYSIS_SR
    assert sig.channels == 1
    assert sig.duration == pytest.approx(dur, abs=0.02)

    # Analysis view: mono, float32, at the analysis rate.
    assert sig.sr == ANALYSIS_SR
    assert sig.y.ndim == 1
    assert sig.y.dtype == np.float32
    # No resampling needed -> analysis length tracks native length exactly.
    assert sig.y.shape[0] == sig.y_native.shape[0]


def test_resampling_to_analysis_rate(tmp_wav):
    """A 48 kHz mono file is resampled to ANALYSIS_SR; sr_native is preserved."""
    native_sr = 48000
    dur = 2.0
    y = click_track(120.0, duration=dur, sr=native_sr)
    path = tmp_wav(y, native_sr, name="native48.wav")

    sig = load_audio(path)

    assert sig.sr_native == native_sr
    assert sig.sr == ANALYSIS_SR
    assert ANALYSIS_SR != native_sr  # the resample path was actually exercised

    assert sig.y.ndim == 1
    assert sig.y.dtype == np.float32
    # Analysis length is the resampled length (~ dur * ANALYSIS_SR), not native.
    assert sig.y.shape[0] == pytest.approx(dur * ANALYSIS_SR, rel=0.02)
    assert sig.y.shape[0] != sig.y_native.shape[0]
    assert sig.duration == pytest.approx(dur, abs=0.02)


def test_stereo_file_keeps_channel_count_but_mono_analysis(tmp_path):
    """A 2-channel file reports channels == 2 yet yields a 1-D analysis signal."""
    native_sr = 44100
    dur = 1.5
    n = int(native_sr * dur)
    rng = np.random.default_rng(0)
    left = 0.5 * np.sin(2 * np.pi * 220.0 * np.arange(n) / native_sr)
    right = 0.4 * np.sin(2 * np.pi * 330.0 * np.arange(n) / native_sr)
    stereo = np.stack([left, right], axis=1).astype(np.float32)  # (frames, 2)

    path = str(tmp_path / "stereo.wav")
    sf.write(path, stereo, native_sr, subtype="PCM_16")

    sig = load_audio(path)

    assert sig.channels == 2
    assert sig.sr_native == native_sr
    # Native view retains both channels ...
    assert sig.y_native.ndim == 2
    assert sig.y_native.shape[1] == 2
    # ... while the analysis view is a mono downmix at the analysis rate.
    assert sig.y.ndim == 1
    assert sig.y.dtype == np.float32
    assert sig.sr == ANALYSIS_SR
    assert sig.duration == pytest.approx(dur, abs=0.02)
