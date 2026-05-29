"""Audio intake — the shared IO layer.

Loaded exactly once per file. Two views come out of one read:

* ``y`` — mono, float32, resampled to the analysis rate. This feeds onset
  detection and the tempograms (tempo work does not need full bandwidth).
* ``y_native`` — the signal at its ORIGINAL sample rate and channel count.
  Loudness (LUFS / true peak) must be measured here, not on the downsampled
  mono mix, or the numbers drift from what mastering tools report.

WAV is the primary intake format (per spec), but the loader falls back to
librosa/audioread for anything soundfile cannot open, so the GUI never hard
-fails on a stray AIFF/FLAC/MP3 drop.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ANALYSIS_SR


@dataclass
class AudioSignal:
    path: str
    y: np.ndarray  # (n,) mono float32 @ sr (analysis rate)
    sr: int  # analysis sample rate
    y_native: np.ndarray  # (n,) or (n, ch) float32 @ sr_native (loudness rate)
    sr_native: int
    channels: int
    duration: float  # seconds


def load_audio(path: str, analysis_sr: int = ANALYSIS_SR) -> AudioSignal:
    """Load ``path`` into an :class:`AudioSignal`.

    Parameters
    ----------
    path:
        Path to the audio file (WAV expected; other formats tolerated).
    analysis_sr:
        Target sample rate for the mono analysis view.
    """
    y_native, sr_native = _read_any(path)

    # Channel count and a native-rate float32 copy for loudness.
    if y_native.ndim == 1:
        channels = 1
    else:
        # soundfile returns (frames, channels). Keep that orientation.
        channels = y_native.shape[1]
    y_native = y_native.astype(np.float32, copy=False)
    duration = (y_native.shape[0]) / float(sr_native)

    # Mono downmix for tempo analysis.
    if y_native.ndim == 1:
        mono = y_native
    else:
        mono = y_native.mean(axis=1)

    # Resample mono to the analysis rate.
    if sr_native != analysis_sr:
        import librosa

        y = librosa.resample(
            np.ascontiguousarray(mono, dtype=np.float32),
            orig_sr=sr_native,
            target_sr=analysis_sr,
            res_type="soxr_hq",
        )
    else:
        y = np.ascontiguousarray(mono, dtype=np.float32)

    return AudioSignal(
        path=path,
        y=y.astype(np.float32, copy=False),
        sr=analysis_sr,
        y_native=y_native,
        sr_native=sr_native,
        channels=channels,
        duration=duration,
    )


def _read_any(path: str) -> tuple[np.ndarray, int]:
    """Read a file to (samples, sr), preserving native rate and channels."""
    try:
        import soundfile as sf

        data, sr = sf.read(path, dtype="float32", always_2d=False)
        return data, int(sr)
    except Exception:
        # Fallback: librosa/audioread. mono=False preserves channels; the
        # returned shape is (channels, frames), so transpose to (frames, ch).
        import librosa

        data, sr = librosa.load(path, sr=None, mono=False)
        if data.ndim == 2:
            data = data.T
        return data.astype(np.float32), int(sr)
