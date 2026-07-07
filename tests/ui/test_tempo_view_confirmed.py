"""Confirmed-state view-model tests — ruling R-M3-4 (plan D7).

CONFIRMED · HUMAN is a pure VIEW-layer recompute over the untouched engine
result: the confirmed bpm becomes the effective primary for every chip, the
raised/HumanPill row, the tempogram primary marker, and the readout — while
FELT stays the engine measurement (04 executable truth wins over wireframe
F4; only felt's relation chip recomputes).

Pure Python — no Qt anywhere; the engine venv collects and runs these.
"""

from __future__ import annotations

from copy import deepcopy

from rai_analyzer.contracts import AnalysisResult, Candidate, TempoResult

from rai_ui.state.formatters import relationship_chip
from rai_ui.state.tempo_view import build_tempo_view
from rai_ui.state.verdict import VerdictKind, VerdictState

PRIMARY = 205.15
FELT = 102.57
CONFIRMED = 102.5  # the second-ranked candidate — a human picked the half


def make_result(ambiguous=True):
    tempo = TempoResult(
        primary_bpm=PRIMARY,
        felt_bpm=FELT,
        candidates=[
            Candidate(bpm=PRIMARY, score=1.86, salience=0.912),
            Candidate(bpm=CONFIRMED, score=1.50, salience=0.800),
            Candidate(bpm=153.75, score=1.20, salience=0.700),
        ],
        ambiguous=ambiguous,
        ambiguity_reason="primary 205 is outside the drill band" if ambiguous else None,
    )
    return AnalysisResult(
        path="/tmp/beat.wav", duration=6.0, sr=44100, channels=2, tempo=tempo
    )


CONFIRMED_STATE = VerdictState(
    kind=VerdictKind.CONFIRMED_HUMAN,
    path="/tmp/beat.wav",
    confirmed_bpm=CONFIRMED,
    prev_kind=VerdictKind.AMBIGUOUS,
)


def confirmed_view(result=None, state=CONFIRMED_STATE):
    return build_tempo_view(result if result is not None else make_result(), None, state)


# ---------------------------------------------------------------------------
# Candidate rows: pill + primary styling move, ALL chips recompute
# ---------------------------------------------------------------------------


def test_confirmed_row_gets_primary_and_human_pill():
    rows = confirmed_view().candidates
    by_bpm = {r.bpm: r for r in rows}
    assert by_bpm[CONFIRMED].is_primary is True
    assert by_bpm[CONFIRMED].confirmed_human is True
    # The engine's original primary row loses the raised styling and pill.
    assert by_bpm[PRIMARY].is_primary is False
    assert by_bpm[PRIMARY].confirmed_human is False
    assert by_bpm[153.75].confirmed_human is False


def test_all_chips_recompute_against_confirmed_bpm():
    rows = confirmed_view().candidates
    by_bpm = {r.bpm: r for r in rows}
    # Pure formatter math against the NEW primary (04:728-739).
    assert by_bpm[CONFIRMED].chip.text == "×1 · primary"
    assert by_bpm[CONFIRMED].chip.kind == "primary"
    assert by_bpm[PRIMARY].chip.text == relationship_chip(PRIMARY, CONFIRMED)
    assert by_bpm[PRIMARY].chip.text == "2× · double-time"
    assert by_bpm[PRIMARY].chip.kind == "related"
    assert by_bpm[153.75].chip.text == relationship_chip(153.75, CONFIRMED)
    assert by_bpm[153.75].chip.text == "1½× · dotted"


def test_unconfirmed_rendering_unchanged():
    """Control: without a confirmation the engine primary still leads."""
    vm = build_tempo_view(
        make_result(), None, VerdictState(kind=VerdictKind.AMBIGUOUS)
    )
    rows = vm.candidates
    assert rows[0].bpm == PRIMARY and rows[0].is_primary
    assert all(r.confirmed_human is False for r in rows)
    assert vm.readout.primary_text == "205.15"


def test_confirmed_bpm_matching_no_row_still_recomputes():
    """A hand-rolled confirmation off the candidate grid: no row is primary
    or pilled, but chips and readout still follow the confirmed bpm."""
    state = VerdictState(
        kind=VerdictKind.CONFIRMED_HUMAN, confirmed_bpm=99.0,
        prev_kind=VerdictKind.AMBIGUOUS,
    )
    vm = confirmed_view(state=state)
    assert all(not r.is_primary and not r.confirmed_human for r in vm.candidates)
    by_bpm = {r.bpm: r for r in vm.candidates}
    assert by_bpm[PRIMARY].chip.text == relationship_chip(PRIMARY, 99.0)
    assert vm.readout.primary_text == "99.00"
    assert vm.markers[0].bpm == 99.0


def test_confirmed_row_tolerance_is_a_hundredth():
    """04:737's detector: |candidate − confirmed| < 0.01."""
    state = VerdictState(
        kind=VerdictKind.CONFIRMED_HUMAN, confirmed_bpm=CONFIRMED + 0.005,
        prev_kind=VerdictKind.AMBIGUOUS,
    )
    rows = confirmed_view(state=state).candidates
    assert {r.bpm: r.confirmed_human for r in rows}[CONFIRMED] is True


# ---------------------------------------------------------------------------
# Markers: primary moves, felt UNCHANGED
# ---------------------------------------------------------------------------


def test_primary_marker_moves_to_confirmed_bpm():
    markers = confirmed_view().markers
    primary_marker = markers[0]
    assert primary_marker.kind == "primary"
    assert primary_marker.bpm == CONFIRMED
    assert primary_marker.label == "102.50 · PRIMARY"


def test_felt_marker_stays_at_engine_value():
    markers = confirmed_view().markers
    felt_marker = [m for m in markers if m.kind == "felt"][0]
    assert felt_marker.bpm == FELT
    assert felt_marker.label == "102.57 · FELT"


# ---------------------------------------------------------------------------
# Readout: primary text follows, FELT stays engine (R-M3-4 vs wireframe F4)
# ---------------------------------------------------------------------------


def test_readout_primary_is_confirmed_and_felt_is_engine():
    readout = confirmed_view().readout
    assert readout.primary_text == "102.50"
    assert readout.felt_text == "102.57"  # engine value, NOT recomputed
    # ... but felt's relation chip recomputes against the new primary (04:850).
    assert readout.felt_chip.text == relationship_chip(FELT, CONFIRMED)
    assert readout.felt_chip.text == "×1 · primary"
    assert readout.felt_chip.kind == "related"  # the felt chip is never "primary"-styled


def test_verdict_copy_and_actions():
    verdict_view = confirmed_view().readout.verdict
    assert verdict_view.kind == "confirmed_human"
    assert verdict_view.word == "CONFIRMED · HUMAN"
    assert verdict_view.reasons == (
        "you chose 102.50 — saved as ground truth",
    )
    assert verdict_view.show_undo is True
    assert verdict_view.show_tiebreak is False


# ---------------------------------------------------------------------------
# Guards: kind-gated overlay, WORKING/ERROR blank untouched
# ---------------------------------------------------------------------------


def test_stale_confirmed_bpm_on_other_kinds_is_inert():
    """Only CONFIRMED · HUMAN carries the overlay: a hand-built CONFIDENT
    state with a leftover confirmed_bpm must render the engine primary."""
    state = VerdictState(kind=VerdictKind.CONFIDENT, confirmed_bpm=CONFIRMED)
    vm = build_tempo_view(make_result(ambiguous=False), None, state)
    assert vm.readout.primary_text == "205.15"
    assert vm.markers[0].bpm == PRIMARY
    assert all(not r.confirmed_human for r in vm.candidates)


def test_working_and_error_blank_even_with_confirmed_bpm():
    """R-M1-3's blank rule outranks the overlay: WORKING/ERROR show nothing,
    whatever a hand-built state claims was confirmed."""
    for kind in (VerdictKind.WORKING, VerdictKind.ERROR):
        state = VerdictState(kind=kind, confirmed_bpm=CONFIRMED)
        vm = build_tempo_view(make_result(), None, state)
        assert vm.candidates == ()
        assert vm.markers == ()
        assert vm.readout.primary_text == "—"


def test_confirmed_overlay_never_mutates_the_engine_result():
    """D7: display overlay ONLY — the AnalysisResult is untouched."""
    result = make_result()
    before = deepcopy(result.tempo)
    confirmed_view(result=result)
    assert result.tempo.primary_bpm == before.primary_bpm
    assert [c.bpm for c in result.tempo.candidates] == [
        c.bpm for c in before.candidates
    ]
    assert result.tempo.felt_bpm == before.felt_bpm


def test_confirmed_human_without_bpm_falls_back_to_engine_primary():
    """A CONFIRMED_HUMAN state missing its bpm (hand-built) must not crash
    and must not invent a primary."""
    state = VerdictState(kind=VerdictKind.CONFIRMED_HUMAN, confirmed_bpm=None)
    vm = build_tempo_view(make_result(), None, state)
    assert vm.readout.primary_text == "205.15"
    assert vm.readout.verdict.reasons == ()  # no invented copy
