"""Constants for the M2 metrics layer — the single place numbers live.

Everything a metrics module needs to agree on is defined here so the modules
cannot drift apart (same pattern as :mod:`rai_analyzer.config` for the tempo
engine, kept separate because the metrics layer must not import the frozen
engine's config).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Spectrum (Welch) — ruling R-M2-7
# ---------------------------------------------------------------------------

#: Welch segment length at the native sample rate. Shorter files use
#: ``min(SPECTRUM_NPERSEG, n)``. scipy defaults supply the rest of the recipe:
#: Hann window, 50% overlap, per-segment constant detrend.
SPECTRUM_NPERSEG = 16384

#: Audible-range mask applied to the PSD: 20 Hz up to min(20 kHz, Nyquist).
#: Every percentage in :mod:`.bands` is a share of THIS range's total energy.
FMIN_HZ = 20.0
FMAX_HZ = 20000.0

# ---------------------------------------------------------------------------
# Six-band map (v3-canonical) — ruling R-M2-3
# ---------------------------------------------------------------------------

#: ``(key, low_hz, high_hz)`` — percentages of total 20 Hz–20 kHz PSD energy.
#: Bands are half-open ``[low, high)`` except the last (``air``), which is
#: closed at 20 kHz so the six shares partition the audible mask exactly
#: (they sum to ~100 whenever the signal has energy).
#:
#:   sub 20–60 · bass 60–120 · low-mid 120–350 · mid 350–2000 ·
#:   high-mid 2000–6000 · air 6000–20000 Hz
#:
#: ``sub`` (20–60 Hz) is the UI's Sub/bass card value (R-M2-2); ``bass``
#: (60–120 Hz) and the full map are engine-only in M2.
SIX_BAND_EDGES_HZ: tuple[tuple[str, float, float], ...] = (
    ("sub", 20.0, 60.0),
    ("bass", 60.0, 120.0),
    ("low_mid", 120.0, 350.0),
    ("mid", 350.0, 2000.0),
    ("high_mid", 2000.0, 6000.0),
    ("air", 6000.0, 20000.0),
)

#: Guard for "no measurable energy" denominators (PSD totals, mid+side
#: energies). Below this the quantity is undefined -> NaN, never a fake 0.0
#: (v1's silence 0.0 lied — ruling R-M2-5's doctrine applied layer-wide).
ENERGY_EPS = 0.0
