"""Metrical-profile fingerprint term — the strongest genre-specific weapon.

How it resolves the octave
--------------------------
For a candidate BPM we treat one bar as ``beats_per_bar`` beats and divide it
into ``bins_per_bar`` (16) slots — a 16th-note grid. Every onset-envelope frame
falls into one slot of the bar it lands in; summing each band's energy per slot
across all bars yields a 16-bin *metrical profile* for that band: where, within
the bar, that band's energy sits.

Drill/trap has a very particular metrical fingerprint — syncopated kick, a
2-&-4 snare backbeat, dense even hats. That shape only emerges when the bar is
folded at the *true notated* tempo. A wrong-octave candidate folds the same
audio at the wrong metrical resolution:

* the **half-time** fold (bpm/2) packs two real 16ths into every grid slot, so
  the bar's structure is smeared and the characteristic kick/snare placement
  is washed out;
* the **double-time** fold (bpm*2) splits one real bar across two folded bars,
  duplicating/aliasing the pattern.

Either way the folded profile correlates *worse* with the learned genre
fingerprint than the true-octave fold does — and that gap is exactly the
disambiguating evidence this term contributes.

Phase invariance
----------------
``fold_to_grid`` searches sub-bin phase offsets and keeps the phase that makes
the folded profile *sharpest* (peak-to-mean), so the grid locks onto the
groove. But the spectral-flux onset envelope peaks slightly *after* each
transient, and "bin 0" of the bar is arbitrary, so the absolute rotation of the
folded profile is not meaningful — only the *relative* metrical shape is. The
fingerprint comparison is therefore made rotation-invariant (best cosine over
all 16 circular shifts). This compares the *pattern*, not an absolute phase,
which is what makes the term robust without weakening octave discrimination
(the half/double folds have genuinely different shapes at every rotation).

Contract (imported by ``evidence/__init__`` and the resolver — do not rename):

    score_fingerprint(bpm: float, features: Features,
                      params: FingerprintParams) -> TermScore
"""

from __future__ import annotations

import json
import os
import threading
from typing import Iterable, Optional

import numpy as np

from ..config import FingerprintParams, TempoConfig
from ..contracts import Features, TermScore

_EPS = 1e-12

# Packaged default fingerprint location (this file lives in rai_analyzer/evidence/).
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_FINGERPRINT_PATH = os.path.join(_PACKAGE_ROOT, "fingerprints", "drill.json")

# Disk-load cache keyed by absolute path, so re-scoring every candidate (and
# every file) does not re-read JSON. Guarded for parallel-safe access.
_FP_CACHE: dict[str, dict] = {}
_FP_CACHE_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Folding
# ---------------------------------------------------------------------------


def _normalize_profile(p: np.ndarray) -> np.ndarray:
    """L2-normalise a profile to a unit vector (zeros stay zeros)."""
    p = np.asarray(p, dtype=np.float64)
    n = float(np.linalg.norm(p))
    return p / n if n > _EPS else np.zeros_like(p)


def fold_to_grid(
    env: np.ndarray,
    times: np.ndarray,
    bpm: float,
    bins_per_bar: int = 16,
    beats_per_bar: int = 4,
    phase_search_steps: int = 16,
) -> tuple[np.ndarray, float]:
    """Fold an onset envelope onto a ``bins_per_bar``-slot metrical grid.

    Parameters
    ----------
    env, times:
        Onset-strength envelope and its frame-centre times (seconds), same
        length. ``env`` is treated as non-negative energy.
    bpm:
        Candidate tempo. ``bar_seconds = beats_per_bar * 60 / bpm`` and
        ``bin_seconds = bar_seconds / bins_per_bar``.
    bins_per_bar, beats_per_bar:
        Grid resolution and metre (4/4 by default).
    phase_search_steps:
        Number of phase offsets, spanning exactly one bin, that are tried; the
        phase maximising grid sharpness (peak-to-mean of the folded profile) is
        chosen.

    Returns
    -------
    (profile, best_phase):
        ``profile`` is the L2-normalised ``bins_per_bar``-vector at the best
        phase; ``best_phase`` is the chosen offset in seconds. Degenerate input
        (no bins, non-positive bpm, empty/silent envelope) yields a zero
        profile and zero phase — never NaN, never an exception.
    """
    bins = int(bins_per_bar)
    env = np.asarray(env, dtype=np.float64)
    times = np.asarray(times, dtype=np.float64)

    if bins <= 0 or bpm <= 0 or env.size == 0 or times.size == 0:
        return np.zeros(max(bins, 0), dtype=np.float64), 0.0

    # Match lengths defensively (BandEnvelopes already aligns them).
    m = min(env.size, times.size)
    env = np.maximum(env[:m], 0.0)
    times = times[:m]

    if not np.isfinite(env).any() or float(env.sum()) <= _EPS:
        return np.zeros(bins, dtype=np.float64), 0.0

    bar_seconds = beats_per_bar * 60.0 / bpm
    bin_seconds = bar_seconds / bins
    steps = max(1, int(phase_search_steps))

    best_profile: Optional[np.ndarray] = None
    best_phase = 0.0
    best_sharpness = -np.inf

    for k in range(steps):
        phase = (k / steps) * bin_seconds
        # Bar position of each frame -> bin index in [0, bins).
        pos = np.mod(times - phase, bar_seconds) / bin_seconds
        idx = np.floor(pos).astype(np.intp)
        # Guard the rare floating-point edge that lands exactly on `bins`.
        np.clip(idx, 0, bins - 1, out=idx)

        profile = np.zeros(bins, dtype=np.float64)
        np.add.at(profile, idx, env)

        total = float(profile.sum())
        if total <= _EPS:
            sharpness = 0.0
        else:
            # Peak-to-mean: high when energy concentrates on a few grid slots
            # (a well-aligned groove), low when it is smeared across the bar.
            sharpness = float(profile.max()) / (total / bins)

        if sharpness > best_sharpness:
            best_sharpness = sharpness
            best_profile = profile
            best_phase = phase

    if best_profile is None:  # pragma: no cover - guarded above
        return np.zeros(bins, dtype=np.float64), 0.0

    return _normalize_profile(best_profile), float(best_phase)


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _best_rotational_cosine(profile: np.ndarray, reference: np.ndarray) -> float:
    """Best cosine similarity over all circular rotations of ``profile``.

    Both inputs are assumed (re-)normalised to unit L2 norm; the result is
    clamped to [0, 1] (envelopes are non-negative, so the relevant similarity
    is non-negative). Rotation-invariance absorbs the onset-envelope phase lag
    and the arbitrary bar origin while preserving the *shape* difference between
    the true octave and its half/double folds.
    """
    profile = _normalize_profile(profile)
    reference = _normalize_profile(reference)
    if float(np.linalg.norm(profile)) <= _EPS or float(np.linalg.norm(reference)) <= _EPS:
        return 0.0
    n = profile.size
    if reference.size != n:
        # Shape mismatch (e.g. fingerprint trained at a different resolution):
        # fall back to a direct comparison on the overlap.
        k = min(n, reference.size)
        return max(0.0, min(1.0, float(np.dot(profile[:k], reference[:k]))))
    best = -1.0
    for r in range(n):
        c = float(np.dot(np.roll(profile, r), reference))
        if c > best:
            best = c
    return max(0.0, min(1.0, best))


# ---------------------------------------------------------------------------
# Fingerprint IO (load / save / cache)
# ---------------------------------------------------------------------------


def save_fingerprint(fingerprint: dict, path: str) -> str:
    """Serialise a per-band fingerprint dict to JSON at ``path``.

    The dict maps band name -> list/array of ``bins_per_bar`` non-negative
    floats. Profiles are stored L2-normalised. Metadata keys (anything not a
    band, e.g. ``"_meta"``) are preserved verbatim.
    """
    out: dict = {}
    for key, value in fingerprint.items():
        if key.startswith("_"):
            out[key] = value
            continue
        out[key] = [float(x) for x in _normalize_profile(np.asarray(value, dtype=np.float64))]
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
    return path


def _coerce_loaded(raw: dict) -> dict:
    """Turn a freshly parsed JSON dict into band -> np.ndarray profiles."""
    fp: dict = {}
    for key, value in raw.items():
        if key.startswith("_"):
            fp[key] = value
            continue
        fp[key] = _normalize_profile(np.asarray(value, dtype=np.float64))
    return fp


def load_fingerprint(path: Optional[str] = None) -> dict:
    """Load a fingerprint, caching by resolved path.

    ``path is None`` loads the packaged default ``fingerprints/drill.json``
    (resolved relative to this module, so it works from any working directory
    and from an installed package). The returned dict maps band name ->
    unit-normalised ``np.ndarray`` plus any ``_meta`` metadata.
    """
    resolved = os.path.abspath(path) if path else _DEFAULT_FINGERPRINT_PATH

    with _FP_CACHE_LOCK:
        cached = _FP_CACHE.get(resolved)
    if cached is not None:
        return cached

    with open(resolved, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    fp = _coerce_loaded(raw)

    with _FP_CACHE_LOCK:
        _FP_CACHE[resolved] = fp
    return fp


def clear_fingerprint_cache() -> None:
    """Drop the disk-load cache (used by tests / after re-learning)."""
    with _FP_CACHE_LOCK:
        _FP_CACHE.clear()


# ---------------------------------------------------------------------------
# Learning (re-derive the fingerprint from ground-truth WAVs)
# ---------------------------------------------------------------------------


def learn_fingerprint(items: Iterable[tuple], cfg: TempoConfig) -> dict:
    """Learn a per-band metrical fingerprint from ground-truth tracks.

    Parameters
    ----------
    items:
        Iterable of ``(Features, true_bpm)`` pairs — the features of each
        ground-truth track and its known notated tempo.
    cfg:
        The full :class:`TempoConfig`; ``cfg.fingerprint`` supplies the grid
        geometry (bins/beats/phase steps) and the band list.

    Returns
    -------
    dict
        ``band -> unit-normalised np.ndarray`` of length ``bins_per_bar``,
        averaged over all tracks folded at their TRUE bpm, plus a ``_meta``
        block recording how it was built. Bands with no energy across the whole
        corpus come back as zero vectors.

    This is the function the producer runs once the real WAVs land in
    ``validation/fixtures/`` to replace the bootstrap ``drill.json``.
    """
    fp = cfg.fingerprint
    bins = int(fp.bins_per_bar)
    accum = {band: np.zeros(bins, dtype=np.float64) for band in fp.bands}
    n_tracks = 0

    for features, true_bpm in items:
        if true_bpm is None or true_bpm <= 0:
            continue
        bands = features.bands
        n_tracks += 1
        for band in fp.bands:
            profile, _ = fold_to_grid(
                bands.band(band),
                bands.times,
                float(true_bpm),
                bins_per_bar=bins,
                beats_per_bar=fp.beats_per_bar,
                phase_search_steps=fp.phase_search_steps,
            )
            # Accumulate unit profiles so every track contributes equally,
            # independent of its absolute onset energy / duration.
            accum[band] += _normalize_profile(profile)

    result: dict = {band: _normalize_profile(vec) for band, vec in accum.items()}
    result["_meta"] = {
        "source": "learned",
        "n_tracks": n_tracks,
        "bins_per_bar": bins,
        "beats_per_bar": fp.beats_per_bar,
        "bands": list(fp.bands),
    }
    return result


# ---------------------------------------------------------------------------
# The evidence term
# ---------------------------------------------------------------------------


def score_fingerprint(bpm: float, features: Features, params: FingerprintParams) -> TermScore:
    """Evidence term: how well ``bpm``'s folded metrical profile matches the
    learned genre fingerprint.

    Folds each band in ``params.bands`` at ``bpm``'s best phase, compares each
    folded profile to the learned per-band fingerprint via rotation-invariant
    cosine similarity, and combines the per-band similarities into a single
    [0, 1] score. The true notated octave folds drill's metrical structure
    coherently and matches the fingerprint best; half/double folds smear or
    alias it and match worse — that gap is the octave-disambiguating evidence.

    Degenerate input (non-positive bpm, empty/silent envelope, no usable
    fingerprint band) returns a low but valid score and never raises or emits
    NaN — :class:`TermScore` additionally clamps defensively.
    """
    try:
        fingerprint = load_fingerprint(params.fingerprint_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        # Missing / corrupt fingerprint must not crash the resolver: this term
        # simply abstains with a low score and an explanatory detail.
        return TermScore(value=0.0, detail={"error": f"fingerprint load failed: {exc}"})

    bands = features.bands
    per_band: dict[str, float] = {}
    phases: dict[str, float] = {}
    weights: dict[str, float] = {}

    for band in params.bands:
        reference = fingerprint.get(band)
        if reference is None or float(np.linalg.norm(np.asarray(reference))) <= _EPS:
            # No fingerprint for this band -> it carries no evidence.
            continue
        env = bands.band(band)
        profile, phase = fold_to_grid(
            env,
            bands.times,
            float(bpm),
            bins_per_bar=params.bins_per_bar,
            beats_per_bar=params.beats_per_bar,
            phase_search_steps=params.phase_search_steps,
        )
        sim = _best_rotational_cosine(profile, np.asarray(reference, dtype=np.float64))
        per_band[band] = sim
        phases[band] = phase
        # Weight each band by how much rhythmic energy it actually carries on
        # this track, so a band with no onsets (zero profile) cannot drag the
        # score down and a strongly-grooving band dominates the verdict.
        weights[band] = float(np.asarray(env, dtype=np.float64).sum())

    if not per_band:
        return TermScore(
            value=0.0,
            detail={"reason": "no usable band/fingerprint overlap", "bpm": float(bpm)},
        )

    total_w = sum(weights.values())
    if total_w <= _EPS:
        # All considered bands silent -> uniform (equal) weighting of whatever
        # similarities we have (all near zero anyway).
        value = float(np.mean(list(per_band.values())))
    else:
        value = sum(per_band[b] * weights[b] for b in per_band) / total_w

    return TermScore(
        value=value,
        detail={
            "bpm": float(bpm),
            "per_band": {b: round(per_band[b], 4) for b in per_band},
            "band_weights": {b: round(weights[b], 3) for b in weights},
            "phase_seconds": {b: round(phases[b], 5) for b in phases},
            "fingerprint_source": fingerprint.get("_meta", {}).get("source", "unknown"),
        },
    )
