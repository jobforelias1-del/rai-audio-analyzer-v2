"""The acceptance gate.

Spec: *green unit tests are not the gate. Passing the ground-truth tracks is the
gate.* This module runs the real :func:`rai_analyzer.analyze_file` pipeline over
the ground-truth fixtures and applies the gate criterion to each.

The gate criterion (per track)::

    recall            = the truth was surfaced as a candidate at all
    avoided_v1_error  = the primary BPM did NOT reproduce v1's confident-wrong number
    hit               = the primary BPM matched the truth within tolerance
    flagged           = the engine flagged the result ambiguous

    PASS  <=>  recall AND avoided_v1_error AND (hit OR flagged)

Rationale: the signature feature is *reliability*. A confidently-wrong octave
fails. But either nailing the truth OR honestly flagging ambiguity (with the
truth surfaced in the candidate set for a human tiebreak) passes — both are
trustworthy outcomes, which is the inverse of v1's failure mode.

When no real fixtures are present, the harness synthesises drill beats and runs
the *same* gate logic + printing, so it always emits visible three-track-format
output and proves the pipeline and the gate both work.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from typing import Optional

from rai_analyzer import analyze_file
from rai_analyzer.contracts import AnalysisResult

from .ground_truth import GROUND_TRUTH, GroundTruthTrack, available_tracks

# ---------------------------------------------------------------------------
# Per-track outcome
# ---------------------------------------------------------------------------


@dataclass
class TrackOutcome:
    """The gate's verdict for a single track, with the numbers behind it."""

    name: str
    true_bpm: float
    v1_wrong_bpm: Optional[float]
    error_type: str

    primary_bpm: float
    felt_bpm: Optional[float]
    flagged: bool

    hit: bool
    recall: bool
    avoided_v1_error: bool

    @property
    def passed(self) -> bool:
        """Gate criterion: truth surfaced, v1 error avoided, and right-or-honest."""
        return self.recall and self.avoided_v1_error and (self.hit or self.flagged)


# ---------------------------------------------------------------------------
# Core gate evaluation (shared by the real gate and the synthetic self-test)
# ---------------------------------------------------------------------------


def _evaluate(
    track: GroundTruthTrack,
    result: AnalysisResult,
    tol: float,
    recall_tol: float,
) -> TrackOutcome:
    """Apply the gate criterion to one analysis result against its ground truth."""
    t = result.tempo
    true_bpm = track.true_bpm

    hit = abs(t.primary_bpm - true_bpm) <= tol * true_bpm

    # Recall: was the truth surfaced as a candidate at all?
    recall = any(abs(c.bpm - true_bpm) <= recall_tol * true_bpm for c in t.candidates)

    # Avoided v1's confident-wrong number? (No recorded wrong number => trivially yes.)
    if track.v1_wrong_bpm is None:
        avoided_v1_error = True
    else:
        avoided_v1_error = abs(t.primary_bpm - track.v1_wrong_bpm) > tol * track.v1_wrong_bpm

    return TrackOutcome(
        name=track.name,
        true_bpm=true_bpm,
        v1_wrong_bpm=track.v1_wrong_bpm,
        error_type=track.error_type,
        primary_bpm=t.primary_bpm,
        felt_bpm=t.felt_bpm,
        flagged=t.ambiguous,
        hit=hit,
        recall=recall,
        avoided_v1_error=avoided_v1_error,
    )


def _yn(flag: bool) -> str:
    return "YES" if flag else "no "


def _print_track_block(
    track: GroundTruthTrack,
    result: AnalysisResult,
    outcome: TrackOutcome,
    recall_tol: float,
) -> None:
    """Print the per-track gate block: truth vs predicted vs felt, flags, candidates."""
    t = result.tempo
    verdict = "PASS" if outcome.passed else "FAIL"

    felt_str = f"{outcome.felt_bpm:7.2f}" if outcome.felt_bpm is not None else "   None"
    v1_str = f"{outcome.v1_wrong_bpm:.2f}" if outcome.v1_wrong_bpm is not None else "none recorded"

    print("-" * 72)
    print(f"  {track.name}    [{verdict}]")
    print("-" * 72)
    print(f"    true       {outcome.true_bpm:7.2f} BPM")
    print(f"    predicted  {outcome.primary_bpm:7.2f} BPM  (primary)")
    print(f"    felt       {felt_str} BPM")
    print(f"    v1 wrong   {v1_str}    [{track.error_type}]")
    print(
        f"    flagged?   {_yn(outcome.flagged)}     "
        f"recall?  {_yn(outcome.recall)}     "
        f"hit?  {_yn(outcome.hit)}     "
        f"avoided-v1?  {_yn(outcome.avoided_v1_error)}"
    )
    reason = t.ambiguity_reason if t.ambiguity_reason else "(none — engine was confident)"
    print(f"    ambiguity  {reason}")
    if t.raw_best_bpm is not None and t.priored_best_bpm is not None:
        print(
            f"    raw peak   {t.raw_best_bpm:7.2f} BPM    "
            f"priored peak {t.priored_best_bpm:7.2f} BPM"
        )
    print()
    print(f"    CANDIDATES (ranked)   [truth = {outcome.true_bpm:.2f} BPM]")
    print(f"      {'BPM':>8}  {'salience':>8}  {'score':>7}  relationship")
    for c in t.candidates:
        # Mark with the SAME tolerance that drove the recall? verdict, so the
        # printed "<- truth" markers always agree with the recall column.
        is_truth = abs(c.bpm - outcome.true_bpm) <= recall_tol * outcome.true_bpm
        marker = "  <- truth" if is_truth else ""
        print(
            f"      {c.bpm:8.2f}  {c.salience:8.3f}  {c.score:7.3f}  "
            f"{c.relationship.value}{marker}"
        )
    print()


def _print_aggregate(outcomes: list[TrackOutcome], gate_passed: bool, label: str) -> None:
    """Print the aggregate rates and the overall gate verdict."""
    n = len(outcomes)
    if n == 0:
        return
    recall_rate = sum(o.recall for o in outcomes) / n
    ambiguity_rate = sum(o.flagged for o in outcomes) / n
    hit_rate = sum(o.hit for o in outcomes) / n
    avoid_rate = sum(o.avoided_v1_error for o in outcomes) / n
    n_pass = sum(o.passed for o in outcomes)

    print("=" * 72)
    print(f"  AGGREGATE  ({label})")
    print("=" * 72)
    print(f"    candidate-set RECALL  (truth surfaced)      {recall_rate:6.1%}   ({sum(o.recall for o in outcomes)}/{n})")
    print(f"    AMBIGUITY rate        (declined force-pick)  {ambiguity_rate:6.1%}   ({sum(o.flagged for o in outcomes)}/{n})")
    print(f"    exact-HIT rate        (primary == truth)     {hit_rate:6.1%}   ({sum(o.hit for o in outcomes)}/{n})")
    print(f"    v1-error AVOIDANCE    (no confident-wrong)   {avoid_rate:6.1%}   ({sum(o.avoided_v1_error for o in outcomes)}/{n})")
    print()
    print(f"    tracks passing gate                          {n_pass}/{n}")
    print("=" * 72)
    status = "PASS" if gate_passed else "FAIL"
    print(f"  GATE: {status}   (pass <=> recall AND avoided-v1 AND (hit OR flagged), all tracks)")
    print("=" * 72)
    print()


def _run_over_tracks(
    pairs: list[tuple[GroundTruthTrack, AnalysisResult]],
    tol: float,
    recall_tol: float,
    label: str,
) -> bool:
    """Evaluate + print every (track, result) pair, then the aggregate. Returns gate pass."""
    outcomes: list[TrackOutcome] = []
    for track, result in pairs:
        outcome = _evaluate(track, result, tol, recall_tol)
        _print_track_block(track, result, outcome, recall_tol)
        outcomes.append(outcome)

    gate_passed = bool(outcomes) and all(o.passed for o in outcomes)
    _print_aggregate(outcomes, gate_passed, label)
    return gate_passed


# ---------------------------------------------------------------------------
# No-fixtures path: friendly instructions + synthetic self-test
# ---------------------------------------------------------------------------


def _print_missing_fixtures_help() -> None:
    """Explain exactly which WAVs to drop where when none are present."""
    from .ground_truth import FIXTURES_DIR

    print("=" * 72)
    print("  NO REAL FIXTURES FOUND")
    print("=" * 72)
    print("  The acceptance gate runs against the producer's DAW-warp-confirmed")
    print("  WAVs. They are large binaries and are .gitignored, so they are not in")
    print("  the repo. Drop these three files into the fixtures directory:")
    print()
    print(f"      {FIXTURES_DIR}")
    print()
    for t in GROUND_TRUTH:
        print(f"      {t.filename:<32}  (true {t.true_bpm:.2f} BPM — {t.name})")
    print()
    print("  Once present, the harness auto-detects and consumes them — just re-run")
    print("  `python3 -m validation`. See fixtures/README.md for details (including")
    print("  re-learning the drill fingerprint from these tracks).")
    print()
    print("  Meanwhile, running the SYNTHETIC SELF-TEST below to prove the pipeline")
    print("  and the gate logic both work end-to-end.")
    print()


# Synthetic stand-ins. drill_pattern(bpm) emits a beat whose NOTATED tempo is
# bpm but whose emphasised backbeat pulls autocorrelation toward bpm/2 — the
# octave pathology in miniature. We pair each with a v1-style wrong half-time
# number so the synthetic gate exercises the exact avoided_v1_error path.
_SYNTHETIC_SPECS: tuple[tuple[str, float, float, str], ...] = (
    ("Synthetic Drill @150", 150.0, 75.0, "octave (x1/2) — synthetic"),
    ("Synthetic Drill @154", 154.0, 77.0, "octave (x1/2) — synthetic"),
    ("Synthetic Drill @166", 166.0, 83.0, "octave (x1/2) — synthetic"),
)


def _build_synthetic_pairs(tmpdir: str) -> list[tuple[GroundTruthTrack, AnalysisResult]]:
    """Synthesize drill WAVs at the spec tempos, analyze them, return (track, result)."""
    from rai_analyzer.synthetic import drill_pattern, write_wav

    pairs: list[tuple[GroundTruthTrack, AnalysisResult]] = []
    for name, true_bpm, v1_wrong, err in _SYNTHETIC_SPECS:
        filename = f"synthetic_drill_{true_bpm:.0f}.wav"
        path = os.path.join(tmpdir, filename)
        write_wav(path, drill_pattern(true_bpm))
        track = GroundTruthTrack(
            name=name,
            filename=filename,
            true_bpm=true_bpm,
            v1_wrong_bpm=v1_wrong,
            error_type=err,
        )
        result = analyze_file(path, with_loudness=False)
        pairs.append((track, result))
    return pairs


def _run_synthetic_self_test(tol: float, recall_tol: float) -> bool:
    """Synthesize three drills and run the SAME gate logic + printing over them."""
    print("#" * 72)
    print("#  SYNTHETIC SELF-TEST (no real fixtures found)")
    print("#  Same gate logic + format as the real acceptance gate, on synthetic")
    print("#  drill beats. Proves the analyze_file pipeline and the gate both work.")
    print("#" * 72)
    print()
    with tempfile.TemporaryDirectory(prefix="rai_synth_") as tmpdir:
        pairs = _build_synthetic_pairs(tmpdir)
        return _run_over_tracks(pairs, tol, recall_tol, label="SYNTHETIC SELF-TEST")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_gate(tol: float = 0.02, recall_tol: float = 0.03) -> bool:
    """Run the acceptance gate.

    Analyzes every ground-truth fixture that is present and applies the gate
    criterion (recall AND avoided_v1_error AND (hit OR flagged)) to each; the
    overall gate passes iff all available tracks pass. ``tol`` is the fractional
    tolerance for an exact hit / for matching v1's wrong number; ``recall_tol``
    is the fractional tolerance for counting the truth as "surfaced".

    If no real fixtures are present, prints drop-in instructions and then runs
    the synthetic self-test (same logic + format). Returns the boolean gate
    result (synthetic self-test result when there are no real fixtures).
    """
    tracks = available_tracks()

    if not tracks:
        _print_missing_fixtures_help()
        return _run_synthetic_self_test(tol, recall_tol)

    print("#" * 72)
    print("#  REAL ACCEPTANCE GATE")
    print(f"#  {len(tracks)}/{len(GROUND_TRUTH)} ground-truth fixtures present.  "
          f"tol={tol:.0%}  recall_tol={recall_tol:.0%}")
    print("#  Spec: green unit tests are NOT the gate — passing these tracks is.")
    print("#" * 72)
    print()

    if len(tracks) < len(GROUND_TRUTH):
        missing = [t.filename for t in GROUND_TRUTH if not t.exists()]
        print(f"  NOTE: {len(missing)} fixture(s) missing — gate runs over the "
              f"{len(tracks)} present: {', '.join(missing)}")
        print()

    pairs = [(track, analyze_file(track.path, with_loudness=False)) for track in tracks]
    return _run_over_tracks(pairs, tol, recall_tol, label="REAL ACCEPTANCE GATE")
