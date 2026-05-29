"""Tier-1 loudness measurements: integrated LUFS + true peak (dBTP).

>>> STATUS: STUB. Computes only the trivial sample peak so the pipeline runs.
>>> The real implementation (pyloudnorm BS.1770 integrated loudness + 4x
>>> oversampled true peak) is built by a dedicated agent against this contract.

Contract (do not change without updating analyzer.py):

    measure_loudness(signal: AudioSignal) -> LoudnessResult

  * Measure on ``signal.y_native`` at ``signal.sr_native`` (NOT the downsampled
    mono analysis view) so numbers match mastering tools.
  * ``lufs_i``         — ITU-R BS.1770 integrated loudness via pyloudnorm.
  * ``true_peak_dbtp`` — true peak via >=4x oversampling, then 20*log10(max|x|).
  * ``sample_peak_dbfs`` — raw sample peak in dBFS.
"""

from __future__ import annotations

import numpy as np

from .contracts import LoudnessResult
from .io_audio import AudioSignal


def measure_loudness(signal: AudioSignal) -> LoudnessResult:
    """STUB — sample peak only; LUFS/true-peak pending (see module docstring)."""
    y = signal.y_native
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    sample_peak_dbfs = 20.0 * np.log10(peak) if peak > 0 else -np.inf
    return LoudnessResult(
        lufs_i=float("nan"),
        true_peak_dbtp=float("nan"),
        sample_peak_dbfs=sample_peak_dbfs,
    )
