"""Min/max decimation for waveform overview drawing (pure numpy, no Qt).

A track is millions of samples; a plot well is a few hundred pixels. Naive
stride decimation (``y[::step]``) is wrong for audio: it drops transients and
clip peaks between strides, so the overview would lie about exactly the
things this analyzer exists to measure. Min/max decimation keeps, per pixel
bin, both extremes — the drawn envelope then provably contains every sample,
and a single-sample clip stays visible at any zoom.
"""

from __future__ import annotations

import numpy as np


def minmax_decimate(y: np.ndarray, target_bins: int) -> tuple[np.ndarray, np.ndarray]:
    """Reduce ``y`` to ``(mins, maxs)`` over ``target_bins`` contiguous bins.

    Bin edges come from ``linspace`` so uneven divisions spread the remainder
    evenly across the span (no fat last bin). When ``len(y) <= target_bins``
    the signal is already at or below display resolution and is passed
    through unchanged as ``(y, y)`` — upsampling would fabricate data.

    ``y`` must be 1-D; it is converted to float64 so integer PCM input plots
    identically to float input. Raises ``ValueError`` on a non-positive
    ``target_bins`` or non-1-D input.
    """
    if target_bins <= 0:
        raise ValueError(f"target_bins must be positive, got {target_bins}")
    y = np.asarray(y, dtype=np.float64)
    if y.ndim != 1:
        raise ValueError(f"y must be 1-D, got shape {y.shape}")
    n = y.shape[0]
    if n <= target_bins:
        return y, y
    # n > target_bins guarantees strictly increasing integer edges, which
    # reduceat requires (an empty slice would echo a single sample instead
    # of reducing).
    edges = np.linspace(0, n, target_bins + 1).astype(np.intp)
    mins = np.minimum.reduceat(y, edges[:-1])
    maxs = np.maximum.reduceat(y, edges[:-1])
    return mins, maxs
