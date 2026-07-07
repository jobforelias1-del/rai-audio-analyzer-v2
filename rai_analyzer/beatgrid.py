"""Beat-phase estimation — where beat one sits, given a resolved tempo (M2).

NEW in M2 and strictly additive: nothing in the frozen engine imports this
module. It reuses the engine's own machinery read-only (ruling R-M2-14 — one
truth beats decoupling): the per-band onset envelopes already living in
``Features.bands``, the combined-envelope weighting from
:func:`rai_analyzer.tempogram.build_combined_envelope`, and the metrical fold
from :func:`rai_analyzer.evidence.fingerprint.fold_to_grid`.

How it works
------------
Fold the combined onset envelope onto a fine sub-beat grid (32 bins per beat)
at the given tempo. ``fold_to_grid``'s sub-bin phase search aligns the grid to
the groove; the folded profile is then an "eye diagram" of the beat — energy
piles up where the onsets sit. The circular energy centroid around the profile
peak gives the onset position modulo the beat period at well-under-frame
resolution (frame times are folded as continuous float64, so many bars sample
sub-frame offsets — the same property that gives the fingerprint term its
~6 ms phase quantum).

The onset-lag constant
----------------------
librosa's spectral-flux envelope peaks slightly *after* each transient. The
engine never needed a number for that lag — the fingerprint comparison is
rotation-invariant — but an absolute beat-one time must subtract it.
``ONSET_LAG_SECONDS`` is CALIBRATED against synthetic click tracks (first
click exactly at t=0) across 90/120/153.85/166.01 BPM: raw detected phases
were 44.5/43.3/42.6/42.9 ms, so the constant is their center, 0.0433 s. The
click-track tests in ``tests/test_beatgrid.py`` re-derive this bound (|error|
<= 10 ms after correction) on every run.

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

#: Spectral-flux onset-envelope lag, seconds (see module docstring). Applied
#: as ``phase = (raw_peak_position - ONSET_LAG_SECONDS) % period``.
ONSET_LAG_SECONDS = 0.0433

#: Sub-beat grid resolution for the fold. 32 bins/beat keeps single-bin error
#: below ~7 ms at 90 BPM even before the centroid refinement.
_BINS_PER_BEAT = 32

#: Phase-search granularity handed to ``fold_to_grid`` (spans one bin).
_PHASE_SEARCH_STEPS = 32

#: Circular centroid half-width (bins) around the profile peak.
_CENTROID_HALFWIDTH = 5


@dataclass(frozen=True)
class BeatGrid:
    """A beat grid anchored in absolute file time."""

    phase_seconds: float  # first-beat offset in [0, period), lag-corrected
    period_seconds: float  # 60 / bpm
    confidence: float  # 0..1; 0.0 for silence/degenerate audio


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
    times = features.bands.times

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

    # Circular energy centroid around the peak bin -> sub-bin onset position.
    idx = int(np.argmax(profile))
    offsets = np.arange(-_CENTROID_HALFWIDTH, _CENTROID_HALFWIDTH + 1)
    neighborhood = profile[(idx + offsets) % bins]
    weight = float(neighborhood.sum())
    delta = float(np.sum(offsets * neighborhood) / weight) if weight > 0.0 else 0.0

    raw_position = grid_phase + (idx + 0.5 + delta) * bin_seconds
    phase = float(np.mod(raw_position - ONSET_LAG_SECONDS, period))

    # Confidence from fold sharpness: peak-to-mean of the folded profile,
    # mapped to [0, 1) via 1 - 1/sharpness (flat profile -> 0, clean groove
    # -> ~0.9). Monotone in sharpness, never NaN.
    mean = float(profile.mean())
    sharpness = peak / mean if mean > 0.0 else 0.0
    confidence = min(1.0, max(0.0, 1.0 - 1.0 / sharpness)) if sharpness > 0.0 else 0.0

    return BeatGrid(phase_seconds=phase, period_seconds=period, confidence=confidence)
