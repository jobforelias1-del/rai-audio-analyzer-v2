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
    POPOVER_TITLE,
    RELEARN_MIN_CONFIRMS,
    REVERT_LINK_TEXT,
    SOURCE_PACKAGED_TEXT,
    SOURCE_USER_TEXT,
    ProfilePopover,
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
        (popover._source_label, 12),
        (popover._count_label, 12),
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
