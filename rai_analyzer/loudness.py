"""Tier-1 loudness measurements: integrated LUFS + true peak (dBTP).

Real implementation against the contract in :mod:`rai_analyzer.contracts`:

    measure_loudness(signal: AudioSignal) -> LoudnessResult

  * Measure on ``signal.y_native`` at ``signal.sr_native`` (NOT the downsampled
    mono analysis view) so numbers match mastering tools.
  * ``lufs_i``         — ITU-R BS.1770 / EBU R128 integrated loudness via
    ``pyloudnorm.Meter(sr).integrated_loudness(data)``. BS.1770 gating needs a
    block of audio (~0.4 s); clips shorter than the meter's block size cannot be
    gated, so ``lufs_i`` is ``nan`` for them (rather than crashing). Digital
    silence reads ``-inf`` (pyloudnorm's value, passed through unchanged).
  * ``true_peak_dbtp`` — true peak via >=4x oversampling (``resample_poly`` at
    4:1, per channel), then ``20*log10(max|oversampled|)``. The max across
    channels is taken. >= the sample peak by construction.
  * ``sample_peak_dbfs`` — raw sample peak, ``20*log10(max|y_native|)``.

  Silence (peak 0) maps to ``-inf`` for both peak figures. Nothing here raises
  on mono/stereo/empty/short input: the result is always finite-or-(-inf)/nan.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import resample_poly

from .contracts import LoudnessResult
from .io_audio import AudioSignal

# True-peak oversampling factor. BS.1770-4 specifies >=4x for content sampled
# at <= 48 kHz, which covers the overwhelming majority of intake material.
_TP_OVERSAMPLE = 4


def _to_2d(y: np.ndarray) -> np.ndarray:
    """Return ``y`` as a 2-D ``(n, channels)`` float64 array.

    ``y_native`` is ``(n,)`` for mono or ``(n, channels)`` for multichannel
    (soundfile orientation). We normalise to 2-D so the per-channel loops below
    don't have to special-case mono.
    """
    arr = np.asarray(y, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    return arr


def _db_from_amplitude(peak: float) -> float:
    """dB of a linear amplitude; ``-inf`` for a non-positive (silent) peak."""
    if peak > 0.0:
        return float(20.0 * np.log10(peak))
    return float("-inf")


def _sample_peak_dbfs(y2d: np.ndarray) -> float:
    """Raw sample peak across all channels, in dBFS."""
    if y2d.size == 0:
        return float("-inf")
    peak = float(np.max(np.abs(y2d)))
    return _db_from_amplitude(peak)


def _true_peak_dbtp(y2d: np.ndarray, factor: int = _TP_OVERSAMPLE) -> float:
    """True peak (dBTP) via ``factor``x polyphase oversampling, per channel.

    Oversampling reconstructs inter-sample peaks the raw samples miss, so this
    is always >= the sample peak. The max across channels is returned.
    """
    if y2d.size == 0:
        return float("-inf")

    # resample_poly needs more than one sample to interpolate; for 0/1-sample
    # input there are no inter-sample peaks, so fall back to the sample peak.
    if y2d.shape[0] < 2:
        return _sample_peak_dbfs(y2d)

    max_peak = 0.0
    for ch in range(y2d.shape[1]):
        chan = np.ascontiguousarray(y2d[:, ch], dtype=np.float64)
        up = resample_poly(chan, factor, 1)
        ch_peak = float(np.max(np.abs(up))) if up.size else 0.0
        if ch_peak > max_peak:
            max_peak = ch_peak

    # The reconstructed peak can dip just under the raw sample peak at the
    # signal edges of short windows; never report below the true sample peak.
    sample_peak = float(np.max(np.abs(y2d)))
    if sample_peak > max_peak:
        max_peak = sample_peak

    return _db_from_amplitude(max_peak)


def _integrated_lufs(y2d: np.ndarray, sr: int) -> float:
    """BS.1770 integrated loudness (LUFS); ``nan`` if too short to gate.

    pyloudnorm wants ``(n,)`` mono or ``(n, channels)`` and raises if the audio
    is shorter than the meter's gating block (~0.4 s). We check the length up
    front and return ``nan`` for sub-block clips instead of letting it throw.
    Digital silence returns ``-inf`` from pyloudnorm; we pass that through.
    """
    import pyloudnorm as pyln

    n = y2d.shape[0]
    if n == 0 or sr <= 0:
        return float("nan")

    meter = pyln.Meter(sr)
    # Need strictly more than one block of samples for the gating to run.
    min_samples = int(np.ceil(meter.block_size * sr))
    if n <= min_samples:
        return float("nan")

    # pyloudnorm squeezes a single channel itself, but be explicit: mono ->
    # (n,), multichannel -> (n, channels).
    data = y2d[:, 0] if y2d.shape[1] == 1 else y2d

    try:
        loudness = meter.integrated_loudness(data)
    except Exception:
        # Any unexpected meter failure must not sink the measurement.
        return float("nan")
    return float(loudness)


def measure_loudness(signal: AudioSignal) -> LoudnessResult:
    """Measure integrated LUFS, true peak (dBTP), and sample peak (dBFS).

    Operates on ``signal.y_native`` at ``signal.sr_native`` so the figures line
    up with mastering tools. Robust to mono/stereo, silence, and very short
    clips: never raises, never returns a crashing NaN for the peaks.
    """
    y2d = _to_2d(signal.y_native)
    sr = int(signal.sr_native)

    sample_peak = _sample_peak_dbfs(y2d)
    true_peak = _true_peak_dbtp(y2d)
    lufs = _integrated_lufs(y2d, sr)

    return LoudnessResult(
        lufs_i=lufs,
        true_peak_dbtp=true_peak,
        sample_peak_dbfs=sample_peak,
    )
