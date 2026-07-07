"""End-to-end M1 Tempo-section tests: session in, three synced surfaces out.

The binding contracts under test (offscreen, fake engine payloads through the
REAL session/reducer — the same drive path tests/ui/test_shell.py uses):

* A finished analysis populates the tempogram (curve, band, markers), the
  candidate table, and the rail/bridge readouts from ONE view-model — the
  rail and bridge can never disagree on a digit.
* Navigation lands on Tempo after a result (R7); the rail is MainWindow-level
  chrome, hidden on the hero page, persistent across sections (R10).
* The header toggle swaps rail ⇄ bridge, updates its tooltip, persists the
  choice via QSettings, and the numbers survive the swap.
* Every flagship action wires to the real flow as of M3: tiebreak entry
  points open the C-14 overlay (ambiguous only), ▶ hear fires the verbatim
  design toast + the click service, undo reverts through session.undo() —
  never a dead click, and never a toast for a transition that didn't happen.
* Working, no-tempo, and error states render on all surfaces.

Qt-dependent throughout — PySide6/pytest-qt are importorskip'd before any Qt
import so the Qt-less engine venv skips this module cleanly.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings

from tests.ui.test_tempo_view import (
    make_features,
    make_result,
    make_tempo,
    no_tempo_result,
)

TEMPO_PAGE = 2  # hero=0, Overview=1, Tempo=2
EM_DASH = "—"

AMBIGUOUS_REASON = (
    "primary 205 is outside the drill band [140–170], yet 155 sits inside it"
)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """MainWindow with recent-files AND ui-pref settings isolated to tmp INIs."""
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
    qtbot.addWidget(win)
    return win


def finish_analysis(
    qtbot, window, result=None, features=None, path="/tmp/beat.wav", md5="f0" * 16
):
    """begin() then finish() — completions only reduce from WORKING (the
    reducer's stale-completion guard), so verdict-dependent assertions must
    drive the full lifecycle.

    ``md5`` defaults to a fake hash so confirm/undo PERSIST into the per-test
    temp store (the conftest isolation) and the design toasts fire; pass
    ``md5=None`` to exercise the honest "session only" degradation.
    """
    if result is None:
        result = make_result()
    if features is None:
        features = make_features()
    window.session.begin(path)
    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(result, features, None, 1.23, md5=md5)
    return result


# ---------------------------------------------------------------------------
# Result → all three surfaces
# ---------------------------------------------------------------------------


def test_result_populates_tempogram_table_and_readouts(window, qtbot):
    finish_analysis(qtbot, window)
    vm = window.tempo_section.view()

    # View-model reached the section.
    assert vm.has_result is True
    assert [m.kind for m in vm.markers] == ["primary", "felt"]

    # Tempogram: curve + both markers visible, band from the engine config.
    pane = window.tempo_section.tempogram
    assert pane._curve.isVisible()
    assert pane._marker_lines["primary"].isVisible()
    assert pane._marker_lines["felt"].isVisible()
    assert pane._marker_lines["primary"].value() == pytest.approx(205.15)
    assert tuple(pane._band.getRegion()) == (140.0, 170.0)
    assert pane._chips["primary"].label() == "205.15 · PRIMARY"

    # Candidate table: one row per candidate, primary first.
    model = window.tempo_section.candidates.model
    assert model.rowCount() == len(vm.candidates) == 2
    assert model.index(0, 0).data() == "205.15"

    # Rail and bridge: identical numbers from the one ReadoutView.
    assert window.rail.primary_value.text() == "205.15"
    assert window.bridge.primary_value.text() == "205.15"
    assert window.rail.felt_value.text() == window.bridge.felt_value.text() == "102.57"
    assert window.rail.verdict_block.view().kind == "confident"


def test_lands_on_tempo_and_rail_visibility_follows_pages(window, qtbot):
    window.show()
    # Hero page: neither readout surface shows (R10).
    assert window.stack.currentIndex() == 0
    assert not window.rail.isVisible()
    assert not window.bridge.isVisible()

    finish_analysis(qtbot, window)
    assert window.stack.currentIndex() == TEMPO_PAGE  # R7
    assert window.rail.isVisible()
    assert not window.bridge.isVisible()

    # The rail persists across sections (R10).
    window.nav.button("Report").click()
    assert window.rail.isVisible()


# ---------------------------------------------------------------------------
# Rail ⇄ bridge toggle (R10)
# ---------------------------------------------------------------------------


def test_bridge_toggle_swaps_surfaces_and_numbers_survive(window, qtbot):
    from rai_ui.widgets.header import RAIL_TOOLTIP_COLLAPSE, RAIL_TOOLTIP_EXPAND

    window.show()
    finish_analysis(qtbot, window)
    assert window.header.rail_toggle.toolTip() == RAIL_TOOLTIP_COLLAPSE

    window.header.rail_toggle.click()
    assert not window.rail.isVisible()
    assert window.bridge.isVisible()
    assert window.header.rail_toggle.toolTip() == RAIL_TOOLTIP_EXPAND
    # Same data, same digits, after the swap (C-02: "same data as the rail").
    assert window.bridge.primary_value.text() == "205.15"
    assert window.bridge.view() == window.rail.view()

    window.header.rail_toggle.click()
    assert window.rail.isVisible()
    assert not window.bridge.isVisible()
    assert window.header.rail_toggle.toolTip() == RAIL_TOOLTIP_COLLAPSE


def test_collapsed_mode_persists_via_qsettings(window, qtbot, tmp_path):
    import rai_ui.main_window as mw

    window.show()
    finish_analysis(qtbot, window)
    window.header.rail_toggle.click()  # collapse → persisted

    stored = mw._ui_settings().value("ui/rail_collapsed", False, type=bool)
    assert stored is True

    # A fresh window (same monkeypatched settings) restores bridge mode.
    win2 = mw.MainWindow()
    qtbot.addWidget(win2)
    assert win2._rail_collapsed is True
    win2.show()
    finish_analysis(qtbot, win2, path="/tmp/other.wav")
    assert win2.bridge.isVisible()
    assert not win2.rail.isVisible()


# ---------------------------------------------------------------------------
# Working state
# ---------------------------------------------------------------------------


def test_working_state_toggles_sweep_skeleton_and_verdict(window, qtbot):
    window.show()
    window.nav.set_current("Tempo")

    window.session.begin("/tmp/beat.wav")
    pane = window.tempo_section.tempogram
    table = window.tempo_section.candidates
    assert pane._overlay.isVisible()
    assert pane.sweep_running()
    assert table._body.currentWidget() is table.skeleton
    assert window.rail.verdict_block.view().kind == "working"
    assert window.rail.verdict_block.view().word == "WORKING…"

    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(make_result(), make_features(), None, 1.0)
    assert not pane._overlay.isVisible()
    assert not pane.sweep_running()
    assert table._body.currentWidget() is table.view
    assert window.rail.verdict_block.view().kind == "confident"


# ---------------------------------------------------------------------------
# M3 flagship wiring (the R6 inert toasts are gone — real flows, never a
# dead click; the full arcs live in tests/ui/test_flagship_end_to_end.py)
# ---------------------------------------------------------------------------


def test_rail_tiebreak_button_click_opens_overlay(window, qtbot):
    window.show()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)

    button = window.rail.verdict_block._tiebreak_button
    assert button.isVisible()
    assert not window.tempo_section.candidates.tiebreak.isVisible()
    button.click()
    # The overlay opened over the candidates pane and the shell landed on
    # Tempo (the rail button is reachable from any section).
    assert window.stack.currentIndex() == TEMPO_PAGE
    assert window.tempo_section.candidates.tiebreak.isVisible()


def test_candidates_header_and_bridge_tiebreak_open_overlay(window, qtbot):
    window.show()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)
    overlay = window.tempo_section.candidates.tiebreak

    window.tempo_section.candidates.tiebreak_button.click()
    assert overlay.isVisible()
    overlay.dismiss()
    assert not overlay.isVisible()

    window.header.rail_toggle.click()  # bridge mode
    window.bridge._tiebreak_button.click()
    assert overlay.isVisible()


def test_tiebreak_entry_is_ambiguous_only(window, qtbot):
    # R-M3-6: a confident verdict has NO tiebreak entry point — a stray
    # signal (stale click racing a state change) must not raise the overlay.
    window.show()
    finish_analysis(qtbot, window)  # confident
    window.rail.tiebreak_requested.emit()
    assert not window.tempo_section.candidates.tiebreak.isVisible()


class _FakeHearPreview:
    """The ClickPreview API the hear wiring consults — toggle semantics and
    the read-back ``playing_bpm`` truth (R-M3-21), recording calls."""

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

    def clear(self) -> None:
        self._playing = None

    def set_source(self, features, signal_obj) -> None:
        pass

    @property
    def playing_bpm(self):
        return self._playing


def test_hear_requested_fires_design_toast_and_click_service(window, qtbot):
    window.show()
    finish_analysis(qtbot, window)
    fake = _FakeHearPreview()
    window.click_preview = fake
    # The cell-click → hear_requested path is covered by the table's own
    # tests; here the wiring from the section signal to the toast + click
    # service is what's under test (R-M3-10: the clicked ROW's bpm).
    window.tempo_section.candidates.hear_requested.emit(205.15)
    assert window.toast.isVisible()
    assert (
        window.toast.label.text()
        == "▶ click-grid preview · 205.15 BPM — audible in the app"
    )
    assert fake.calls == [("preview", 205.15)]
    # R-M3-21: the playing row's cell follows the service's truth.
    assert window.tempo_section.candidates.model.playing_bpm == 205.15


def test_hear_same_row_click_stops_without_a_second_toast(window, qtbot):
    # R-M3-21 toggle semantics: the second click on the playing row STOPS the
    # preview, reverts the cell, and fires NO toast (start-only).
    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT, STOP_TEXT

    window.show()
    finish_analysis(qtbot, window)
    fake = _FakeHearPreview()
    window.click_preview = fake
    model = window.tempo_section.candidates.model

    window.tempo_section.candidates.hear_requested.emit(205.15)
    assert model.index(0, COL_HEAR).data() == STOP_TEXT
    window.toast.hide()  # arm the no-second-toast assertion

    window.tempo_section.candidates.hear_requested.emit(205.15)
    assert fake.calls[-1] == ("stop",)
    assert fake.playing_bpm is None
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert not window.toast.isVisible()  # the toast fires only on a START


def test_hear_other_row_click_switches_the_preview(window, qtbot):
    # Clicking another row while one plays SWITCHES (one engine, D3) — the
    # stop cell moves, and the new start gets its own toast.
    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT, STOP_TEXT

    window.show()
    finish_analysis(qtbot, window)
    fake = _FakeHearPreview()
    window.click_preview = fake
    model = window.tempo_section.candidates.model
    second = window.tempo_section.view().candidates[1].bpm

    window.tempo_section.candidates.hear_requested.emit(205.15)
    window.tempo_section.candidates.hear_requested.emit(second)
    assert fake.calls == [("preview", 205.15), ("preview", second)]
    assert fake.playing_bpm == second
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert model.index(1, COL_HEAR).data() == STOP_TEXT
    assert window.toast.isVisible()
    assert f"{second:.2f} BPM" in window.toast.label.text()


def test_hear_dead_device_start_gets_no_toast_and_no_stop_cell(window, qtbot):
    # Truthfulness: a start the service could not deliver (no device / no
    # source — preview no-ops with a log) must not toast "audible in the
    # app" and must not paint a ⏸ stop cell.
    from rai_ui.widgets.candidate_table import COL_HEAR, HEAR_TEXT

    class _DeadPreview(_FakeHearPreview):
        def preview(self, bpm) -> None:  # the no-op degradation path
            self.calls.append(("preview", float(bpm)))

    window.show()
    finish_analysis(qtbot, window)
    window.click_preview = _DeadPreview()
    window.tempo_section.candidates.hear_requested.emit(205.15)
    assert not window.toast.isVisible()
    model = window.tempo_section.candidates.model
    assert model.index(0, COL_HEAR).data() == HEAR_TEXT
    assert model.playing_bpm is None


def test_undo_reverts_confirmation_and_toasts(window, qtbot):
    window.show()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)
    window.session.confirm(155.25)
    assert window.rail.verdict_block.view().kind == "confirmed_human"

    window.rail.undo_requested.emit()
    assert window.toast.label.text() == "Reverted — verdict back to AMBIGUOUS"
    assert window.rail.verdict_block.view().kind == "ambiguous"


def test_undo_without_confirmation_is_a_silent_no_op(window, qtbot):
    # The reducer's guard is the truth: no transition, no "Reverted" toast.
    window.show()
    finish_analysis(qtbot, window)  # confident — nothing to undo
    window.rail.undo_requested.emit()
    assert not window.toast.isVisible()
    assert window.rail.verdict_block.view().kind == "confident"


# ---------------------------------------------------------------------------
# Persistence honesty (review finding: the toast branches on ConfirmOutcome —
# the design copy only when a journal record actually landed)
# ---------------------------------------------------------------------------


def _ambiguous_analysis(qtbot, window, md5="f0" * 16):
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result, md5=md5)


def test_confirm_toast_is_design_copy_when_persisted(window, qtbot):
    import rai_ui.main_window as mw

    window.show()
    _ambiguous_analysis(qtbot, window)
    window._on_confirm_requested(155.25)
    assert window.rail.verdict_block.view().kind == "confirmed_human"
    assert window.toast.label.text() == mw.TOAST_CONFIRM


def test_confirm_without_md5_gets_session_only_toast(window, qtbot):
    # Worker md5 is best-effort by contract — md5=None is designed-reachable.
    # The confirmation stands in-session, but nothing was journaled and
    # nothing will boot CONFIRMED on re-open: the toast must not claim
    # "the engine learns from this".
    import rai_ui.main_window as mw

    window.show()
    _ambiguous_analysis(qtbot, window, md5=None)
    window._on_confirm_requested(155.25)
    assert window.rail.verdict_block.view().kind == "confirmed_human"
    assert window.toast.label.text() == mw.TOAST_CONFIRM_SESSION_ONLY


def test_confirm_journal_write_failure_gets_session_only_toast(
    window, qtbot, monkeypatch
):
    import rai_ui.main_window as mw
    from rai_ui.services import ground_truth_store

    def _boom(**kwargs):
        raise OSError("disk full")

    window.show()
    _ambiguous_analysis(qtbot, window)
    monkeypatch.setattr(ground_truth_store, "append_confirm", _boom)
    window._on_confirm_requested(155.25)
    assert window.rail.verdict_block.view().kind == "confirmed_human"  # click kept
    assert window.toast.label.text() == mw.TOAST_CONFIRM_SESSION_ONLY


def test_undo_without_md5_gets_session_only_toast(window, qtbot):
    # An unjournaled retraction means the confirmation would RESURRECT on
    # next boot — "Reverted" alone would over-promise.
    import rai_ui.main_window as mw

    window.show()
    _ambiguous_analysis(qtbot, window, md5=None)
    window.session.confirm(155.25)
    window.rail.undo_requested.emit()
    assert window.rail.verdict_block.view().kind == "ambiguous"
    assert window.toast.label.text() == mw.TOAST_UNDO_SESSION_ONLY


def test_refused_confirm_shows_no_toast(window, qtbot):
    # ConfirmOutcome.accepted is False (nothing to confirm in the no-file
    # state — the reducer's guard is the truth): no toast, nothing changed.
    window.show()
    window._on_confirm_requested(155.25)
    assert not window.toast.isVisible()
    assert window.rail.verdict_block.view().kind == "no_file"


# ---------------------------------------------------------------------------
# Tiebreak overlay geometry (review finding 9 — the live-repro regression)
# ---------------------------------------------------------------------------


def test_tiebreak_overlay_geometry_survives_resize_on_another_section(window, qtbot):
    """Open overlay → nav away (R-M3-8 keeps it open) → resize → return:
    the overlay must cover the pane at its CURRENT size. The old
    ``isVisible()`` guard skipped background-page resizes and the overlay
    came back at stale geometry, exposing live ▶ hear cells around a
    nominally modal surface (adversarial-review live repro)."""
    from PySide6.QtWidgets import QApplication

    window.show()
    window.resize(1000, 640)
    QApplication.processEvents()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)

    pane = window.tempo_section.candidates
    overlay = pane.tiebreak
    pane.tiebreak_button.click()
    assert overlay.isVisible()

    window.nav.button("Report").click()  # nav away — overlay stays open
    assert not overlay.isVisible()  # effective visibility only (page hidden)

    window.resize(1280, 800)  # the pane resizes on the background page
    QApplication.processEvents()

    window.nav.button("Tempo").click()  # return
    QApplication.processEvents()
    assert overlay.isVisible()
    assert overlay.geometry() == pane.rect().adjusted(1, 1, -1, -1), (
        "overlay geometry went stale across a hidden-page resize"
    )


# ---------------------------------------------------------------------------
# No-tempo and error states
# ---------------------------------------------------------------------------


def test_no_tempo_renders_neutral_everywhere(window, qtbot):
    window.show()
    finish_analysis(qtbot, window, result=no_tempo_result(), path="/tmp/silent.wav")

    pane = window.tempo_section.tempogram
    assert pane._no_tempo_label.isVisible()
    assert pane._no_tempo_label.text() == (
        "no periodicity — silent file — nothing to track"
    )
    assert pane._baseline.isVisible()
    assert not pane._curve.isVisible()

    table = window.tempo_section.candidates
    assert table._body.currentWidget() is table.empty_label
    assert table.empty_label.text() == "no candidates — silent file — nothing to track"

    assert window.rail.primary_value.text() == EM_DASH
    assert window.rail.verdict_block.view().kind == "no_tempo"
    assert window.rail.verdict_block.view().show_tiebreak is False


def test_analysis_failure_renders_error_verdict(window, qtbot):
    window.show()
    window.session.begin("/tmp/broken.wav")
    with qtbot.waitSignal(window.session.analysis_failed):
        window.session.fail("could not read file")

    assert window.rail.verdict_block.view().kind == "error"
    assert window.rail.verdict_block.view().reasons == ("could not read file",)
    # Working surfaces are back off.
    assert not window.tempo_section.tempogram._overlay.isVisible()


def test_failed_reanalysis_never_resurrects_previous_result(window, qtbot):
    """analyze(A) ok → analyze(B) fails: B's ERROR must not wear A's numbers.

    Review finding 2026-07-07 (3/3 verified): fail() keeps the session's
    last_result, so without the ERROR blank in build_tempo_view every tempo
    surface repopulated with file A's measurements under file B's name.
    """
    window.show()
    finish_analysis(qtbot, window)  # file A lands
    assert window.rail.primary_value.text() == "205.15"

    window.session.begin("/tmp/fileB.wav")
    with qtbot.waitSignal(window.session.analysis_failed):
        window.session.fail("could not decode")

    assert window.rail.verdict_block.view().kind == "error"
    assert window.rail.primary_value.text() == "—"
    assert window.bridge.primary_value.text() == "—"
    assert window.tempo_section.candidates.model.rowCount() == 0
    assert not window.tempo_section.tempogram._marker_lines["primary"].isVisible()
    assert not window.tempo_section.tempogram._curve.isVisible()


# ---------------------------------------------------------------------------
# Recents pills polish (C-18)
# ---------------------------------------------------------------------------


def test_recent_pills_use_qss_object_name_and_label(window, qtbot):
    from rai_ui.widgets.empty_state import RECENT_LABEL_TEXT, RECENT_PILL_HEIGHT

    assert not window.hero.recent_label.isVisibleTo(window.hero)  # nothing recent yet
    finish_analysis(qtbot, window)

    chips = window.hero._chips
    assert len(chips) == 1
    assert chips[0].objectName() == "recentPill"
    # h24 content-box pinned widget-level (Landmine 6).
    assert chips[0].maximumHeight() == RECENT_PILL_HEIGHT
    assert chips[0].minimumHeight() == RECENT_PILL_HEIGHT
    assert chips[0].text() == "beat.wav"
    assert window.hero.recent_label.text() == RECENT_LABEL_TEXT
    assert window.hero.recent_label.isVisibleTo(window.hero)
