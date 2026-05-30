"""Ground truth for the acceptance gate — DAW-warp confirmed.

These three tracks are the gate. Their true tempos were confirmed by warping
each track to a grid in a DAW (and, for the Taco track, cross-checked against an
external/Google-confirmed value). ``v1_wrong_bpm`` records the confident-wrong
number RAI Audio Analyzer v1 produced for the track — the exact failure mode
(a silently-picked octave / fractional alias) this rebuild exists to never
reproduce. ``None`` means v1 had no recorded wrong number for that track.

This module is pure data + paths. It pulls in nothing heavy (no librosa/numpy),
so anything can import the truth table cheaply.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

# Absolute path to the fixtures directory. The real ground-truth WAVs are large
# binaries and are .gitignored (see fixtures/README.md); the producer drops them
# in here and the harness auto-detects them.
FIXTURES_DIR: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@dataclass(frozen=True)
class GroundTruthTrack:
    """One DAW-warp-confirmed ground-truth track.

    ``true_bpm``      — the confirmed notated tempo (the gate target).
    ``v1_wrong_bpm``  — v1's confident-wrong number, or ``None`` if none recorded.
    ``error_type``    — human-readable description of v1's failure for that track.
    """

    name: str
    filename: str
    true_bpm: float
    v1_wrong_bpm: Optional[float]
    error_type: str

    @property
    def path(self) -> str:
        """Absolute path where this track's WAV is expected to live."""
        return os.path.join(FIXTURES_DIR, self.filename)

    def exists(self) -> bool:
        """True if the fixture WAV is present on disk."""
        return os.path.isfile(self.path)


# The truth table. Order is intentional (matches how the producer presents them).
GROUND_TRUTH: tuple[GroundTruthTrack, ...] = (
    GroundTruthTrack(
        name="Ledger En Acier",
        filename="ledger_en_acier.wav",
        true_bpm=166.01,
        v1_wrong_bpm=83.0,
        error_type="octave (x2)",
    ),
    GroundTruthTrack(
        name="Mathematics of the Menace",
        filename="mathematics_of_the_menace.wav",
        true_bpm=153.85,
        v1_wrong_bpm=96.0,
        error_type="fractional (~5:8)",
    ),
    GroundTruthTrack(
        name="Taco — Puttin' On The Ritz",
        filename="taco_puttin_on_the_ritz.wav",
        true_bpm=99.0,
        v1_wrong_bpm=None,
        error_type="external cross-check (Google-confirmed)",
    ),
)


def available_tracks() -> list[GroundTruthTrack]:
    """The subset of ground-truth tracks whose WAV fixtures are present."""
    return [t for t in GROUND_TRUTH if t.exists()]
