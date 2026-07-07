"""Band energy shares integrated from the shared Welch PSD (R-M2-2 / R-M2-3).

Each band's value is its share of the total 20 Hz–20 kHz PSD energy, in
percent — v1's intuitive "% of what you can hear" definition, extended from
v1's two bands (Sub/Bass) to the v3-canonical six-band map in
:data:`rai_analyzer.metrics.params.SIX_BAND_EDGES_HZ`.

The PSD is computed once by :func:`rai_analyzer.metrics.spectrum.welch_psd`
and handed in here — bands never run their own FFT (compute once, share).

Silence policy: with zero audible energy a share is undefined, so every value
is NaN (serialized ``None``) — never v1's lying 0.0.
"""

from __future__ import annotations

import numpy as np

from .contracts import BandEnergyResult
from .params import ENERGY_EPS, SIX_BAND_EDGES_HZ
from .spectrum import audible_mask


def compute_band_energies(freqs: np.ndarray, psd: np.ndarray) -> BandEnergyResult:
    """Integrate the shared (unmasked) PSD into six-band percentage shares.

    Bands are half-open ``[lo, hi)`` except the last (``air``), which closes
    at 20 kHz to match the inclusive audible mask — so the six shares
    partition the audible total exactly and sum to ~100 for any signal with
    energy. Bands above Nyquist simply integrate to zero.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    psd = np.asarray(psd, dtype=np.float64)

    audible = audible_mask(freqs)
    total = float(np.sum(psd[audible])) if freqs.size else 0.0

    if total <= ENERGY_EPS:
        nan = float("nan")
        six = {name: nan for name, _lo, _hi in SIX_BAND_EDGES_HZ}
        return BandEnergyResult(sub_pct=nan, bass_pct=nan, six_band=six)

    last_name = SIX_BAND_EDGES_HZ[-1][0]
    six: dict[str, float] = {}
    for name, lo, hi in SIX_BAND_EDGES_HZ:
        if name == last_name:
            m = (freqs >= lo) & (freqs <= hi)  # closed top edge (matches mask)
        else:
            m = (freqs >= lo) & (freqs < hi)
        six[name] = float(np.sum(psd[m]) / total * 100.0)

    return BandEnergyResult(sub_pct=six["sub"], bass_pct=six["bass"], six_band=six)
