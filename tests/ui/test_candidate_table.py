"""Candidate table + chips tests (C-13 / C-09).

Qt-dependent — PySide6/pytest-qt are importorskip'd so the Qt-less engine
venv skips this module cleanly (R15: submodules imported directly, no
``__init__`` edits).

The chip matrix here is the widget-level face of the R1 gate: a candidate set
covering EVERY engine ``Relationship`` member flows through the real
``build_tempo_view`` → ``CandidateModel`` path, and the chip text the table
renders must equal the design's computed copy character-for-character (chip
labels come from ``rai_ui.state.formatters.relationship_chip`` — never
hand-authored, never re-derived in a widget).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSize, Qt

from rai_analyzer.contracts import (
    AnalysisResult,
    Candidate,
    Relationship,
    TempoResult,
    classify_relationship,
)
from rai_ui.state.formatters import relationship_chip
from rai_ui.state.tempo_view import (
    EMPTY_VIEW,
    CandidateRowView,
    ChipView,
    build_tempo_view,
)
from rai_ui.state.verdict import VerdictKind, VerdictState
from rai_ui.widgets.candidate_table import (
    COL_BPM,
    COL_HEAR,
    COL_RELATION,
    COL_SALIENCE,
    COL_SCORE,
    COLUMN_WIDTHS,
    HEADERS,
    HEAR_TEXT,
    ROW_GAP,
    ROW_HEIGHT,
    ROW_ROLE,
    CandidatePane,
)
from rai_ui.widgets.chips import (
    CHIP_HEIGHT,
    HUMAN_PILL_TEXT,
    HumanPill,
    RelationshipChip,
    chip_palette,
    chip_width,
    human_pill_width,
)

PRIMARY_BPM = 150.0


# ---------------------------------------------------------------------------
# Builders (engine-shaped, mirroring test_tempo_view.py)
# ---------------------------------------------------------------------------


def make_tempo(
    primary_bpm: float = PRIMARY_BPM,
    felt_bpm: float | None = None,
    extra_bpms: tuple[float, ...] = (75.0, 300.0),
    ambiguous: bool = False,
    ambiguity_reason: str | None = None,
) -> TempoResult:
    """Ranked-primary-first TempoResult (candidates[0] IS the primary)."""
    candidates = [Candidate(bpm=primary_bpm, score=1.86, salience=0.912)]
    for i, bpm in enumerate(extra_bpms):
        candidates.append(
            Candidate(bpm=bpm, score=1.5 - 0.05 * i, salience=max(0.05, 0.8 - 0.04 * i))
        )
    return TempoResult(
        primary_bpm=primary_bpm,
        felt_bpm=felt_bpm,
        candidates=candidates,
        ambiguous=ambiguous,
        ambiguity_reason=ambiguity_reason,
    )


def make_result(tempo: TempoResult | None = None) -> AnalysisResult:
    return AnalysisResult(
        path="/tmp/beat.wav",
        duration=6.0,
        sr=44100,
        channels=2,
        tempo=tempo if tempo is not None else make_tempo(),
        loudness=None,
    )


def no_tempo_result() -> AnalysisResult:
    """The resolver's exact no-tempo shape."""
    return make_result(
        TempoResult(
            primary_bpm=0.0,
            felt_bpm=None,
            candidates=[],
            ambiguous=True,
            ambiguity_reason="No tempo detected (signal too quiet or too short).",
        )
    )


CONFIDENT = VerdictState(kind=VerdictKind.CONFIDENT, path="/tmp/beat.wav")
AMBIGUOUS = VerdictState(kind=VerdictKind.AMBIGUOUS, path="/tmp/beat.wav")
CONFIRMED = VerdictState(
    kind=VerdictKind.CONFIRMED_HUMAN,
    path="/tmp/beat.wav",
    confirmed_bpm=155.25,
    prev_kind=VerdictKind.AMBIGUOUS,
)


def make_vm(
    tempo: TempoResult | None = None,
    verdict: VerdictState = CONFIDENT,
):
    return build_tempo_view(make_result(tempo), None, verdict)


@pytest.fixture
def pane(qtbot):
    widget = CandidatePane()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def shown_pane(qtbot, pane):
    pane.resize(760, 400)
    with qtbot.waitExposed(pane):
        pane.show()
    return pane


# ---------------------------------------------------------------------------
# Chip matrix — every engine Relationship member, design copy verbatim (R1)
# ---------------------------------------------------------------------------

# candidate BPM (vs primary 150.0) → (engine member, verbatim design chip).
# One row per Relationship member — all 9, asserted below.
CHIP_MATRIX = [
    (150.0, Relationship.SELF, "×1 · primary"),
    (75.0, Relationship.OCTAVE_DOWN, "½× · half-time"),
    (300.0, Relationship.OCTAVE_UP, "2× · double-time"),
    (225.0, Relationship.DOTTED_UP, "1½× · dotted"),
    (100.0, Relationship.DOTTED_DOWN, "⅔× · dotted"),
    (112.5, Relationship.FRACTIONAL, "¾× · cross"),
    (50.0, Relationship.THIRD, "⅓× · triplet"),
    (450.0, Relationship.TRIPLE, "3× · triplet"),
    (157.0, Relationship.UNRELATED, "unrelated"),
]


class TestChipMatrix:
    @pytest.fixture()
    def loaded_pane(self, pane):
        extra = tuple(bpm for bpm, _, _ in CHIP_MATRIX[1:])
        vm = make_vm(make_tempo(primary_bpm=PRIMARY_BPM, extra_bpms=extra))
        pane.set_rows(vm)
        return pane

    def test_matrix_covers_every_relationship_member(self):
        assert {member for _, member, _ in CHIP_MATRIX} == set(Relationship)
        assert len(set(Relationship)) == 9

    def test_matrix_agrees_with_engine_classifier(self):
        # SELF is an identity check in the resolver; for every other row the
        # engine's own classifier must name the member the matrix claims.
        for bpm, member, _ in CHIP_MATRIX[1:]:
            assert classify_relationship(bpm, PRIMARY_BPM) is member, bpm

    def test_rendered_chip_text_matches_design_copy_verbatim(self, loaded_pane):
        model = loaded_pane.model
        assert model.rowCount() == len(CHIP_MATRIX)
        for i, (bpm, _, expected) in enumerate(CHIP_MATRIX):
            index = model.index(i, COL_RELATION)
            assert index.data(Qt.ItemDataRole.DisplayRole) == expected, bpm
            assert index.data(ROW_ROLE).chip.text == expected, bpm

    def test_chip_text_comes_from_the_formatter(self, loaded_pane):
        # R1: the label the table shows IS relationship_chip's output.
        model = loaded_pane.model
        for i, (bpm, _, _) in enumerate(CHIP_MATRIX):
            rendered = model.index(i, COL_RELATION).data(Qt.ItemDataRole.DisplayRole)
            assert rendered == relationship_chip(bpm, PRIMARY_BPM), bpm

    def test_chip_kinds(self, loaded_pane):
        rows = [
            loaded_pane.model.index(i, 0).data(ROW_ROLE)
            for i in range(len(CHIP_MATRIX))
        ]
        assert rows[0].chip.kind == "primary"
        for row in rows[1:]:
            expected = "unrelated" if row.chip.text == "unrelated" else "related"
            assert row.chip.kind == expected, row.bpm

    def test_pane_paints_without_error(self, qtbot, loaded_pane):
        # Exercise the delegate paint path (row bg, chip, bar, hear) for the
        # full matrix — a crash or a Qt paint warning would surface here.
        loaded_pane.resize(760, 500)
        with qtbot.waitExposed(loaded_pane):
            loaded_pane.show()
        image = loaded_pane.grab().toImage()
        assert not image.isNull()


# ---------------------------------------------------------------------------
# Model — formats, order, variable row count
# ---------------------------------------------------------------------------


class TestModel:
    def test_display_columns(self, pane):
        pane.set_rows(make_vm())
        model = pane.model
        assert model.index(0, COL_BPM).data() == "150.00"
        assert model.index(0, COL_SALIENCE).data() == "0.912"
        assert model.index(0, COL_SCORE).data() == "1.86"
        assert model.index(0, COL_HEAR).data() == HEAR_TEXT
        assert HEAR_TEXT == "▶ hear"  # verbatim design copy

    def test_headers_pre_uppercased_with_blank_sections(self, pane):
        model = pane.model
        got = tuple(
            model.headerData(i, Qt.Orientation.Horizontal) for i in range(len(HEADERS))
        )
        assert got == ("BPM", "RELATION", "SALIENCE", "", "SCORE", "")

    def test_primary_row_flagged(self, pane):
        pane.set_rows(make_vm())
        assert pane.model.index(0, 0).data(ROW_ROLE).is_primary is True
        assert pane.model.index(1, 0).data(ROW_ROLE).is_primary is False

    def test_rank_order_preserved_verbatim(self, pane):
        # Rows render in the engine's ranked order — never re-sorted, even
        # when BPM values are non-monotonic.
        vm = make_vm(make_tempo(primary_bpm=140.22, extra_bpms=(70.25, 280.5, 105.0)))
        pane.set_rows(vm)
        got = [
            pane.model.index(i, 0).data(ROW_ROLE).bpm
            for i in range(pane.model.rowCount())
        ]
        assert got == [140.22, 70.25, 280.5, 105.0]

    def test_variable_row_count_no_hardcoding(self, pane):
        many = tuple(60.0 + 7.0 * i for i in range(15))  # 16 rows with primary
        pane.set_rows(make_vm(make_tempo(extra_bpms=many)))
        assert pane.model.rowCount() == 16
        pane.set_rows(make_vm(make_tempo(extra_bpms=(75.0,))))
        assert pane.model.rowCount() == 2
        pane.set_rows(EMPTY_VIEW)
        assert pane.model.rowCount() == 0

    def test_rows_not_editable(self, pane):
        pane.set_rows(make_vm())
        flags = pane.model.flags(pane.model.index(0, COL_BPM))
        assert not flags & Qt.ItemFlag.ItemIsEditable
        assert flags & Qt.ItemFlag.ItemIsSelectable


# ---------------------------------------------------------------------------
# View configuration — no sorting, single selection, geometry
# ---------------------------------------------------------------------------


class TestViewConfig:
    def test_sorting_disabled(self, pane):
        assert pane.view.isSortingEnabled() is False

    def test_single_row_selection_no_edit(self, pane):
        from PySide6.QtWidgets import QAbstractItemView

        assert (
            pane.view.selectionMode()
            is QAbstractItemView.SelectionMode.SingleSelection
        )
        assert (
            pane.view.selectionBehavior()
            is QAbstractItemView.SelectionBehavior.SelectRows
        )
        assert (
            pane.view.editTriggers()
            == QAbstractItemView.EditTrigger.NoEditTriggers
        )

    def test_row_height_is_40_plus_2_gap(self, pane):
        assert ROW_HEIGHT == 40 and ROW_GAP == 2
        assert pane.view.verticalHeader().defaultSectionSize() == 42

    def test_fixed_column_widths(self, shown_pane):
        for column, width in enumerate(COLUMN_WIDTHS):
            if width >= 0:
                assert shown_pane.view.columnWidth(column) == width, column


# ---------------------------------------------------------------------------
# Signals — hear / tiebreak
# ---------------------------------------------------------------------------


class TestSignals:
    def test_hear_click_emits_row_bpm(self, qtbot, shown_pane):
        shown_pane.set_rows(make_vm())
        view = shown_pane.view
        rect = view.visualRect(shown_pane.model.index(0, COL_HEAR))
        with qtbot.waitSignal(shown_pane.hear_requested, timeout=1000) as blocker:
            qtbot.mouseClick(
                view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
            )
        assert blocker.args == [150.0]

    def test_click_elsewhere_does_not_emit_hear(self, qtbot, shown_pane):
        shown_pane.set_rows(make_vm())
        fired = []
        shown_pane.hear_requested.connect(fired.append)
        rect = shown_pane.view.visualRect(shown_pane.model.index(0, COL_BPM))
        qtbot.mouseClick(
            shown_pane.view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center()
        )
        assert fired == []

    def test_ambiguous_shows_open_tiebreak_and_emits(self, qtbot, pane):
        pane.set_rows(make_vm(make_tempo(ambiguous=True), verdict=AMBIGUOUS))
        assert pane.tiebreak_button.isVisibleTo(pane)
        assert pane.tiebreak_button.text() == "Open tiebreak"
        assert not pane.undo_button.isVisibleTo(pane)
        with qtbot.waitSignal(pane.tiebreak_requested, timeout=1000):
            pane.tiebreak_button.click()

    def test_confirmed_shows_undo_ghost_and_emits(self, qtbot, pane):
        pane.set_rows(make_vm(verdict=CONFIRMED))
        assert pane.undo_button.isVisibleTo(pane)
        assert pane.undo_button.text() == "Undo tiebreak"
        assert not pane.tiebreak_button.isVisibleTo(pane)
        # Inert M3 seam: routed to tiebreak_requested (MainWindow toasts).
        with qtbot.waitSignal(pane.tiebreak_requested, timeout=1000):
            pane.undo_button.click()

    def test_confident_hides_both_header_actions(self, pane):
        pane.set_rows(make_vm())
        assert not pane.tiebreak_button.isVisibleTo(pane)
        assert not pane.undo_button.isVisibleTo(pane)


# ---------------------------------------------------------------------------
# Working skeleton
# ---------------------------------------------------------------------------


class TestWorkingSkeleton:
    def test_skeleton_toggles(self, pane):
        pane.set_rows(make_vm())
        assert pane._body.currentWidget() is pane.view
        pane.set_working(True)
        assert pane._body.currentWidget() is pane.skeleton
        pane.set_working(False)
        assert pane._body.currentWidget() is pane.view

    def test_rows_survive_a_working_cycle(self, pane):
        pane.set_rows(make_vm())
        before = pane.model.rowCount()
        pane.set_working(True)
        pane.set_working(False)
        assert pane.model.rowCount() == before

    def test_pulse_runs_only_while_visible_and_working(self, qtbot, shown_pane):
        shown_pane.set_rows(make_vm())
        assert shown_pane.skeleton.pulse_running is False
        shown_pane.set_working(True)
        assert shown_pane.skeleton.pulse_running is True
        shown_pane.hide()
        assert shown_pane.skeleton.pulse_running is False  # must stop when hidden
        with qtbot.waitExposed(shown_pane):
            shown_pane.show()
        assert shown_pane.skeleton.pulse_running is True
        shown_pane.set_working(False)
        assert shown_pane.skeleton.pulse_running is False

    def test_working_pane_paints_without_error(self, qtbot, shown_pane):
        shown_pane.set_working(True)
        assert not shown_pane.grab().toImage().isNull()


# ---------------------------------------------------------------------------
# Empty copy — `no candidates — {sub}`
# ---------------------------------------------------------------------------


class TestEmptyCopy:
    def test_no_file_sub(self, pane):
        pane.set_rows(EMPTY_VIEW)
        assert pane._body.currentWidget() is pane.empty_label
        assert (
            pane.empty_label.text()
            == "no candidates — drop a WAV anywhere in this window"
        )

    def test_no_tempo_sub(self, pane):
        vm = build_tempo_view(
            no_tempo_result(), None, VerdictState(kind=VerdictKind.NO_TEMPO)
        )
        pane.set_rows(vm)
        assert pane._body.currentWidget() is pane.empty_label
        assert pane.empty_label.text() == "no candidates — silent file — nothing to track"

    def test_sub_less_verdict_falls_back_to_bare_copy(self, pane):
        vm = build_tempo_view(
            no_tempo_result(), None, VerdictState(kind=VerdictKind.ERROR)
        )
        pane.set_rows(vm)
        assert pane.empty_label.text() == "no candidates"


# ---------------------------------------------------------------------------
# Chip widgets (chips.py)
# ---------------------------------------------------------------------------


class TestChipWidgets:
    def test_palette_matches_design_hexes(self):
        # C-09 verbatim: primary = amber marker pair; unrelated mutes;
        # every other relation = strong border + primary text.
        assert chip_palette("primary") == ("#E9A23F", "#F5C67F")
        assert chip_palette("related") == ("#333D49", "#E9EDF2")
        assert chip_palette("unrelated") == ("#242B34", "#7E8896")

    def test_palette_rejects_unknown_kind(self):
        with pytest.raises(KeyError):
            chip_palette("verdict")

    def test_relationship_chip_starts_empty(self, qtbot):
        chip = RelationshipChip()
        qtbot.addWidget(chip)
        assert chip.chip is None
        assert chip.sizeHint() == QSize(0, CHIP_HEIGHT)

    def test_relationship_chip_set_chip(self, qtbot):
        chip = RelationshipChip()
        qtbot.addWidget(chip)
        view = ChipView(text="½× · half-time", kind="related")
        chip.set_chip(view)
        assert chip.chip == view
        assert chip.height() == 20
        assert chip.width() == chip_width(view) > 0

    def test_relationship_chip_width_tracks_text(self, qtbot):
        chip = RelationshipChip()
        qtbot.addWidget(chip)
        chip.set_chip(ChipView(text="2× · double-time", kind="related"))
        wide = chip.width()
        chip.set_chip(ChipView(text="unrelated", kind="unrelated"))
        assert chip.width() < wide

    def test_relationship_chip_renders(self, qtbot):
        chip = RelationshipChip()
        qtbot.addWidget(chip)
        chip.set_chip(ChipView(text="×1 · primary", kind="primary"))
        with qtbot.waitExposed(chip):
            chip.show()
        assert not chip.grab().toImage().isNull()

    def test_human_pill_copy_and_geometry(self, qtbot):
        pill = HumanPill()
        qtbot.addWidget(pill)
        assert HUMAN_PILL_TEXT == "✓ HUMAN"  # verbatim design copy
        assert pill.height() == 20
        assert pill.width() == human_pill_width()
        with qtbot.waitExposed(pill):
            pill.show()
        assert not pill.grab().toImage().isNull()

    def test_confirmed_human_row_paints_pill(self, qtbot, pane):
        # M3 surface exercised now: a hand-built confirmed row must paint the
        # chip + ✓ HUMAN pair without error.
        row = CandidateRowView(
            bpm=155.25,
            bpm_text="155.25",
            salience=0.9,
            salience_text="0.900",
            score_text="1.80",
            chip=ChipView(text="×1 · primary", kind="primary"),
            is_primary=True,
            confirmed_human=True,
        )
        pane.model.set_rows((row,))
        pane.resize(760, 300)
        with qtbot.waitExposed(pane):
            pane.show()
        assert pane.model.index(0, 0).data(ROW_ROLE).confirmed_human is True
        assert not pane.grab().toImage().isNull()
