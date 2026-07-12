"""M3 flagship end-to-end arcs — the Stage-3 integration proof.

Everything here drives the REAL MainWindow offscreen with REAL analyses on
synthetic WAVs (the worker thread, the session, the reducer, the journal, the
view-model fan-out — no layer mocked except audio):

* the full tiebreak arc: analyze → AMBIGUOUS → open overlay → select →
  preview (faked click service) → confirm → journal persisted → CONFIRMED ·
  HUMAN on every surface → reopen the same bytes boots CONFIRMED · HUMAN →
  undo → retraction written → AMBIGUOUS restored → reopen boots AMBIGUOUS;
* a second file is unaffected by the first file's confirmation;
* WORKING and ERROR still blank every tempo surface after a confirmation
  (R-M1-3 held through the M3 overlay);
* the relearn round-trip through the header chip → popover → controller:
  user profile written (+ validated), backup on the second run, one-step
  revert, the worker picks the injected profile up (the analyze path
  provably changes) while ``DEFAULT_CONFIG`` stays untouched;
* the analysis ⇄ relearn mutual exclusion (Wire stage): relearn refuses with
  a toast while an analysis is in flight, and every analysis entry point
  refuses with a toast while a relearn runs;
* playback-state honesty: a natural EOF in the REAL ClickPreview (fake
  stream, real premix math) resets the tiebreak card to '▶ preview click
  grid' via the ``stopped`` signal, and the next click starts fresh;
* undo clears the tiebreak selection while confirm keeps it (04:861/862);
* the acceptance gate stays byte-identical AFTER a populated journal, a
  relearned user profile, and a revert (the R-M3-13 exit criterion, re-proven
  on top of this module's arcs).

Audio is faked: ``window.click_preview`` is swapped for a recording fake —
CI never opens an audio device (plan §3), and the premix math has its own
exact suite in tests/ui/test_click_preview.py.

The ground-truth store is ALWAYS a per-test temp dir (tests/ui/conftest.py
autouse isolation — hard rule R-M3-2); the gate test additionally redirects
``HOME`` for its subprocess. Qt-dependent — importorskip'd so the engine venv
skips cleanly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings, Qt

from rai_ui.services import ground_truth_store as gts
from rai_ui.state.verdict import VerdictKind

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_BASELINE = os.path.join(
    _REPO_ROOT, "docs", "baselines", "gate-reference-v3baseline.txt"
)

ANALYSIS_TIMEOUT_MS = 60_000
RELEARN_TIMEOUT_MS = 180_000
EM_DASH = "—"


class FakeClickPreview:
    """The ClickPreview API surface, recording calls instead of playing.

    Mirrors the real service's contract exactly (preview/toggle/stop/
    set_source/clear/playing_bpm) so the MainWindow wiring under test is the
    production wiring, byte for byte.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self._playing: float | None = None

    def preview(self, bpm) -> None:
        self.calls.append(("preview", float(bpm)))
        self._playing = float(bpm)

    def toggle(self, bpm) -> None:
        if self._playing is not None and float(bpm) == self._playing:
            self.stop()
        else:
            self.preview(bpm)

    def stop(self) -> None:
        self.calls.append(("stop",))
        self._playing = None

    def set_source(self, features, signal_obj) -> None:
        self.calls.append(("set_source", features is not None, signal_obj is not None))

    def clear(self) -> None:
        self.calls.append(("clear",))
        self._playing = None

    @property
    def playing_bpm(self):
        return self._playing


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """Real MainWindow with QSettings isolated and the click service faked.

    (The ground-truth store is already isolated by the tests/ui conftest.)
    """
    import rai_ui.main_window as mw
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    monkeypatch.setattr(
        mw,
        "_ui_settings",
        lambda: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    win = mw.MainWindow()
    win.click_preview = FakeClickPreview()
    qtbot.addWidget(win)
    return win


def _write_drill(tmp_path, bpm: float, name: str = "drill.wav") -> str:
    """An 8 s synthetic drill WAV — honestly AMBIGUOUS end-to-end (the raw
    tempogram peaks at the half tempo while the prior favors the notated one,
    verified for 140/150/165)."""
    from rai_analyzer.synthetic import drill_pattern, write_wav

    return write_wav(str(tmp_path / name), drill_pattern(bpm, duration=8.0))


def _analyze(window, qtbot, path: str) -> None:
    """One REAL analysis through open_path (worker thread, generation gate)."""
    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_path(path)


def _confirm_three_clicks(tmp_path) -> list[str]:
    """Journal three effective confirmations of real on-disk WAVs."""
    from rai_analyzer.synthetic import click_track, write_wav

    paths = []
    for name, bpm in (("c140.wav", 140.0), ("c150.wav", 150.0), ("c165.wav", 165.0)):
        path = write_wav(str(tmp_path / name), click_track(bpm, duration=6.0))
        gts.append_confirm(gts.file_md5(path), bpm, name, path)
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# The full tiebreak arc
# ---------------------------------------------------------------------------


def test_full_tiebreak_arc(window, qtbot, tmp_path):
    import rai_ui.main_window as mw
    from rai_ui.widgets.tiebreak import confirm_label

    fake = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)

    session = window.session
    assert session.verdict_state.kind is VerdictKind.AMBIGUOUS
    md5 = session.last_md5
    assert md5, "worker must hash the analyzed file (R-M3-3)"
    # The click engine was re-armed with the fresh payload on result.
    assert ("set_source", True, True) in fake.calls

    # -- open the overlay through the real ambiguous entry point ------------
    pane = window.tempo_section.candidates
    overlay = pane.tiebreak
    assert pane.tiebreak_button.isVisible()
    pane.tiebreak_button.click()
    assert overlay.isVisible()

    vm = window.tempo_section.view()
    reasons = "; ".join(vm.readout.verdict.reasons)
    assert reasons and overlay.reason_label.text() == reasons  # ORIGINAL reason

    # -- select the second-ranked card; the confirm label follows -----------
    overlay.cards[1].clicked.emit()
    chosen = overlay.chosen_bpm
    assert chosen == pytest.approx(vm.candidates[1].bpm)
    assert overlay.confirm_button.text() == confirm_label(vm.candidates[1].bpm_text)

    # -- preview through the faked shared engine ----------------------------
    overlay.cards[1].preview_button.click()
    assert fake.playing_bpm == pytest.approx(chosen)
    assert ("preview", chosen) in fake.calls
    overlay.cards[1].preview_button.click()  # toggle off -> stop
    assert fake.playing_bpm is None
    overlay.cards[1].preview_button.click()  # leave it playing for confirm

    # -- confirm: session + journal + toast + stop ---------------------------
    overlay.confirm_button.click()
    assert not overlay.isVisible()
    assert window.toast.label.text() == mw.TOAST_CONFIRM
    assert fake.playing_bpm is None  # confirm stops playback (design §3.3)
    assert session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN
    assert session.verdict_state.confirmed_bpm == pytest.approx(chosen)

    truth = gts.lookup(md5)
    assert truth is not None
    assert truth.bpm == pytest.approx(chosen)
    assert truth.path == wav  # relearn re-verifies files here (R-M3-11)

    # -- CONFIRMED · HUMAN everywhere (display overlay, R-M3-4) -------------
    vm = window.tempo_section.view()
    assert vm.readout.verdict.kind == "confirmed_human"
    confirmed_rows = [r for r in vm.candidates if r.confirmed_human]
    assert len(confirmed_rows) == 1
    assert confirmed_rows[0].is_primary
    assert confirmed_rows[0].bpm == pytest.approx(chosen)
    assert vm.markers[0].bpm == pytest.approx(chosen)  # tempogram marker moved
    assert vm.readout.primary_text == confirmed_rows[0].bpm_text
    assert window.rail.verdict_block.view().kind == "confirmed_human"
    assert pane.undo_button.isVisible()
    assert not pane.tiebreak_button.isVisible()  # no re-entry — undo first

    # -- reopen the SAME bytes: boots CONFIRMED · HUMAN quietly (R-M3-3) ----
    _analyze(window, qtbot, wav)
    assert session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN
    assert session.verdict_state.confirmed_bpm == pytest.approx(chosen)
    vm = window.tempo_section.view()
    assert any(r.confirmed_human for r in vm.candidates)

    # -- undo: reducer transition + journaled retraction ---------------------
    pane.undo_button.click()
    assert window.toast.label.text() == mw.TOAST_UNDO
    assert session.verdict_state.kind is VerdictKind.AMBIGUOUS
    assert gts.lookup(md5) is None
    with open(gts.journal_path(), "r", encoding="utf-8") as fh:
        records = [json.loads(line) for line in fh if line.strip()]
    assert records[-1]["kind"] == "retract"
    assert records[-1]["retracts_md5"] == md5

    vm = window.tempo_section.view()
    assert not any(r.confirmed_human for r in vm.candidates)
    assert vm.candidates[0].is_primary  # engine primary restored

    # -- the retraction survives a reopen (undo works across sessions) ------
    _analyze(window, qtbot, wav)
    assert session.verdict_state.kind is VerdictKind.AMBIGUOUS


def test_second_file_unaffected_by_first_confirmation(window, qtbot, tmp_path):
    window.show()
    wav_a = _write_drill(tmp_path, 140.0, "a.wav")
    wav_b = _write_drill(tmp_path, 165.0, "b.wav")

    _analyze(window, qtbot, wav_a)
    chosen = window.tempo_section.view().candidates[0].bpm
    window.session.confirm(chosen)
    assert window.session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN

    # Different bytes, different md5 — no stored truth applies.
    _analyze(window, qtbot, wav_b)
    assert window.session.verdict_state.kind is VerdictKind.AMBIGUOUS
    assert not any(
        r.confirmed_human for r in window.tempo_section.view().candidates
    )

    # And the first file still boots confirmed.
    _analyze(window, qtbot, wav_a)
    assert window.session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN
    assert window.session.verdict_state.confirmed_bpm == pytest.approx(chosen)


def test_working_and_error_still_blank_after_confirmation(window, qtbot, tmp_path):
    """R-M1-3 held through M3: the instrument never shows a number it didn't
    just measure — a confirmation does not exempt the blank rule."""
    fake = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)
    window.session.confirm(window.tempo_section.view().candidates[0].bpm)
    assert window.tempo_section.view().readout.verdict.kind == "confirmed_human"

    fake.calls.clear()
    window.session.begin(wav)  # WORKING blanks everything
    vm = window.tempo_section.view()
    assert vm.readout.verdict.kind == "working"
    assert vm.readout.primary_text == EM_DASH
    assert vm.candidates == ()
    assert vm.markers == ()
    assert ("clear",) in fake.calls  # begin cleared the click engine (R-M3-8)

    window.session.fail("decoder exploded")  # ERROR blank
    vm = window.tempo_section.view()
    assert vm.readout.verdict.kind == "error"
    assert vm.readout.primary_text == EM_DASH
    assert vm.candidates == ()


def test_undo_clears_tiebreak_selection_confirm_keeps_it(window, qtbot, tmp_path):
    """Design truth 04:861/862 (recon §2.4): confirm KEEPS chosenIdx, undo
    CLEARS it — a retracted choice must never reopen armed (one stray Space
    away from re-saving the ground truth the user just took back)."""
    from rai_ui.widgets.tiebreak import CONFIRM_DISABLED_TEXT

    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)
    pane = window.tempo_section.candidates
    overlay = pane.tiebreak

    pane.tiebreak_button.click()
    overlay.cards[1].clicked.emit()
    assert overlay.chosen_index == 1

    # Confirm: overlay closes, selection SURVIVES (04:861).
    overlay.confirm_button.click()
    assert window.session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN
    assert overlay.chosen_index == 1

    # Undo through the real header ghost: selection CLEARED (04:862).
    pane.undo_button.click()
    assert window.session.verdict_state.kind is VerdictKind.AMBIGUOUS
    assert overlay.chosen_index is None

    # Reopen: no selected chrome, the 'Pick a candidate' ghost — not an
    # armed 'Set {bpm} — save as ground truth' footer.
    pane.tiebreak_button.click()
    assert overlay.isVisible()
    assert overlay.chosen_index is None
    assert overlay.confirm_button.text() == CONFIRM_DISABLED_TEXT
    assert not any(card.selected for card in overlay.cards)


# ---------------------------------------------------------------------------
# Playback-state honesty: natural EOF resets the card (findings 7/10/15)
# ---------------------------------------------------------------------------


class _FakeStream:
    """Minimal OutputStream stand-in — plan §3's faked-player doctrine."""

    def __init__(self) -> None:
        self.active = True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.active = False

    def close(self) -> None:
        pass


@pytest.fixture
def window_real_preview(qtbot, tmp_path, monkeypatch):
    """Real MainWindow keeping the REAL ClickPreview (stopped wiring live),
    with only the sounddevice stream factory swapped for a fake — CI never
    opens an audio device, but the premix math and the stopped-signal path
    are the production code."""
    import rai_ui.main_window as mw
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    monkeypatch.setattr(
        mw,
        "_ui_settings",
        lambda: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    win = mw.MainWindow()
    win.click_preview._stream_factory = lambda samplerate, channels, fill: _FakeStream()
    qtbot.addWidget(win)
    return win


def test_eof_stopped_preview_resets_card_and_next_click_is_live(
    window_real_preview, qtbot, tmp_path
):
    """Natural end-of-buffer → ``stopped`` → card back to '▶ preview click
    grid', pulse stopped — and the NEXT click starts a fresh preview instead
    of dead-toggling an already-stopped engine (the review's dead-click
    repro, findings 7/10/15)."""
    import numpy as np

    from rai_ui.widgets.tiebreak import PREVIEW_ACTIVE_TEXT, PREVIEW_IDLE_TEXT

    window = window_real_preview
    engine = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)

    pane = window.tempo_section.candidates
    overlay = pane.tiebreak
    pane.tiebreak_button.click()
    assert overlay.isVisible()

    # Start a card preview through the real engine (fake stream underneath).
    overlay.cards[0].preview_button.click()
    assert overlay.preview_index == 0
    assert overlay.cards[0].preview_button.text() == PREVIEW_ACTIVE_TEXT
    assert engine.playing_bpm is not None

    # Natural EOF: drain the whole premix in one audio-callback fill. The
    # callback only FLAGS the transition (never emits) …
    with engine._lock:
        frames, channels = engine._buffer.shape
    scratch = np.zeros((frames + 16, channels), dtype=np.float32)
    assert engine._fill(scratch, frames + 16) is True
    assert engine.playing_bpm is None  # truthful the instant playback ends

    # … and the main-thread poll turns it into exactly one ``stopped``.
    with qtbot.waitSignal(engine.stopped, timeout=1000):
        engine._poll_playback()

    # The wiring reset the card: idle copy, no pulse, no phantom preview.
    assert overlay.preview_index is None
    assert overlay.cards[0].preview_button.text() == PREVIEW_IDLE_TEXT
    assert not overlay.cards[0].preview_button.pulse_running

    # Never a dead click: the next press STARTS playback (one click, live).
    overlay.cards[0].preview_button.click()
    assert overlay.preview_index == 0
    assert engine.playing_bpm == pytest.approx(
        window.tempo_section.view().candidates[0].bpm
    )


# ---------------------------------------------------------------------------
# R-M3-21: the hear cell is a truthful ▶ hear / ⏸ stop toggle pair
# ---------------------------------------------------------------------------


def _click_hear_cell(qtbot, window, row: int) -> None:
    """A REAL mouse click on the hear cell of ``row`` (the production
    view.clicked → hear_requested → MainWindow toggle path, end to end)."""
    from rai_ui.widgets.candidate_table import COL_HEAR

    pane = window.tempo_section.candidates
    rect = pane.view.visualRect(pane.model.index(row, COL_HEAR))
    qtbot.mouseClick(
        pane.view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
    )


def test_hear_cell_toggle_arc(window, qtbot, tmp_path):
    """hear → the cell flips to ⏸ stop + design toast; same-row click stops
    (cell reverts, NO second toast — start-only); other-row click switches
    the one engine and moves the stop cell (R-M3-21)."""
    import rai_ui.main_window as mw
    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT, STOP_TEXT

    fake = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)

    model = window.tempo_section.candidates.model
    assert model.rowCount() >= 2
    bpm0 = window.tempo_section.view().candidates[0].bpm
    bpm1 = window.tempo_section.view().candidates[1].bpm

    # Start: cell flips to stop for THIS row only, the design toast fires.
    _click_hear_cell(qtbot, window, 0)
    assert ("preview", bpm0) in fake.calls
    assert fake.playing_bpm == bpm0
    assert model.index(0, COL_HEAR).data() == STOP_TEXT
    assert model.index(1, COL_HEAR).data() == HEAR_TEXT
    assert window.toast.label.text() == mw.hear_toast(bpm0)

    # Same-row click: STOP — cell reverts, and no second toast (start-only).
    window.toast.hide()
    _click_hear_cell(qtbot, window, 0)
    assert fake.calls[-1] == ("stop",)
    assert fake.playing_bpm is None
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert not window.toast.isVisible()

    # Other-row click while playing: the one engine SWITCHES (D3) — the stop
    # cell moves with it and the new start gets its own toast.
    _click_hear_cell(qtbot, window, 0)
    _click_hear_cell(qtbot, window, 1)
    assert fake.calls[-1] == ("preview", bpm1)
    assert fake.playing_bpm == bpm1
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert model.index(1, COL_HEAR).data() == STOP_TEXT
    assert window.toast.label.text() == mw.hear_toast(bpm1)


def test_tiebreak_card_preview_takeover_reverts_hear_cell(window, qtbot, tmp_path):
    """A tiebreak-card preview takes the one engine over from a table ▶ hear
    (a pointer swap that never emits ``stopped`` by contract) — the table
    cell must revert to ▶ hear at the takeover, even when the card's bpm
    EQUALS the row's (the strictest case: cards and rows share candidate
    bpms; the cell must not claim a preview the overlay now owns)."""
    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT, STOP_TEXT

    fake = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)
    assert window.session.verdict_state.kind is VerdictKind.AMBIGUOUS

    pane = window.tempo_section.candidates
    model = pane.model
    bpm0 = window.tempo_section.view().candidates[0].bpm

    _click_hear_cell(qtbot, window, 0)
    assert model.index(0, COL_HEAR).data() == STOP_TEXT

    pane.tiebreak_button.click()  # overlay opens; playback keeps running
    overlay = pane.tiebreak
    assert overlay.isVisible()
    overlay.cards[0].preview_button.click()  # card 0 = the SAME bpm as row 0
    assert fake.playing_bpm == bpm0  # the engine plays on (pointer swap)…
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT  # …overlay-owned now
    assert model.playing_bpm is None


def test_service_stopped_signal_reverts_hear_cell(
    window_real_preview, qtbot, tmp_path
):
    """Natural EOF in the REAL ClickPreview (fake stream) → ``stopped`` →
    the hear cell reverts from ⏸ stop to ▶ hear — the cell follows the
    SERVICE, not click bookkeeping (R-M3-21 / landmine 20) — and the next
    click STARTS fresh instead of dead-toggling."""
    import numpy as np

    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT, STOP_TEXT

    window = window_real_preview
    engine = window.click_preview
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)

    model = window.tempo_section.candidates.model
    bpm0 = window.tempo_section.view().candidates[0].bpm

    _click_hear_cell(qtbot, window, 0)
    assert engine.playing_bpm == bpm0
    assert model.index(0, COL_HEAR).data() == STOP_TEXT

    # Natural EOF: drain the premix in one audio-callback fill (flag only) …
    with engine._lock:
        frames, channels = engine._buffer.shape
    scratch = np.zeros((frames + 16, channels), dtype=np.float32)
    assert engine._fill(scratch, frames + 16) is True
    # … and the main-thread poll delivers exactly one ``stopped``.
    with qtbot.waitSignal(engine.stopped, timeout=1000):
        engine._poll_playback()

    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert model.playing_bpm is None

    # Never a dead click: the next press STARTS playback and re-flips the cell.
    _click_hear_cell(qtbot, window, 0)
    assert engine.playing_bpm == bpm0
    assert model.index(0, COL_HEAR).data() == STOP_TEXT


# ---------------------------------------------------------------------------
# Analysis ⇄ relearn mutual exclusion (review finding 18 — load-bearing)
# ---------------------------------------------------------------------------


def test_relearn_refused_while_analysis_in_flight(window, qtbot, tmp_path):
    """confirm → analysis in flight → relearn request refuses with the toast
    and starts NO run (the fingerprint cache is path-keyed and content-blind;
    a mid-resolve publish would mix two profiles into one verdict)."""
    import rai_ui.main_window as mw

    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)
    window.session.confirm(window.tempo_section.view().candidates[0].bpm)
    assert window.session.verdict_state.kind is VerdictKind.CONFIRMED_HUMAN

    # A second analysis is in flight (WORKING is the session's truth).
    window.session.begin(wav)
    assert window.session.verdict_state.kind is VerdictKind.WORKING

    window.profile_popover.relearn_requested.emit()  # the popover button path
    assert window.toast.label.text() == mw.TOAST_RELEARN_BLOCKED_BY_ANALYSIS
    assert not window.relearn.is_running()
    assert "relearning" not in window.status.left_label.text()


def test_analysis_refused_while_relearn_running(window, qtbot, tmp_path, monkeypatch):
    """Every analysis entry point funnels through open_path; while the
    controller reports a live relearn the drop is refused with the toast and
    the session is untouched (no begin, no WORKING blank, no worker)."""
    import rai_ui.main_window as mw

    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)
    verdict_before = window.session.verdict_state
    threads_before = list(window._threads)

    monkeypatch.setattr(window.relearn, "is_running", lambda: True)
    window.open_path(str(tmp_path / "another.wav"))

    assert window.toast.label.text() == mw.TOAST_ANALYSIS_BLOCKED_BY_RELEARN
    assert window.session.verdict_state is verdict_before  # no begin happened
    assert window.session.path == wav
    assert window._threads == threads_before  # no worker launched


# ---------------------------------------------------------------------------
# Relearn round-trip through the real chrome
# ---------------------------------------------------------------------------


def test_relearn_round_trip_worker_pickup_and_revert(window, qtbot, tmp_path):
    import rai_ui.main_window as mw
    from rai_analyzer.config import DEFAULT_CONFIG
    from rai_analyzer.evidence.fingerprint import clear_fingerprint_cache

    window.show()
    clear_fingerprint_cache()
    try:
        # Packaged-profile baseline for the pickup proof.
        probe = _write_drill(tmp_path, 150.0, "probe.wav")
        _analyze(window, qtbot, probe)
        packaged_scores = [
            (c.bpm, c.score) for c in window.session.last_result.tempo.candidates
        ]

        _confirm_three_clicks(tmp_path)

        # Header genre chip (a REAL mouse click) -> popover with fresh truth.
        qtbot.mouseClick(window.header.genre_chip, Qt.MouseButton.LeftButton)
        popover = window.profile_popover
        assert popover.isVisible()
        assert popover.state() == {
            "profile_kind": "packaged",
            "relearned_date": None,
            "confirmed_count": 3,
            "backup_exists": False,
        }
        assert popover.relearn_button.isEnabled()  # the >=3 gate is open

        # Relearn through the real button; the controller thread completes.
        with qtbot.waitSignal(window.relearn.finished, timeout=RELEARN_TIMEOUT_MS):
            popover.relearn_button.click()
        assert not popover.isVisible()  # hidden the moment the run started
        assert os.path.exists(gts.user_profile_path())
        assert gts.validate_profile_file(gts.user_profile_path()) is True
        assert window.toast.label.text() == mw.TOAST_RELEARN_DONE_FMT.format(n=3)
        assert "relearning" not in window.status.left_label.text()  # cleared

        # The status-bar progress seam, driven deterministically.
        window._on_relearn_progress(2, 3)
        assert "relearning 2/3" in window.status.left_label.text()
        window.status.set_relearn_progress(None)
        assert "relearning" not in window.status.left_label.text()

        # Worker pickup: the same probe now scores against the user profile.
        _analyze(window, qtbot, probe)
        injected_scores = [
            (c.bpm, c.score) for c in window.session.last_result.tempo.candidates
        ]
        assert injected_scores != packaged_scores, (
            "the worker must inject the relearned profile (R-M3-12) — "
            "identical scores mean relearning is theater"
        )
        # The deliberate visible act never mutates the shared singleton.
        assert DEFAULT_CONFIG.fingerprint.fingerprint_path is None

        # Second relearn: the existing profile is backed up first (D6).
        qtbot.mouseClick(window.header.genre_chip, Qt.MouseButton.LeftButton)
        state = popover.state()
        assert state["profile_kind"] == "user"
        assert state["backup_exists"] is False
        with qtbot.waitSignal(window.relearn.finished, timeout=RELEARN_TIMEOUT_MS):
            popover.relearn_button.click()
        assert os.path.exists(gts.user_profile_backup_path())

        # Revert: backup consumed, profile stays valid, RC toast copy.
        qtbot.mouseClick(window.header.genre_chip, Qt.MouseButton.LeftButton)
        assert popover.state()["backup_exists"] is True
        assert popover._revert_link.isVisibleTo(popover)
        popover.revert_requested.emit()  # the link's linkActivated path
        assert window.toast.label.text() == mw.TOAST_PROFILE_REVERTED
        assert not popover.isVisible()
        assert not os.path.exists(gts.user_profile_backup_path())
        assert os.path.exists(gts.user_profile_path())
        assert gts.validate_profile_file(gts.user_profile_path()) is True
    finally:
        clear_fingerprint_cache()  # drop temp-profile entries from the cache


# ---------------------------------------------------------------------------
# The gate stays sealed AFTER all of it (R-M3-13 re-proven on this module)
# ---------------------------------------------------------------------------


def _all_fixtures_present() -> bool:
    from validation.ground_truth import GROUND_TRUTH, available_tracks

    return len(available_tracks()) == len(GROUND_TRUTH)


def _md5_bytes(path: str) -> str:
    return gts.file_md5(path)


@pytest.mark.skipif(
    not _all_fixtures_present(),
    reason="acceptance-gate fixtures not on disk — byte-compare undefined",
)
def test_gate_byte_identical_after_flagship_mutations(tmp_path, monkeypatch):
    """Populated journal + relearned user profile + backup + revert — then the
    gate subprocess must still print the pinned baseline byte for byte.

    Runs last in this module (pytest file order), so the earlier arcs have
    already exercised every flagship mutation in this very process; this test
    replays the store/profile mutations under a fake HOME the subprocess
    inherits, so if the gate ever grew an App Support read it reads THIS.
    """
    from rai_analyzer.evidence.fingerprint import clear_fingerprint_cache
    from rai_ui.services import relearn

    packaged_fp = os.path.join(_REPO_ROOT, "rai_analyzer", "fingerprints", "drill.json")
    packaged_before = _md5_bytes(packaged_fp)

    fake_home = tmp_path / "home"
    app_support = (
        fake_home / "Library" / "Application Support" / "RAI Audio Analyzer"
    )
    monkeypatch.setattr(gts, "_store_dir", lambda: str(app_support))

    clear_fingerprint_cache()
    try:
        _confirm_three_clicks(tmp_path)
        first = relearn.run_relearn()
        assert first.learned == 3 and first.backup_path is None
        second = relearn.run_relearn()  # creates the backup
        assert second.backup_path is not None
        relearn.revert_profile()  # backup consumed; user profile still ACTIVE
        assert os.path.exists(gts.user_profile_path())
        assert gts.validate_profile_file(gts.user_profile_path()) is True
    finally:
        clear_fingerprint_cache()

    # Nothing leaked into the packaged tree (the forbidden write, R-M3-13).
    assert _md5_bytes(packaged_fp) == packaged_before
    fp_dir = os.path.join(_REPO_ROOT, "rai_analyzer", "fingerprints")
    assert sorted(os.listdir(fp_dir)) == ["drill.json"]

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    proc = subprocess.run(
        [sys.executable, "-m", "validation"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=600,
    )
    with open(_BASELINE, "rb") as fh:
        baseline = fh.read()
    assert proc.returncode == 0, proc.stdout.decode(errors="replace")
    assert proc.stdout == baseline, (
        "gate output drifted after the flagship arcs — the M3 exit criterion "
        "is violated"
    )


# ---------------------------------------------------------------------------
# Popover placement (M5 backlog item 2): the popup never occludes a readout
# ---------------------------------------------------------------------------


def _global_rect(widget):
    from PySide6.QtCore import QPoint, QRect

    top_left = widget.mapToGlobal(QPoint(0, 0))
    return QRect(top_left.x(), top_left.y(), widget.width(), widget.height())


def test_popover_placement_clears_header_rail_and_bridge(window, qtbot, tmp_path):
    """The real chip click places the popover below the header hairline,
    fully clear of the rail (rail mode) and of the 76px strip (bridge mode).
    The old anchor failed all three at every window size (M5 finding #2)."""
    window.show()
    wav = _write_drill(tmp_path, 140.0)
    _analyze(window, qtbot, wav)  # land on Tempo so a readout is visible

    # Rail mode.
    window._set_rail_collapsed(False)
    assert window.rail.isVisible()
    qtbot.mouseClick(window.header.genre_chip, Qt.MouseButton.LeftButton)
    popover = window.profile_popover
    assert popover.isVisible()
    pop_rect = popover.frameGeometry()
    assert not pop_rect.intersects(_global_rect(window.rail))
    assert pop_rect.top() >= _global_rect(window.header).bottom()
    popover.hide()

    # Bridge mode.
    window._set_rail_collapsed(True)
    assert window.bridge.isVisible()
    qtbot.mouseClick(window.header.genre_chip, Qt.MouseButton.LeftButton)
    pop_rect = popover.frameGeometry()
    assert not pop_rect.intersects(_global_rect(window.bridge))
    assert pop_rect.top() >= _global_rect(window.header).bottom()
    popover.hide()
