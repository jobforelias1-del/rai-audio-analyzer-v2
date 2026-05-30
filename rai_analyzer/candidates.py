"""Tempo-candidate generation.

The spec is emphatic: **do not restrict to {1/2, 1, 2}.** Two known failures
prove why. (96 -> 154) is roughly a 5:8 fractional alias from locking onto a
dotted-eighth / tresillo pulse. And Mathematics of the Menace (true 153.85) was
read as a 192 BPM lock — 153.85 is 4/5 of 192, a **5:4 family** alias that no
octave/dotted multiplier can reach, so the truth was never even surfaced. So we:

1. Multiply the strongest product-tempogram peaks by the full multiplier set
   ``[1/3, 1/2, 5/8, 2/3, 3/4, 4/5, 1, 5/4, 4/3, 3/2, 8/5, 2, 3]`` (octave +
   dotted/triplet + the 5:4 and 5:8 hemiola families), and
2. Inject the strong *independent* product-tempogram peaks directly into the
   candidate set — even if no multiplier produced them. This is what catches a
   fractional alias that is not a clean ratio of the dominant peak.

The result is a de-duplicated, range-filtered list of BPM hypotheses. Scoring
(the evidence terms) decides between them; candidate generation only has to
guarantee the truth is *present*.
"""

from __future__ import annotations

from .config import TempoConfig
from .contracts import Features
from .tempogram import curve_peaks


def generate_candidates(features: Features, cfg: TempoConfig) -> list[float]:
    """Return the de-duplicated BPM candidate set for an analysis."""
    cp = cfg.candidates
    curve = features.tempo_curve
    peaks = curve_peaks(curve, n=8, min_salience=0.04)
    if not peaks:
        return []

    raw: list[float] = []

    # (1) Multiplier family off the top two product peaks. Using the top two
    #     (not just the argmax) guards against the argmax itself being an alias.
    for base_bpm, _ in peaks[:2]:
        for m in cp.multipliers:
            raw.append(base_bpm * m)

    # (2) Strong independent peaks injected directly (catches the ~5:8 alias).
    for bpm, sal in peaks[: cp.n_independent_peaks]:
        if sal >= cp.independent_peak_floor:
            raw.append(bpm)

    # Range filter, then de-duplicate within tolerance keeping the higher-salience
    # representative of each cluster.
    in_range = [b for b in raw if cp.bpm_min <= b <= cp.bpm_max]
    return _dedup(in_range, curve, cp.dedup_tol)


def _dedup(bpms: list[float], curve, tol: float) -> list[float]:
    """Merge BPMs within ``tol`` (relative); keep the most-salient representative."""
    if not bpms:
        return []
    ordered = sorted(set(round(b, 4) for b in bpms))
    clusters: list[list[float]] = [[ordered[0]]]
    for b in ordered[1:]:
        if abs(b - clusters[-1][-1]) / clusters[-1][-1] <= tol:
            clusters[-1].append(b)
        else:
            clusters.append([b])
    reps: list[float] = []
    for cluster in clusters:
        # Representative = member with the highest product-tempogram salience.
        reps.append(max(cluster, key=lambda b: curve.value_at(b)))
    return sorted(reps)
