"""Whole-file dynamics: sample peak, RMS, crest factor (ruling R-M2-5).

v2-canonical definitions, all in float64 on ``y_native`` at the native rate:

* ``peak_dbfs``  = ``20*log10(max|y_native|)`` across ALL channels — by
  construction identical to ``loudness.sample_peak_dbfs`` (the D2 cross-check
  test enforces the identity on every fixture). v1 measured its peak on the
  mono downmix, so anti-phase stereo content cancelled and it under-read —
  the documented divergence.
* ``rms_dbfs``   = ``20*log10(sqrt(mean(x^2)))`` over all samples, all
  channels, whole file. No windowing in M2.
* ``crest_db``   = ``peak_dbfs - rms_dbfs`` (the UI's "Dyn range"). Silence
  gives ``-inf`` peak/RMS and **NaN** crest — v1 reported 0.0 there, which
  claimed "no dynamics" instead of "nothing to measure".
"""

from __future__ import annotations

import numpy as np

from .contracts import DynamicsResult


def _db_from_amplitude(amp: float) -> float:
    """dB of a linear amplitude; ``-inf`` for a non-positive (silent) level."""
    if amp > 0.0:
        return float(20.0 * np.log10(amp))
    return float("-inf")


def compute_dynamics(y_native: np.ndarray) -> DynamicsResult:
    """Measure peak/RMS/crest on the native-rate signal. Never raises."""
    y = np.asarray(y_native, dtype=np.float64)

    if y.size == 0:
        return DynamicsResult(
            peak_dbfs=float("-inf"), rms_dbfs=float("-inf"), crest_db=float("nan")
        )

    peak_dbfs = _db_from_amplitude(float(np.max(np.abs(y))))
    rms_dbfs = _db_from_amplitude(float(np.sqrt(np.mean(np.square(y)))))

    if np.isfinite(peak_dbfs) and np.isfinite(rms_dbfs):
        crest_db = float(peak_dbfs - rms_dbfs)
    else:
        crest_db = float("nan")

    return DynamicsResult(peak_dbfs=peak_dbfs, rms_dbfs=rms_dbfs, crest_db=crest_db)
