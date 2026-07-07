"""Composition: one call, one shared PSD, one :class:`SignalResult`.

``compute_signal_result`` is the metrics layer's single entry point (imported
by full path — the package ``__init__`` is deliberately re-export-free)::

    from rai_analyzer.metrics.compute import compute_signal_result
    result = compute_signal_result(signal)

It measures on ``signal.y_native`` / ``signal.sr_native`` only — the metrics
layer never touches the 22.05 kHz mono analysis view. The Welch PSD is
computed exactly once and shared between the spectrum contract and the band
integrator (the only non-trivial cost in the layer, per R-M2-18).

The ``AudioSignal`` import is type-checking-only on purpose: at runtime this
package needs nothing from the engine beyond the two attributes it reads,
which keeps the metrics layer numpy/scipy-pure (pinned by the engine-boundary
test).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .bands import compute_band_energies
from .contracts import SignalResult
from .dynamics import compute_dynamics
from .spectrum import build_spectrum_data, welch_psd
from .stereo import compute_stereo

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rai_analyzer.io_audio import AudioSignal


def compute_signal_result(signal: "AudioSignal") -> SignalResult:
    """Compute the full M2 metrics record for one loaded signal. Never raises
    on silent/short/mono/stereo input — undefined quantities are NaN/None per
    the contracts' documented policies."""
    y_native = signal.y_native
    sr_native = int(signal.sr_native)

    # One Welch pass, shared by spectrum + bands (compute once, share).
    freqs, psd = welch_psd(y_native, sr_native)

    return SignalResult(
        spectrum=build_spectrum_data(freqs, psd),
        dynamics=compute_dynamics(y_native),
        bands=compute_band_energies(freqs, psd),
        stereo=compute_stereo(y_native),
    )
