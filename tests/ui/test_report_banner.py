"""Tests for the Report confirmed-truth banner (M4, R-M4-11).

The banner is screen CHROME: it mounts between the Report toolbar and the
text edit, shows ONLY for a CONFIRMED · HUMAN verdict, carries the verbatim
copy, wears the confirmed-green palette — and the text edit's
copyable/exported content is BYTE-UNCHANGED by its presence (the M0 verbatim
guarantee is the whole reason the design's in-text line became chrome).

Qt-dependent — importorskip'd so the engine venv skips cleanly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from rai_ui.sections.report import ReportSection
from rai_ui.theme._tokens_gen import (
    COLOR_SEMANTIC_CONFIDENT_BG,
    COLOR_SEMANTIC_CONFIDENT_BORDER,
    COLOR_SEMANTIC_CONFIDENT_TEXT,
)
from rai_ui.widgets.report_banner import BANNER_TEXT_FMT, ReportBanner, banner_text
from tests.ui.test_compare_view import make_result


@pytest.fixture
def banner(qtbot):
    banner = ReportBanner()
    qtbot.addWidget(banner)
    return banner


class TestBannerWidget:
    def test_hidden_until_confirmed(self, banner):
        assert not banner.isVisibleTo(banner.parentWidget() or banner)
        assert banner.isHidden()
        assert banner.label.text() == ""

    def test_copy_verbatim(self, banner):
        banner.set_state(155.25)
        assert not banner.isHidden()
        assert (
            banner.label.text()
            == "✓ CONFIRMED · HUMAN — human tiebreak · 155.25 saved as ground truth"
        )
        assert banner_text(155.25) == BANNER_TEXT_FMT.format(bpm="155.25")

    def test_bpm_renders_two_decimals(self, banner):
        banner.set_state(140.0)
        assert "140.00 saved as ground truth" in banner.label.text()

    def test_none_hides_and_clears(self, banner):
        banner.set_state(155.25)
        banner.set_state(None)
        assert banner.isHidden()
        assert banner.label.text() == ""

    def test_confirmed_green_palette(self, banner):
        frame_sheet = banner.styleSheet()
        assert COLOR_SEMANTIC_CONFIDENT_BG in frame_sheet
        assert COLOR_SEMANTIC_CONFIDENT_BORDER in frame_sheet
        assert COLOR_SEMANTIC_CONFIDENT_TEXT in banner.label.styleSheet()


class TestBannerInReportSection:
    @pytest.fixture
    def section(self, qtbot):
        section = ReportSection()
        qtbot.addWidget(section)
        return section

    def test_mounts_between_toolbar_and_text_edit(self, section):
        layout = section.layout()
        banner_index = layout.indexOf(section.banner)
        text_index = layout.indexOf(section.text_edit)
        assert banner_index == 1  # toolbar layout is item 0
        assert text_index == banner_index + 1

    def test_hidden_by_default(self, section):
        assert section.banner.isHidden()

    def test_report_bytes_unchanged_by_banner(self, section):
        """The R-M4-11 pin: to_report() stays byte-verbatim in the text edit
        whatever the banner does."""
        result = make_result()
        section.set_result(result)
        before = section.text_edit.toPlainText()
        assert before == result.to_report()  # the M0 guarantee still holds

        section.banner.set_state(155.25)
        assert section.text_edit.toPlainText() == before

        section.banner.set_state(None)
        assert section.text_edit.toPlainText() == before
