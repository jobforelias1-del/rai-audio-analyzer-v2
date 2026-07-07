"""Stereo width + inter-channel correlation (ruling R-M2-4).

* ``width_pct`` — v1's mid/side energy ratio, kept as v2-canonical and scaled
  to percent: ``100 * E_side / (E_mid + E_side)`` over the whole file, where
  ``mid = 0.5*(L+R)`` and ``side = 0.5*(L-R)``. 0 = mono, 50 = uncorrelated,
  100 = anti-phase. (v1 only ever surfaced a word — Mono/Narrow/Balanced/Wide
  — from this same ratio; the number itself is the v3 surface.)
* ``correlation`` — Pearson r of L vs R (float64, whole file). NEW in v2:
  v1 had no correlation figure.

Files with more than two channels measure width/correlation on channels 0 and
1 (as v1 did) — multichannel-beyond-stereo intake is out of scope for the
width model.

Edge policy:

* mono file           -> width **0.0** (a MEASUREMENT — matches the demo's
  "0 %"), correlation ``None`` (undefined with one channel);
* silent stereo file  -> width NaN, correlation ``None`` (nothing to measure);
* constant/zero-variance channel -> correlation ``None`` (Pearson undefined).
"""

from __future__ import annotations

import numpy as np

from .contracts import StereoResult


def compute_stereo(y_native: np.ndarray) -> StereoResult:
    """Measure stereo width + correlation on the native-rate signal."""
    y = np.asarray(y_native, dtype=np.float64)

    if y.ndim < 2 or y.shape[1] < 2:
        # Mono: zero side energy by definition — width 0.0 is the measurement.
        return StereoResult(width_pct=0.0, correlation=None)

    left = y[:, 0]
    right = y[:, 1]

    mid = 0.5 * (left + right)
    side = 0.5 * (left - right)
    mid_e = float(np.sum(np.square(mid)))
    side_e = float(np.sum(np.square(side)))

    denom = mid_e + side_e
    if denom <= 0.0:
        # Digital silence in a stereo container: width is undefined.
        return StereoResult(width_pct=float("nan"), correlation=None)

    width_pct = float(100.0 * side_e / denom)

    # Pearson r needs variance in both channels.
    if float(np.std(left)) <= 0.0 or float(np.std(right)) <= 0.0:
        correlation = None
    else:
        r = float(np.corrcoef(left, right)[0, 1])
        correlation = r if np.isfinite(r) else None

    return StereoResult(width_pct=width_pct, correlation=correlation)
