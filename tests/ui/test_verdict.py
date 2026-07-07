"""Exhaustive transition-matrix tests for the pure verdict reducer.

Pure Python — no Qt imports anywhere, so this module collects and runs in the
engine CI environment (no PySide6) as well as the UI venv. States are built
through ``reduce`` itself (not hand-constructed) so every assertion also
exercises a real path into that state.
"""

from __future__ import annotations

import dataclasses

import pytest

from rai_ui.state.verdict import (
    INITIAL,
    AnalysisFailed,
    AnalysisOk,
    Confirm,
    OpenFile,
    Undo,
    VerdictKind,
    VerdictState,
    reduce,
)

PATH = "/music/track.wav"


def make(kind: VerdictKind) -> VerdictState:
    """Build a state of the given kind via real reducer paths."""
    if kind is VerdictKind.NO_FILE:
        return INITIAL
    working = reduce(INITIAL, OpenFile(PATH))
    if kind is VerdictKind.WORKING:
        return working
    if kind is VerdictKind.CONFIDENT:
        return reduce(working, AnalysisOk(ambiguous=False))
    if kind is VerdictKind.AMBIGUOUS:
        return reduce(working, AnalysisOk(ambiguous=True))
    if kind is VerdictKind.NO_TEMPO:
        return reduce(working, AnalysisOk(ambiguous=False, has_tempo=False))
    if kind is VerdictKind.CONFIRMED_HUMAN:
        return reduce(reduce(working, AnalysisOk(ambiguous=True)), Confirm(140.0))
    if kind is VerdictKind.ERROR:
        return reduce(working, AnalysisFailed("decode failed"))
    raise AssertionError(kind)


ALL_KINDS = list(VerdictKind)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_state():
    assert INITIAL.kind is VerdictKind.NO_FILE
    assert INITIAL.path is None
    assert INITIAL.confirmed_bpm is None
    assert INITIAL.error_msg is None
    assert INITIAL.prev_kind is None


def test_state_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        INITIAL.kind = VerdictKind.WORKING  # type: ignore[misc]


def test_reduce_rejects_non_events():
    with pytest.raises(TypeError):
        reduce(INITIAL, "open")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# OpenFile: allowed from every state, always a clean WORKING
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ALL_KINDS)
def test_open_file_from_every_state(kind):
    state = make(kind)
    new = reduce(state, OpenFile("/music/other.wav"))
    assert new.kind is VerdictKind.WORKING
    assert new.path == "/music/other.wav"
    # Everything from the previous file is cleared.
    assert new.confirmed_bpm is None
    assert new.error_msg is None
    assert new.prev_kind is None
    # And the input state was not mutated.
    assert state == make(kind)


# ---------------------------------------------------------------------------
# AnalysisOk resolution (from WORKING)
# ---------------------------------------------------------------------------


def test_ok_confident():
    new = reduce(make(VerdictKind.WORKING), AnalysisOk(ambiguous=False))
    assert new.kind is VerdictKind.CONFIDENT
    assert new.path == PATH  # path survives completion
    assert new.prev_kind is None


def test_ok_ambiguous():
    new = reduce(make(VerdictKind.WORKING), AnalysisOk(ambiguous=True))
    assert new.kind is VerdictKind.AMBIGUOUS


def test_ok_no_tempo():
    new = reduce(make(VerdictKind.WORKING), AnalysisOk(ambiguous=False, has_tempo=False))
    assert new.kind is VerdictKind.NO_TEMPO


def test_ok_no_tempo_wins_over_ambiguous():
    # No tempo means there is nothing to be ambiguous about.
    new = reduce(make(VerdictKind.WORKING), AnalysisOk(ambiguous=True, has_tempo=False))
    assert new.kind is VerdictKind.NO_TEMPO
    assert new.confirmed_bpm is None


@pytest.mark.parametrize(
    "ambiguous,expected_prev",
    [(False, VerdictKind.CONFIDENT), (True, VerdictKind.AMBIGUOUS)],
)
def test_ok_with_restored_confirmation(ambiguous, expected_prev):
    new = reduce(
        make(VerdictKind.WORKING),
        AnalysisOk(ambiguous=ambiguous, confirmed_bpm=140.5),
    )
    assert new.kind is VerdictKind.CONFIRMED_HUMAN
    assert new.confirmed_bpm == 140.5
    assert new.prev_kind is expected_prev  # Undo knows where to go back to


def test_failed():
    new = reduce(make(VerdictKind.WORKING), AnalysisFailed("unsupported codec"))
    assert new.kind is VerdictKind.ERROR
    assert new.error_msg == "unsupported codec"
    assert new.path == PATH


# ---------------------------------------------------------------------------
# Stale-completion guard: Ok/Failed ignored outside WORKING
# ---------------------------------------------------------------------------

NON_WORKING = [k for k in ALL_KINDS if k is not VerdictKind.WORKING]


@pytest.mark.parametrize("kind", NON_WORKING)
@pytest.mark.parametrize(
    "event",
    [
        AnalysisOk(ambiguous=False),
        AnalysisOk(ambiguous=True),
        AnalysisOk(ambiguous=False, has_tempo=False),
        AnalysisOk(ambiguous=False, confirmed_bpm=99.0),
        AnalysisFailed("late worker"),
    ],
    ids=["ok-confident", "ok-ambiguous", "ok-no-tempo", "ok-confirmed", "failed"],
)
def test_completions_ignored_outside_working(kind, event):
    state = make(kind)
    assert reduce(state, event) == state


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", [VerdictKind.CONFIDENT, VerdictKind.AMBIGUOUS], ids=str
)
def test_confirm_from_engine_verdicts(kind):
    state = make(kind)
    new = reduce(state, Confirm(151.0))
    assert new.kind is VerdictKind.CONFIRMED_HUMAN
    assert new.confirmed_bpm == 151.0
    assert new.prev_kind is kind


def test_reconfirm_replaces_bpm_keeps_provenance():
    confirmed = make(VerdictKind.CONFIRMED_HUMAN)  # prev = AMBIGUOUS, bpm 140
    again = reduce(confirmed, Confirm(70.0))
    assert again.kind is VerdictKind.CONFIRMED_HUMAN
    assert again.confirmed_bpm == 70.0
    assert again.prev_kind is VerdictKind.AMBIGUOUS  # original provenance kept


@pytest.mark.parametrize(
    "kind",
    [VerdictKind.NO_FILE, VerdictKind.WORKING, VerdictKind.NO_TEMPO, VerdictKind.ERROR],
    ids=str,
)
def test_confirm_noop_when_nothing_to_confirm(kind):
    state = make(kind)
    assert reduce(state, Confirm(120.0)) == state


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


def test_undo_restores_ambiguous():
    confirmed = make(VerdictKind.CONFIRMED_HUMAN)
    undone = reduce(confirmed, Undo())
    assert undone.kind is VerdictKind.AMBIGUOUS
    assert undone.confirmed_bpm is None
    assert undone.prev_kind is None
    assert undone.path == PATH


def test_undo_restores_confident():
    confirmed = reduce(make(VerdictKind.CONFIDENT), Confirm(151.0))
    undone = reduce(confirmed, Undo())
    assert undone.kind is VerdictKind.CONFIDENT
    assert undone.confirmed_bpm is None


def test_undo_after_reconfirm_restores_engine_verdict():
    # Confirm twice, undo once: back to the engine's verdict, not the first
    # human number.
    state = make(VerdictKind.AMBIGUOUS)
    state = reduce(state, Confirm(140.0))
    state = reduce(state, Confirm(70.0))
    undone = reduce(state, Undo())
    assert undone.kind is VerdictKind.AMBIGUOUS
    assert undone.confirmed_bpm is None


def test_confirm_undo_confirm_roundtrip():
    state = make(VerdictKind.AMBIGUOUS)
    state = reduce(state, Confirm(140.0))
    state = reduce(state, Undo())
    state = reduce(state, Confirm(141.0))
    assert state.kind is VerdictKind.CONFIRMED_HUMAN
    assert state.confirmed_bpm == 141.0
    assert state.prev_kind is VerdictKind.AMBIGUOUS


def test_undo_without_provenance_falls_back_to_ambiguous():
    # Hand-built confirmed state with no prev_kind: undo must not fabricate
    # engine confidence.
    state = VerdictState(kind=VerdictKind.CONFIRMED_HUMAN, path=PATH, confirmed_bpm=120.0)
    undone = reduce(state, Undo())
    assert undone.kind is VerdictKind.AMBIGUOUS


@pytest.mark.parametrize(
    "kind", [k for k in ALL_KINDS if k is not VerdictKind.CONFIRMED_HUMAN], ids=str
)
def test_undo_noop_everywhere_else(kind):
    state = make(kind)
    assert reduce(state, Undo()) == state
