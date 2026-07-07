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
* Every M3-seam action (hear / tiebreak / undo) answers with the R6 toast —
  present-but-inert, never a dead click.
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


def finish_analysis(qtbot, window, result=None, features=None, path="/tmp/beat.wav"):
    """begin() then finish() — completions only reduce from WORKING (the
    reducer's stale-completion guard), so verdict-dependent assertions must
    drive the full lifecycle."""
    if result is None:
        result = make_result()
    if features is None:
        features = make_features()
    window.session.begin(path)
    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(result, features, None, 1.23)
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
# M3 seams → R6 toasts (never a dead click)
# ---------------------------------------------------------------------------


def test_rail_tiebreak_button_click_toasts_r6_copy(window, qtbot):
    window.show()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)

    button = window.rail.verdict_block._tiebreak_button
    assert button.isVisible()  # live-looking, never disabled-greyed (R6)
    button.click()
    assert window.toast.isVisible()
    assert window.toast.label.text() == "Tiebreak flow arrives in M3"


def test_candidates_header_and_bridge_tiebreak_toast(window, qtbot):
    window.show()
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=AMBIGUOUS_REASON))
    finish_analysis(qtbot, window, result=result)

    window.tempo_section.candidates.tiebreak_button.click()
    assert window.toast.label.text() == "Tiebreak flow arrives in M3"

    window.header.rail_toggle.click()  # bridge mode
    window.bridge._tiebreak_button.click()
    assert window.toast.label.text() == "Tiebreak flow arrives in M3"


def test_hear_requested_toasts_r6_copy(window, qtbot):
    window.show()
    finish_analysis(qtbot, window)
    # The cell-click → hear_requested path is covered by the table's own
    # tests; here the wiring from the section signal to the toast is what's
    # under test.
    window.tempo_section.candidates.hear_requested.emit(205.15)
    assert window.toast.isVisible()
    assert window.toast.label.text() == "Audio preview arrives in M3"


def test_undo_requested_routes_to_tiebreak_toast(window, qtbot):
    window.show()
    finish_analysis(qtbot, window)
    window.rail.undo_requested.emit()
    assert window.toast.label.text() == "Tiebreak flow arrives in M3"


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
