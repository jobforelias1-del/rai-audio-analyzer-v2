"""Tunable configuration for the tempo engine.

The build spec is explicit: *each evidence term is a separate, independently
testable function with named, tunable weights, so resolution heuristics can be
adjusted against the gate without touching the rest.* This module is where
those named constants live. Nothing in here is magic-numbered into the engine;
the resolver and every term receive their slice of this config.

To tune against the acceptance gate, edit values here (or build a `TempoConfig`
in the harness) and re-run the validation harness — no engine code changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Audio is resampled to this rate before tempo analysis. 22.05 kHz is the
# librosa default and is more than enough for onset/tempo work; it keeps the
# tempograms fast. Loudness is measured on the ORIGINAL-rate signal, not this.
ANALYSIS_SR: int = 22050

# STFT hop for onset envelopes -> onset-envelope frame rate = SR / HOP.
HOP_LENGTH: int = 512

# Multiband split points (Hz). low < LOW_MID_HZ < mid < MID_HIGH_HZ < high.
LOW_MID_HZ: float = 200.0
MID_HIGH_HZ: float = 8000.0


@dataclass
class PriorParams:
    """Soft log-normal tempo prior, fit from the ground-truth set.

    The prior favours the region where drill/trap is *notated* (full-time,
    ~130-175) over the half-time feel region (~65-90). It is deliberately SOFT
    (wide sigma, non-zero floor) so it nudges rather than dictates — its main
    job is to power the raw-vs-priored divergence ambiguity trigger, not to
    overrule strong rhythmic evidence.

    Re-fit from the WAVs via ``rai_analyzer.evidence.prior.fit_prior`` once the
    ground-truth fixtures are dropped in.
    """

    center_bpm: float = 145.0  # geometric centre (BPM) of the prior bump
    sigma: float = 0.30  # width in natural-log-BPM units (soft)
    floor: float = 0.12  # minimum prior weight (keeps the prior from zeroing a candidate)


@dataclass
class FingerprintParams:
    """Metrical-profile fingerprint term — the strongest genre-specific weapon.

    Each band's onset energy is folded into a ``bins_per_bar``-bin grid at the
    candidate's best phase and compared to a genre fingerprint learned by
    averaging the folded profiles of the ground-truth tracks.
    """

    bins_per_bar: int = 16  # 16th-note grid over one bar
    beats_per_bar: int = 4  # assume 4/4
    phase_search_steps: int = 16  # phase offsets tried when folding (== bins_per_bar)
    bands: tuple[str, ...] = ("low", "mid", "high")
    # Path to the learned fingerprint JSON; None => packaged default drill.json.
    fingerprint_path: Optional[str] = None


@dataclass
class HihatParams:
    """Hi-hat subdivision-density term.

    Expresses the dominant high-band tatum as a fraction of the candidate beat.
    A persistent high-band stream that only parses as constant 32nds/64ths
    under the slower candidate is evidence to double. Density must be SUSTAINED
    across sections (guards against transient rolls/fills).
    """

    min_band_hz: float = MID_HIGH_HZ  # high band lower edge
    n_sections: int = 6  # split track into N sections for the sustained-density check
    min_active_sections: float = 0.6  # fraction of sections that must show the density
    # Tatum:beat ratios a human hears as musical subdivisions. A candidate whose
    # hat stream lands on one of these (esp. 4 = straight 16ths) is plausible;
    # one that forces 8/16 (32nds/64ths everywhere) is probably too slow.
    musical_ratios: tuple[float, ...] = (1.0, 2.0, 3.0, 4.0, 6.0)
    implausible_ratio: float = 6.5  # ratio at/above which we treat hats as "too fine"


@dataclass
class TempogramTermParams:
    """Raw product-tempogram salience term (octave-resistant base evidence)."""

    sharpen: float = 1.0  # exponent applied to salience (>1 sharpens peaks)


@dataclass
class CandidateParams:
    """Candidate generation (spec: do NOT restrict to {1/2, 1, 2})."""

    # Octave AND fractional multipliers. 2/3 & 3/2 catch dotted / triplet locks;
    # the engine also injects independent tempogram peaks (e.g. the ~5:8 alias).
    multipliers: tuple[float, ...] = (1 / 3, 1 / 2, 2 / 3, 1.0, 3 / 2, 2.0, 3.0)
    bpm_min: float = 60.0  # plausible reported-tempo floor
    bpm_max: float = 200.0  # plausible reported-tempo ceiling
    dedup_tol: float = 0.03  # candidates within 3% are the same reported tempo; merge
    n_independent_peaks: int = 4  # add up to N strong product-tempogram peaks directly
    independent_peak_floor: float = 0.20  # min salience for an injected independent peak


@dataclass
class AmbiguityParams:
    """When to decline to force-pick an octave."""

    # Trigger 1 (most reliable): raw argmax(tempogram) vs argmax(tempogram*prior)
    # differ by more than this fraction => the prior is fighting the raw signal.
    divergence_tol: float = 0.03
    # Trigger 2: the runner-up is octave/fractional-related to the winner AND
    # scores within this fraction of the winner.
    score_close_frac: float = 0.82
    # The "felt" (tappable) tempo band, used to derive felt_bpm.
    felt_min: float = 60.0
    felt_max: float = 110.0


@dataclass
class ResolverWeights:
    """Weights for the evidence-term weighted sum.

    The fingerprint is the strongest genre-specific weapon, so it leads. The
    prior is intentionally the lightest scoring term (it does its real work in
    the divergence trigger, not by overruling rhythm).
    """

    fingerprint: float = 1.0
    hihat_density: float = 0.7
    tempogram: float = 0.6
    prior: float = 0.4


@dataclass
class TempoConfig:
    """The complete tunable surface of the tempo engine."""

    prior: PriorParams = field(default_factory=PriorParams)
    fingerprint: FingerprintParams = field(default_factory=FingerprintParams)
    hihat: HihatParams = field(default_factory=HihatParams)
    tempogram_term: TempogramTermParams = field(default_factory=TempogramTermParams)
    candidates: CandidateParams = field(default_factory=CandidateParams)
    ambiguity: AmbiguityParams = field(default_factory=AmbiguityParams)
    weights: ResolverWeights = field(default_factory=ResolverWeights)

    # Product-tempogram BPM grid.
    bpm_grid_min: float = 40.0
    bpm_grid_max: float = 240.0
    bpm_grid_step: float = 0.25

    # Band weights when combining onset envelopes into the primary tempogram.
    # Low+mid carry the beat; high is down-weighted here (it drives the separate
    # hi-hat-density term and its own high_curve instead).
    band_weights: tuple[float, float, float] = (1.0, 1.0, 0.3)  # (low, mid, high)


DEFAULT_CONFIG = TempoConfig()
