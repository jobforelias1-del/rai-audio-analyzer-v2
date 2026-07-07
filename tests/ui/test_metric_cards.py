"""Metric-card widget tests: GaugeCard / RowsCard / TempoCard (04:352–441).

The binding contracts under test:

* Cards render their view-models VERBATIM — every string (values, captions,
  chip copy) arrives prebuilt from ``rai_ui.state.signal_view`` and the
  widget derives nothing. Real view-model paths are exercised through
  ``build_signal_view`` / ``build_overview_view`` with real engine metrics
  contracts (fakes shared with tests/ui/test_signal_view.py — one truth).
* C-06 chips: present exactly when the view carries one, hidden otherwise;
  a chip that leaves the view leaves the card (R-M2-10).
* Em-dash absence and −∞ measurement both render verbatim; the gauge is a
  clamped 0..1 fill and absence keeps the bar at 0 (the demo's "— (bar 0)").
* The Tempo card's verdict word is the ONLY tinted text (R-M2-20): tint maps
  from the view, numerals never re-color, and the ◆ before the ambiguous
  word is a DRAWN icon keyed off ``AMBIGUOUS_VERDICT_WORD`` — never a font
  glyph.
* Landmine 8 (the M1 review's HIGH defect class): every designed type size
  survives the REAL app stylesheet — asserted here under ``load_qss()``
  exactly like tests/ui/test_type_ramp.py, because offscreen widget tests
  without the QSS cannot catch a missing ``type_pin``.

Qt-dependent throughout — PySide6/pytest-qt are importorskip'd before any Qt
import so the Qt-less engine venv skips this module cleanly.
"""

import math

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QFont

from rai_ui.state.signal_view import (
    AMBIGUOUS_VERDICT_WORD,
    EMPTY_OVERVIEW_VIEW,
    EMPTY_SIGNAL_VIEW,
    ChipNote,
    GaugeCardView,
    MetricRowView,
    RowsCardView,
    TempoCardView,
    build_overview_view,
    build_signal_view,
)
from rai_ui.state.verdict import VerdictKind
from rai_ui.theme import load_qss
from rai_ui.theme._tokens_gen import (
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_CONFIDENT_BASE,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
)
from rai_ui.widgets.metric_cards import AbsenceChip, GaugeBar, GaugeCard, RowsCard, TempoCard
from tests.ui.test_signal_view import (
    CONFIDENT,
    make_signal_result,
    silent_signal_result,
    state,
)
from tests.ui.test_tempo_view import make_result

EM_DASH = "—"
NEG_INF_TEXT = "−∞"  # U+2212 minus — never the ASCII hyphen

MONO = "IBM Plex Mono"  # token: type.family.numeric
SANS = "IBM Plex Sans"  # token: type.family.ui


# ---------------------------------------------------------------------------
# Hand-built card views (widget-level edges the full builders share)
# ---------------------------------------------------------------------------


def gauge_view(
    value: str = "62 %",
    frac: float | None = 0.62,
    chip: ChipNote | None = None,
) -> GaugeCardView:
    return GaugeCardView(
        label="Stereo width",
        value_text=value,
        gauge_frac=frac,
        caption="mid/side correlation, whole file",
        chip=chip,
    )


def rows_view(chip: ChipNote | None = None) -> RowsCardView:
    return RowsCardView(
        label="Loudness",
        rows=(
            MetricRowView(label="Integrated", value_text="−9.80", unit="LUFS"),
            MetricRowView(label="True peak", value_text="−0.60", unit="dBTP"),
            MetricRowView(label="Sample peak", value_text="−1.10", unit="dBFS"),
        ),
        chip=chip,
    )


def tempo_view(
    word: str = "✓ confident",
    tint: str = COLOR_SEMANTIC_CONFIDENT_BASE,
) -> TempoCardView:
    return TempoCardView(
        primary_text="140.22",
        felt_text="70.11",
        verdict_word=word,
        verdict_tint=tint,
    )


# ---------------------------------------------------------------------------
# GaugeBar — the clamped fill
# ---------------------------------------------------------------------------


class TestGaugeBar:
    def test_fraction_passes_through_in_range(self, qtbot):
        bar = GaugeBar()
        qtbot.addWidget(bar)
        bar.set_fraction(0.62)
        assert bar.fraction() == pytest.approx(0.62)

    @pytest.mark.parametrize(
        "raw,clamped",
        [(1.7, 1.0), (-0.5, 0.0), (0.0, 0.0), (1.0, 1.0)],
    )
    def test_fraction_clamps_to_unit_interval(self, qtbot, raw, clamped):
        bar = GaugeBar()
        qtbot.addWidget(bar)
        bar.set_fraction(raw)
        assert bar.fraction() == clamped

    def test_non_finite_fraction_draws_empty(self, qtbot):
        bar = GaugeBar()
        qtbot.addWidget(bar)
        for raw in (math.nan, math.inf, -math.inf):
            bar.set_fraction(raw)
            assert bar.fraction() == 0.0


# ---------------------------------------------------------------------------
# GaugeCard
# ---------------------------------------------------------------------------


class TestGaugeCard:
    def test_renders_view_verbatim(self, qtbot):
        card = GaugeCard()
        qtbot.addWidget(card)
        card.set_view(gauge_view())
        assert card.title_label.text() == "STEREO WIDTH"  # 11px labels are uppercase
        assert card.value_label.text() == "62 %"
        assert card.caption_label.text() == "mid/side correlation, whole file"
        assert not card.gauge.isHidden()
        assert card.gauge.fraction() == pytest.approx(0.62)
        assert card.chip_label.isHidden()

    def test_card_chrome_object_name(self, qtbot):
        for card in (GaugeCard(), RowsCard(), TempoCard()):
            qtbot.addWidget(card)
            assert card.objectName() == "metricCard"  # theme QSS contract

    def test_chip_present_then_absent(self, qtbot):
        card = GaugeCard()
        qtbot.addWidget(card)
        card.set_view(gauge_view(value=EM_DASH, frac=0.0, chip=ChipNote(text="silent file")))
        assert not card.chip_label.isHidden()
        assert card.chip_label.text() == "silent file"
        # The chip leaves with the view — never sticky (R-M2-10).
        card.set_view(gauge_view())
        assert card.chip_label.isHidden()
        assert card.chip_label.text() == ""

    def test_absence_keeps_gauge_at_zero(self, qtbot):
        # The demo's silence rendering: "— (bar 0)" — bar present, empty.
        card = GaugeCard()
        qtbot.addWidget(card)
        card.set_view(gauge_view(value=EM_DASH, frac=0.0))
        assert card.value_label.text() == EM_DASH
        assert not card.gauge.isHidden()
        assert card.gauge.fraction() == 0.0

    def test_dr_shape_has_no_gauge_and_fixed_unit(self, qtbot):
        card = GaugeCard(unit="dB")
        qtbot.addWidget(card)
        card.set_view(
            GaugeCardView(
                label="Dynamic range",
                value_text="8.2",
                gauge_frac=None,
                caption="crest-based, whole file · RMS −16.4 dB",
                chip=None,
            )
        )
        assert card.gauge.isHidden()  # no gauge bar on the DR card (04:436–440)
        assert card.unit_label is not None
        assert card.unit_label.text() == "dB"
        # The design template renders the unit unconditionally — "— dB" on
        # absence included — so it never hides with the value.
        card.set_view(
            GaugeCardView(
                label="Dynamic range",
                value_text=EM_DASH,
                gauge_frac=None,
                caption="crest-based, whole file · RMS −∞",
                chip=ChipNote(text="silent file"),
            )
        )
        assert not card.unit_label.isHidden()

    def test_width_and_sub_cards_have_no_unit_label(self, qtbot):
        card = GaugeCard()
        qtbot.addWidget(card)
        assert card.unit_label is None  # "%" rides inside value_text

    def test_neg_inf_rms_is_a_measurement_in_the_caption(self, qtbot):
        # −∞ is a measurement, rendered as one (C-06) — straight through the
        # real view-model on the engine's exact silence shape.
        vm = build_signal_view(
            make_result(), silent_signal_result(), state(VerdictKind.CONFIDENT)
        )
        card = GaugeCard(unit="dB")
        qtbot.addWidget(card)
        card.set_view(vm.dr_card)
        assert card.value_label.text() == EM_DASH  # crest NaN → absence
        assert NEG_INF_TEXT in card.caption_label.text()  # RMS −∞ → measurement
        assert not card.chip_label.isHidden()
        assert card.chip_label.text() == "silent file"

    def test_empty_view_state(self, qtbot):
        card = GaugeCard()
        qtbot.addWidget(card)
        card.set_view(EMPTY_SIGNAL_VIEW.width_card)
        assert card.value_label.text() == EM_DASH
        assert card.chip_label.isHidden()  # no analysis → no chip (R-M2-10)
        assert card.gauge.fraction() == 0.0

    def test_set_view_idempotent(self, qtbot):
        card = GaugeCard()
        qtbot.addWidget(card)
        view = gauge_view()
        card.set_view(view)
        card.set_view(view)
        assert card.view() == view
        assert card.value_label.text() == "62 %"

    def test_confident_demo_values_through_real_view_model(self, qtbot):
        vm = build_signal_view(make_result(), make_signal_result(), CONFIDENT)
        width, sub, dr = GaugeCard(), GaugeCard(), GaugeCard(unit="dB")
        for card in (width, sub, dr):
            qtbot.addWidget(card)
        width.set_view(vm.width_card)
        sub.set_view(vm.sub_card)
        dr.set_view(vm.dr_card)
        # Console confident scenario (04:682) verbatim.
        assert width.value_label.text() == "62 %"
        assert sub.value_label.text() == "21 %"
        assert dr.value_label.text() == "8.2"
        assert width.gauge.fraction() == pytest.approx(0.62)
        assert sub.gauge.fraction() == pytest.approx(0.21)


# ---------------------------------------------------------------------------
# RowsCard
# ---------------------------------------------------------------------------


class TestRowsCard:
    def test_renders_rows_verbatim(self, qtbot):
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(rows_view())
        assert card.title_label.text() == "LOUDNESS"
        assert [label.text() for label in card.row_name_labels] == [
            "Integrated",
            "True peak",
            "Sample peak",
        ]
        assert [label.text() for label in card.row_value_labels] == [
            "−9.80",
            "−0.60",
            "−1.10",
        ]
        assert [
            label.text() if label is not None else None
            for label in card.row_unit_labels
        ] == ["LUFS", "dBTP", "dBFS"]

    def test_unitless_rows_have_no_unit_label(self, qtbot):
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(
            RowsCardView(
                label="Dynamics",
                rows=(
                    MetricRowView(label="Dyn range", value_text="8.2", unit="dB"),
                    MetricRowView(label="Sub/bass", value_text="21 %", unit=None),
                    MetricRowView(label="Stereo width", value_text="62 %", unit=None),
                ),
                chip=None,
            )
        )
        assert card.row_unit_labels[0] is not None
        assert card.row_unit_labels[1] is None
        assert card.row_unit_labels[2] is None

    def test_steady_state_update_reuses_rows(self, qtbot):
        # Same (label, unit) skeleton → same QLabel objects, new strings.
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(rows_view())
        before = list(card.row_value_labels)
        second = RowsCardView(
            label="Loudness",
            rows=(
                MetricRowView(label="Integrated", value_text="−12.00", unit="LUFS"),
                MetricRowView(label="True peak", value_text="−2.00", unit="dBTP"),
                MetricRowView(label="Sample peak", value_text="−2.40", unit="dBFS"),
            ),
            chip=None,
        )
        card.set_view(second)
        assert card.row_value_labels == before  # identity — no rebuild
        assert card.row_value_labels[0].text() == "−12.00"

    def test_skeleton_change_rebuilds_rows(self, qtbot):
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(rows_view())  # 3 rows
        vm = build_overview_view(make_result(), None, make_signal_result(), CONFIDENT)
        card.set_view(vm.file_card)  # 4 rows, different labels
        assert len(card.row_value_labels) == 4
        assert [label.text() for label in card.row_name_labels] == [
            "Name",
            "Length",
            "Rate",
            "Channels",
        ]

    def test_chip_present_then_absent(self, qtbot):
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(rows_view(chip=ChipNote(text="undefined below 0.4 s")))
        assert not card.chip_label.isHidden()
        assert card.chip_label.text() == "undefined below 0.4 s"
        card.set_view(rows_view())
        assert card.chip_label.isHidden()

    def test_dash_and_neg_inf_render_verbatim(self, qtbot):
        # Silence through the real view-model: −∞ measurements next to
        # chip-explained absence, one card (design recon §3).
        vm = build_overview_view(
            make_result(), None, silent_signal_result(), state(VerdictKind.CONFIDENT)
        )
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(vm.dynamics_card)
        assert card.row_value_labels[0].text() == EM_DASH  # crest: absence
        assert not card.chip_label.isHidden()
        assert card.chip_label.text() == "silent file"

    def test_empty_view_state(self, qtbot):
        card = RowsCard()
        qtbot.addWidget(card)
        card.set_view(EMPTY_OVERVIEW_VIEW.loudness_card)
        assert all(label.text() == EM_DASH for label in card.row_value_labels)
        assert card.chip_label.isHidden()


# ---------------------------------------------------------------------------
# TempoCard
# ---------------------------------------------------------------------------


class TestTempoCard:
    def test_confident_word_and_tint(self, qtbot):
        card = TempoCard()
        qtbot.addWidget(card)
        card.set_view(tempo_view())
        assert card.title_label.text() == "TEMPO"
        assert card.primary_value.text() == "140.22"
        assert card.felt_value.text() == "70.11"
        assert card.felt_caption.text() == "felt"  # lowercase caption (04:363)
        assert card.word_label.text() == "✓ confident"
        assert COLOR_SEMANTIC_CONFIDENT_BASE in card.word_label.styleSheet()
        assert card.diamond_label.isHidden()

    def test_ambiguous_gets_drawn_diamond(self, qtbot):
        card = TempoCard()
        qtbot.addWidget(card)
        card.set_view(
            tempo_view(word=AMBIGUOUS_VERDICT_WORD, tint=COLOR_SEMANTIC_AMBIGUOUS_BASE)
        )
        # The word text carries NO ◆ — the mark is a drawn icon (R-M2-20).
        assert "◆" not in card.word_label.text()
        assert card.word_label.text() == AMBIGUOUS_VERDICT_WORD
        assert COLOR_SEMANTIC_AMBIGUOUS_BASE in card.word_label.styleSheet()
        assert not card.diamond_label.isHidden()
        assert not card.diamond_label.pixmap().isNull()

    def test_diamond_leaves_with_the_ambiguous_word(self, qtbot):
        card = TempoCard()
        qtbot.addWidget(card)
        card.set_view(
            tempo_view(word=AMBIGUOUS_VERDICT_WORD, tint=COLOR_SEMANTIC_AMBIGUOUS_BASE)
        )
        card.set_view(tempo_view())
        assert card.diamond_label.isHidden()

    def test_muted_dash_fallback(self, qtbot):
        card = TempoCard()
        qtbot.addWidget(card)
        card.set_view(tempo_view(word=EM_DASH, tint=COLOR_TEXT_MUTED))
        assert card.word_label.text() == EM_DASH
        assert COLOR_TEXT_MUTED in card.word_label.styleSheet()
        assert card.diamond_label.isHidden()

    def test_numerals_never_tinted_by_verdict(self, qtbot):
        # Semantic color never tints a numeral (CL:158): the value labels'
        # stylesheets are construction state and survive every set_view.
        card = TempoCard()
        qtbot.addWidget(card)
        primary_qss = card.primary_value.styleSheet()
        felt_qss = card.felt_value.styleSheet()
        assert COLOR_TEXT_PRIMARY in primary_qss
        card.set_view(
            tempo_view(word=AMBIGUOUS_VERDICT_WORD, tint=COLOR_SEMANTIC_AMBIGUOUS_BASE)
        )
        assert card.primary_value.styleSheet() == primary_qss
        assert card.felt_value.styleSheet() == felt_qss

    def test_overview_view_model_end_to_end(self, qtbot):
        vm = build_overview_view(make_result(), None, make_signal_result(), CONFIDENT)
        card = TempoCard()
        qtbot.addWidget(card)
        card.set_view(vm.tempo_card)
        assert card.word_label.text() == "✓ confident"
        assert card.primary_value.text() == vm.tempo_card.primary_text


# ---------------------------------------------------------------------------
# Landmine 8 — designed type survives the REAL app stylesheet
# ---------------------------------------------------------------------------


@pytest.fixture
def themed_app(qapp):
    """The real theme QSS on the shared QApplication, reverted on teardown."""
    qss = load_qss()
    # Precondition: the app-wide font rule this module guards against still
    # exists (same premise check as tests/ui/test_type_ramp.py).
    assert '"IBM Plex Sans"' in qss and "font-size: 13px" in qss, (
        "theme app.qss no longer carries the app-wide QWidget font rule — "
        "re-examine whether the landmine-8 type pins are still required"
    )
    old = qapp.styleSheet()
    qapp.setStyleSheet(qss)
    yield qapp
    qapp.setStyleSheet(old)


def _polished_font(app, qtbot, widget, label) -> QFont:
    """``label.font()`` once the stylesheet has actually been resolved."""
    qtbot.addWidget(widget)
    widget.show()
    app.processEvents()
    label.ensurePolished()
    return label.font()


def _assert_type(font: QFont, family: str, px: int, weight: int) -> None:
    assert font.family() == family, f"family {font.family()!r} != {family!r}"
    assert font.pixelSize() == px, f"pixelSize {font.pixelSize()} != {px}"
    assert int(font.weight()) == weight, f"weight {int(font.weight())} != {weight}"


class TestTypeRampUnderRealTheme:
    def test_gauge_value_is_mono_30(self, themed_app, qtbot):
        card = GaugeCard()
        card.set_view(gauge_view())
        font = _polished_font(themed_app, qtbot, card, card.value_label)
        _assert_type(font, MONO, 30, 500)  # metric-m 30/500 (C-07)

    def test_gauge_card_label_is_sans_11_medium(self, themed_app, qtbot):
        card = GaugeCard()
        card.set_view(gauge_view())
        font = _polished_font(themed_app, qtbot, card, card.title_label)
        _assert_type(font, SANS, 11, 500)  # card label 11/500 uppercase
        assert font.letterSpacingType() == QFont.SpacingType.PercentageSpacing
        assert font.letterSpacing() == pytest.approx(107.0)  # 0.07em

    def test_gauge_caption_is_sans_11(self, themed_app, qtbot):
        card = GaugeCard()
        card.set_view(gauge_view())
        font = _polished_font(themed_app, qtbot, card, card.caption_label)
        _assert_type(font, SANS, 11, 400)  # caption 11px (04:428)

    def test_dr_inline_unit_is_mono_14(self, themed_app, qtbot):
        card = GaugeCard(unit="dB")
        font = _polished_font(themed_app, qtbot, card, card.unit_label)
        _assert_type(font, MONO, 14, 400)  # inline dB unit 14px (04:438)

    def test_chip_is_sans_10(self, themed_app, qtbot):
        card = GaugeCard()
        card.set_view(gauge_view(value=EM_DASH, frac=0.0, chip=ChipNote(text="silent file")))
        font = _polished_font(themed_app, qtbot, card, card.chip_label)
        # design 10.5px — floored to 10 (integer QFont pixel sizes; see
        # metric_cards module docstring).
        _assert_type(font, SANS, 10, 400)

    def test_rows_value_is_mono_16_600(self, themed_app, qtbot):
        card = RowsCard()
        card.set_view(rows_view())
        font = _polished_font(themed_app, qtbot, card, card.row_value_labels[0])
        _assert_type(font, MONO, 16, 600)  # metric row 16/600 (04:369)

    def test_rows_name_is_sans_12(self, themed_app, qtbot):
        card = RowsCard()
        card.set_view(rows_view())
        font = _polished_font(themed_app, qtbot, card, card.row_name_labels[0])
        _assert_type(font, SANS, 12, 400)  # row label 12px secondary

    def test_rows_unit_is_mono_10_500(self, themed_app, qtbot):
        card = RowsCard()
        card.set_view(rows_view())
        font = _polished_font(themed_app, qtbot, card, card.row_unit_labels[0])
        _assert_type(font, MONO, 10, 500)  # unit suffix 10/500

    def test_file_variant_values_are_mono_12_500(self, themed_app, qtbot):
        card = RowsCard(value_px=12, value_weight=QFont.Weight.Medium)
        vm = build_overview_view(make_result(), None, make_signal_result(), CONFIDENT)
        card.set_view(vm.file_card)
        font = _polished_font(themed_app, qtbot, card, card.row_value_labels[0])
        _assert_type(font, MONO, 12, 500)  # File card values 12/500 (04:382)

    def test_tempo_primary_is_mono_34_600(self, themed_app, qtbot):
        card = TempoCard()
        card.set_view(tempo_view())
        font = _polished_font(themed_app, qtbot, card, card.primary_value)
        _assert_type(font, MONO, 34, 600)  # Overview primary 34/600 (04:358)

    def test_tempo_felt_is_mono_19_500(self, themed_app, qtbot):
        card = TempoCard()
        card.set_view(tempo_view())
        font = _polished_font(themed_app, qtbot, card, card.felt_value)
        _assert_type(font, MONO, 19, 500)  # felt 19/500 (04:361)

    def test_tempo_felt_caption_is_sans_11(self, themed_app, qtbot):
        card = TempoCard()
        card.set_view(tempo_view())
        font = _polished_font(themed_app, qtbot, card, card.felt_caption)
        _assert_type(font, SANS, 11, 400)  # lowercase "felt" caption 11px

    def test_tempo_verdict_word_is_sans_12(self, themed_app, qtbot):
        card = TempoCard()
        card.set_view(tempo_view())
        font = _polished_font(themed_app, qtbot, card, card.word_label)
        _assert_type(font, SANS, 12, 400)  # verdict summary line 12px (04:365)

    def test_control_bare_default_gauge_value(self, qapp, qtbot):
        # CONTROL: the pins must not regress the unstyled case.
        old = qapp.styleSheet()
        qapp.setStyleSheet("")
        try:
            card = GaugeCard()
            card.set_view(gauge_view())
            font = _polished_font(qapp, qtbot, card, card.value_label)
            _assert_type(font, MONO, 30, 500)
        finally:
            qapp.setStyleSheet(old)


# ---------------------------------------------------------------------------
# AbsenceChip in isolation
# ---------------------------------------------------------------------------


class TestAbsenceChip:
    def test_hidden_until_noted(self, qtbot):
        chip = AbsenceChip()
        qtbot.addWidget(chip)
        assert chip.isHidden()
        chip.set_note(ChipNote(text="unavailable for this file"))
        assert not chip.isHidden()
        assert chip.text() == "unavailable for this file"
        chip.set_note(None)
        assert chip.isHidden()
        assert chip.text() == ""

    def test_pill_height_is_20(self, qtbot):
        chip = AbsenceChip()
        qtbot.addWidget(chip)
        assert chip.height() == 20  # C-06 pill h20
