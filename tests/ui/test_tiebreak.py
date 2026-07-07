"""Tiebreak overlay tests (C-14 / rulings R-M3-6, R-M3-7, R-M3-17).

The 04 Console's demo JS is the executable truth these tests pin:

* top-3 ranked cards, chips computed against the ORIGINAL engine primary;
* selection (chosenIdx) and preview (previewIdx) are INDEPENDENT states;
* ✕ / Esc stop the preview but PRESERVE the selection;
* confirm is enabled only with a selection ("Set {bpm} — save as ground
  truth" vs the static "Pick a candidate" ghost) and never fires without one;
* keyboard per R-M3-7: ←/→ move selection, Space toggles preview on the
  selected card, Enter selects (NEVER confirms), Esc closes;
* the preview buttons emit ``preview_requested(bpm)`` /
  ``preview_stop_requested()`` — no audio service is imported here.

Qt-dependent — PySide6/pytest-qt are importorskip'd so the Qt-less engine
venv skips this module cleanly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from rai_analyzer.contracts import AnalysisResult, Candidate, TempoResult
from rai_ui.state.tempo_view import build_tempo_view
from rai_ui.state.verdict import VerdictKind, VerdictState
from rai_ui.widgets.candidate_table import CandidatePane
from rai_ui.widgets.tiebreak import (
    BAND_IN_TEXT,
    BAND_OUT_TEXT,
    BPM_PX,
    CARD_MIN_HEIGHT,
    CLOSE_SIZE,
    CONFIRM_DISABLED_TEXT,
    CONFIRM_HEIGHT,
    FOOTER_HINT_TEXT,
    FOOTER_SAVE_TEXT,
    MAX_CARDS,
    PREVIEW_ACTIVE_TEXT,
    PREVIEW_HEIGHT,
    PREVIEW_IDLE_TEXT,
    SALIENCE_LABEL_PREFIX,
    TITLE_TEXT,
    TiebreakOverlay,
    confirm_label,
)

# The 04 demo's ambiguous scenario: primary 205.15 outside the drill band,
# 155.25 inside it — the cards that made the flow's design case.
PRIMARY_BPM = 205.15
AMBIGUOUS_REASON = (
    "primary 205 is outside the drill band [140–170], yet 155 sits inside it"
)

AMBIGUOUS = VerdictState(kind=VerdictKind.AMBIGUOUS, path="/tmp/beat.wav")
WORKING = VerdictState(kind=VerdictKind.WORKING, path="/tmp/beat.wav")


def make_tempo(extra_bpms: tuple[float, ...] = (102.57, 155.25, 68.38)) -> TempoResult:
    candidates = [Candidate(bpm=PRIMARY_BPM, score=1.86, salience=0.912)]
    for i, bpm in enumerate(extra_bpms):
        candidates.append(
            Candidate(bpm=bpm, score=1.5 - 0.05 * i, salience=max(0.05, 0.8 - 0.04 * i))
        )
    return TempoResult(
        primary_bpm=PRIMARY_BPM,
        felt_bpm=102.57,
        candidates=candidates,
        ambiguous=True,
        ambiguity_reason=AMBIGUOUS_REASON,
    )


def make_vm(tempo: TempoResult | None = None, verdict: VerdictState = AMBIGUOUS):
    result = AnalysisResult(
        path="/tmp/beat.wav",
        duration=6.0,
        sr=44100,
        channels=2,
        tempo=tempo if tempo is not None else make_tempo(),
        loudness=None,
    )
    return build_tempo_view(result, None, verdict)


@pytest.fixture
def overlay(qtbot):
    widget = TiebreakOverlay()
    qtbot.addWidget(widget)
    widget.set_view(make_vm())
    return widget


@pytest.fixture
def shown_overlay(qtbot, overlay):
    overlay.resize(760, 340)
    with qtbot.waitExposed(overlay):
        overlay.show()
    return overlay


def recorded(signal):
    fired: list = []
    signal.connect(lambda *args: fired.append(args))
    return fired


# ---------------------------------------------------------------------------
# Verbatim design copy + geometry literals
# ---------------------------------------------------------------------------


class TestDesignCopy:
    def test_copy_verbatim(self):
        assert TITLE_TEXT == "Human tiebreak — which grid locks?"
        assert PREVIEW_IDLE_TEXT == "▶ preview click grid"
        assert PREVIEW_ACTIVE_TEXT == "previewing click grid — ⏸"
        assert BAND_IN_TEXT == "✓ in drill band"
        assert BAND_OUT_TEXT == "outside band"
        assert FOOTER_HINT_TEXT == (
            "▶ overlays a click track on the audio · pick the grid that locks"
        )
        assert FOOTER_SAVE_TEXT == "saved locally · feeds the engine's relearning"
        assert CONFIRM_DISABLED_TEXT == "Pick a candidate"
        assert confirm_label("155.25") == "Set 155.25 — save as ground truth"

    def test_geometry_literals(self):
        # 04:306-345 (+ R-M3-18: tiebreak BPM 30px, 04/C-14 over C-07's 44).
        assert MAX_CARDS == 3
        assert BPM_PX == 30
        assert CARD_MIN_HEIGHT == 186
        assert CLOSE_SIZE == 26
        assert PREVIEW_HEIGHT == 28
        assert CONFIRM_HEIGHT == 38

    def test_header_reason_is_the_original_ambiguity_reason(self, overlay):
        assert overlay.reason_label.text() == AMBIGUOUS_REASON
        assert overlay.title_label.text() == TITLE_TEXT


# ---------------------------------------------------------------------------
# Cards — top-3 slice, content, chips vs the ORIGINAL primary
# ---------------------------------------------------------------------------


class TestCards:
    def test_exactly_top_three_ranked_cards(self, overlay):
        # 4 candidates in the vm; tb = cands.slice(0, 3) (04:742).
        visible = [c for c in overlay.cards if not c.isHidden()]
        assert len(visible) == 3
        assert [c.bpm_label.text() for c in visible] == ["205.15", "102.57", "155.25"]

    def test_two_candidates_render_two_cards(self, overlay):
        overlay.set_view(make_vm(make_tempo(extra_bpms=(102.57,))))
        visible = [c for c in overlay.cards if not c.isHidden()]
        assert len(visible) == 2
        assert overlay.cards[2].isHidden()

    def test_chips_computed_against_original_engine_primary(self, overlay):
        # The vm's ambiguous-state chips ARE the vs-original-primary values
        # (04:745); the card renders that text in the fixed neutral style.
        vm = make_vm()
        for card, row in zip(overlay.cards, vm.candidates[:3]):
            assert card.chip.chip.text == row.chip.text
            assert card.chip.chip.kind == "related"  # 04:319 — one chip style
        assert overlay.cards[0].chip.chip.text == "×1 · primary"
        assert overlay.cards[1].chip.chip.text == "½× · half-time"

    def test_band_tag_from_engine_band_not_hardcoded_copy(self, overlay):
        # 155.25 sits in [140, 170] (vm.band from the engine config).
        assert overlay.cards[2].band_label.text() == BAND_IN_TEXT
        assert overlay.cards[0].band_label.text() == BAND_OUT_TEXT
        assert overlay.cards[1].band_label.text() == BAND_OUT_TEXT
        # in-band green vs muted (04:746)
        assert "#8FE8B4" in overlay.cards[2].band_label.styleSheet()
        assert "#7E8896" in overlay.cards[0].band_label.styleSheet()

    def test_salience_bar_and_label(self, overlay):
        card = overlay.cards[0]
        assert card.bar.salience == pytest.approx(0.912)
        assert card.salience_label.text() == f"{SALIENCE_LABEL_PREFIX}0.912"

    def test_bpm_numeral_type_is_mono_30_600(self, overlay):
        from PySide6.QtGui import QFont

        font = overlay.cards[0].bpm_label.font()
        assert font.pixelSize() == 30
        assert font.weight() == QFont.Weight.DemiBold
        # landmine 8: the widget-level pin must restate the same values
        assert "font-size: 30px" in overlay.cards[0].bpm_label.styleSheet()
        assert "font-weight: 600" in overlay.cards[0].bpm_label.styleSheet()


# ---------------------------------------------------------------------------
# Selection vs preview — INDEPENDENT states (C-14 verbatim)
# ---------------------------------------------------------------------------


class TestSelectionVsPreview:
    def test_card_click_selects(self, qtbot, shown_overlay):
        card = shown_overlay.cards[1]
        qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
        assert shown_overlay.chosen_index == 1
        assert card.selected is True
        assert shown_overlay.cards[0].selected is False

    def test_selecting_another_card_moves_selection(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[0], Qt.MouseButton.LeftButton)
        qtbot.mouseClick(shown_overlay.cards[2], Qt.MouseButton.LeftButton)
        assert shown_overlay.chosen_index == 2
        assert shown_overlay.cards[0].selected is False
        assert shown_overlay.cards[2].selected is True

    def test_preview_click_does_not_select(self, qtbot, shown_overlay):
        # the demo's stopPropagation (04:750): preview never chooses.
        card = shown_overlay.cards[1]
        with qtbot.waitSignal(shown_overlay.preview_requested, timeout=1000) as blocker:
            qtbot.mouseClick(card.preview_button, Qt.MouseButton.LeftButton)
        assert blocker.args == [102.57]
        assert shown_overlay.preview_index == 1
        assert shown_overlay.chosen_index is None
        assert card.previewing is True
        assert card.selected is False

    def test_preview_toggles_off_with_stop_signal(self, qtbot, shown_overlay):
        card = shown_overlay.cards[0]
        qtbot.mouseClick(card.preview_button, Qt.MouseButton.LeftButton)
        with qtbot.waitSignal(shown_overlay.preview_stop_requested, timeout=1000):
            qtbot.mouseClick(card.preview_button, Qt.MouseButton.LeftButton)
        assert shown_overlay.preview_index is None
        assert card.previewing is False

    def test_previewing_another_card_moves_the_single_slot(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[0].preview_button, Qt.MouseButton.LeftButton)
        stops = recorded(shown_overlay.preview_stop_requested)
        with qtbot.waitSignal(shown_overlay.preview_requested, timeout=1000) as blocker:
            qtbot.mouseClick(
                shown_overlay.cards[2].preview_button, Qt.MouseButton.LeftButton
            )
        # one preview_requested with the NEW bpm, no interleaved stop — the
        # audio service swaps at the same frame index (R-M3-8).
        assert blocker.args == [155.25]
        assert stops == []
        assert shown_overlay.preview_index == 2
        assert shown_overlay.cards[0].previewing is False
        assert shown_overlay.cards[2].previewing is True

    def test_selecting_does_not_stop_a_running_preview(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[1].preview_button, Qt.MouseButton.LeftButton)
        stops = recorded(shown_overlay.preview_stop_requested)
        qtbot.mouseClick(shown_overlay.cards[0], Qt.MouseButton.LeftButton)
        assert stops == []
        assert shown_overlay.chosen_index == 0
        assert shown_overlay.preview_index == 1

    def test_card_can_be_selected_and_previewing_at_once(self, qtbot, shown_overlay):
        card = shown_overlay.cards[2]
        qtbot.mouseClick(card, Qt.MouseButton.LeftButton)
        qtbot.mouseClick(card.preview_button, Qt.MouseButton.LeftButton)
        assert card.selected is True and card.previewing is True
        assert not shown_overlay.grab().toImage().isNull()  # paint smoke

    def test_preview_button_carries_verbatim_copy(self, qtbot, shown_overlay):
        # QPushButton.text() = the design copy (▶/⏸ drawn at paint time).
        button = shown_overlay.cards[0].preview_button
        assert button.text() == PREVIEW_IDLE_TEXT
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert button.text() == PREVIEW_ACTIVE_TEXT
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
        assert button.text() == PREVIEW_IDLE_TEXT

    def test_pulse_runs_only_while_previewing_and_visible(self, qtbot, shown_overlay):
        card = shown_overlay.cards[0]
        assert card.preview_button.pulse_running is False
        qtbot.mouseClick(card.preview_button, Qt.MouseButton.LeftButton)
        assert card.preview_button.pulse_running is True
        shown_overlay.hide()
        assert card.preview_button.pulse_running is False


# ---------------------------------------------------------------------------
# Confirm footer — enable state, computed label, guarded click
# ---------------------------------------------------------------------------


class TestConfirm:
    def test_starts_as_pick_a_candidate_ghost(self, overlay):
        assert overlay.confirm_button.text() == CONFIRM_DISABLED_TEXT

    def test_ghost_click_is_a_noop(self, qtbot, shown_overlay):
        confirms = recorded(shown_overlay.confirm_requested)
        qtbot.mouseClick(shown_overlay.confirm_button, Qt.MouseButton.LeftButton)
        assert confirms == []
        assert shown_overlay.isVisible()

    def test_selection_enables_with_computed_label(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[2], Qt.MouseButton.LeftButton)
        assert (
            shown_overlay.confirm_button.text() == "Set 155.25 — save as ground truth"
        )
        qtbot.mouseClick(shown_overlay.cards[1], Qt.MouseButton.LeftButton)
        assert (
            shown_overlay.confirm_button.text() == "Set 102.57 — save as ground truth"
        )

    def test_confirm_emits_bpm_closes_stops_preview_keeps_selection(
        self, qtbot, shown_overlay
    ):
        qtbot.mouseClick(shown_overlay.cards[2], Qt.MouseButton.LeftButton)
        qtbot.mouseClick(shown_overlay.cards[0].preview_button, Qt.MouseButton.LeftButton)
        stops = recorded(shown_overlay.preview_stop_requested)
        closed = recorded(shown_overlay.closed)
        with qtbot.waitSignal(shown_overlay.confirm_requested, timeout=1000) as blocker:
            qtbot.mouseClick(shown_overlay.confirm_button, Qt.MouseButton.LeftButton)
        assert blocker.args == [155.25]
        assert stops == [()]  # confirm nulls previewIdx (04:861)
        assert not shown_overlay.isVisible()
        assert shown_overlay.chosen_index == 2  # chosenIdx retained
        assert closed == []  # confirm speaks via confirm_requested, not closed


# ---------------------------------------------------------------------------
# Dismiss — ✕ semantics (04:857)
# ---------------------------------------------------------------------------


class TestDismiss:
    def test_close_stops_preview_keeps_selection(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[1], Qt.MouseButton.LeftButton)
        qtbot.mouseClick(shown_overlay.cards[1].preview_button, Qt.MouseButton.LeftButton)
        stops = recorded(shown_overlay.preview_stop_requested)
        with qtbot.waitSignal(shown_overlay.closed, timeout=1000):
            qtbot.mouseClick(shown_overlay.close_button, Qt.MouseButton.LeftButton)
        assert stops == [()]
        assert not shown_overlay.isVisible()
        assert shown_overlay.chosen_index == 1  # selection SURVIVES ✕
        assert shown_overlay.preview_index is None

    def test_reopen_shows_preserved_selection(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[1], Qt.MouseButton.LeftButton)
        shown_overlay.dismiss()
        shown_overlay.set_view(make_vm())  # same candidates re-rendered
        with qtbot.waitExposed(shown_overlay):
            shown_overlay.show()
        assert shown_overlay.chosen_index == 1
        assert shown_overlay.cards[1].selected is True

    def test_dismiss_without_preview_emits_no_stop(self, qtbot, shown_overlay):
        stops = recorded(shown_overlay.preview_stop_requested)
        shown_overlay.dismiss()
        assert stops == []


# ---------------------------------------------------------------------------
# set_view — new candidates reset, same candidates preserve
# ---------------------------------------------------------------------------


class TestSetView:
    def test_new_candidates_reset_selection_and_preview(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[1], Qt.MouseButton.LeftButton)
        qtbot.mouseClick(shown_overlay.cards[0].preview_button, Qt.MouseButton.LeftButton)
        stops = recorded(shown_overlay.preview_stop_requested)
        shown_overlay.set_view(make_vm(make_tempo(extra_bpms=(70.11, 140.22))))
        assert shown_overlay.chosen_index is None
        assert shown_overlay.preview_index is None
        assert stops == [()]  # the dying preview is stopped, not leaked
        assert shown_overlay.confirm_button.text() == CONFIRM_DISABLED_TEXT

    def test_same_candidates_preserve_selection(self, qtbot, shown_overlay):
        qtbot.mouseClick(shown_overlay.cards[2], Qt.MouseButton.LeftButton)
        shown_overlay.set_view(make_vm())
        assert shown_overlay.chosen_index == 2
        assert (
            shown_overlay.confirm_button.text() == "Set 155.25 — save as ground truth"
        )


# ---------------------------------------------------------------------------
# Keyboard (R-M3-7): ←/→ select · Space preview · Enter selects only · Esc
# ---------------------------------------------------------------------------


class TestKeyboard:
    def test_arrows_move_selection_with_clamp(self, qtbot, shown_overlay):
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)  # None → first card
        assert shown_overlay.chosen_index == 0
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)
        assert shown_overlay.chosen_index == 2
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)  # clamped at the end
        assert shown_overlay.chosen_index == 2
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Left)
        assert shown_overlay.chosen_index == 1
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Left)
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Left)  # clamped at the start
        assert shown_overlay.chosen_index == 0

    def test_enter_selects_and_never_confirms(self, qtbot, shown_overlay):
        confirms = recorded(shown_overlay.confirm_requested)
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Return)  # None → first card
        assert shown_overlay.chosen_index == 0
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Return)  # with a selection: no-op
        assert shown_overlay.chosen_index == 0
        assert confirms == []  # ground truth is a deliberate CLICK (D6)
        assert shown_overlay.isVisible()

    def test_space_toggles_preview_on_selected_card(self, qtbot, shown_overlay):
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)  # select card 0
        with qtbot.waitSignal(shown_overlay.preview_requested, timeout=1000) as blocker:
            qtbot.keyClick(shown_overlay, Qt.Key.Key_Space)
        assert blocker.args == [205.15]
        assert shown_overlay.preview_index == 0
        with qtbot.waitSignal(shown_overlay.preview_stop_requested, timeout=1000):
            qtbot.keyClick(shown_overlay, Qt.Key.Key_Space)
        assert shown_overlay.preview_index is None

    def test_space_without_selection_is_a_noop(self, qtbot, shown_overlay):
        previews = recorded(shown_overlay.preview_requested)
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Space)
        assert previews == []
        assert shown_overlay.preview_index is None

    def test_escape_closes_preserving_selection(self, qtbot, shown_overlay):
        qtbot.keyClick(shown_overlay, Qt.Key.Key_Right)
        with qtbot.waitSignal(shown_overlay.closed, timeout=1000):
            qtbot.keyClick(shown_overlay, Qt.Key.Key_Escape)
        assert not shown_overlay.isVisible()
        assert shown_overlay.chosen_index == 0


# ---------------------------------------------------------------------------
# Pane integration — mount, geometry, bubbling, undo seam (R-M3-17)
# ---------------------------------------------------------------------------


@pytest.fixture
def pane(qtbot):
    widget = CandidatePane()
    qtbot.addWidget(widget)
    widget.set_rows(make_vm())
    return widget


@pytest.fixture
def shown_pane(qtbot, pane):
    pane.resize(760, 420)
    with qtbot.waitExposed(pane):
        pane.show()
    return pane


class TestPaneIntegration:
    def test_open_tiebreak_covers_the_pane(self, qtbot, shown_pane):
        assert not shown_pane.tiebreak.isVisible()
        shown_pane.open_tiebreak()
        assert shown_pane.tiebreak.isVisible()
        expected = shown_pane.rect().adjusted(1, 1, -1, -1)
        assert shown_pane.tiebreak.size() == expected.size()
        # entrance is an 8px rise: wait for the 220ms raiIn to settle
        qtbot.waitUntil(
            lambda: shown_pane.tiebreak.pos() == expected.topLeft(), timeout=2000
        )
        assert not shown_pane.tiebreak.grab().toImage().isNull()

    def test_resize_keeps_overlay_glued(self, qtbot, shown_pane):
        shown_pane.open_tiebreak()
        shown_pane.resize(820, 460)
        expected = shown_pane.rect().adjusted(1, 1, -1, -1)
        assert shown_pane.tiebreak.size() == expected.size()

    def test_close_tiebreak_dismisses(self, qtbot, shown_pane):
        shown_pane.open_tiebreak()
        shown_pane.close_tiebreak()
        assert not shown_pane.tiebreak.isVisible()
        shown_pane.close_tiebreak()  # idempotent when already closed

    def test_pane_bubbles_overlay_signals(self, qtbot, shown_pane):
        shown_pane.open_tiebreak()
        with qtbot.waitSignal(shown_pane.preview_requested, timeout=1000) as blocker:
            qtbot.mouseClick(
                shown_pane.tiebreak.cards[1].preview_button, Qt.MouseButton.LeftButton
            )
        assert blocker.args == [102.57]
        qtbot.mouseClick(shown_pane.tiebreak.cards[2], Qt.MouseButton.LeftButton)
        stops = recorded(shown_pane.preview_stop_requested)
        with qtbot.waitSignal(shown_pane.confirm_requested, timeout=1000) as blocker:
            qtbot.mouseClick(
                shown_pane.tiebreak.confirm_button, Qt.MouseButton.LeftButton
            )
        assert blocker.args == [155.25]
        assert stops == [()]

    def test_non_ambiguous_view_dismisses_open_overlay(self, qtbot, shown_pane):
        # A new analysis (WORKING blanks everything) lands while the overlay
        # is up: it must close, preview stopped — R-M3-6 leaves no tiebreak
        # surface outside the ambiguous verdict.
        shown_pane.open_tiebreak()
        qtbot.mouseClick(
            shown_pane.tiebreak.cards[0].preview_button, Qt.MouseButton.LeftButton
        )
        stops = recorded(shown_pane.preview_stop_requested)
        shown_pane.set_rows(make_vm(verdict=WORKING))
        assert not shown_pane.tiebreak.isVisible()
        assert stops == [()]

    def test_ambiguous_rerender_keeps_overlay_open(self, qtbot, shown_pane):
        shown_pane.open_tiebreak()
        shown_pane.set_rows(make_vm())  # same ambiguous analysis re-rendered
        assert shown_pane.tiebreak.isVisible()

    def test_undo_ghost_emits_undo_requested_not_tiebreak(self, qtbot, pane):
        confirmed = VerdictState(
            kind=VerdictKind.CONFIRMED_HUMAN,
            path="/tmp/beat.wav",
            confirmed_bpm=155.25,
            prev_kind=VerdictKind.AMBIGUOUS,
        )
        pane.set_rows(make_vm(verdict=confirmed))
        assert pane.undo_button.isVisibleTo(pane)
        tiebreaks = recorded(pane.tiebreak_requested)
        with qtbot.waitSignal(pane.undo_requested, timeout=1000):
            pane.undo_button.click()
        assert tiebreaks == []


# ---------------------------------------------------------------------------
# Section bubbling + open/close API
# ---------------------------------------------------------------------------


class TestSectionBubbling:
    @pytest.fixture
    def section(self, qtbot):
        from rai_ui.sections.tempo import TempoSection

        widget = TempoSection()
        qtbot.addWidget(widget)
        widget.set_view(make_vm())
        return widget

    def test_section_forwards_all_new_signals(self, qtbot, section):
        pane = section.candidates
        with qtbot.waitSignal(section.undo_requested, timeout=1000):
            pane.undo_requested.emit()
        with qtbot.waitSignal(section.preview_requested, timeout=1000) as blocker:
            pane.preview_requested.emit(155.25)
        assert blocker.args == [155.25]
        with qtbot.waitSignal(section.preview_stop_requested, timeout=1000):
            pane.preview_stop_requested.emit()
        with qtbot.waitSignal(section.confirm_requested, timeout=1000) as blocker:
            pane.confirm_requested.emit(102.57)
        assert blocker.args == [102.57]

    def test_section_open_close_tiebreak(self, qtbot, section):
        section.resize(900, 700)
        with qtbot.waitExposed(section):
            section.show()
        section.open_tiebreak()
        assert section.candidates.tiebreak.isVisible()
        section.close_tiebreak()
        assert not section.candidates.tiebreak.isVisible()
