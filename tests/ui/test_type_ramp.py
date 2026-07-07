"""Type-ramp regression under the REAL app stylesheet (M0 landmine 6).

The shipped app boots through ``create_app``, which applies the theme QSS —
and its app-wide ``QWidget { font-family: "IBM Plex Sans"; font-size: 13px }``
rule OUTRANKS any ``QLabel.setFont``. Every designed type size on the readout
surfaces (rail hero 40, felt 24, metric rows 16, bridge 28/17, verdict word)
must therefore be pinned at widget-stylesheet level (``type_pin`` — the same
convention as the header wordmark and candidate-table titles) or it silently
renders as 13px body text in the real app while passing every bare-QApplication
test.

These tests construct the widgets UNDER the real stylesheet (mirroring the
``tools/preview_shots.py`` boot: ``app.setStyleSheet(load_qss())``) and assert
that each label's ``font()`` — which reflects the stylesheet-RESOLVED font
after polish — lands on the designed family / pixel size / weight. A control
test repeats the hero assertion under the bare default so the pins are proven
harmless without the theme too.

The stylesheet is applied to the (possibly pre-existing, session-scoped)
pytest-qt QApplication and restored on teardown so no other module inherits it.

Qt-dependent — PySide6/pytest-qt are importorskip'd so the Qt-less engine
venv skips this module cleanly.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtGui import QFont

from rai_ui.theme import load_qss
from rai_ui.widgets.meter_bridge import MeterBridge
from rai_ui.widgets.metric_readout import MetricRail, group_label
from rai_ui.widgets.verdict_block import VerdictBlock

MONO = "IBM Plex Mono"  # token: type.family.numeric
SANS = "IBM Plex Sans"  # token: type.family.ui


@pytest.fixture
def themed_app(qapp):
    """The real theme QSS on the shared QApplication, reverted on teardown."""
    qss = load_qss()
    # Precondition: the threat this module guards against is still real —
    # the theme's app-wide rule forces Plex Sans 13px on every QWidget. If
    # this base rule ever leaves the theme, fail HERE (not in an assertion)
    # so the failure names the changed premise.
    assert '"IBM Plex Sans"' in qss and "font-size: 13px" in qss, (
        "theme app.qss no longer carries the app-wide QWidget font rule — "
        "re-examine whether the landmine-6 type pins are still required"
    )
    old = qapp.styleSheet()
    qapp.setStyleSheet(qss)
    yield qapp
    qapp.setStyleSheet(old)


@pytest.fixture
def bare_app(qapp):
    """Explicitly-bare QApplication (another module may have left QSS applied)."""
    old = qapp.styleSheet()
    qapp.setStyleSheet("")
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


# ---------------------------------------------------------------------------
# Under the REAL stylesheet — the landmine-6 regression proper
# ---------------------------------------------------------------------------


class TestRailRampUnderRealTheme:
    def test_primary_numeral_is_hero_mono_40(self, themed_app, qtbot):
        rail = MetricRail()
        font = _polished_font(themed_app, qtbot, rail, rail.primary_value)
        _assert_type(font, MONO, 40, 600)  # rail primary 40/600 (R2)

    def test_felt_numeral_is_mono_24(self, themed_app, qtbot):
        rail = MetricRail()
        font = _polished_font(themed_app, qtbot, rail, rail.felt_value)
        _assert_type(font, MONO, 24, 500)  # rail felt 24/500 (R2)

    def test_metric_row_value_is_mono_16(self, themed_app, qtbot):
        rail = MetricRail()
        font = _polished_font(themed_app, qtbot, rail, rail.lufs_value)
        _assert_type(font, MONO, 16, 600)  # metric row 16/600 (R2)


class TestBridgeRampUnderRealTheme:
    def test_primary_numeral_is_mono_28(self, themed_app, qtbot):
        bridge = MeterBridge()
        font = _polished_font(themed_app, qtbot, bridge, bridge.primary_value)
        _assert_type(font, MONO, 28, 600)  # bridge primary 28/600 (R2)

    def test_felt_numeral_is_mono_17(self, themed_app, qtbot):
        bridge = MeterBridge()
        font = _polished_font(themed_app, qtbot, bridge, bridge.felt_value)
        _assert_type(font, MONO, 17, 500)  # bridge felt 17/500 (R2)

    def test_verdict_word_is_mono_12(self, themed_app, qtbot):
        bridge = MeterBridge()
        font = _polished_font(themed_app, qtbot, bridge, bridge.word_label)
        _assert_type(font, MONO, 12, 600)  # bridge word 12/600


class TestVerdictWordUnderRealTheme:
    def test_rail_verdict_word_is_mono_13(self, themed_app, qtbot):
        block = VerdictBlock()
        font = _polished_font(themed_app, qtbot, block, block._word_label)
        _assert_type(font, MONO, 13, 600)  # verdict word 13/600


class TestM2CardsRampUnderRealTheme:
    """The M2 Overview/Signal designed type survives the real stylesheet.

    tests/ui/test_metric_cards.py covers every card label exhaustively; the
    entries here are the KEY sizes on the shared regression gate, per the
    integrate manifest — one per new designed scale step."""

    def _rows_view(self):
        from rai_ui.state.signal_view import MetricRowView, RowsCardView

        return RowsCardView(
            label="Loudness",
            rows=(MetricRowView(label="Integrated", value_text="−9.80", unit="LUFS"),),
            chip=None,
        )

    def test_tempo_card_primary_is_mono_34(self, themed_app, qtbot):
        from rai_ui.widgets.metric_cards import TempoCard

        card = TempoCard()
        font = _polished_font(themed_app, qtbot, card, card.primary_value)
        _assert_type(font, MONO, 34, 600)  # Overview primary 34/600 (04:358)

    def test_tempo_card_felt_is_mono_19(self, themed_app, qtbot):
        from rai_ui.widgets.metric_cards import TempoCard

        card = TempoCard()
        font = _polished_font(themed_app, qtbot, card, card.felt_value)
        _assert_type(font, MONO, 19, 500)  # Overview felt 19/500 (04:361)

    def test_gauge_card_value_is_mono_30(self, themed_app, qtbot):
        from rai_ui.widgets.metric_cards import GaugeCard

        card = GaugeCard()
        font = _polished_font(themed_app, qtbot, card, card.value_label)
        _assert_type(font, MONO, 30, 500)  # Signal metric value 30/500 (C-07 m)

    def test_rows_card_value_is_mono_16(self, themed_app, qtbot):
        from rai_ui.widgets.metric_cards import RowsCard

        card = RowsCard()
        card.set_view(self._rows_view())
        font = _polished_font(themed_app, qtbot, card, card.row_value_labels[0])
        _assert_type(font, MONO, 16, 600)  # card row value 16/600 (04:369)

    def test_file_card_value_is_mono_12(self, themed_app, qtbot):
        from rai_ui.widgets.metric_cards import RowsCard

        card = RowsCard(value_px=12, value_weight=QFont.Weight.Medium)
        card.set_view(self._rows_view())
        font = _polished_font(themed_app, qtbot, card, card.row_value_labels[0])
        _assert_type(font, MONO, 12, 500)  # File card compact value (04:382)


class TestM2PaneLabelsUnderRealTheme:
    def test_spectrum_pane_title_is_sans_11(self, themed_app, qtbot):
        from rai_ui.plots.spectrum import SpectrumPane

        pane = SpectrumPane()
        font = _polished_font(themed_app, qtbot, pane, pane._title)
        _assert_type(font, SANS, 11, 500)  # pane label 11/500 (C-16)

    def test_spectrum_pane_caption_is_sans_11(self, themed_app, qtbot):
        # "average magnitude · log frequency" — designed text (design recon
        # §7): 11px Plex Sans regular, NOT the app-wide 13px body rule.
        from rai_ui.plots.spectrum import SpectrumPane

        pane = SpectrumPane()
        font = _polished_font(themed_app, qtbot, pane, pane._caption)
        _assert_type(font, SANS, 11, 400)  # pane caption 11/400 (C-16)

    def test_spectrum_well_copy_label_is_sans_13(self, themed_app, qtbot):
        """The well's silent/unmeasurable copy label (R-M2-8 + the
        unmeasurable state) is authored copy with a designed size. Its 13px
        Plex Sans 400 coincides with the app-wide body rule TODAY, so this
        pin can't fail through landmine 6 alone — it pins the DESIGNED value
        so a future body-rule change cannot silently restyle the copy."""
        import dataclasses

        from rai_ui.plots.spectrum import SpectrumPane
        from rai_ui.state.signal_view import (
            EMPTY_SIGNAL_VIEW,
            UNMEASURABLE_SPECTRUM_TEXT,
        )

        pane = SpectrumPane()
        pane.set_view(
            dataclasses.replace(
                EMPTY_SIGNAL_VIEW,
                unmeasurable=True,
                unmeasurable_text=UNMEASURABLE_SPECTRUM_TEXT,
            )
        )
        assert pane._silent_label.isVisibleTo(pane)  # copy actually shown
        font = _polished_font(themed_app, qtbot, pane, pane._silent_label)
        _assert_type(font, SANS, 13, 400)  # well copy 13/400 (C-17 neutral)

    def test_waveform_pane_title_is_sans_11(self, themed_app, qtbot):
        from rai_ui.plots.waveform import WaveformPane

        pane = WaveformPane()
        font = _polished_font(themed_app, qtbot, pane, pane._title)
        _assert_type(font, SANS, 11, 500)  # pane label 11/500 (C-16)


class TestGroupLabelUnderRealTheme:
    def test_group_label_type_and_tracking_survive(self, themed_app, qtbot):
        """11px/500 uppercase heading keeps its 0.07em QFont tracking: the
        QSS pin overrides family/size/weight only — letter-spacing is not a
        QSS property in Qt and must ride through the resolve."""
        label = group_label("Loudness")
        font = _polished_font(themed_app, qtbot, label, label)
        _assert_type(font, SANS, 11, 500)
        assert font.letterSpacingType() == QFont.SpacingType.PercentageSpacing
        assert font.letterSpacing() == pytest.approx(107.0)  # 0.07em


# ---------------------------------------------------------------------------
# M3: tiebreak overlay + profile popover designed labels (landmine 8 —
# offscreen widget tests without the QSS cannot catch a font wipe; only this
# real-stylesheet gate proves the type_pin actually holds)
# ---------------------------------------------------------------------------


def _ambiguous_vm():
    """A real ambiguous TempoViewModel with 3 candidates for overlay.set_view."""
    from rai_analyzer.contracts import AnalysisResult, Candidate, TempoResult

    from rai_ui.state import verdict
    from rai_ui.state.tempo_view import build_tempo_view

    tempo = TempoResult(
        primary_bpm=205.15,
        felt_bpm=102.57,
        candidates=[
            Candidate(bpm=205.15, score=2.02, salience=0.98),
            Candidate(bpm=155.25, score=1.61, salience=0.76),
            Candidate(bpm=102.5, score=1.44, salience=0.61),
        ],
        ambiguous=True,
        ambiguity_reason=(
            "primary 205 is outside the drill band [140–170], yet 155 sits inside it"
        ),
    )
    result = AnalysisResult(
        path="/tmp/amb.wav", duration=8.0, sr=44100, channels=2, tempo=tempo
    )
    state = verdict.reduce(verdict.INITIAL, verdict.OpenFile(path=result.path))
    state = verdict.reduce(state, verdict.AnalysisOk(ambiguous=True))
    return build_tempo_view(result, None, state)


class TestM3TiebreakRampUnderRealTheme:
    def _overlay(self):
        from rai_ui.widgets.tiebreak import TiebreakOverlay

        overlay = TiebreakOverlay()
        overlay.set_view(_ambiguous_vm())
        return overlay

    def test_card_bpm_numeral_is_mono_30(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(themed_app, qtbot, overlay, overlay.cards[0].bpm_label)
        _assert_type(font, MONO, 30, 600)  # R-M3-18: 04/C-14's 30, not C-07's 44

    def test_title_is_sans_15(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(themed_app, qtbot, overlay, overlay.title_label)
        _assert_type(font, SANS, 15, 600)  # header title 15/600 (04:309)

    def test_reason_is_sans_12(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(themed_app, qtbot, overlay, overlay.reason_label)
        _assert_type(font, SANS, 12, 400)  # verdictReasonBase 12px (04:311)

    def test_band_tag_is_sans_11(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(themed_app, qtbot, overlay, overlay.cards[0].band_label)
        _assert_type(font, SANS, 11, 500)  # band tag 11/500 (04:319)

    def test_salience_label_is_mono_11(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(
            themed_app, qtbot, overlay, overlay.cards[0].salience_label
        )
        _assert_type(font, MONO, 11, 400)  # 'salience 0.980' mono 11 (04:321)

    def test_footer_hint_is_sans_11(self, themed_app, qtbot):
        overlay = self._overlay()
        font = _polished_font(themed_app, qtbot, overlay, overlay.hint_label)
        _assert_type(font, SANS, 11, 400)  # footer hints 11px (04:336-338)


class TestM3PopoverRampUnderRealTheme:
    def _popover(self):
        from rai_ui.widgets.profile_popover import ProfilePopover

        popover = ProfilePopover()
        popover.set_state(
            profile_kind="user",
            relearned_date="2026-07-07",
            confirmed_count=3,
            backup_exists=True,
        )
        return popover

    def test_title_is_sans_11(self, themed_app, qtbot):
        popover = self._popover()
        font = _polished_font(themed_app, qtbot, popover, popover._title)
        _assert_type(font, SANS, 11, 500)  # pane-label idiom 11/500

    def test_source_line_is_mono_12(self, themed_app, qtbot):
        popover = self._popover()
        font = _polished_font(themed_app, qtbot, popover, popover._source_label)
        _assert_type(font, MONO, 12, 400)  # measurement-ish status: mono 12

    def test_count_line_is_mono_12(self, themed_app, qtbot):
        popover = self._popover()
        font = _polished_font(themed_app, qtbot, popover, popover._count_label)
        _assert_type(font, MONO, 12, 400)

    def test_revert_link_is_sans_12(self, themed_app, qtbot):
        popover = self._popover()
        font = _polished_font(themed_app, qtbot, popover, popover._revert_link)
        _assert_type(font, SANS, 12, 400)  # inline accent-link idiom

    def test_footer_is_sans_11(self, themed_app, qtbot):
        popover = self._popover()
        font = _polished_font(themed_app, qtbot, popover, popover._footer)
        _assert_type(font, SANS, 11, 400)  # designed footer copy (04:83)


# ---------------------------------------------------------------------------
# CONTROL: bare default — the pins must not regress the unstyled case
# ---------------------------------------------------------------------------


class TestControlBareDefault:
    def test_primary_numeral_still_mono_40_without_theme(self, bare_app, qtbot):
        rail = MetricRail()
        font = _polished_font(bare_app, qtbot, rail, rail.primary_value)
        _assert_type(font, MONO, 40, 600)

    def test_tiebreak_bpm_still_mono_30_without_theme(self, bare_app, qtbot):
        from rai_ui.widgets.tiebreak import TiebreakOverlay

        overlay = TiebreakOverlay()
        overlay.set_view(_ambiguous_vm())
        font = _polished_font(bare_app, qtbot, overlay, overlay.cards[0].bpm_label)
        _assert_type(font, MONO, 30, 600)
