"""Audio analysis primitives: load WAV, peak/RMS, BPM estimation.

v2 additions (appended below the v1 functions, which are unchanged):
    load_wav_full, compute_lufs_approx, compute_dynamic_range,
    compute_spectrum, compute_band_energies, compute_stereo_width

v3 additions (appended below v2 — v1 and v2 are unchanged):
    TrackMetrics dataclass, analyze_track, compare_tracks
    These compose the v1/v2 primitives so compare-mode (and any future
    target-profile evaluation) can pass a single TrackMetrics snapshot
    around instead of re-running primitives.
"""

import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import scipy.signal as _sig
from scipy.io import wavfile


def load_wav(path):
    """Load a WAV file and return (mono_samples_float32, sample_rate, duration_sec).

    Samples are normalized to the range [-1.0, 1.0]. Stereo is downmixed to mono.
    """
    sr, data = wavfile.read(path)

    # Normalize to float [-1, 1] based on the source dtype.
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    elif data.dtype == np.uint8:
        data = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.float32:
        pass
    elif data.dtype == np.float64:
        data = data.astype(np.float32)
    else:
        data = data.astype(np.float32)

    # Downmix to mono if multichannel.
    if data.ndim > 1:
        data = data.mean(axis=1)

    duration = len(data) / float(sr)
    return data, sr, duration


def compute_peak_dbfs(samples):
    """Peak amplitude in dBFS. Returns -inf for pure silence."""
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * np.log10(peak)


def compute_rms_dbfs(samples):
    """RMS level in dBFS. Returns -inf for pure silence."""
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * np.log10(rms)


def estimate_bpm(samples, sr, min_bpm=60.0, max_bpm=200.0):
    """Approximate BPM via energy-envelope autocorrelation.

    Steps:
      1. Frame energy with 1024-sample window, 512 hop.
      2. Half-wave-rectified first difference -> onset envelope.
      3. Autocorrelate envelope; pick the strongest lag inside the BPM range.
    """
    if samples.size < sr:  # need at least ~1 second
        return 0.0

    hop = 512
    win = 1024
    n_frames = 1 + (len(samples) - win) // hop
    if n_frames < 4:
        return 0.0

    # Per-frame energy.
    energy = np.empty(n_frames, dtype=np.float64)
    for i in range(n_frames):
        start = i * hop
        chunk = samples[start:start + win]
        energy[i] = np.sum(chunk * chunk)

    # Onset envelope: positive part of the first difference.
    diff = np.diff(energy)
    onset = np.maximum(diff, 0.0)

    # Subtract local mean and normalize so autocorrelation is well-behaved.
    onset = onset - onset.mean()
    peak = np.max(np.abs(onset))
    if peak == 0.0:
        return 0.0
    onset = onset / peak

    # Autocorrelation (positive lags only).
    ac = np.correlate(onset, onset, mode="full")
    ac = ac[ac.size // 2:]

    frame_rate = sr / hop  # frames per second
    min_lag = max(1, int(round(frame_rate * 60.0 / max_bpm)))
    max_lag = int(round(frame_rate * 60.0 / min_bpm))
    max_lag = min(max_lag, ac.size - 1)
    if max_lag <= min_lag:
        return 0.0

    search = ac[min_lag:max_lag + 1]
    best_lag = int(np.argmax(search)) + min_lag
    if best_lag <= 0:
        return 0.0

    bpm = 60.0 * frame_rate / best_lag
    return float(round(bpm, 1))


# ---------------------------------------------------------------------------
# v2 additions
# ---------------------------------------------------------------------------


def load_wav_full(path):
    """Like load_wav, but also returns the raw multichannel array.

    Returns: (mono_samples, sample_rate, duration_sec, raw_channels)
      - mono_samples: 1-D float32, [-1, 1], same as load_wav()
      - raw_channels: ndarray with shape (N, n_channels) for multichannel,
        or 1-D for mono. Used by stereo-width analysis.
    """
    sr, data = wavfile.read(path)

    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    elif data.dtype == np.uint8:
        data = (data.astype(np.float32) - 128.0) / 128.0
    elif data.dtype == np.float32:
        pass
    elif data.dtype == np.float64:
        data = data.astype(np.float32)
    else:
        data = data.astype(np.float32)

    raw = data
    if data.ndim > 1:
        mono = data.mean(axis=1).astype(np.float32)
    else:
        mono = data

    duration = len(mono) / float(sr)
    return mono, sr, duration, raw


# ITU-R BS.1770-4 K-weighting biquad coefficients (designed for 48 kHz).
# Used directly at any sample rate; the response is approximate elsewhere,
# which matches the spec's "no need for full standard compliance" relaxation.
_K_PRE_B = np.array([1.53512485958697, -2.69169618940638, 1.19839281085285])
_K_PRE_A = np.array([1.0, -1.69065929318241, 0.73248077421585])
_K_RLB_B = np.array([1.0, -2.0, 1.0])
_K_RLB_A = np.array([1.0, -1.99004745483398, 0.99007225036621])


def compute_lufs_approx(samples, sr):
    """Approximate integrated loudness in LUFS.

    Applies BS.1770 K-weighting (high-shelf "pre-filter" + RLB high-pass) and
    converts the mean square to LUFS via the standard -0.691 dB offset. No
    block-based gating: this is a simple integrated estimate, not a full
    BS.1770 implementation.
    """
    if samples.size == 0:
        return float("-inf")

    x = samples.astype(np.float64)
    y = _sig.lfilter(_K_PRE_B, _K_PRE_A, x)
    y = _sig.lfilter(_K_RLB_B, _K_RLB_A, y)

    mean_sq = float(np.mean(y * y))
    if mean_sq <= 0.0:
        return float("-inf")
    return -0.691 + 10.0 * np.log10(mean_sq)


def compute_dynamic_range(peak_db, rms_db):
    """Crest factor: Peak (dBFS) - RMS (dBFS), in dB.

    Returns 0.0 if either input is non-finite (e.g. silence).
    """
    if not np.isfinite(peak_db) or not np.isfinite(rms_db):
        return 0.0
    return float(peak_db - rms_db)


def compute_spectrum(samples, sr, nperseg=8192):
    """Averaged power spectrum via Welch's method, restricted to 20 Hz – 20 kHz.

    Returns (freqs_hz, magnitudes_db). Uses a Hann window and 50% overlap.
    """
    if samples.size == 0:
        return np.array([]), np.array([])

    n = int(min(nperseg, samples.size))
    if n < 64:
        return np.array([]), np.array([])

    freqs, psd = _sig.welch(samples.astype(np.float64), fs=sr, nperseg=n)
    mask = (freqs >= 20.0) & (freqs <= 20000.0)
    f = freqs[mask]
    p = psd[mask]
    db = 10.0 * np.log10(p + 1e-12)
    return f, db


def compute_band_energies(samples, sr, bands, nperseg=8192):
    """Relative energy per band, expressed as % of audible-range total.

    bands: iterable of (name, low_hz, high_hz). The denominator is the
    integrated PSD over 20 Hz – 20 kHz, so values are intuitive percentages
    of "what you can hear" rather than of the full Nyquist range.
    """
    names = [b[0] for b in bands]
    if samples.size == 0:
        return {name: 0.0 for name in names}

    n = int(min(nperseg, samples.size))
    if n < 64:
        return {name: 0.0 for name in names}

    freqs, psd = _sig.welch(samples.astype(np.float64), fs=sr, nperseg=n)

    audible = (freqs >= 20.0) & (freqs <= 20000.0)
    total = float(np.sum(psd[audible]))
    if total <= 0.0:
        return {name: 0.0 for name in names}

    out = {}
    for name, lo, hi in bands:
        m = (freqs >= lo) & (freqs < hi)
        out[name] = float(np.sum(psd[m]) / total * 100.0)
    return out


def compute_stereo_width(raw_channels):
    """Classify stereo width from raw channel data.

    Uses the side/(mid+side) energy ratio. A true mono signal in a stereo
    container scores 0; perfectly uncorrelated channels score ~0.5.

    Returns one of: 'Mono', 'Narrow', 'Balanced', 'Wide'.
    """
    if (
        raw_channels is None
        or raw_channels.ndim < 2
        or raw_channels.shape[1] < 2
    ):
        return "Mono"

    L = raw_channels[:, 0].astype(np.float64)
    R = raw_channels[:, 1].astype(np.float64)

    mid = 0.5 * (L + R)
    side = 0.5 * (L - R)

    mid_e = float(np.sum(mid * mid))
    side_e = float(np.sum(side * side))

    if mid_e + side_e <= 0.0:
        return "Mono"

    ratio = side_e / (mid_e + side_e)

    if ratio < 0.02:
        return "Mono"
    if ratio < 0.10:
        return "Narrow"
    if ratio < 0.30:
        return "Balanced"
    return "Wide"


# ---------------------------------------------------------------------------
# v3 additions: TrackMetrics + compare logic
# ---------------------------------------------------------------------------


# Frequency bands for the low-end analysis. Kept here so analyze_track is the
# single source of truth for what gets computed; the UI can still override
# them by calling compute_band_energies directly if needed.
_DEFAULT_LOW_BANDS = [
    ("Sub", 20.0, 60.0),
    ("Bass", 60.0, 120.0),
]


@dataclass
class TrackMetrics:
    """Snapshot of all v2 metrics for a single audio file.

    The fields are split into three groups: identification (file_name etc.),
    scalar metrics (bpm, peak_db, ...), and plot-ready arrays (samples,
    spectrum_*). The plot data is optional so future callers — e.g. a target-
    profile evaluator — can construct a TrackMetrics from numbers alone
    without paying for FFT plots.
    """

    file_name: str = ""
    duration: float = 0.0
    sample_rate: int = 0
    channels: int = 1

    bpm: float = 0.0
    peak_db: float = float("-inf")
    rms_db: float = float("-inf")
    lufs: float = float("-inf")
    dynamic_range: float = 0.0
    sub_pct: float = 0.0
    bass_pct: float = 0.0
    stereo_width: str = "Mono"

    # Plot-ready arrays. Optional so non-UI callers can skip them.
    samples: Optional[np.ndarray] = field(default=None, repr=False)
    spectrum_freqs: Optional[np.ndarray] = field(default=None, repr=False)
    spectrum_db: Optional[np.ndarray] = field(default=None, repr=False)


def analyze_track(path):
    """Run all v1+v2 metrics on a WAV file and return a TrackMetrics.

    This is the single entry point for compare-mode workflows. To add target-
    profile evaluation in the future, write a separate
    ``evaluate_against_target(metrics, target) -> list[str]`` that consumes
    a TrackMetrics — keeping pairwise comparison and target evaluation as
    independent steps over the same snapshot type.
    """
    mono, sr, dur, raw = load_wav_full(path)

    peak = compute_peak_dbfs(mono)
    rms = compute_rms_dbfs(mono)
    lufs = compute_lufs_approx(mono, sr)
    dr = compute_dynamic_range(peak, rms)
    bpm = estimate_bpm(mono, sr)
    bands = compute_band_energies(mono, sr, _DEFAULT_LOW_BANDS)
    width = compute_stereo_width(raw)
    freqs, db = compute_spectrum(mono, sr)

    n_ch = int(raw.shape[1]) if raw.ndim > 1 else 1

    return TrackMetrics(
        file_name=os.path.basename(path),
        duration=float(dur),
        sample_rate=int(sr),
        channels=n_ch,
        bpm=float(bpm),
        peak_db=float(peak),
        rms_db=float(rms),
        lufs=float(lufs),
        dynamic_range=float(dr),
        sub_pct=float(bands.get("Sub", 0.0)),
        bass_pct=float(bands.get("Bass", 0.0)),
        stereo_width=str(width),
        samples=mono,
        spectrum_freqs=freqs,
        spectrum_db=db,
    )


def _format_delta(name, val_a, val_b, unit, descriptor, mode="is", precision=1):
    """Render one pairwise difference as a short human-readable line.

    mode='is'  -> "Track A is 1.8 dB louder"
    mode='has' -> "Track A has 5.2% more sub"

    Returns "<name>: identical" if the difference rounds to zero, and
    "<name>: -" if either input is non-finite (silence).
    """
    if not (np.isfinite(val_a) and np.isfinite(val_b)):
        return f"{name}: -"

    diff = val_a - val_b
    threshold = 0.5 * (10 ** -precision)
    if abs(diff) < threshold:
        return f"{name}: identical"

    who = "Track A" if diff > 0 else "Track B"
    verb = "is" if mode == "is" else "has"
    amount = f"{abs(diff):.{precision}f}"
    return f"{name}: {who} {verb} {amount}{unit} {descriptor}"


def compare_tracks(a, b):
    """Return human-readable difference lines for two TrackMetrics.

    Output is a flat list of strings ready for display. The same shape will
    work for a future ``evaluate_against_target()`` that returns target-fit
    lines like "Sub Energy: within target", so the delta UI panel can render
    either one without structural changes.
    """
    return [
        _format_delta("BPM",         a.bpm,           b.bpm,           " BPM", "faster",       mode="is"),
        _format_delta("Peak",        a.peak_db,       b.peak_db,       " dB",  "hotter",       mode="is"),
        _format_delta("RMS",         a.rms_db,        b.rms_db,        " dB",  "louder",       mode="is"),
        _format_delta("LUFS",        a.lufs,          b.lufs,          " LU",  "louder",       mode="is"),
        _format_delta("DR",          a.dynamic_range, b.dynamic_range, " dB",  "more dynamic", mode="is"),
        _format_delta("Sub Energy",  a.sub_pct,       b.sub_pct,       "%",    "more sub",     mode="has"),
        _format_delta("Bass Energy", a.bass_pct,      b.bass_pct,      "%",    "more bass",    mode="has"),
    ]
