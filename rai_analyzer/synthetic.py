"""Synthetic test-signal generators.

The real ground-truth WAVs are provided by the producer as drop-in fixtures and
are not in the repo. To self-verify the engine without them, these generators
produce signals with *known* tempo structure — including the octave pathology
the engine exists to solve: a strong half-time backbeat (which pulls the
autocorrelation toward bpm/2) combined with a busy hi-hat stream (which is the
high-band evidence for the true, notated bpm).

Shared by the unit tests, the evidence-term agents, and the validation
harness's self-test. Pure numpy; ``write_wav`` needs soundfile.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import ANALYSIS_SR
from .io_audio import AudioSignal

# 16th-note positions (0..15) per 4/4 bar for the synthetic drill kit.
_KICK_STEPS = (0, 3, 6, 10)  # syncopated, tresillo-flavoured
_SNARE_STEPS = (4, 12)  # backbeat on 2 & 4 -> pulse at bpm/2 (the half-time trap)
_HAT_STEPS = tuple(range(16))  # straight 16ths -> tatum at 4x bpm


def _env(n: int, decay: float, sr: int) -> np.ndarray:
    t = np.arange(n) / sr
    return np.exp(-t / decay)


def synth_kick(sr: int, dur: float = 0.22) -> np.ndarray:
    n = int(sr * dur)
    t = np.arange(n) / sr
    f = 110.0 * np.exp(-t / 0.03) + 45.0  # pitch drop
    return (np.sin(2 * np.pi * np.cumsum(f) / sr) * _env(n, 0.16, sr)).astype(np.float32)


def synth_snare(sr: int, dur: float = 0.18, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(0)
    n = int(sr * dur)
    noise = rng.standard_normal(n)
    # crude band emphasis (200 Hz - 4 kHz) via first-difference + smoothing
    body = np.sin(2 * np.pi * 185.0 * np.arange(n) / sr)
    return ((0.7 * noise + 0.5 * body) * _env(n, 0.12, sr)).astype(np.float32)


def synth_hat(sr: int, dur: float = 0.05, rng: np.random.Generator | None = None) -> np.ndarray:
    rng = rng or np.random.default_rng(1)
    n = int(sr * dur)
    noise = rng.standard_normal(n)
    # high-pass-ish: emphasise fast oscillation so energy sits above ~8 kHz
    hp = np.diff(noise, prepend=noise[0])
    hp = np.diff(hp, prepend=hp[0])
    return (hp * _env(n, 0.02, sr)).astype(np.float32)


def _place(out: np.ndarray, sample: np.ndarray, idx: int, gain: float) -> None:
    end = min(idx + sample.size, out.size)
    if idx < out.size:
        out[idx:end] += gain * sample[: end - idx]


def click_track(
    bpm: float, duration: float = 20.0, sr: int = ANALYSIS_SR, seed: int = 0
) -> np.ndarray:
    """A plain metronome: one broadband click per beat. Unambiguous tempo."""
    rng = np.random.default_rng(seed)
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float32)
    click = synth_hat(sr, dur=0.04, rng=rng)  # single clean broadband transient per beat
    beat = 60.0 / bpm
    t = 0.0
    while t < duration:
        _place(out, click, int(t * sr), 1.0)
        t += beat
    return _normalize(out)


def drill_pattern(
    bpm: float,
    duration: float = 24.0,
    sr: int = ANALYSIS_SR,
    seed: int = 0,
    half_time_emphasis: float = 1.4,
) -> np.ndarray:
    """A synthetic drill beat whose NOTATED tempo is ``bpm``.

    The snare backbeat (2 & 4) is emphasised so the raw autocorrelation is pulled
    toward the half-time ``bpm/2`` pulse, while straight-16th hats provide the
    high-band evidence for the true ``bpm``. This is the octave ambiguity in
    miniature: a correct engine surfaces both bpm and bpm/2 and either resolves
    to bpm or flags ambiguity — it must not silently report bpm/2.
    """
    rng = np.random.default_rng(seed)
    n = int(duration * sr)
    out = np.zeros(n, dtype=np.float32)

    kick = synth_kick(sr)
    snare = synth_snare(sr, rng=rng)
    hat = synth_hat(sr, rng=rng)

    sixteenth = 60.0 / bpm / 4.0
    bar = 16 * sixteenth
    n_bars = int(duration / bar) + 1

    for b in range(n_bars):
        bar_t = b * bar
        for s in _KICK_STEPS:
            _place(out, kick, int((bar_t + s * sixteenth) * sr), rng.uniform(0.9, 1.0))
        for s in _SNARE_STEPS:
            _place(
                out, snare, int((bar_t + s * sixteenth) * sr), half_time_emphasis * rng.uniform(0.9, 1.0)
            )
        for s in _HAT_STEPS:
            _place(out, hat, int((bar_t + s * sixteenth) * sr), rng.uniform(0.3, 0.55))

    out += 0.002 * rng.standard_normal(n).astype(np.float32)  # light noise floor
    return _normalize(out)


def _normalize(y: np.ndarray, peak: float = 0.89) -> np.ndarray:
    m = float(np.max(np.abs(y))) if y.size else 0.0
    return (y * (peak / m)).astype(np.float32) if m > 0 else y


def as_signal(y: np.ndarray, sr: int = ANALYSIS_SR, path: str = "<synthetic>") -> AudioSignal:
    """Wrap a mono array as an :class:`AudioSignal` for direct ``build_features`` use."""
    y = np.ascontiguousarray(y, dtype=np.float32)
    return AudioSignal(
        path=path, y=y, sr=sr, y_native=y, sr_native=sr, channels=1, duration=y.size / sr
    )


def write_wav(path: str, y: np.ndarray, sr: int = ANALYSIS_SR) -> str:
    """Write a mono signal to a 16-bit WAV (for harness/GUI fixtures)."""
    import soundfile as sf

    sf.write(path, np.asarray(y, dtype=np.float32), sr, subtype="PCM_16")
    return path
