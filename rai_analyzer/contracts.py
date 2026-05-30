"""Data contracts for RAI Audio Analyzer v2.

This module is the single source of truth for the shapes that flow through the
analyzer. Every other module — the DSP layer, the evidence-term functions, the
resolver, the GUI, and the validation harness — imports its types from here and
nowhere else. Keep this module dependency-light (numpy only) so it can be
imported by anything without pulling in librosa.

The design intent (from the build spec): the tempo engine must *never silently
pick an octave*. Its job is to surface a ranked, explained candidate set and to
flag ambiguity for a human tiebreak. These dataclasses are built around that
contract: a `Candidate` always carries why it was ranked where it was, and a
`TempoResult` always carries whether the answer is trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Signal-layer contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BandEnvelopes:
    """Per-band onset-strength envelopes on a shared frame grid.

    Multiband onset detection (spec section 1) splits the signal into three
    perceptual streams that carry independent rhythmic evidence:

    * ``low``  — kick / 808 / low transients
    * ``mid``  — snare / clap / body of the groove
    * ``high`` — hats / clicks / shakers (the subdivision stream)

    ``full`` is the summed broadband onset envelope, used for the primary
    tempogram. All envelopes share ``times`` (frame centre times, seconds).
    """

    sr: int
    hop_length: int
    times: np.ndarray  # (T,) frame centre times in seconds
    low: np.ndarray  # (T,) E_low onset strength
    mid: np.ndarray  # (T,) E_mid onset strength
    high: np.ndarray  # (T,) E_high onset strength
    full: np.ndarray  # (T,) broadband onset strength

    @property
    def frame_rate(self) -> float:
        """Onset-envelope sample rate (frames per second)."""
        return self.sr / self.hop_length

    def band(self, name: str) -> np.ndarray:
        return {"low": self.low, "mid": self.mid, "high": self.high, "full": self.full}[name]


@dataclass(frozen=True)
class TempoCurve:
    """A 1-D global tempo-salience curve on a BPM grid.

    This is *not* the 2-D librosa tempogram — it is the time-averaged,
    octave-resistant salience produced by the product tempogram (spec section
    2). ``salience`` is the ACF x DFT product (normalised to its own max);
    ``acf`` and ``dft`` are the two factors retained for diagnostics and for
    the raw-vs-priored ambiguity trigger.
    """

    bpms: np.ndarray  # (B,) BPM grid (monotonic increasing)
    salience: np.ndarray  # (B,) product salience, normalised to [0, 1]
    acf: np.ndarray  # (B,) autocorrelation-tempogram salience (aliases DOWN)
    dft: np.ndarray  # (B,) Fourier-tempogram salience (aliases UP)

    def value_at(self, bpm: float) -> float:
        """Linear-interpolated product salience at an arbitrary BPM."""
        return float(np.interp(bpm, self.bpms, self.salience, left=0.0, right=0.0))

    def factor_at(self, bpm: float, which: str) -> float:
        arr = {"acf": self.acf, "dft": self.dft, "salience": self.salience}[which]
        return float(np.interp(bpm, self.bpms, arr, left=0.0, right=0.0))


@dataclass(frozen=True)
class Features:
    """Everything an evidence term needs, computed exactly once per file.

    The resolver builds this and hands the *same* immutable instance to every
    evidence term. Terms must treat it as read-only. This is what lets the
    evidence functions be pure, independently testable, and parallel-safe.
    """

    sr: int
    hop_length: int
    duration: float
    bands: BandEnvelopes
    tempo_curve: TempoCurve  # combined (low+mid weighted) product tempogram
    high_curve: TempoCurve  # high-band-only product tempogram (hi-hat density)


# ---------------------------------------------------------------------------
# Tempo-resolution contracts
# ---------------------------------------------------------------------------


class Relationship(str, Enum):
    """How a candidate relates to the chosen primary tempo.

    Used both to explain the candidate set to a human and to drive ambiguity
    detection (octave/fractional partners scoring strongly = ambiguous).
    """

    SELF = "self"
    OCTAVE_UP = "octave_up"  # ~x2
    OCTAVE_DOWN = "octave_down"  # ~x1/2
    TRIPLE = "triple"  # ~x3
    THIRD = "third"  # ~x1/3
    DOTTED_UP = "dotted_up"  # ~x3/2
    DOTTED_DOWN = "dotted_down"  # ~x2/3
    FRACTIONAL = "fractional"  # other small-integer ratio (e.g. ~5:8 tresillo alias)
    UNRELATED = "unrelated"


# Canonical ratios for relationship classification, ordered by specificity.
_RATIO_TABLE: tuple[tuple[float, Relationship], ...] = (
    (1.0, Relationship.SELF),
    (2.0, Relationship.OCTAVE_UP),
    (0.5, Relationship.OCTAVE_DOWN),
    (3.0, Relationship.TRIPLE),
    (1.0 / 3.0, Relationship.THIRD),
    (3.0 / 2.0, Relationship.DOTTED_UP),
    (2.0 / 3.0, Relationship.DOTTED_DOWN),
    # Fractional aliases seen in the wild (tresillo / dotted-eighth locks).
    (5.0 / 8.0, Relationship.FRACTIONAL),
    (8.0 / 5.0, Relationship.FRACTIONAL),
    (3.0 / 4.0, Relationship.FRACTIONAL),
    (4.0 / 3.0, Relationship.FRACTIONAL),
    (5.0 / 4.0, Relationship.FRACTIONAL),
    (4.0 / 5.0, Relationship.FRACTIONAL),
    (5.0 / 6.0, Relationship.FRACTIONAL),
    (6.0 / 5.0, Relationship.FRACTIONAL),
)


def classify_relationship(bpm: float, reference: float, tol: float = 0.04) -> Relationship:
    """Classify ``bpm`` relative to ``reference`` by nearest simple ratio.

    ``tol`` is the fractional tolerance on the ratio (default 4%). Anything that
    does not land near a tabled ratio is ``UNRELATED``.
    """
    if reference <= 0 or bpm <= 0:
        return Relationship.UNRELATED
    ratio = bpm / reference
    best: Optional[Relationship] = None
    best_err = tol
    for target, rel in _RATIO_TABLE:
        err = abs(ratio - target) / target
        if err < best_err:
            best_err = err
            best = rel
    return best if best is not None else Relationship.UNRELATED


@dataclass
class TermScore:
    """One evidence term's verdict on one candidate.

    ``value`` is normalised to [0, 1] (higher = the term favours this
    candidate). ``detail`` carries diagnostics for the report / debugging.
    Every evidence term returns this exact shape — that uniformity is what
    makes the resolver a simple weighted sum and lets terms be built in
    parallel against a fixed contract.
    """

    value: float
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Defensive clamp: terms should already return [0, 1], but the resolver
        # must never be poisoned by a stray NaN or out-of-range value.
        v = float(self.value)
        if not np.isfinite(v):
            v = 0.0
        self.value = min(1.0, max(0.0, v))


@dataclass
class Candidate:
    """A tempo hypothesis with its full evidential record."""

    bpm: float
    score: float = 0.0  # total weighted evidence score
    salience: float = 0.0  # product-tempogram salience [0, 1], surfaced to user
    relationship: Relationship = Relationship.SELF  # vs the chosen primary
    terms: dict = field(default_factory=dict)  # term name -> TermScore

    def to_dict(self) -> dict:
        return {
            "bpm": round(self.bpm, 2),
            "salience": round(self.salience, 3),
            "score": round(self.score, 4),
            "relationship": self.relationship.value,
            "terms": {k: round(v.value, 3) for k, v in self.terms.items()},
        }


@dataclass
class TempoResult:
    """The tempo engine's complete, human-auditable verdict.

    ``ambiguous`` + ``ambiguity_reason`` are the signature feature: when the
    engine cannot honestly commit to one octave, it says so rather than
    emitting a confident wrong number. ``raw_best_bpm`` / ``priored_best_bpm``
    expose the raw-vs-priored divergence trigger for transparency.
    """

    primary_bpm: float
    felt_bpm: Optional[float]
    candidates: list[Candidate]
    ambiguous: bool
    ambiguity_reason: Optional[str] = None
    raw_best_bpm: Optional[float] = None
    priored_best_bpm: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "primary_bpm": round(self.primary_bpm, 2),
            "felt_bpm": round(self.felt_bpm, 2) if self.felt_bpm is not None else None,
            "ambiguous": self.ambiguous,
            "ambiguity_reason": self.ambiguity_reason,
            "raw_best_bpm": round(self.raw_best_bpm, 2) if self.raw_best_bpm is not None else None,
            "priored_best_bpm": (
                round(self.priored_best_bpm, 2) if self.priored_best_bpm is not None else None
            ),
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ---------------------------------------------------------------------------
# Loudness contracts (Tier-1 measurements)
# ---------------------------------------------------------------------------


@dataclass
class LoudnessResult:
    """Loudness vs. commercial targets (ITU-R BS.1770 / EBU R128).

    Dynamic range / crest factor is explicitly deferred per spec, so it is not
    here.
    """

    lufs_i: float  # integrated loudness (LUFS)
    true_peak_dbtp: float  # true peak (dBTP), >= sample peak
    sample_peak_dbfs: float  # raw sample peak (dBFS)

    def to_dict(self) -> dict:
        return {
            "lufs_i": round(self.lufs_i, 2),
            "true_peak_dbtp": round(self.true_peak_dbtp, 2),
            "sample_peak_dbfs": round(self.sample_peak_dbfs, 2),
        }


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------


@dataclass
class AnalysisResult:
    """The complete analysis of one audio file."""

    path: str
    duration: float
    sr: int
    channels: int
    tempo: TempoResult
    loudness: Optional[LoudnessResult] = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "duration": round(self.duration, 2),
            "sr": self.sr,
            "channels": self.channels,
            "tempo": self.tempo.to_dict(),
            "loudness": self.loudness.to_dict() if self.loudness else None,
        }

    def to_report(self) -> str:
        """Render the human-readable text panel shown in the GUI output tab.

        Defined here (not in the GUI) so the CLI, the validation harness, and
        the GUI all show byte-identical reports.
        """
        import os

        t = self.tempo
        lines: list[str] = []
        lines.append(f"FILE     {os.path.basename(self.path)}")
        lines.append(f"LENGTH   {self.duration:6.1f} s    {self.sr} Hz    {self.channels} ch")
        lines.append("")
        lines.append("=" * 52)
        if t.ambiguous:
            lines.append("TEMPO    ⚠  AMBIGUOUS — human tiebreak recommended")
        else:
            lines.append("TEMPO    ✓  confident")
        lines.append("=" * 52)
        lines.append(f"  primary   {t.primary_bpm:7.2f} BPM")
        if t.felt_bpm is not None:
            lines.append(f"  felt      {t.felt_bpm:7.2f} BPM")
        if t.ambiguity_reason:
            lines.append(f"  note      {t.ambiguity_reason}")
        if t.raw_best_bpm is not None and t.priored_best_bpm is not None:
            lines.append(
                f"  raw peak  {t.raw_best_bpm:7.2f} BPM   "
                f"priored {t.priored_best_bpm:7.2f} BPM"
            )
        lines.append("")
        lines.append("  CANDIDATES (ranked)")
        lines.append("  " + "-" * 50)
        lines.append(f"  {'BPM':>8}  {'salience':>8}  {'score':>7}  relationship")
        for c in t.candidates:
            lines.append(
                f"  {c.bpm:8.2f}  {c.salience:8.3f}  {c.score:7.3f}  {c.relationship.value}"
            )
        lines.append("")
        if self.loudness is not None:
            ld = self.loudness
            lines.append("=" * 52)
            lines.append("LOUDNESS")
            lines.append("=" * 52)
            lines.append(f"  integrated   {ld.lufs_i:7.2f} LUFS")
            lines.append(f"  true peak    {ld.true_peak_dbtp:7.2f} dBTP")
            lines.append(f"  sample peak  {ld.sample_peak_dbfs:7.2f} dBFS")
        return "\n".join(lines)
