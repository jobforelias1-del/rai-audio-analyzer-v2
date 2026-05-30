"""Validation harness for RAI Audio Analyzer v2 — the ACCEPTANCE GATE.

The build spec is explicit: *green unit tests are not the gate; passing the
ground-truth tracks is the gate.* This package runs that gate.

It loads the DAW-warp-confirmed ground truth (``ground_truth.py``), runs the
real :func:`rai_analyzer.analyze_file` pipeline over whatever fixtures are
present, and prints a per-track verdict (predicted vs true vs felt, whether the
truth was surfaced as a candidate, whether the engine flagged ambiguity, and the
full ranked candidate list). When no real fixtures are present it runs the SAME
gate logic over synthetic drill beats so the harness always produces visible,
three-track-format output and proves the pipeline + gate both work.

Run it with ``python3 -m validation``.
"""

from __future__ import annotations

from .ground_truth import FIXTURES_DIR, GROUND_TRUTH, GroundTruthTrack
from .harness import TrackOutcome, run_gate

__all__ = [
    "run_gate",
    "TrackOutcome",
    "GROUND_TRUTH",
    "GroundTruthTrack",
    "FIXTURES_DIR",
]
