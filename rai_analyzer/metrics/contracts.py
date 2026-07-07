"""Result contracts for the M2 metrics layer.

Same doctrine as :mod:`rai_analyzer.contracts` (which is frozen, hence this
sibling): dependency-light (numpy only), immutable carriers, hand-written
``to_dict`` with pre-rounded plain floats. One deliberate upgrade over the
frozen file: serialization is **JSON-strict** (ruling R-M2-12) — every
non-finite float maps to ``None`` so ``json.dumps(d, allow_nan=False)`` always
succeeds. ``-inf`` peaks and NaN crests are honest *measurements* in the
dataclasses; ``None`` is their honest *serialization*.

Array policy (justified per the brief's "your call"): ``SpectrumData``'s
``freqs`` / ``psd_db`` arrays are **excluded** from ``to_dict``. They are plot
payload, not metrics — thousands of rounded floats would bloat every JSON
export while pinning nothing a consumer could assert against. ``to_dict``
instead records the array summary (point count + frequency span) so the
omission is visible in the serialized record. Consumers who want the curve
take it from the live object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


def _json_num(value: float, ndigits: int) -> Optional[float]:
    """Round a float for JSON; non-finite (nan/±inf) becomes ``None``."""
    v = float(value)
    if not np.isfinite(v):
        return None
    return round(v, ndigits)


@dataclass(frozen=True)
class SpectrumData:
    """Channel-power-averaged Welch spectrum, masked to the audible range.

    ``psd_db`` is ``10*log10(PSD)`` and deliberately UNNORMALIZED — the UI
    normalizes for display (max at the 0 dB top, −90 dB floor, R-M2-7). Bins
    with zero power read ``-inf`` (a silent file's honest spectrum).
    """

    freqs: np.ndarray  # (k,) Hz, masked 20 .. min(20000, nyquist)
    psd_db: np.ndarray  # (k,) 10*log10(power-averaged PSD)

    def to_dict(self) -> dict:
        # Arrays excluded by policy (see module docstring): summary only.
        k = int(self.freqs.size)
        return {
            "n_points": k,
            "fmin_hz": _json_num(self.freqs[0], 2) if k else None,
            "fmax_hz": _json_num(self.freqs[-1], 2) if k else None,
        }


@dataclass(frozen=True)
class DynamicsResult:
    """Whole-file dynamics at the native rate (v2-canonical, R-M2-5)."""

    peak_dbfs: float  # == loudness sample peak by construction (D2 cross-check)
    rms_dbfs: float  # whole-file RMS over all samples, all channels
    crest_db: float  # peak - rms; NaN on silence (never a lying 0.0)

    def to_dict(self) -> dict:
        return {
            "peak_dbfs": _json_num(self.peak_dbfs, 2),
            "rms_dbfs": _json_num(self.rms_dbfs, 2),
            "crest_db": _json_num(self.crest_db, 2),
        }


@dataclass(frozen=True)
class BandEnergyResult:
    """Band shares of total 20 Hz–20 kHz PSD energy (R-M2-2 / R-M2-3).

    All values are NaN when the audible range carries no energy (silence) —
    a share of nothing is undefined, not zero.
    """

    sub_pct: float  # 20-60 Hz share — the UI's Sub/bass card value
    bass_pct: float  # 60-120 Hz share (engine-only in M2)
    six_band: dict[str, float]  # keys: sub, bass, low_mid, mid, high_mid, air

    def to_dict(self) -> dict:
        return {
            "sub_pct": _json_num(self.sub_pct, 2),
            "bass_pct": _json_num(self.bass_pct, 2),
            "six_band": {k: _json_num(v, 2) for k, v in self.six_band.items()},
        }


@dataclass(frozen=True)
class StereoResult:
    """Stereo width + inter-channel correlation (R-M2-4).

    ``width_pct = 100 * E_side / (E_mid + E_side)``: 0 = mono, 50 =
    uncorrelated, 100 = anti-phase. A mono file measures width 0.0 (a
    MEASUREMENT, not absence); its correlation is ``None`` (undefined with one
    channel). Digitally silent stereo is NaN width / ``None`` correlation —
    nothing to measure.
    """

    width_pct: float
    correlation: Optional[float]  # Pearson r of L vs R; None when undefined

    def to_dict(self) -> dict:
        return {
            "width_pct": _json_num(self.width_pct, 2),
            "correlation": (
                _json_num(self.correlation, 3) if self.correlation is not None else None
            ),
        }


@dataclass(frozen=True)
class SignalResult:
    """The complete M2 signal-metrics record for one file."""

    spectrum: SpectrumData
    dynamics: DynamicsResult
    bands: BandEnergyResult
    stereo: StereoResult

    def to_dict(self) -> dict:
        return {
            "spectrum": self.spectrum.to_dict(),
            "dynamics": self.dynamics.to_dict(),
            "bands": self.bands.to_dict(),
            "stereo": self.stereo.to_dict(),
        }
