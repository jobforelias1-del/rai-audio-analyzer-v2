"""RAI Audio Analyzer — octave-resistant tempo analysis for drill/trap.

The signature feature: *this number is reliable.* The tempo engine never
silently picks an octave — it surfaces a ranked, explained candidate set and
flags ambiguity for a human tiebreak, which is the inverse of the failure mode
(a confidently wrong BPM) that triggered this rebuild.
"""

from __future__ import annotations

from .analyzer import analyze_file
from .config import DEFAULT_CONFIG, TempoConfig
from .contracts import (
    AnalysisResult,
    Candidate,
    LoudnessResult,
    Relationship,
    TempoResult,
)

__version__ = "3.0.0"

__all__ = [
    "analyze_file",
    "TempoConfig",
    "DEFAULT_CONFIG",
    "AnalysisResult",
    "TempoResult",
    "Candidate",
    "LoudnessResult",
    "Relationship",
    "__version__",
]
