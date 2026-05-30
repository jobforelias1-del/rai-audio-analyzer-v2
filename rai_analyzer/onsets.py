"""Multiband onset detection (spec section 1).

Splits the signal into three perceptual onset streams plus a broadband
reference, all on one shared frame grid:

* ``low``  (< 200 Hz)        — kick / 808 / low transients
* ``mid``  (200 Hz - 8 kHz)  — snare / clap / groove body
* ``high`` (> 8 kHz)         — hats / clicks / shakers (the subdivision stream)

We use librosa's established spectral-flux onset strength (``onset_strength`` /
``onset_strength_multi``) rather than reinventing it — the spec is explicit:
use established DSP, do not reinvent standard algorithms. The multiband split
is done by mapping the Hz cut points onto mel-filter indices and letting
``onset_strength_multi`` integrate each band separately.
"""

from __future__ import annotations

import numpy as np

from .config import HOP_LENGTH, LOW_MID_HZ, MID_HIGH_HZ
from .contracts import BandEnvelopes

_N_FFT = 2048
_N_MELS = 128
_FMIN = 20.0


def compute_band_envelopes(
    y: np.ndarray,
    sr: int,
    hop_length: int = HOP_LENGTH,
    low_mid_hz: float = LOW_MID_HZ,
    mid_high_hz: float = MID_HIGH_HZ,
) -> BandEnvelopes:
    """Compute per-band onset-strength envelopes for a mono signal."""
    import librosa

    if y.ndim != 1:
        y = np.mean(y, axis=tuple(range(1, y.ndim)))
    y = np.ascontiguousarray(y, dtype=np.float32)

    fmax = sr / 2.0
    mel_S = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=_N_FFT, hop_length=hop_length, n_mels=_N_MELS, fmin=_FMIN, fmax=fmax
    )
    mel_db = librosa.power_to_db(mel_S, ref=np.max)
    mel_f = librosa.mel_frequencies(n_mels=_N_MELS, fmin=_FMIN, fmax=fmax)

    # Mel-bin boundaries for the Hz cut points, clamped so each band is non-empty.
    b_lo = int(np.clip(np.searchsorted(mel_f, low_mid_hz), 1, _N_MELS - 2))
    b_hi = int(np.clip(np.searchsorted(mel_f, mid_high_hz), b_lo + 1, _N_MELS - 1))
    channels = [0, b_lo, b_hi, _N_MELS]

    env_multi = librosa.onset.onset_strength_multi(
        S=mel_db, sr=sr, hop_length=hop_length, channels=channels
    )
    # env_multi: (3, T) -> low, mid, high
    low, mid, high = env_multi[0], env_multi[1], env_multi[2]

    # Broadband reference envelope (standard recipe over all mel bins).
    full = librosa.onset.onset_strength(S=mel_db, sr=sr, hop_length=hop_length)

    # Align lengths defensively (should already match).
    T = min(len(low), len(mid), len(high), len(full))
    low, mid, high, full = low[:T], mid[:T], high[:T], full[:T]
    times = librosa.times_like(full, sr=sr, hop_length=hop_length)[:T]

    return BandEnvelopes(
        sr=sr,
        hop_length=hop_length,
        times=np.asarray(times, dtype=np.float64),
        low=_clean(low),
        mid=_clean(mid),
        high=_clean(high),
        full=_clean(full),
    )


def _clean(x: np.ndarray) -> np.ndarray:
    """Non-negative, finite, float64 envelope."""
    x = np.asarray(x, dtype=np.float64)
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    return np.maximum(x, 0.0)
