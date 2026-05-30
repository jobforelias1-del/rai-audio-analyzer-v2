"""Product tempogram — the core octave-resistant engine (spec section 2).

The central insight: the two standard tempogram methods fail in *opposite*
directions.

* The **autocorrelation** tempogram aliases DOWNWARD — a real pulse at the
  beat also autocorrelates strongly at twice the lag, so ACF over-favours the
  half-tempo.
* The **Fourier (DFT)** tempogram aliases UPWARD — the beat's harmonics put
  energy at the double-tempo, so DFT over-favours the double-tempo.

Multiplying the two (the *product tempogram*) suppresses each method's
spurious octave (one method's phantom peak meets the other method's trough)
while reinforcing the tempo where they agree. This is an established
octave-disambiguation technique; we build it from librosa's standard
``tempogram`` / ``fourier_tempogram`` rather than reinventing the transforms.
"""

from __future__ import annotations

import numpy as np

from .config import HOP_LENGTH, TempoConfig
from .contracts import BandEnvelopes, Features, TempoCurve
from .io_audio import AudioSignal
from .onsets import compute_band_envelopes

_EPS = 1e-9
_WIN_LENGTH = 384  # tempogram analysis window (frames); librosa default, well tested


def _bpm_grid(cfg: TempoConfig) -> np.ndarray:
    n = int(round((cfg.bpm_grid_max - cfg.bpm_grid_min) / cfg.bpm_grid_step)) + 1
    return np.linspace(cfg.bpm_grid_min, cfg.bpm_grid_max, n)


def _norm(x: np.ndarray) -> np.ndarray:
    m = float(np.max(x)) if x.size else 0.0
    return x / m if m > _EPS else np.zeros_like(x)


def product_tempogram(
    env: np.ndarray,
    sr: int,
    hop_length: int,
    bpm_grid: np.ndarray,
    win_length: int = _WIN_LENGTH,
) -> TempoCurve:
    """Build the octave-resistant product tempo-salience curve for one envelope."""
    import librosa

    env = np.ascontiguousarray(np.asarray(env, dtype=np.float32))
    if env.size < 8 or float(np.max(env)) <= _EPS:
        z = np.zeros_like(bpm_grid)
        return TempoCurve(bpms=bpm_grid, salience=z, acf=z.copy(), dft=z.copy())

    win = int(min(win_length, max(16, env.size)))

    # --- Autocorrelation tempogram (aliases downward) ---
    acf_tg = librosa.feature.tempogram(
        onset_envelope=env, sr=sr, hop_length=hop_length, win_length=win
    )
    acf_bpms = librosa.tempo_frequencies(win, sr=sr, hop_length=hop_length)
    acf_mean = np.mean(np.abs(acf_tg), axis=1)
    acf_grid = _resample_to_grid(acf_bpms, acf_mean, bpm_grid)

    # --- Fourier tempogram (aliases upward) ---
    dft_tg = librosa.feature.fourier_tempogram(
        onset_envelope=env, sr=sr, hop_length=hop_length, win_length=win
    )
    dft_bpms = librosa.fourier_tempo_frequencies(sr=sr, hop_length=hop_length, win_length=win)
    dft_mean = np.mean(np.abs(dft_tg), axis=1)
    dft_grid = _resample_to_grid(dft_bpms, dft_mean, bpm_grid)

    acf_grid = _norm(acf_grid)
    dft_grid = _norm(dft_grid)
    product = _norm(acf_grid * dft_grid)

    return TempoCurve(bpms=bpm_grid, salience=product, acf=acf_grid, dft=dft_grid)


def _resample_to_grid(src_bpms: np.ndarray, src_vals: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Interpolate a (possibly non-monotonic / inf-laden) tempo curve onto ``grid``."""
    bpms = np.asarray(src_bpms, dtype=np.float64)
    vals = np.asarray(src_vals, dtype=np.float64)
    good = np.isfinite(bpms) & np.isfinite(vals) & (bpms > 0)
    bpms, vals = bpms[good], vals[good]
    if bpms.size == 0:
        return np.zeros_like(grid)
    order = np.argsort(bpms)
    bpms, vals = bpms[order], vals[order]
    # Collapse duplicate BPMs (can happen at coarse lags) by max.
    uniq, idx = np.unique(bpms, return_inverse=True)
    if uniq.size != bpms.size:
        agg = np.zeros(uniq.size)
        np.maximum.at(agg, idx, vals)
        bpms, vals = uniq, agg
    return np.interp(grid, bpms, vals, left=0.0, right=0.0)


def build_combined_envelope(bands: BandEnvelopes, cfg: TempoConfig) -> np.ndarray:
    """Weighted combination of band envelopes for the primary tempogram."""
    w_low, w_mid, w_high = cfg.band_weights
    return w_low * _norm(bands.low) + w_mid * _norm(bands.mid) + w_high * _norm(bands.high)


def build_features(signal: AudioSignal, cfg: TempoConfig) -> Features:
    """Compute everything the evidence terms need, exactly once."""
    bands = compute_band_envelopes(signal.y, signal.sr, hop_length=HOP_LENGTH)
    grid = _bpm_grid(cfg)

    combined = build_combined_envelope(bands, cfg)
    tempo_curve = product_tempogram(combined, signal.sr, bands.hop_length, grid)
    high_curve = product_tempogram(bands.high, signal.sr, bands.hop_length, grid)

    return Features(
        sr=signal.sr,
        hop_length=bands.hop_length,
        duration=signal.duration,
        bands=bands,
        tempo_curve=tempo_curve,
        high_curve=high_curve,
    )


def curve_peaks(
    curve: TempoCurve, n: int = 8, min_salience: float = 0.05, min_separation_bpm: float = 4.0
) -> list[tuple[float, float]]:
    """Return up to ``n`` (bpm, salience) peaks of a tempo curve, strongest first."""
    from scipy.signal import find_peaks

    sal = curve.salience
    if sal.size == 0 or float(np.max(sal)) <= _EPS:
        return []
    step = curve.bpms[1] - curve.bpms[0]
    distance = max(1, int(round(min_separation_bpm / step)))
    idx, _ = find_peaks(sal, height=min_salience, distance=distance)
    if idx.size == 0:
        idx = np.array([int(np.argmax(sal))])
    peaks = sorted(((float(curve.bpms[i]), float(sal[i])) for i in idx), key=lambda p: -p[1])
    return peaks[:n]


def refine_bpm(
    env: np.ndarray, sr: int, hop_length: int, bpm0: float, rel: float = 0.06, smooth: float = 2.0
) -> float:
    """Refine a coarse BPM estimate to sub-grid precision.

    Finds the autocorrelation peak of the (lightly smoothed) onset envelope in a
    narrow lag window around ``bpm0`` and parabolically interpolates it to a
    fractional lag. The smoothing is essential: a near-impulse onset envelope
    has a combed autocorrelation that biases a raw fractional-lag search, so we
    broaden the onset peaks first, then refine. This recovers DAW-marker
    precision (e.g. 153.85 rather than 154.0) once the octave is chosen.
    """
    from scipy.ndimage import gaussian_filter1d

    env = np.asarray(env, dtype=np.float64)
    if env.size < 16 or bpm0 <= 0:
        return float(bpm0)
    e = gaussian_filter1d(env, sigma=smooth)
    e = e - e.mean()
    if np.linalg.norm(e) <= _EPS:
        return float(bpm0)

    # FFT autocorrelation (positive lags).
    m = e.size
    nfft = 1 << int(np.ceil(np.log2(2 * m)))
    spec = np.fft.rfft(e, nfft)
    acf = np.fft.irfft(spec * np.conj(spec), nfft)[:m]

    fps = sr / hop_length
    lag0 = 60.0 * fps / bpm0
    lo = max(1, int(np.floor(lag0 * (1 - rel))))
    hi = min(m - 2, int(np.ceil(lag0 * (1 + rel))))
    if hi <= lo:
        return float(bpm0)

    li = lo + int(np.argmax(acf[lo : hi + 1]))
    # Parabolic interpolation around the integer-lag peak for sub-frame precision.
    y0, y1, y2 = acf[li - 1], acf[li], acf[li + 1]
    denom = y0 - 2 * y1 + y2
    delta = 0.5 * (y0 - y2) / denom if abs(denom) > _EPS else 0.0
    delta = float(np.clip(delta, -0.5, 0.5))
    lag_star = li + delta
    return float(60.0 * fps / lag_star) if lag_star > 0 else float(bpm0)
