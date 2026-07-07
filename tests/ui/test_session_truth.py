"""Session ground-truth wiring tests (rulings R-M3-3 and R-M3-20).

``SessionState.confirm``/``undo`` are the ONLY ground-truth mutation entry
points: reducer event + journal record + broadcast, with the reducer's guards
deciding legality. ``finish(md5=...)`` is the re-open path: an effective
stored confirmation boots the verdict straight to CONFIRMED · HUMAN through
the reserved ``AnalysisOk(confirmed_bpm=...)`` hook — display overlay only,
the engine result object untouched.

Driven with fake payloads (the session never inspects them) against the
autouse-isolated temp store. A bare QObject emits signals without a
QApplication, so no pytest-qt fixture is needed.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from rai_analyzer.contracts import AnalysisResult, Candidate, TempoResult

from rai_ui.services import ground_truth_store as gts
from rai_ui.state import verdict
from rai_ui.state.session import ConfirmOutcome, SessionState

MD5_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
MD5_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def make_result(path="/tmp/beat.wav", bpm=205.15, ambiguous=True):
    tempo = TempoResult(
        primary_bpm=bpm,
        felt_bpm=bpm / 2,
        candidates=[
            Candidate(bpm=bpm, score=1.86, salience=0.912),
            Candidate(bpm=bpm / 2, score=1.50, salience=0.800),
        ],
        ambiguous=ambiguous,
        ambiguity_reason="primary outside the drill band" if ambiguous else None,
    )
    return AnalysisResult(
        path=path, duration=6.0, sr=44100, channels=1, tempo=tempo
    )


def run_analysis(session, md5=MD5_A, ambiguous=True, path="/tmp/beat.wav", bpm=205.15):
    session.begin(path)
    session.finish(make_result(path=path, bpm=bpm, ambiguous=ambiguous), None, None, 1.0, md5=md5)


def _journal_records() -> list[dict]:
    with open(gts.journal_path(), "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------------------
# confirm() — R-M3-20
# ---------------------------------------------------------------------------


def test_confirm_transitions_persists_and_broadcasts():
    session = SessionState()
    run_analysis(session, ambiguous=True)
    seen = []
    session.verdict_changed.connect(lambda s: seen.append(s))

    outcome = session.confirm(102.5)
    assert outcome == ConfirmOutcome(accepted=True, persisted=True, reason=None)

    state = session.verdict_state
    assert state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert state.confirmed_bpm == 102.5
    assert state.prev_kind is verdict.VerdictKind.AMBIGUOUS
    assert seen and seen[-1] is state  # broadcast carried the new state

    truth = gts.lookup(MD5_A)
    assert truth is not None and truth.bpm == 102.5
    assert truth.name == "beat.wav"
    assert truth.path == "/tmp/beat.wav"


def test_confirm_from_confident_also_legal():
    session = SessionState()
    run_analysis(session, ambiguous=False)
    session.confirm(155.0)
    assert session.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert session.verdict_state.prev_kind is verdict.VerdictKind.CONFIDENT


def test_reconfirm_replaces_bpm_and_appends_second_record():
    session = SessionState()
    run_analysis(session)
    session.confirm(102.5)
    session.confirm(205.15)
    assert session.verdict_state.confirmed_bpm == 205.15
    assert session.verdict_state.prev_kind is verdict.VerdictKind.AMBIGUOUS
    assert gts.lookup(MD5_A).bpm == 205.15  # last record wins
    assert [r["kind"] for r in _journal_records()] == ["confirm", "confirm"]


def test_confirm_illegal_state_is_a_logged_noop():
    session = SessionState()  # NO_FILE — nothing on screen to confirm
    seen = []
    session.verdict_changed.connect(lambda s: seen.append(s))
    outcome = session.confirm(120.0)
    assert session.verdict_state.kind is verdict.VerdictKind.NO_FILE
    assert seen == []  # no broadcast for a refused event
    assert gts.effective_truths() == {}  # and nothing journaled
    assert outcome.accepted is False and outcome.persisted is False
    assert "nothing to confirm" in outcome.reason


def test_confirm_without_md5_transitions_but_does_not_persist():
    session = SessionState()
    run_analysis(session, md5=None)
    outcome = session.confirm(120.0)
    assert session.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert gts.effective_truths() == {}
    # The outcome tells the toast layer the truth: accepted, NOT persisted.
    assert outcome == ConfirmOutcome(
        accepted=True, persisted=False, reason="no file hash"
    )


def test_confirm_survives_store_write_failure(monkeypatch):
    """A disk hiccup must not eat the user's click: the in-session confirm
    stands, the failure is logged (never raised) — and reported honestly in
    the outcome."""
    session = SessionState()
    run_analysis(session)

    def _boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(gts, "append_confirm", _boom)
    outcome = session.confirm(102.5)
    assert session.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert outcome.accepted is True and outcome.persisted is False
    assert outcome.reason == "journal write failed: disk full"


def test_confirm_outcome_is_frozen():
    """The outcome object is a shared contract — immutability is part of it."""
    import dataclasses

    outcome = ConfirmOutcome(accepted=True, persisted=True, reason=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.persisted = False


# ---------------------------------------------------------------------------
# undo() — R-M3-20 / retraction across sessions R-M3-1
# ---------------------------------------------------------------------------


def test_undo_restores_prev_kind_and_writes_retraction():
    session = SessionState()
    run_analysis(session, ambiguous=True)
    session.confirm(102.5)
    seen = []
    session.verdict_changed.connect(lambda s: seen.append(s))

    outcome = session.undo()
    assert outcome == ConfirmOutcome(accepted=True, persisted=True, reason=None)

    assert session.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS
    assert session.verdict_state.confirmed_bpm is None
    assert seen and seen[-1] is session.verdict_state
    assert gts.lookup(MD5_A) is None
    last = _journal_records()[-1]
    assert last["kind"] == "retract" and last["retracts_md5"] == MD5_A


def test_undo_illegal_state_is_a_logged_noop():
    import os

    session = SessionState()
    run_analysis(session)  # AMBIGUOUS — nothing confirmed
    seen = []
    session.verdict_changed.connect(lambda s: seen.append(s))
    outcome = session.undo()
    assert session.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS
    assert seen == []
    assert not os.path.exists(gts.journal_path())  # nothing ever journaled
    assert outcome.accepted is False and outcome.persisted is False
    assert "nothing to undo" in outcome.reason


def test_undo_writes_no_retraction_when_journal_absent():
    session = SessionState()
    run_analysis(session, md5=None)
    session.confirm(120.0)  # not persisted (no md5)
    outcome = session.undo()
    assert session.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS
    import os

    assert not os.path.exists(gts.journal_path())
    assert outcome == ConfirmOutcome(
        accepted=True, persisted=False, reason="no file hash"
    )


def test_undo_survives_store_write_failure(monkeypatch):
    """A failed retraction write must not raise — and the outcome must say
    the retraction did NOT land (the confirmation resurrects on next boot)."""
    session = SessionState()
    run_analysis(session)
    session.confirm(102.5)

    def _boom(md5):
        raise OSError("disk full")

    monkeypatch.setattr(gts, "append_retract", _boom)
    outcome = session.undo()
    assert session.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS
    assert outcome.accepted is True and outcome.persisted is False
    assert outcome.reason == "journal write failed: disk full"
    # The journal was never retracted — the store still holds the truth.
    assert gts.lookup(MD5_A).bpm == 102.5


# ---------------------------------------------------------------------------
# finish(md5=...) — the R-M3-3 re-open path
# ---------------------------------------------------------------------------


def test_reopen_confirmed_file_boots_confirmed_human():
    # Session one: confirm and throw the session away.
    s1 = SessionState()
    run_analysis(s1, ambiguous=True)
    s1.confirm(102.5)

    # Session two (fresh boot): same bytes, same md5 → CONFIRMED · HUMAN.
    s2 = SessionState()
    run_analysis(s2, ambiguous=True)
    state = s2.verdict_state
    assert state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert state.confirmed_bpm == 102.5
    # prev_kind derives from the fresh engine verdict, so Undo restores what
    # the engine ACTUALLY said this run.
    assert state.prev_kind is verdict.VerdictKind.AMBIGUOUS


def test_reopen_prev_kind_tracks_fresh_engine_confidence():
    s1 = SessionState()
    run_analysis(s1, ambiguous=False)
    s1.confirm(155.0)
    s2 = SessionState()
    run_analysis(s2, ambiguous=False)
    assert s2.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert s2.verdict_state.prev_kind is verdict.VerdictKind.CONFIDENT


def test_reopen_after_retraction_boots_plain_verdict():
    s1 = SessionState()
    run_analysis(s1)
    s1.confirm(102.5)
    s1.undo()
    s2 = SessionState()
    run_analysis(s2)
    assert s2.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS


def test_reopen_cross_session_undo_retracts_the_store():
    """Undo of a BOOTED confirmation (confirmed in a previous session) must
    write the retraction too — undo works across sessions."""
    s1 = SessionState()
    run_analysis(s1)
    s1.confirm(102.5)

    s2 = SessionState()
    run_analysis(s2)
    assert s2.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    s2.undo()
    assert s2.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS
    assert gts.lookup(MD5_A) is None

    s3 = SessionState()
    run_analysis(s3)
    assert s3.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS


def test_other_files_unaffected():
    s1 = SessionState()
    run_analysis(s1, md5=MD5_A)
    s1.confirm(102.5)
    run_analysis(s1, md5=MD5_B, path="/tmp/other.wav")
    assert s1.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS  # B never confirmed
    assert s1.last_md5 == MD5_B


def test_finish_without_md5_keeps_pre_m3_behavior():
    session = SessionState()
    session.begin("/tmp/beat.wav")
    session.finish(make_result(), None, None, 1.0)  # five-arg pre-M3 caller
    assert session.last_md5 is None
    assert session.verdict_state.kind is verdict.VerdictKind.AMBIGUOUS


def test_fields_first_ordering_includes_md5():
    """The documented ordering contract: ``last_md5`` (like every payload
    field) is already set when ``verdict_changed`` fires."""
    session = SessionState()
    session.begin("/tmp/beat.wav")
    seen = []
    session.verdict_changed.connect(lambda s: seen.append(session.last_md5))
    session.finish(make_result(), None, None, 1.0, md5=MD5_A)
    assert seen[-1] == MD5_A


def test_finish_survives_torn_multibyte_journal():
    """The review's brick scenario: a crash-torn multibyte byte in the
    journal must NOT propagate out of the store lookup inside ``finish`` —
    the completion lands, the verdict resolves, working(False) fires."""
    gts.append_confirm(md5=MD5_A, bpm=102.5, name="beat.wav")
    with open(gts.journal_path(), "ab") as fh:
        fh.write(b'{"v": 1, "kind": "confirm", "name": "caf\xe9\n')  # torn é

    session = SessionState()
    flags = []
    session.working.connect(lambda w: flags.append(w))
    run_analysis(session)  # must not raise
    assert flags[-1] is False  # the session is not stuck at WORKING
    # The intact confirmation before the torn line still boots the overlay.
    assert session.verdict_state.kind is verdict.VerdictKind.CONFIRMED_HUMAN
    assert session.verdict_state.confirmed_bpm == 102.5


def test_no_tempo_wins_over_stored_truth():
    """A silent re-analysis of a once-confirmed file has nothing to overlay:
    the reducer resolves has_tempo=False to NO_TEMPO first."""
    gts.append_confirm(md5=MD5_A, bpm=102.5, name="beat.wav")
    session = SessionState()
    session.begin("/tmp/beat.wav")
    silent = AnalysisResult(
        path="/tmp/beat.wav",
        duration=3.0,
        sr=44100,
        channels=1,
        tempo=TempoResult(primary_bpm=0.0, felt_bpm=None, candidates=[], ambiguous=True),
    )
    session.finish(silent, None, None, 0.4, md5=MD5_A)
    assert session.verdict_state.kind is verdict.VerdictKind.NO_TEMPO
