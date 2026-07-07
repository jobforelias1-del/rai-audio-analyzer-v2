"""Averaged power spectrum via Welch's method (ruling R-M2-7).

Recipe (v2-canonical):

* runs on ``y_native`` **per channel at the NATIVE rate** in float64;
* ``nperseg = min(16384, n)``, Hann window, 50% overlap (scipy defaults for
  window/overlap/detrend — the same defaults v1's recipe relied on);
* per-channel PSDs are averaged **in the POWER domain** — never downmix to
  mono first (v1 averaged channels before the FFT, so anti-phase content
  cancelled out of its spectrum entirely: the documented v1 cancellation bug);
* masked to 20 Hz .. min(20 kHz, Nyquist).

The linear PSD is computed ONCE per analysis and shared with :mod:`.bands`
(which integrates it) — hence the split into :func:`welch_psd` (shared,
unmasked) and :func:`build_spectrum_data` (masked dB view for the contract).
"""

from __future__ import annotations

import numpy as np
from scipy.signal import welch

from .contracts import SpectrumData
from .params import FMAX_HZ, FMIN_HZ, SPECTRUM_NPERSEG

_EMPTY = np.zeros(0, dtype=np.float64)


def _to_2d(y: np.ndarray) -> np.ndarray:
    """Return ``y`` as ``(n, channels)`` float64 (mono ``(n,)`` -> ``(n, 1)``)."""
    arr = np.asarray(y, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    return arr


def welch_psd(y_native: np.ndarray, sr_native: int) -> tuple[np.ndarray, np.ndarray]:
    """Channel-power-averaged Welch PSD of ``y_native`` at the native rate.

    Returns ``(freqs, psd)`` over the full 0..Nyquist range (UNMASKED — the
    audible-range mask belongs to the consumers). Degenerate input (fewer than
    two samples, or a non-positive rate) yields empty arrays rather than an
    exception: there is no spectrum to measure.
    """
    y2d = _to_2d(y_native)
    n = y2d.shape[0]
    if n < 2 or sr_native <= 0:
        return _EMPTY.copy(), _EMPTY.copy()

    nperseg = int(min(SPECTRUM_NPERSEG, n))
    # scipy defaults: hann window, noverlap = nperseg // 2, constant detrend.
    freqs, psd = welch(y2d, fs=float(sr_native), nperseg=nperseg, axis=0)

    # POWER-domain average across channels (never a pre-FFT downmix).
    psd_avg = psd.mean(axis=1) if psd.ndim == 2 else psd
    return np.asarray(freqs, dtype=np.float64), np.asarray(psd_avg, dtype=np.float64)


def audible_mask(freqs: np.ndarray) -> np.ndarray:
    """Boolean mask for the 20 Hz .. min(20 kHz, Nyquist) analysis range.

    ``freqs`` never exceeds Nyquist, so the 20 kHz cap does the whole job;
    inclusive at both edges (the six-band map's ``air`` band matches).
    """
    return (freqs >= FMIN_HZ) & (freqs <= FMAX_HZ)


def build_spectrum_data(freqs: np.ndarray, psd: np.ndarray) -> SpectrumData:
    """Mask the shared PSD to the audible range and convert to (unnormalized) dB.

    Zero-power bins map to ``-inf`` honestly (silence has no level to report);
    the JSON contract turns non-finite into ``None`` and the UI renders its
    silence copy instead of a curve (R-M2-8).
    """
    mask = audible_mask(freqs)
    f = np.asarray(freqs[mask], dtype=np.float64)
    p = np.asarray(psd[mask], dtype=np.float64)
    with np.errstate(divide="ignore"):
        db = 10.0 * np.log10(p)
    return SpectrumData(freqs=f, psd_db=db)
