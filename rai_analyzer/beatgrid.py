"""Beat-phase estimation — where beat one sits, given a resolved tempo (M2).

NEW in M2 and strictly additive: nothing in the frozen engine imports this
module. It reuses the engine's own machinery read-only (ruling R-M2-14 — one
truth beats decoupling): the per-band onset envelopes already living in
``Features.bands``, the combined-envelope weighting from
:func:`rai_analyzer.tempogram.build_combined_envelope`, and the metrical fold
from :func:`rai_analyzer.evidence.fingerprint.fold_to_grid`.

How it works
------------
The combined onset envelope is first resampled onto a fine time grid
(``_ENVELOPE_OVERSAMPLE`` x the frame rate, linear interpolation). This is an
anti-aliasing step: raw frames arrive every ~23.2 ms (hop 512 @ 22050 Hz)
while the fold's sub-beat bins are ~15.6 ms at 120 BPM, so folding raw frames
leaves some bins empty and others double-filled — spurious profile structure
that both distorts the onset edge and inflates sharpness on structureless
input. After resampling every bin receives many samples and the folded
profile tracks the true envelope shape.

The resampled envelope is folded onto a fine sub-beat grid (32 bins per beat)
at the given tempo. ``fold_to_grid``'s sub-bin phase search aligns the grid
to the groove; the folded profile is then an "eye diagram" of the beat —
energy piles up where the onsets sit.

Onset location: leading edge, not centroid
------------------------------------------
The onset is located by *leading-edge detection* on the folded profile:
walking backward (circularly) from the profile peak to the first bin below a
threshold at ``_EDGE_FRACTION`` (one half) of the peak height above the
circular baseline (the profile median), then linearly interpolating the
crossing to sub-bin precision. The half-rise crossing tracks the *attack
start* of the onset-envelope response, which is set by the analysis window
sliding onto the transient and is therefore nearly identical for every click
shape. A circular energy *centroid* (the previous estimator) is
click-shape-dependent: it pulls toward the energy tail of long decays, so a
constant calibrated on one fixture misplaces every other transient shape
(measured: a 40 ms hat read ~43 ms while a 1-sample impulse read ~17.5 ms —
a ~26 ms shape-dependent spread, blowing the ±10 ms budget of R-M2-14).

The onset-lag constant
----------------------
``ONSET_LAG_SECONDS`` is the residual bias of the half-rise leading-edge
crossing, CALIBRATED on synthetic 1-sample-impulse click tracks (first click
exactly at t=0) across 90/120/153.85/166.01 BPM: raw detected phases were
+0.2/+3.1/-0.8/-1.2 ms, so the constant is their mean, 0.0003 s. It is nearly
zero because librosa's mel/onset chain uses *centered* STFT frames — energy
smears symmetrically around the transient, so the half-rise of the flux
response sits almost exactly on the onset itself. (The previous constant,
0.0433 s, was an estimator artifact, not a chain property: ~17.5 ms of it was
the flux-chain response as read by the centroid on an impulse, and the
remaining ~26 ms was the energy-centroid pull of the 40 ms calibration
fixture's decay tail.) The click-track tests in ``tests/test_beatgrid.py``
re-derive the ±10 ms bound across five click shapes (40 ms hat, 5 ms burst,
2 ms click, 1-sample impulse, synthetic snare) on every run.

Confidence: null-normalized sharpness
-------------------------------------
Raw fold sharpness (peak/mean of the profile) is biased upward on short
structureless input: ``fold_to_grid`` returns the sharpest profile over its
32 phase offsets (a max-selection bias) and short files fold few envelope
samples per bin (high variance). Raw sharpness therefore read 4 s of white
noise as sharpness ~3 (old confidence 0.66-0.81, above real-groove bars).
The fix measures that bias *on the same envelope*: the envelope is re-folded
at four detuned tempos (``bpm * f`` and ``bpm / f`` for the incommensurate
factors ``_NULL_DETUNE_FACTORS``, chosen to avoid simple ratios that alias
with real grooves), where any true groove smears out but every bias mechanism
still operates. Confidence is the clamped excess of the target sharpness over
the mean null sharpness::

    confidence = clamp(1 - null_sharpness / target_sharpness, 0, 1)

Structureless input scores ~0 (target ≈ null, both inflated by the same
bias); a clean groove scores high (target >> null). Always in [0, 1], never
NaN.

Degenerate policy (documented choice per the brief): a non-finite or
non-positive ``bpm`` raises ``ValueError`` — a resolved tempo is this
function's precondition, so a garbage BPM is a programming error, not a
measurement outcome. Silence / empty envelopes are measurement outcomes and
return ``confidence 0.0`` (phase 0.0, never NaN).

Engine-only in M2: not part of ``SignalResult``; M3 wires the click preview.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import DEFAULT_CONFIG
from .contracts import Features
from .evidence.fingerprint import fold_to_grid
from .tempogram import build_combined_envelope

#: Residual bias of the half-rise leading-edge onset locator, seconds (see
#: module docstring — calibrated on 1-sample-impulse click tracks). Applied
#: as ``phase = (raw_edge_position - ONSET_LAG_SECONDS) % period``.
ONSET_LAG_SECONDS = 0.0003

#: Sub-beat grid resolution for the fold. 32 bins/beat keeps single-bin error
#: below ~7 ms at 90 BPM even before the sub-bin edge interpolation.
_BINS_PER_BEAT = 32

#: Phase-search granularity handed to ``fold_to_grid`` (spans one bin).
_PHASE_SEARCH_STEPS = 32

#: Envelope oversampling factor before folding (anti-aliasing; see module
#: docstring). 8x turns ~23.2 ms frames into ~2.9 ms samples, so every
#: ~15-21 ms fold bin receives several samples at any tempo in range.
_ENVELOPE_OVERSAMPLE = 8

#: Leading-edge threshold, as a fraction of peak height above the circular
#: baseline. One half = the standard half-rise crossing.
_EDGE_FRACTION = 0.5

#: Detuned-tempo factors for the confidence null (each used as bpm*f and
#: bpm/f). Incommensurate with the simple integer ratios (2, 3/2, 4/3, ...)
#: that a real groove's subdivisions could alias with.
_NULL_DETUNE_FACTORS = (1.0732, 1.0891)


@dataclass(frozen=True)
class BeatGrid:
    """A beat grid anchored in absolute file time."""

    phase_seconds: float  # first-beat offset in [0, period), lag-corrected
    period_seconds: float  # 60 / bpm
    confidence: float  # 0..1; 0.0 for silence/degenerate audio


def _resample_envelope(env: np.ndarray, times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Linearly resample the onset envelope onto a fine, uniform time grid.

    Defensive on shape/values: lengths are matched, non-finite values are
    zeroed and negatives clipped (onset strength is non-negative energy), so
    the fold and the sharpness statistics can never go NaN downstream.
    """
    env = np.nan_to_num(
        np.asarray(env, dtype=np.float64), nan=0.0, posinf=0.0, neginf=0.0
    )
    np.maximum(env, 0.0, out=env)
    times = np.asarray(times, dtype=np.float64)
    m = min(env.size, times.size)
    env, times = env[:m], times[:m]
    if m < 2:
        return env, times
    dt = float(times[1] - times[0]) / _ENVELOPE_OVERSAMPLE
    if not np.isfinite(dt) or dt <= 0.0:
        return env, times
    t_fine = np.arange(times[0], times[-1], dt)
    return np.interp(t_fine, times, env), t_fine


def _sharpness(profile: np.ndarray) -> float:
    """Peak-to-mean of a folded profile (>= 1 for any non-degenerate fold)."""
    if profile.size == 0:
        return 0.0
    peak = float(np.max(profile))
    mean = float(profile.mean())
    return peak / mean if mean > 0.0 else 0.0


def _leading_edge_position(profile: np.ndarray) -> float:
    """Continuous bin coordinate of the onset's leading edge (see module doc).

    Walks backward (circularly) from the profile peak to the first bin below
    the half-rise threshold, then linearly interpolates the crossing. Bin
    ``k`` aggregates the envelope over ``[k, k+1)`` bins, so its mass center
    is the coordinate ``k + 0.5``. Falls back to the peak center if the
    profile never drops below threshold within one beat (near-flat profile —
    the phase is then meaningless anyway and confidence will be ~0).
    """
    bins = profile.size
    idx = int(np.argmax(profile))
    peak = float(profile[idx])
    baseline = float(np.median(profile))
    threshold = baseline + _EDGE_FRACTION * (peak - baseline)
    limit = min(_BINS_PER_BEAT, bins - 1)
    for k in range(1, limit + 1):
        below = float(profile[(idx - k) % bins])
        if below < threshold:
            above = float(profile[(idx - k + 1) % bins])
            frac = (threshold - below) / (above - below)
            return (idx - k + 0.5) + frac
    return idx + 0.5


def _null_normalized_confidence(
    env: np.ndarray,
    times: np.ndarray,
    bpm: float,
    beats_per_bar: int,
    target_profile: np.ndarray,
) -> float:
    """Confidence = clamped excess of target sharpness over the detuned null."""
    target = _sharpness(target_profile)
    if target <= 0.0:
        return 0.0
    bins = _BINS_PER_BEAT * beats_per_bar
    nulls = []
    for factor in _NULL_DETUNE_FACTORS:
        for null_bpm in (bpm * factor, bpm / factor):
            null_profile, _ = fold_to_grid(
                env,
                times,
                null_bpm,
                bins_per_bar=bins,
                beats_per_bar=beats_per_bar,
                phase_search_steps=_PHASE_SEARCH_STEPS,
            )
            nulls.append(_sharpness(null_profile))
    null_ref = float(np.mean(nulls)) if nulls else 0.0
    if null_ref <= 0.0:
        # Energy conservation makes this unreachable for a non-degenerate
        # target fold; stay conservative (and NaN-free) if it ever happens.
        return 0.0
    return float(min(1.0, max(0.0, 1.0 - null_ref / target)))


def estimate_beat_phase(features: Features, bpm: float, beats_per_bar: int = 4) -> BeatGrid:
    """Estimate where the beat sits, modulo the beat period, at ``bpm``.

    Parameters
    ----------
    features:
        The engine's per-file :class:`~rai_analyzer.contracts.Features`
        (already computed once per analysis — no audio reload needed).
    bpm:
        The resolved tempo. Must be finite and positive (``ValueError``
        otherwise — see module docstring).
    beats_per_bar:
        Metre for the fold (4/4 default). The fold runs at bar length so the
        grid alignment sees the full metrical pattern; the returned phase is
        reduced modulo one beat.
    """
    bpm = float(bpm)
    if not np.isfinite(bpm) or bpm <= 0.0:
        raise ValueError(f"bpm must be finite and positive, got {bpm!r}")
    beats_per_bar = int(beats_per_bar)
    if beats_per_bar <= 0:
        raise ValueError(f"beats_per_bar must be positive, got {beats_per_bar!r}")

    period = 60.0 / bpm
    env = build_combined_envelope(features.bands, DEFAULT_CONFIG)
    env, times = _resample_envelope(env, features.bands.times)

    bins = _BINS_PER_BEAT * beats_per_bar
    profile, grid_phase = fold_to_grid(
        env,
        times,
        bpm,
        bins_per_bar=bins,
        beats_per_bar=beats_per_bar,
        phase_search_steps=_PHASE_SEARCH_STEPS,
    )

    peak = float(np.max(profile)) if profile.size else 0.0
    if peak <= 0.0:
        # Silence / degenerate envelope: nothing to lock onto.
        return BeatGrid(phase_seconds=0.0, period_seconds=period, confidence=0.0)

    bar_seconds = beats_per_bar * period
    bin_seconds = bar_seconds / bins

    # Leading-edge onset locator (shape-robust; see module docstring).
    edge_bins = _leading_edge_position(profile)
    raw_position = grid_phase + edge_bins * bin_seconds
    phase = float(np.mod(raw_position - ONSET_LAG_SECONDS, period))

    confidence = _null_normalized_confidence(env, times, bpm, beats_per_bar, profile)

    return BeatGrid(phase_seconds=phase, period_seconds=period, confidence=confidence)
