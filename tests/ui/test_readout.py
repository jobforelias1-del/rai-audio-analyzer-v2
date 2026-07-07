"""Readout-surface tests: verdict block (C-05), metric rail (C-07), meter
bridge (C-02).

The binding contracts under test:

* Every ``VerdictView`` kind the reducer can produce renders — word copy
  verbatim (glyph prefixes included), state skin via the ``verdict`` QSS
  property, the red tiebreak action only in ambiguous, undo only in
  confirmed.
* The ◆ ambiguous mark is a DRAWN icon, never a font glyph (P3 rule).
* Reasons render in full on the rail; one line, ellipsized, tooltip-backed
  on the bridge.
* Rail and bridge consume the SAME ``ReadoutView`` and must show identical
  numbers; numeral labels are never tinted by verdict state (CL:78/158).
* Em-dash absence policy (C-06/R12) and the exact dBTP ≠ dBFS footer copy.

Qt-dependent throughout — PySide6/pytest-qt are importorskip'd before any Qt
import so the Qt-less engine venv skips this module cleanly.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtWidgets import QApplication

from rai_analyzer.contracts import LoudnessResult
from rai_ui.state.tempo_view import EMPTY_VIEW, build_tempo_view
from rai_ui.state.verdict import VerdictKind
from rai_ui.widgets.meter_bridge import (
    BRIDGE_FOOTER,
    BRIDGE_HEIGHT,
    VERDICT_CELL_WIDTH,
    VERDICT_CELL_WIDTH_AMBIGUOUS,
    MeterBridge,
)
from rai_ui.widgets.metric_readout import RAIL_FOOTER, RAIL_WIDTH, MetricRail
from rai_ui.widgets.verdict_block import VerdictBlock, display_word, verdict_qss_property
from tests.ui.test_tempo_view import make_result, make_tempo, no_tempo_result, state

EM_DASH = "—"

AMBIGUOUS_REASON = "primary 205 is outside the drill band [140–170], yet 155 sits inside it"
LOUDNESS = LoudnessResult(lufs_i=-9.3, true_peak_dbtp=-0.82, sample_peak_dbfs=-1.24)


# ---------------------------------------------------------------------------
# ReadoutView builders — one per verdict kind, through the real view-model
# ---------------------------------------------------------------------------


def confident_readout():
    return build_tempo_view(
        make_result(loudness=LOUDNESS), None, state(VerdictKind.CONFIDENT)
    ).readout


def ambiguous_readout(reason: str = AMBIGUOUS_REASON):
    result = make_result(make_tempo(ambiguous=True, ambiguity_reason=reason))
    return build_tempo_view(result, None, state(VerdictKind.AMBIGUOUS)).readout


def confirmed_readout():
    st = state(
        VerdictKind.CONFIRMED_HUMAN, confirmed_bpm=155.25, prev_kind=VerdictKind.AMBIGUOUS
    )
    return build_tempo_view(make_result(), None, st).readout


def working_readout():
    return build_tempo_view(None, None, state(VerdictKind.WORKING)).readout


def error_readout(msg: str = "LibsndfileError: unknown format"):
    return build_tempo_view(None, None, state(VerdictKind.ERROR, error_msg=msg)).readout


def no_tempo_readout():
    return build_tempo_view(no_tempo_result(), None, state(VerdictKind.NO_TEMPO)).readout


READOUT_BY_KIND = {
    VerdictKind.NO_FILE: lambda: EMPTY_VIEW.readout,
    VerdictKind.WORKING: working_readout,
    VerdictKind.CONFIDENT: confident_readout,
    VerdictKind.AMBIGUOUS: ambiguous_readout,
    VerdictKind.CONFIRMED_HUMAN: confirmed_readout,
    VerdictKind.NO_TEMPO: no_tempo_readout,
    VerdictKind.ERROR: error_readout,
}

# (kind, rail word, QSS property, tiebreak shown, undo shown) — design copy
# verbatim: C-05 table + the neutral "— " unavailability prefix.
KIND_MATRIX = [
    (VerdictKind.NO_FILE, "— NO FILE", "neutral", False, False),
    (VerdictKind.WORKING, "WORKING…", "working", False, False),
    (VerdictKind.CONFIDENT, "✓ CONFIDENT", "confident", False, False),
    (VerdictKind.AMBIGUOUS, "AMBIGUOUS", "ambiguous", True, False),
    (VerdictKind.CONFIRMED_HUMAN, "✓ CONFIRMED · HUMAN", "confirmed", False, True),
    (VerdictKind.NO_TEMPO, "— NO TEMPO", "neutral", False, False),
    (VerdictKind.ERROR, "— ERROR", "error", False, False),
]


# ---------------------------------------------------------------------------
# Verdict block (C-05)
# ---------------------------------------------------------------------------


class TestVerdictBlock:
    @pytest.mark.parametrize("kind,word,prop,tiebreak,undo", KIND_MATRIX)
    def test_every_kind_renders(self, qtbot, kind, word, prop, tiebreak, undo):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(READOUT_BY_KIND[kind]().verdict)
        assert block._word_label.text() == word
        assert block.property("verdict") == prop
        assert block._tiebreak_button.isHidden() is not tiebreak
        assert block._undo_line.isHidden() is not undo

    def test_diamond_is_drawn_never_a_font_glyph(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(ambiguous_readout().verdict)
        assert "◆" not in block._word_label.text()  # P3: never a font glyph
        assert not block._icon_label.isHidden()
        assert not block._icon_label.pixmap().isNull()

    def test_no_diamond_outside_ambiguous(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(confident_readout().verdict)
        assert block._icon_label.isHidden()

    def test_ambiguous_sub_and_full_reasons(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        r1 = "raw tempogram peaks at 205, prior favors 155 (dotted_down)"
        r2 = "155 (dotted_down) scores within 12% of 205"
        block.set_verdict(ambiguous_readout(f"{r1}; {r2}").verdict)
        assert block._tiebreak_sub.text() == "HUMAN TIEBREAK NEEDED"
        assert not block._tiebreak_sub.isHidden()
        # Full strings, one line-wrapped label per reason — never truncated.
        assert [lab.text() for lab in block._reason_labels] == [r1, r2]
        assert all(lab.wordWrap() for lab in block._reason_labels)

    def test_neutral_sub_lines(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(EMPTY_VIEW.readout.verdict)
        assert block._neutral_sub.text() == "drop a WAV anywhere in this window"
        block.set_verdict(no_tempo_readout().verdict)
        assert block._neutral_sub.text() == "silent file — nothing to track"

    def test_confirmed_reason_and_undo_link(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(confirmed_readout().verdict)
        assert [lab.text() for lab in block._reason_labels] == [
            "you chose 155.25 — saved as ground truth"
        ]
        seen = []
        block.undo_requested.connect(lambda: seen.append(True))
        block._undo_line.linkActivated.emit("undo")
        assert seen == [True]

    def test_error_renders_message_on_neutral_surface(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(error_readout("decode exploded").verdict)
        assert block.property("verdict") == "error"  # QSS: neutral surface skin
        assert [lab.text() for lab in block._reason_labels] == ["decode exploded"]

    def test_tiebreak_button_signal(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(ambiguous_readout().verdict)
        seen = []
        block.tiebreak_requested.connect(lambda: seen.append(True))
        block._tiebreak_button.click()
        assert seen == [True]

    def test_working_sweep_runs_shown_stops_hidden(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.set_verdict(working_readout().verdict)
        block.show()
        assert block._working_track.is_running()
        block.hide()
        assert not block._working_track.is_running()
        block.show()
        assert block._working_track.is_running()

    def test_working_sweep_stops_on_verdict_change(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        block.show()
        block.set_verdict(working_readout().verdict)
        assert block._working_track.is_running()
        block.set_verdict(confident_readout().verdict)
        assert not block._working_track.is_running()
        assert block._working_track.isHidden()

    def test_set_verdict_idempotent(self, qtbot):
        block = VerdictBlock()
        qtbot.addWidget(block)
        view = ambiguous_readout().verdict
        block.set_verdict(view)
        block.set_verdict(view)  # no duplicate reason labels
        assert len(block._reason_labels) == 1
        assert block.view() == view


# ---------------------------------------------------------------------------
# Metric rail (C-07)
# ---------------------------------------------------------------------------


class TestMetricRail:
    def test_fixed_width(self, qtbot):
        rail = MetricRail()
        qtbot.addWidget(rail)
        assert (rail.minimumWidth(), rail.maximumWidth()) == (RAIL_WIDTH, RAIL_WIDTH)

    def test_numbers_render(self, qtbot):
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(confident_readout())
        assert rail.primary_value.text() == "205.15"
        assert rail.felt_value.text() == "102.57"
        assert rail.lufs_value.text() == "−9.30"
        assert rail.dbtp_value.text() == "−0.82"
        assert rail.dbfs_value.text() == "−1.24"

    def test_empty_view_is_all_em_dashes(self, qtbot):
        rail = MetricRail()  # starts on EMPTY_VIEW.readout
        qtbot.addWidget(rail)
        for label in (
            rail.primary_value,
            rail.felt_value,
            rail.lufs_value,
            rail.dbtp_value,
            rail.dbfs_value,
            rail.dr_value,
            rail.sub_value,
            rail.width_value,
        ):
            assert label.text() == EM_DASH

    def test_m2_metrics_stay_em_dash_with_a_result(self, qtbot):
        """DR / Sub / Width are absence until M2 — never 0, never −∞ (R12)."""
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(confident_readout())
        assert (rail.dr_value.text(), rail.sub_value.text(), rail.width_value.text()) == (
            EM_DASH,
            EM_DASH,
            EM_DASH,
        )

    def test_felt_chip_present_and_absent(self, qtbot):
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(confident_readout())
        assert not rail.felt_chip_label.isHidden()
        assert rail.felt_chip_label.text() == "½× · half-time"
        no_felt = build_tempo_view(
            make_result(make_tempo(felt_bpm=None)), None, state(VerdictKind.CONFIDENT)
        ).readout
        rail.set_view(no_felt)
        assert rail.felt_chip_label.isHidden()
        assert rail.felt_value.text() == EM_DASH

    def test_footer_copy_exact(self, qtbot):
        rail = MetricRail()
        qtbot.addWidget(rail)
        assert rail.footer_label.text() == "dBTP ≠ dBFS — both always shown, never collapsed."
        assert rail.footer_label.text() == RAIL_FOOTER

    def test_signals_forwarded_from_verdict_block(self, qtbot):
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(ambiguous_readout())
        seen = []
        rail.tiebreak_requested.connect(lambda: seen.append("tiebreak"))
        rail.undo_requested.connect(lambda: seen.append("undo"))
        rail.verdict_block._tiebreak_button.click()
        rail.set_view(confirmed_readout())
        rail.verdict_block._undo_line.linkActivated.emit("undo")
        assert seen == ["tiebreak", "undo"]

    def test_numerals_never_tinted_by_verdict(self, qtbot):
        """Semantic color never touches a numeral (CL:158)."""
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(confident_readout())
        styles = [
            label.styleSheet()
            for label in (rail.primary_value, rail.felt_value, rail.lufs_value)
        ]
        rail.set_view(ambiguous_readout())
        assert [
            label.styleSheet()
            for label in (rail.primary_value, rail.felt_value, rail.lufs_value)
        ] == styles


# ---------------------------------------------------------------------------
# Meter bridge (C-02)
# ---------------------------------------------------------------------------


class TestMeterBridge:
    def test_fixed_height(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        assert (bridge.minimumHeight(), bridge.maximumHeight()) == (
            BRIDGE_HEIGHT,
            BRIDGE_HEIGHT,
        )

    def test_verdict_cell_width_swaps_with_ambiguous(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(confident_readout())
        assert bridge.verdict_cell.minimumWidth() == VERDICT_CELL_WIDTH  # 196
        bridge.set_view(ambiguous_readout())
        assert bridge.verdict_cell.minimumWidth() == VERDICT_CELL_WIDTH_AMBIGUOUS  # 280
        bridge.set_view(confident_readout())
        assert bridge.verdict_cell.minimumWidth() == VERDICT_CELL_WIDTH

    @pytest.mark.parametrize("kind,rail_word,prop,tiebreak,undo", KIND_MATRIX)
    def test_every_kind_renders(self, qtbot, kind, rail_word, prop, tiebreak, undo):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        view = READOUT_BY_KIND[kind]()
        bridge.set_view(view)
        assert bridge.word_label.text() == display_word(view.verdict, bridge=True)
        assert bridge._tiebreak_button.isHidden() is not tiebreak
        assert bridge._undo_link.isHidden() is not undo

    def test_ambiguous_word_copy_and_drawn_diamond(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(ambiguous_readout())
        assert bridge.word_label.text() == "AMBIGUOUS — HUMAN TIEBREAK"  # CO:105
        assert "◆" not in bridge.word_label.text()  # P3: never a font glyph
        assert not bridge._icon_label.isHidden()
        assert not bridge._icon_label.pixmap().isNull()

    def test_reason_one_line_ellipsized_with_tooltip(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        long_reason = AMBIGUOUS_REASON + " · " + "; ".join(f"detail {i}" for i in range(30))
        bridge.set_view(confident_readout())
        view = ambiguous_readout(long_reason)
        bridge.set_view(view)
        assert bridge.reason_label.toolTip() == long_reason  # full text survives
        assert bridge.reason_label.full_text() == long_reason
        bridge.resize(900, BRIDGE_HEIGHT)
        bridge.show()
        QApplication.processEvents()
        shown = bridge.reason_label.text()
        assert shown != long_reason
        assert shown.endswith("…")  # elided, single line

    def test_confirmed_reason_ends_with_inline_undo(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(confirmed_readout())
        assert bridge.reason_label.full_text() == "you chose 155.25 — saved as ground truth · "
        assert not bridge._undo_link.isHidden()
        seen = []
        bridge.undo_requested.connect(lambda: seen.append(True))
        bridge._undo_link.linkActivated.emit("undo")
        assert seen == [True]

    def test_neutral_sub_is_the_bridge_reason_line(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(working_readout())
        assert bridge.reason_label.full_text() == "full-track analysis · ~1 s"
        bridge.set_view(EMPTY_VIEW.readout)
        assert bridge.reason_label.full_text() == "drop a WAV anywhere in this window"

    def test_tiebreak_button_signal(self, qtbot):
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(ambiguous_readout())
        seen = []
        bridge.tiebreak_requested.connect(lambda: seen.append(True))
        bridge._tiebreak_button.click()
        assert seen == [True]

    def test_footer_copy_exact(self, qtbot):
        """The bridge caption drops the rail's ', never collapsed.' tail."""
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        assert bridge.footer_label.text() == "dBTP ≠ dBFS — both always shown"
        assert bridge.footer_label.text() == BRIDGE_FOOTER

    def test_numerals_never_tinted_by_verdict(self, qtbot):
        """Verdict cell swaps skin; numeral cells never change color (CL:78)."""
        bridge = MeterBridge()
        qtbot.addWidget(bridge)
        bridge.set_view(confident_readout())
        labels = (
            bridge.primary_value,
            bridge.felt_value,
            bridge.lufs_value,
            bridge.dbtp_value,
            bridge.dbfs_value,
            bridge.dr_value,
            bridge.width_value,
        )
        styles = [label.styleSheet() for label in labels]
        bridge.set_view(ambiguous_readout())
        assert [label.styleSheet() for label in labels] == styles


# ---------------------------------------------------------------------------
# Rail ⇄ bridge parity — one ReadoutView, identical numbers
# ---------------------------------------------------------------------------


class TestRailBridgeParity:
    @pytest.mark.parametrize("kind", list(VerdictKind))
    def test_identical_numbers_from_one_readout_view(self, qtbot, kind):
        """"Same data as the rail" (CL:65) — byte-identical numerals."""
        view = READOUT_BY_KIND[kind]()
        rail = MetricRail()
        bridge = MeterBridge()
        qtbot.addWidget(rail)
        qtbot.addWidget(bridge)
        rail.set_view(view)
        bridge.set_view(view)
        pairs = [
            (rail.primary_value, bridge.primary_value),
            (rail.felt_value, bridge.felt_value),
            (rail.lufs_value, bridge.lufs_value),
            (rail.dbtp_value, bridge.dbtp_value),
            (rail.dbfs_value, bridge.dbfs_value),
            (rail.dr_value, bridge.dr_value),
            (rail.width_value, bridge.width_value),
        ]
        for rail_label, bridge_label in pairs:
            assert rail_label.text() == bridge_label.text()
        assert rail.view() is bridge.view() is view

    def test_rail_additionally_shows_sub_bass(self, qtbot):
        """Sub/bass is a rail-only row (bridge subset is intentional, R12)."""
        rail = MetricRail()
        qtbot.addWidget(rail)
        rail.set_view(confident_readout())
        assert rail.sub_value.text() == EM_DASH
        assert not hasattr(MeterBridge, "sub_value")
