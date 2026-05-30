"""Hi-hat subdivision-density term.

Resolves tempo-octave ambiguity in drill/trap by reading the high band as the
*subdivision stream*. A busy hat line that only makes musical sense at the
doubled tempo is positive evidence that the slower candidate is wrong.

Contract (do not change without updating the resolver and ``__init__``)::

    score_hihat_density(candidate_bpm: float, features: Features,
                        params: HihatParams) -> TermScore

Algorithm
---------
1. **Tatum estimate.** The dominant high-band tatum is the fastest *sustained*
   pulse the hats articulate. We estimate it as the high-band onset *rate*
   (peaks per minute of ``features.bands.high``). This is grid-unbounded — a
   straight-16th hat line at 150 BPM articulates ~600 events/min, which sits far
   above the product-tempogram BPM grid ceiling (240) and therefore never shows
   up as a literal peak in ``features.high_curve`` (the product tempogram aliases
   it down to the beat / half-beat). The onset-rate recovers it directly. We
   fall back to the strongest ``high_curve`` peak when the onset envelope has no
   usable peaks.

2. **Ratio.** ``ratio = tatum_bpm / candidate_bpm``.

3. **Plausibility.** A candidate is PLAUSIBLE when its hat stream lands on a
   musical subdivision (``params.musical_ratios``; especially 4 = straight
   16ths, i.e. tatum ~ 4xbeat). A candidate is IMPLAUSIBLE when the hats only
   parse as constant 32nds/64ths everywhere (``ratio >= params.implausible_ratio``)
   — that is evidence the candidate is too slow and should be DOUBLED, so it
   scores low (and, by construction, its double — half the ratio — scores high).
   Score peaks near a clean small subdivision and decays for non-musical or
   implausibly-fine ratios.

4. **Sustained-density guard.** The track is split into ``params.n_sections``
   sections; the high-band activity (onset rate) is measured in each. A section
   counts as "active" when its rate is a meaningful fraction of the global rate.
   We require activity in at least ``params.min_active_sections`` of the sections
   and fold the active fraction into the score, so a transient roll/fill in one
   section cannot, on its own, be treated as evidence to double.

5. **Periodicity gate.** A multiplicative confidence from the smoothed-envelope
   autocorrelation at the tatum lag keeps broadband noise (flat autocorrelation)
   from masquerading as a dense subdivision. Real periodic hats keep it high; it
   only ever attenuates toward the neutral baseline, never flips the verdict.

Robust to silence / an empty high band: returns a neutral-low, finite score
(never NaN, never raises).
"""

from __future__ import annotations

import numpy as np

from ..config import HihatParams
from ..contracts import Features, TempoCurve, TermScore

_EPS = 1e-9

# Score returned when there is no usable high-band evidence (silence, empty
# band, no detectable pulse). Deliberately below 0.5 so a track with no hi-hat
# subdivision evidence neither favours nor strongly opposes any octave, but
# does not look like positive evidence either.
_NEUTRAL = 0.35

# Onset-peak picking: a peak must clear this fraction of the (global) high-band
# envelope maximum, and consecutive peaks must be at least this many frames
# apart. distance=2 frames caps the detectable rate near the envelope Nyquist
# without splitting a single transient into two.
_PEAK_REL_HEIGHT = 0.15
_PEAK_MIN_DISTANCE = 2

# A section is "active" when its onset rate is at least this fraction of the
# global high-band rate. Distinguishes a sustained hat stream (every section
# near the global rate) from kick/snare bleed in the high band (a small,
# roughly constant fraction of the rate).
_SECTION_ACTIVE_FRAC = 0.5

# Gaussian width (in ratio units) of the plausibility bump around each musical
# subdivision. ~0.18 makes ratio 3.7-4.0 read as a clean 16th lock while a
# clearly non-musical ratio (e.g. 5) falls off.
_PLAUSIBILITY_SIGMA = 0.18

# Upper bound on the confidence blend so even an ideal subdivision lands in a
# "strong but not absolute" band rather than pinned to 0/1. Keeps the term
# honest as one weighted vote and keeps a clean click track non-extreme.
_CONFIDENCE_CEILING = 0.85


def _section_rates(env: np.ndarray, sr: int, hop_length: int, n_sections: int) -> np.ndarray:
    """Per-section high-band onset rate (events per minute), length ``n_sections``.

    Peaks are picked against the GLOBAL envelope maximum (not a per-section max),
    so a quiet section cannot rescale its own noise floor up into apparent
    activity, and a section carrying the dense hat stream reads at the full rate.
    """
    from scipy.signal import find_peaks

    e = np.asarray(env, dtype=np.float64)
    n_sections = max(1, int(n_sections))
    rates = np.zeros(n_sections, dtype=np.float64)
    if e.size < n_sections * 2:
        return rates
    gmax = float(np.max(e))
    if gmax <= _EPS:
        return rates

    fps = sr / float(hop_length)
    bounds = np.linspace(0, e.size, n_sections + 1).astype(int)
    for i in range(n_sections):
        seg = e[bounds[i] : bounds[i + 1]]
        if seg.size < 2:
            continue
        idx, _ = find_peaks(seg, height=_PEAK_REL_HEIGHT * gmax, distance=_PEAK_MIN_DISTANCE)
        dur_min = seg.size / fps / 60.0
        rates[i] = idx.size / dur_min if dur_min > _EPS else 0.0
    return rates


def _tatum_and_active(rates: np.ndarray) -> tuple[float | None, float]:
    """Derive the sustained tatum (BPM) and active-section fraction from per-section rates.

    * **Tatum** is the median rate of the *carrying* sections — those at or above
      half the busiest section's rate. Taking the median of the carrying sections
      (rather than the global onset count) recovers the true fast subdivision
      even when the dense hats occupy only part of the track, and is robust to a
      few unusually busy or quiet sections.
    * **active_fraction** is the fraction of sections whose rate reaches half the
      tatum — i.e. that actually sustain the fast stream. A one-section roll
      yields a low fraction even though it pins the tatum high, which is exactly
      what gates a transient burst out of the doubling evidence.
    """
    rates = np.asarray(rates, dtype=np.float64)
    busiest = float(np.max(rates)) if rates.size else 0.0
    if busiest <= _EPS:
        return None, 0.0
    carrying = rates[rates >= _SECTION_ACTIVE_FRAC * busiest]
    if carrying.size == 0:
        return None, 0.0
    tatum = float(np.median(carrying))
    if tatum <= _EPS:
        return None, 0.0
    active_fraction = float(np.mean(rates >= _SECTION_ACTIVE_FRAC * tatum))
    return tatum, active_fraction


def _tatum_from_curve(curve: TempoCurve) -> float | None:
    """Fallback tatum: the strongest peak of the high-band product tempogram.

    Used only when the onset envelope yields no usable per-section rate. The
    product tempogram is octave-resistant and grid-capped, so this is a coarse
    backstop rather than the primary estimator.
    """
    from ..tempogram import curve_peaks

    peaks = curve_peaks(curve, n=1, min_salience=0.05)
    if not peaks:
        return None
    return float(peaks[0][0])


def _periodicity_at_rate(env: np.ndarray, sr: int, hop_length: int, rate_bpm: float) -> float:
    """Normalised autocorrelation of the (smoothed) envelope at the tatum lag.

    A real periodic hat stream peaks here; broadband noise has a flat
    autocorrelation and scores ~0. Returned in [0, 1].
    """
    from scipy.ndimage import gaussian_filter1d

    e = np.asarray(env, dtype=np.float64)
    if e.size < 16 or float(np.max(e)) <= _EPS or rate_bpm <= _EPS:
        return 0.0
    e = gaussian_filter1d(e, sigma=1.0)
    e = e - e.mean()
    if np.linalg.norm(e) <= _EPS:
        return 0.0

    m = e.size
    nfft = 1 << int(np.ceil(np.log2(2 * m)))
    spec = np.fft.rfft(e, nfft)
    acf = np.fft.irfft(spec * np.conj(spec), nfft)[:m]
    acf = acf / (acf[0] + _EPS)

    fps = sr / float(hop_length)
    lag = 60.0 * fps / rate_bpm
    li = int(round(lag))
    if li < 1 or li >= m - 1:
        return 0.0
    lo, hi = max(1, li - 1), min(m - 1, li + 1)
    return float(np.clip(np.max(acf[lo : hi + 1]), 0.0, 1.0))


def _ratio_plausibility(ratio: float, params: HihatParams) -> float:
    """Map tatum:beat ``ratio`` to a plausibility in [0, 1].

    * ``ratio >= implausible_ratio``  -> hats are constant 32nds/64ths under this
      candidate: small value, decaying as the ratio grows (this is the "should be
      doubled" signal — the doubled candidate gets half the ratio and a high
      value).
    * otherwise -> Gaussian bump on the relative distance to the nearest musical
      subdivision, so a clean small subdivision (esp. 4 = straight 16ths) scores
      near 1 and non-musical ratios fall off.
    """
    if ratio <= _EPS:
        return 0.0
    if ratio >= params.implausible_ratio:
        # Anchor just below the musical band at the boundary, decaying further
        # the finer the (implied) subdivision becomes.
        return float(np.clip(0.18 * (params.implausible_ratio / ratio), 0.0, 0.2))
    ratios = np.asarray(params.musical_ratios, dtype=np.float64)
    ratios = ratios[ratios > _EPS]
    if ratios.size == 0:
        return 0.0
    rel_dist = float(np.min(np.abs(ratio - ratios) / ratios))
    return float(np.exp(-(rel_dist**2) / (2.0 * _PLAUSIBILITY_SIGMA**2)))


def score_hihat_density(bpm: float, features: Features, params: HihatParams) -> TermScore:
    """Evidence term: does the high-band subdivision support this candidate?

    See the module docstring for the full algorithm. Returns a finite
    :class:`TermScore` in [0, 1]; never raises and never returns NaN.
    """
    detail: dict = {"tatum_bpm": None, "ratio": None, "active_fraction": 0.0}

    if bpm <= 0:
        return TermScore(value=_NEUTRAL, detail=detail)

    bands = features.bands
    high = np.asarray(bands.high, dtype=np.float64)
    sr, hop = features.sr, features.hop_length

    # --- Tatum + sustained density, both derived from per-section onset rates. ---
    rates = _section_rates(high, sr, hop, params.n_sections)
    tatum, active_fraction = _tatum_and_active(rates)
    tatum_source = "section_rate"
    if tatum is None:
        # No usable per-section rate; fall back to the high-band product tempogram.
        tatum = _tatum_from_curve(features.high_curve)
        tatum_source = "high_curve"
    if tatum is None or tatum <= _EPS:
        # No usable high-band evidence (silence / empty band). Neutral-low.
        detail["source"] = "none"
        return TermScore(value=_NEUTRAL, detail=detail)

    ratio = tatum / bpm
    plausibility = _ratio_plausibility(ratio, params)

    sustained = active_fraction >= params.min_active_sections

    # --- Periodicity confidence (suppresses noise pretending to be dense). ---
    periodicity = _periodicity_at_rate(high, sr, hop, tatum)

    # Multiplicative gates blend the plausibility verdict back toward the neutral
    # baseline when the density is not sustained or not genuinely periodic. Both
    # gates are candidate-independent (they describe the high band, not the
    # candidate), so they scale every candidate of a track equally and cannot, by
    # themselves, flip which octave wins. When the density is NOT sustained the
    # gate is halved so a transient roll/fill is heavily discounted as doubling
    # evidence. ``_CONFIDENCE_CEILING`` keeps even a perfectly clean, periodic
    # subdivision from pinning the value to the extremes (the term is one of
    # several weighted votes, not a verdict on its own).
    density_gate = active_fraction if sustained else 0.5 * active_fraction
    density_gate = float(np.clip(density_gate, 0.0, 1.0))
    periodicity_gate = float(np.clip(0.4 + 0.6 * periodicity, 0.4, 1.0))
    confidence = _CONFIDENCE_CEILING * density_gate * periodicity_gate

    value = _NEUTRAL + (plausibility - _NEUTRAL) * confidence
    value = float(np.clip(value, 0.0, 1.0))

    detail.update(
        {
            "tatum_bpm": round(float(tatum), 2),
            "ratio": round(float(ratio), 3),
            "active_fraction": round(float(active_fraction), 3),
            "plausibility": round(float(plausibility), 3),
            "periodicity": round(float(periodicity), 3),
            "sustained": bool(sustained),
            "source": tatum_source,
        }
    )
    return TermScore(value=value, detail=detail)
