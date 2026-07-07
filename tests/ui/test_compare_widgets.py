"""Tests for the Compare chip row and Δ table widgets (M4, R-M4-4/7).

Chips: the C-12 hue-lock law (A cyan / B rose, chip = table column = curve),
the three B-chip states with verbatim copy, the ✕ clear affordance, the
whole-chip Browse target, the hint chip and static profile note.

Table: the fixed 6-row grid (150/120/120/90/1fr, gap 12), verbatim headers
(``Δ B−A`` — U+0394/U+2212 sign convention stated in the header), demo-string
pass-through, and above all the **never-tinted-Δ law** (C-15): no set_rows
path may restyle a value cell, whatever the delta's sign or size.

View-models come from the REAL ``build_compare_view`` on real engine
contracts. Qt-dependent — importorskip'd so the engine venv skips cleanly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from rai_ui.state.compare_view import (
    B_EMPTY_CHIP_TEXT,
    B_WORKING_CHIP_TEXT,
    HINT_CHIP_TEXT,
    PROFILE_NOTE_TEXT,
    BStatus,
    build_compare_view,
)
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BG,
    COLOR_PLOT_DATA_A,
    COLOR_PLOT_DATA_B,
    COLOR_PLOT_DATA_B_FILL,
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_CONFIDENT_BASE,
    COLOR_TEXT_PRIMARY,
)
from rai_ui.widgets.compare_chips import CLEAR_TOOLTIP, CompareChipRow
from rai_ui.widgets.compare_table import (
    COLUMN_WIDTHS,
    GRID_GAP,
    HEADERS,
    ROW_COUNT,
    CompareTable,
)
from tests.ui.test_compare_view import DEMO_A, DEMO_A_SIG, DEMO_B, DEMO_B_SIG, make_result


def _vm(status=BStatus.LOADED, b=DEMO_B, b_sig=DEMO_B_SIG):
    return build_compare_view(DEMO_A, DEMO_A_SIG, b, b_sig, status)


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------


@pytest.fixture
def row(qtbot):
    row = CompareChipRow()
    qtbot.addWidget(row)
    return row


class TestChips:
    def test_a_chip_text_and_cyan_hue(self, row):
        row.set_view(_vm())
        assert row.a_chip.text() == "A · gwmstem.wav"
        sheet = row.a_chip.styleSheet()
        assert COLOR_PLOT_DATA_A in sheet  # hue-lock law (C-12)
        assert COLOR_ACCENT_BG in sheet

    def test_b_loaded_chip_rose_with_clear_glyph(self, row):
        row.set_view(_vm())
        chip = row.b_chip
        assert chip.text_label.text() == "B · ref_commercial.wav"
        assert chip.clear_glyph.isVisibleTo(chip)
        assert chip.clear_glyph.text() == "✕"
        assert chip.clear_glyph.toolTip() == CLEAR_TOOLTIP == "Clear reference"
        sheet = chip.styleSheet()
        assert COLOR_PLOT_DATA_B in sheet
        assert COLOR_PLOT_DATA_B_FILL in sheet
        assert "dashed" not in sheet

    def test_b_empty_chip_dashed_browse_target(self, row, qtbot):
        row.set_view(_vm(status=BStatus.EMPTY, b=None, b_sig=None))
        chip = row.b_chip
        assert chip.text_label.text() == B_EMPTY_CHIP_TEXT
        assert chip.text_label.text() == "B · drop a reference WAV — or Browse…"
        assert not chip.clear_glyph.isVisibleTo(chip)
        assert "dashed" in chip.styleSheet()
        with qtbot.waitSignal(row.browse_b_requested, timeout=1000):
            qtbot.mouseClick(chip, Qt.MouseButton.LeftButton)

    def test_b_working_chip_copy_confined_to_chip(self, row):
        row.set_view(_vm(status=BStatus.WORKING, b=None, b_sig=None))
        chip = row.b_chip
        assert chip.text_label.text() == B_WORKING_CHIP_TEXT == "B · analyzing…"
        assert not chip.clear_glyph.isVisibleTo(chip)  # no cancel affordance
        assert "dashed" not in chip.styleSheet()

    def test_loaded_chip_does_not_emit_browse(self, row, qtbot):
        row.set_view(_vm())
        fired = []
        row.browse_b_requested.connect(lambda: fired.append(True))
        qtbot.mouseClick(row.b_chip, Qt.MouseButton.LeftButton)
        assert fired == []

    def test_clear_glyph_emits_clear(self, row, qtbot):
        row.set_view(_vm())
        with qtbot.waitSignal(row.clear_b_requested, timeout=1000):
            qtbot.mouseClick(row.b_chip.clear_glyph, Qt.MouseButton.LeftButton)

    def test_hint_chip_loaded_only_and_verbatim(self, row):
        row.set_view(_vm())
        assert row.hint_chip.isVisibleTo(row)
        assert row.hint_chip.text() == HINT_CHIP_TEXT == "drop a WAV to replace B"
        row.set_view(_vm(status=BStatus.EMPTY, b=None, b_sig=None))
        assert not row.hint_chip.isVisibleTo(row)
        row.set_view(_vm(status=BStatus.WORKING, b=None, b_sig=None))
        assert not row.hint_chip.isVisibleTo(row)

    def test_vs_and_profile_note_verbatim(self, row):
        row.set_view(_vm())
        assert row.vs_label.text() == "vs"
        assert row.note_label.text() == PROFILE_NOTE_TEXT == "same profile · drill 140–170"

    def test_blanked_a_chip_dashes_filename(self, row):
        """M3 blank doctrine pass-through: A WORKING/ERROR → 'A · —' while the
        B chip persists untouched (R-M4-2)."""
        row.set_view(build_compare_view(None, None, DEMO_B, DEMO_B_SIG, BStatus.LOADED))
        assert row.a_chip.text() == "A · —"
        assert row.b_chip.text_label.text() == "B · ref_commercial.wav"


# ---------------------------------------------------------------------------
# Δ table
# ---------------------------------------------------------------------------


@pytest.fixture
def table(qtbot):
    table = CompareTable()
    qtbot.addWidget(table)
    return table


class TestTable:
    def test_headers_verbatim_and_hue_locked(self, table):
        assert HEADERS == ("Metric", "A", "B", "Δ B−A", "Reading")
        assert HEADERS[3] == "Δ B−A"  # U+0394 delta, U+2212 minus
        texts = [label.text() for label in table.header_labels]
        assert texts == ["METRIC", "A", "B", "Δ B−A", "READING"]
        assert COLOR_PLOT_DATA_A in table.header_labels[1].styleSheet()
        assert COLOR_PLOT_DATA_B in table.header_labels[2].styleSheet()
        # Metric/Δ/Reading headers stay muted — Δ is NEVER hue- or
        # verdict-coded, even in its header.
        assert COLOR_PLOT_DATA_A not in table.header_labels[3].styleSheet()
        assert COLOR_PLOT_DATA_B not in table.header_labels[3].styleSheet()

    def test_fixed_six_row_grid(self, table):
        assert ROW_COUNT == 6
        for labels in (
            table.metric_labels,
            table.a_value_labels,
            table.b_value_labels,
            table.delta_labels,
            table.reading_labels,
        ):
            assert len(labels) == 6
        with pytest.raises(ValueError):
            table.set_rows(_vm().rows[:5])

    def test_grid_geometry_per_c15(self, table):
        assert COLUMN_WIDTHS == (150, 120, 120, 90)
        assert GRID_GAP == 12
        body_grid = table.metric_labels[0].parentWidget().layout()
        for col, width in enumerate(COLUMN_WIDTHS):
            assert body_grid.columnMinimumWidth(col) == width
            assert body_grid.columnStretch(col) == 0
        assert body_grid.columnStretch(4) == 1  # Reading takes 1fr
        assert body_grid.horizontalSpacing() == 12

    def test_demo_rows_render_verbatim(self, table):
        table.set_rows(_vm().rows)
        assert [label.text() for label in table.metric_labels] == [
            "Integrated",
            "Primary BPM",
            "True peak",
            "Dynamic range",
            "Sub/bass energy",
            "Stereo width",
        ]
        assert table.a_value_labels[0].text() == "−9.8 LUFS"
        assert table.b_value_labels[0].text() == "−8.4 LUFS"
        assert table.delta_labels[0].text() == "+1.4"
        assert table.reading_labels[0].text() == "B is 1.4 dB louder"
        assert table.delta_labels[1].text() == "−0.35"  # Δ B−A sign convention
        assert table.reading_labels[1].text() == "same grid — B drifts −0.2 %"

    def test_b_empty_rows_dash_b_side(self, table):
        table.set_rows(_vm(status=BStatus.EMPTY, b=None, b_sig=None).rows)
        for labels in (table.b_value_labels, table.delta_labels, table.reading_labels):
            assert all(label.text() == "—" for label in labels)
        assert table.a_value_labels[0].text() == "−9.8 LUFS"  # A stays populated

    def test_delta_never_tinted(self, table):
        """C-15 law: big deltas in BOTH directions leave every stylesheet
        byte-identical — weight 600 is the only emphasis Δ ever gets."""
        sheets_before = [label.styleSheet() for label in table.delta_labels]
        loud_b = make_result(lufs=-2.0, tp=1.2, bpm=310.0, path="/tmp/loud.wav")
        quiet_b = make_result(lufs=-40.0, tp=-30.0, bpm=70.0, path="/tmp/quiet.wav")
        table.set_rows(build_compare_view(DEMO_A, DEMO_A_SIG, loud_b, DEMO_B_SIG, BStatus.LOADED).rows)
        sheets_loud = [label.styleSheet() for label in table.delta_labels]
        table.set_rows(build_compare_view(DEMO_A, DEMO_A_SIG, quiet_b, DEMO_B_SIG, BStatus.LOADED).rows)
        sheets_quiet = [label.styleSheet() for label in table.delta_labels]
        assert sheets_before == sheets_loud == sheets_quiet
        for sheet in sheets_quiet:
            assert COLOR_TEXT_PRIMARY in sheet
            for semantic in (COLOR_SEMANTIC_CONFIDENT_BASE, COLOR_SEMANTIC_AMBIGUOUS_BASE):
                assert semantic not in sheet

    def test_delta_weight_600_values_500(self, table):
        for label in table.delta_labels:
            assert label.font().weight() == QFont.Weight.DemiBold
            assert label.font().pixelSize() == 14
        for label in table.a_value_labels + table.b_value_labels:
            assert label.font().weight() == QFont.Weight.Medium
            assert label.font().pixelSize() == 14
