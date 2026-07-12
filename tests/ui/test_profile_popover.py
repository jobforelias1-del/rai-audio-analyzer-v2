"""Tests for the profile popover (R-M3-11 — the RC-designed relearn surface).

The design has no relearn surface, so there is no mock to pin against — the
binding truths here are the R-M3-11 ruling itself (source line, confirmed
count, ≥3-gated relearn button, backup-gated revert link), the Console chrome
idiom, landmine 8 (type pins), and the architectural fence: the popover is
presentation-only and must import NO service module (the shell pushes state
in and connects the signals — Stage-3 wiring).
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt

from rai_ui.widgets.profile_popover import (
    FOOTER_TEXT,
    GATE_HINT_TEXT,
    POPOVER_DROP,
    POPOVER_GAP,
    POPOVER_TITLE,
    RELEARN_MIN_CONFIRMS,
    REVERT_LINK_TEXT,
    SOURCE_PACKAGED_TEXT,
    SOURCE_USER_TEXT,
    ProfilePopover,
    anchor_position,
    confirmed_count_line,
    relearn_label,
    source_line,
)


@pytest.fixture
def popover(qtbot):
    widget = ProfilePopover()
    qtbot.addWidget(widget)
    return widget


def set_state(widget, **overrides):
    state = {
        "profile_kind": "packaged",
        "relearned_date": None,
        "confirmed_count": 0,
        "backup_exists": False,
    }
    state.update(overrides)
    widget.set_state(**state)
    return state


# ---------------------------------------------------------------------------
# Copy helpers (pure)
# ---------------------------------------------------------------------------


def test_source_line_packaged():
    assert source_line("packaged", None) == "packaged fingerprint"
    # The date is meaningless for the packaged fingerprint — ignored.
    assert source_line("packaged", "2026-07-07") == SOURCE_PACKAGED_TEXT


def test_source_line_user_with_and_without_date():
    assert source_line("user", "2026-07-07") == "user profile · relearned 2026-07-07"
    assert source_line("user", None) == SOURCE_USER_TEXT


def test_source_line_unknown_kind_falls_back_to_packaged():
    # The line reports what the engine READS; an unknown kind renders as the
    # packaged truth rather than inventing a state.
    assert source_line("mystery", None) == SOURCE_PACKAGED_TEXT


def test_relearn_label_states_the_n():
    assert relearn_label(0) == "Relearn from 0 confirmed"
    assert relearn_label(3) == "Relearn from 3 confirmed"
    assert relearn_label(12) == "Relearn from 12 confirmed"


def test_confirmed_count_line_pluralizes():
    assert confirmed_count_line(0) == "0 confirmed truths"
    assert confirmed_count_line(1) == "1 confirmed truth"
    assert confirmed_count_line(3) == "3 confirmed truths"


# ---------------------------------------------------------------------------
# Expansion rows (M5 finding #2, thinness half — 2026-07-12)
# ---------------------------------------------------------------------------


def test_profile_row_is_the_header_chips_own_text(popover):
    # The identity row IS the chip's constant (imported, not retyped) — the
    # popover can never claim a different profile than the chip it pops from
    # — rendered in C-11's active-entry idiom: the amber marker dot + the
    # entry name (the dot identifies the profile; 05:232 makes it
    # load-bearing — "ties the chip to the band shading on the tempogram").
    from rai_ui.theme._tokens_gen import COLOR_SEMANTIC_MARKER_PRIMARY_BASE
    from rai_ui.widgets.header import GENRE_CHIP_TEXT

    row_markup = popover._profile_row.text()
    assert GENRE_CHIP_TEXT in row_markup
    assert "●" in row_markup
    assert COLOR_SEMANTIC_MARKER_PRIMARY_BASE in row_markup  # amber dot


def test_gate_hint_states_the_gate():
    assert str(RELEARN_MIN_CONFIRMS) in GATE_HINT_TEXT
    assert GATE_HINT_TEXT == "relearn unlocks at 3 confirmed truths"


def test_gate_hint_visible_only_below_the_gate(popover):
    # The disabled relearn button states its own unlock condition; once the
    # gate arms, the hint would be noise and disappears.
    popover.set_state(
        profile_kind="packaged",
        relearned_date=None,
        confirmed_count=0,
        backup_exists=False,
    )
    assert not popover._gate_hint.isHidden()
    popover.set_state(
        profile_kind="packaged",
        relearned_date=None,
        confirmed_count=RELEARN_MIN_CONFIRMS - 1,
        backup_exists=False,
    )
    assert not popover._gate_hint.isHidden()
    popover.set_state(
        profile_kind="user",
        relearned_date="2026-07-12",
        confirmed_count=RELEARN_MIN_CONFIRMS,
        backup_exists=True,
    )
    assert popover._gate_hint.isHidden()


# ---------------------------------------------------------------------------
# Rendering per state
# ---------------------------------------------------------------------------


def test_default_state_is_packaged_nothing_confirmed(popover):
    assert popover._title.text() == POPOVER_TITLE
    assert popover._source_label.text() == SOURCE_PACKAGED_TEXT
    assert popover._count_label.text() == "0 confirmed truths"
    assert popover.relearn_button.text() == "Relearn from 0 confirmed"
    assert not popover.relearn_button.isEnabled()
    assert popover._revert_link.isHidden()
    assert popover._footer.text() == FOOTER_TEXT


def test_user_profile_state_renders_all_four_elements(popover):
    set_state(
        popover,
        profile_kind="user",
        relearned_date="2026-07-07",
        confirmed_count=5,
        backup_exists=True,
    )
    assert popover._source_label.text() == "user profile · relearned 2026-07-07"
    assert popover._count_label.text() == "5 confirmed truths"
    assert popover.relearn_button.text() == "Relearn from 5 confirmed"
    assert popover.relearn_button.isEnabled()
    assert not popover._revert_link.isHidden()
    assert REVERT_LINK_TEXT in popover._revert_link.text()


@pytest.mark.parametrize(
    "count,armed", [(0, False), (1, False), (2, False), (3, True), (4, True)]
)
def test_relearn_gate_boundary(popover, count, armed):
    # R-M3-11: enabled at N >= 3, exactly.
    assert RELEARN_MIN_CONFIRMS == 3
    set_state(popover, confirmed_count=count)
    assert popover.relearn_button.isEnabled() is armed


def test_revert_link_follows_backup_existence(popover):
    set_state(popover, backup_exists=True)
    assert not popover._revert_link.isHidden()
    set_state(popover, backup_exists=False)
    assert popover._revert_link.isHidden()


def test_state_hook_reports_last_render(popover):
    state = set_state(
        popover, profile_kind="user", relearned_date=None, confirmed_count=3
    )
    assert popover.state() == state


def test_set_state_is_idempotent(popover):
    from PySide6.QtCore import QObject

    set_state(popover, confirmed_count=4, backup_exists=True)
    children_before = len(popover.findChildren(QObject))
    texts_before = (
        popover._source_label.text(),
        popover._count_label.text(),
        popover.relearn_button.text(),
    )
    set_state(popover, confirmed_count=4, backup_exists=True)
    assert len(popover.findChildren(QObject)) == children_before
    assert (
        popover._source_label.text(),
        popover._count_label.text(),
        popover.relearn_button.text(),
    ) == texts_before


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


def test_relearn_click_emits_signal_when_armed(popover, qtbot):
    set_state(popover, confirmed_count=3)
    with qtbot.waitSignal(popover.relearn_requested, timeout=1000):
        qtbot.mouseClick(popover.relearn_button, Qt.MouseButton.LeftButton)


def test_disabled_relearn_click_emits_nothing(popover, qtbot):
    set_state(popover, confirmed_count=2)
    fired = []
    popover.relearn_requested.connect(lambda: fired.append(True))
    qtbot.mouseClick(popover.relearn_button, Qt.MouseButton.LeftButton)
    assert fired == []


def test_revert_link_emits_signal(popover, qtbot):
    set_state(popover, backup_exists=True)
    with qtbot.waitSignal(popover.revert_requested, timeout=1000):
        # The repo's established link idiom (test_readout.py): linkActivated
        # is the widget's own click path for rich-text links.
        popover._revert_link.linkActivated.emit("revert")


# ---------------------------------------------------------------------------
# Chrome + type pins (landmine 8) + popup behavior
# ---------------------------------------------------------------------------


def test_console_chrome_panel_surface_hairline_border(popover):
    style = popover.styleSheet()
    assert "#12161B" in style  # token: color.surface.panel
    assert "#242B34" in style  # token: color.border.hairline
    assert "border-radius: 7px" in style


def test_popup_window_flag(popover):
    # A real popover: outside clicks dismiss it (Qt.Popup semantics).
    assert popover.windowFlags() & Qt.WindowType.Popup


def test_every_designed_label_is_type_pinned(popover):
    # M1 landmine 8: setFont alone is dead under the app QSS — every label
    # restates family/size/weight at widget-stylesheet level.
    for label, px in (
        (popover._title, 11),
        (popover._profile_row, 12),
        (popover._source_label, 12),
        (popover._count_label, 12),
        (popover._gate_hint, 11),
        (popover._revert_link, 12),
        (popover._footer, 11),
    ):
        style = label.styleSheet()
        assert f"font-size: {px}px" in style
        assert "font-family" in style
        assert label.font().pixelSize() == px
    # The button's type rides its widget QSS block at the same specificity.
    button_style = popover.relearn_button.styleSheet()
    assert "font-size: 13px" in button_style
    assert "font-weight: 600" in button_style


def test_open_at_shows_as_popup(popover, qtbot):
    from PySide6.QtCore import QPoint

    popover.open_at(QPoint(80, 60))
    qtbot.waitUntil(popover.isVisible, timeout=2000)
    assert popover.isVisible()
    popover.hide()


# ---------------------------------------------------------------------------
# Architectural fence: presentation-only, no service imports
# ---------------------------------------------------------------------------


def test_popover_imports_no_service():
    # R-M3-11 architecture: the popover emits signals; the shell owns the
    # store/relearn machinery. Assert at the AST level so a lazy in-function
    # import cannot sneak past a top-level-only check.
    import ast
    import inspect

    import rai_ui.widgets.profile_popover as module

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("rai_ui.services")
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("rai_ui.services")


# ---------------------------------------------------------------------------
# Placement math (M5 backlog item 2 — the occlusion fix)
# ---------------------------------------------------------------------------


class TestAnchorPosition:
    """Pure-math pins for anchor_position — global coords in, QPoint out.

    Scenario numbers mirror the measured defect: at 1100×720 the old anchor
    put a 300px popover at (678, 45) — 6px above the header's bottom
    hairline (y=51) and 112px deep into the rail (rail left x=866).
    """

    def test_rail_mode_dodges_the_rail(self):
        pos = anchor_position(
            chip_right_x=978,      # old x would be 978-300 = 678
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=866,       # old right edge (978) sat 112px past this
            bridge_bottom_y=None,
            min_x=8,
        )
        # Right edge stays POPOVER_GAP left of the rail…
        assert pos.x() + 300 == 866 - POPOVER_GAP
        # …and the top clears the header hairline instead of slicing it.
        assert pos.y() == 51 + POPOVER_DROP

    def test_chip_alignment_wins_when_it_already_clears_the_rail(self):
        # A chip far from the rail keeps the designed right-alignment.
        pos = anchor_position(
            chip_right_x=500,
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=866,
            bridge_bottom_y=None,
            min_x=8,
        )
        assert pos.x() == 500 - 300

    def test_bridge_mode_clears_the_strip(self):
        pos = anchor_position(
            chip_right_x=978,
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=None,      # bridge mode: no rail to dodge
            bridge_bottom_y=127,   # header 51 + 76px strip
            min_x=8,
        )
        assert pos.x() == 978 - 300  # chip alignment holds without a rail
        assert pos.y() == 127 + POPOVER_DROP

    def test_hero_mode_is_plain_chip_alignment_below_header(self):
        pos = anchor_position(
            chip_right_x=978,
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=None,
            bridge_bottom_y=None,
            min_x=8,
        )
        assert pos.x() == 978 - 300
        assert pos.y() == 51 + POPOVER_DROP

    def test_narrow_window_clamps_to_left_content_edge(self):
        pos = anchor_position(
            chip_right_x=290,      # window narrower than the popover
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=100,
            bridge_bottom_y=None,
            min_x=8,
        )
        assert pos.x() == 8  # degrade inside the window, never escape it

    def test_low_window_clamps_to_screen_bottom(self):
        # Review finding (07-12): a plain Qt.Popup gets no screen-fitting
        # from Qt — a window dragged low left the relearn button / revert /
        # footer below the screen edge and unreachable.
        pos = anchor_position(
            chip_right_x=978,
            header_bottom_y=780,   # window dragged near the screen bottom
            popover_width=300,
            rail_left_x=866,
            bridge_bottom_y=None,
            min_x=8,
            screen_bottom_y=900,
            popover_height=220,
        )
        assert pos.y() + 220 + POPOVER_DROP == 900  # bottom stays on-screen
        pos_roomy = anchor_position(
            chip_right_x=978,
            header_bottom_y=51,
            popover_width=300,
            rail_left_x=866,
            bridge_bottom_y=None,
            min_x=8,
            screen_bottom_y=900,
            popover_height=220,
        )
        assert pos_roomy.y() == 51 + POPOVER_DROP  # roomy screen: no effect
