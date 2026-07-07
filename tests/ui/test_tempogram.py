"""Tests for the tempogram pane (C-16).

Everything runs offscreen against hand-built ``TempoViewModel`` instances
(``dataclasses.replace`` over ``EMPTY_VIEW``), so the widget is exercised in
isolation from the engine — the view-model builder has its own suite in
``test_tempo_view.py``.

What matters here, per the M1 manifest:

* band region bounds and immovability,
* marker lines land at their BPM and chips map data-x → widget-x through the
  locked 40–240 domain (side flip past 72% included),
* the no-tempo state renders neutrally (baseline + copy, no curve/markers),
* the working sweep animation starts/stops with effective visibility — no
  timer leaks when the pane is hidden or the overlay dismissed,
* ``set_view`` is idempotent: a second identical call creates no duplicate
  plot items or child widgets.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QObject

from rai_ui.plots.helpers import marker_label_side
from rai_ui.plots.tempogram import (
    CHIP_MARKER_GAP,
    CHIP_TOP_FELT,
    CHIP_TOP_PRIMARY,
    TempogramPane,
    _MarkerChip,
    axis_tick_label,
)
from rai_ui.state.tempo_view import (
    BPM_AXIS_MAX,
    BPM_AXIS_MIN,
    EMPTY_VIEW,
    CandidateRowView,
    ChipView,
    MarkerView,
)

PANE_SIZE = (900, 320)


# ---------------------------------------------------------------------------
# View-model builders (hand-built: this file tests the widget, not the builder)
# ---------------------------------------------------------------------------


def make_marker(bpm: float, kind: str) -> MarkerView:
    word = kind.upper()
    return MarkerView(
        bpm=bpm,
        kind=kind,
        label=f"{bpm:.2f} · {word}",
        side=marker_label_side(bpm, BPM_AXIS_MIN, BPM_AXIS_MAX),
    )


def make_candidate(bpm: float, is_primary: bool = False) -> CandidateRowView:
    return CandidateRowView(
        bpm=bpm,
        bpm_text=f"{bpm:.2f}",
        salience=0.9 if is_primary else 0.7,
        salience_text="0.900" if is_primary else "0.700",
        score_text="1.86" if is_primary else "1.50",
        chip=ChipView(text="×1 · primary" if is_primary else "½× · half-time",
                      kind="primary" if is_primary else "related"),
        is_primary=is_primary,
        confirmed_human=False,
    )


def make_curve() -> tuple[np.ndarray, np.ndarray]:
    bpms = np.linspace(BPM_AXIS_MIN, BPM_AXIS_MAX, 801)
    salience = 0.9 * np.exp(-0.5 * ((bpms - 150.0) / 6.0) ** 2)
    return bpms, salience


def make_vm(
    primary_bpm: float = 150.25,
    felt_bpm: float | None = 75.12,
    no_tempo: bool = False,
):
    bpms, salience = make_curve()
    markers: tuple[MarkerView, ...] = ()
    candidates: tuple[CandidateRowView, ...] = ()
    if not no_tempo:
        markers = (make_marker(primary_bpm, "primary"),)
        if felt_bpm is not None:
            markers += (make_marker(felt_bpm, "felt"),)
        candidates = (
            make_candidate(primary_bpm, is_primary=True),
            make_candidate(primary_bpm / 2),
        )
    return dataclasses.replace(
        EMPTY_VIEW,
        has_result=True,
        no_tempo=no_tempo,
        no_tempo_text="no periodicity — silent file — nothing to track" if no_tempo else None,
        curve_bpms=bpms,
        curve_salience=salience,
        candidates=candidates,
        markers=markers,
    )


@pytest.fixture
def pane(qtbot):
    widget = TempogramPane()
    qtbot.addWidget(widget)
    widget.resize(*PANE_SIZE)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def visible_chips(pane: TempogramPane) -> dict[str, _MarkerChip]:
    return {c.kind: c for c in pane.findChildren(_MarkerChip) if c.isVisible()}


# ---------------------------------------------------------------------------
# Band + locked window
# ---------------------------------------------------------------------------


def test_band_region_matches_view_model(pane):
    pane.set_view(make_vm())
    lo, hi = pane._band.getRegion()
    assert (lo, hi) == pytest.approx((140.0, 170.0))
    assert pane._band.movable is False


def test_band_follows_a_different_band(pane):
    vm = dataclasses.replace(make_vm(), band=(120.0, 150.0))
    pane.set_view(vm)
    assert pane._band.getRegion() == pytest.approx((120.0, 150.0))
    assert pane._band_label.text() == "BAND 120–150"


def test_ranges_locked_and_mouse_disabled(pane):
    pane.set_view(make_vm())
    viewbox = pane._plot.getPlotItem().getViewBox()
    (x_lo, x_hi), (y_lo, y_hi) = viewbox.viewRange()
    assert (x_lo, x_hi) == pytest.approx((BPM_AXIS_MIN, BPM_AXIS_MAX))
    assert (y_lo, y_hi) == pytest.approx((0.0, 1.05))
    assert viewbox.state["mouseEnabled"] == [False, False]
    assert pane._plot.getPlotItem().legend is None  # no legend widget — ever


# ---------------------------------------------------------------------------
# Markers + chips
# ---------------------------------------------------------------------------


def test_marker_lines_sit_at_their_bpm(pane):
    vm = make_vm(primary_bpm=150.25, felt_bpm=75.12)
    pane.set_view(vm)
    primary = pane._marker_lines["primary"]
    felt = pane._marker_lines["felt"]
    assert primary.isVisible() and primary.value() == pytest.approx(150.25)
    assert felt.isVisible() and felt.value() == pytest.approx(75.12)
    # Pen identity: primary solid amber, felt dashed 4-3 violet (tokens/C-08).
    assert primary.pen.color().name().upper() == "#E9A23F"
    assert felt.pen.color().name().upper() == "#A58CF2"
    assert list(felt.pen.dashPattern()) == [4.0, 3.0]


def test_felt_marker_absent_without_felt_bpm(pane):
    pane.set_view(make_vm(felt_bpm=None))
    assert pane._marker_lines["primary"].isVisible()
    assert not pane._marker_lines["felt"].isVisible()
    assert set(visible_chips(pane)) == {"primary"}


def test_chip_maps_bpm_through_locked_domain(pane):
    vm = make_vm(primary_bpm=150.25, felt_bpm=75.12)
    pane.set_view(vm)
    chips = visible_chips(pane)

    # Both below the 72% flip point → side "right": chip's left edge sits
    # CHIP_MARKER_GAP right of the marker's mapped x.
    for kind, bpm in (("primary", 150.25), ("felt", 75.12)):
        x = pane.bpm_to_x(bpm)
        assert chips[kind].x() == round(x + CHIP_MARKER_GAP)

    # The map itself is the locked linear 40–240 domain over the plot bed.
    plot_rect = pane._plot.geometry()
    frac = (150.25 - BPM_AXIS_MIN) / (BPM_AXIS_MAX - BPM_AXIS_MIN)
    assert pane.bpm_to_x(150.25) == pytest.approx(plot_rect.x() + frac * plot_rect.width())


def test_chip_flips_left_past_72_percent(pane):
    # 205.15 → (205.15−40)/200 = 82.6% of the span → side "left".
    vm = make_vm(primary_bpm=205.15, felt_bpm=102.57)
    assert vm.markers[0].side == "left"
    assert vm.markers[1].side == "right"
    pane.set_view(vm)
    chips = visible_chips(pane)

    primary_x = pane.bpm_to_x(205.15)
    chip = chips["primary"]
    assert chip.x() == round(primary_x - CHIP_MARKER_GAP - chip.width())
    assert chip.geometry().right() < primary_x  # fully on the marker's left

    felt_chip = chips["felt"]
    assert felt_chip.x() > pane.bpm_to_x(102.57)  # unflipped stays right


def test_chips_stagger_and_never_clip(pane):
    vm = make_vm(primary_bpm=239.0, felt_bpm=41.0)  # both hugging the edges
    pane.set_view(vm)
    chips = visible_chips(pane)
    assert chips["primary"].y() == CHIP_TOP_PRIMARY
    assert chips["felt"].y() == CHIP_TOP_FELT
    for chip in chips.values():
        assert chip.x() >= 0
        assert chip.geometry().right() <= pane.width()


def test_chip_labels_are_the_view_models(pane):
    vm = make_vm(primary_bpm=205.15, felt_bpm=102.57)
    pane.set_view(vm)
    chips = visible_chips(pane)
    assert chips["primary"].label() == "205.15 · PRIMARY"
    assert chips["felt"].label() == "102.57 · FELT"


# ---------------------------------------------------------------------------
# Axis row
# ---------------------------------------------------------------------------


def test_axis_tick_labels_only_last_carries_unit():
    assert axis_tick_label(40.0, is_last=False) == "40"
    assert axis_tick_label(240.0, is_last=True) == "240 BPM"


def test_axis_row_receives_candidate_ticks(pane):
    vm = make_vm(primary_bpm=150.25)
    pane.set_view(vm)
    assert pane._axis.candidate_bpms() == (150.25, 150.25 / 2)
    pane.set_view(EMPTY_VIEW)
    assert pane._axis.candidate_bpms() == ()


# ---------------------------------------------------------------------------
# No-tempo + empty states
# ---------------------------------------------------------------------------


def test_no_tempo_renders_neutral_state(pane):
    pane.set_view(make_vm(no_tempo=True))
    assert pane._no_tempo_label.isVisible()
    assert pane._no_tempo_label.text() == "no periodicity — silent file — nothing to track"
    assert pane._baseline.isVisible()
    assert pane._baseline.value() == pytest.approx(1.05 / 2)  # plot mid-height
    assert not pane._curve.isVisible()
    assert not pane._marker_lines["primary"].isVisible()
    assert visible_chips(pane) == {}


def test_empty_view_shows_bed_only(pane):
    pane.set_view(EMPTY_VIEW)
    assert not pane._no_tempo_label.isVisible()
    assert not pane._baseline.isVisible()
    assert not pane._curve.isVisible()
    assert visible_chips(pane) == {}
    # The band is a fixed property of the domain — visible even with no file.
    assert pane._band_label.isVisible()


def test_result_after_no_tempo_recovers(pane):
    pane.set_view(make_vm(no_tempo=True))
    pane.set_view(make_vm())
    assert pane._curve.isVisible()
    assert not pane._baseline.isVisible()
    assert not pane._no_tempo_label.isVisible()
    assert pane._marker_lines["primary"].isVisible()


# ---------------------------------------------------------------------------
# Working sweep — start/stop, no timer leaks
# ---------------------------------------------------------------------------


def test_working_overlay_starts_and_stops(pane):
    assert not pane.sweep_running()
    pane.set_working(True)
    assert pane._overlay.isVisible()
    assert pane.sweep_running()
    pane.set_working(False)
    assert not pane._overlay.isVisible()
    assert not pane.sweep_running()


def test_sweep_stops_when_pane_hidden(pane):
    pane.set_working(True)
    assert pane.sweep_running()
    pane.hide()  # e.g. section switch — the hide event reaches the overlay
    assert not pane.sweep_running()
    pane.show()  # still working: the sweep resumes with visibility
    assert pane.sweep_running()
    pane.set_working(False)
    pane.hide()
    assert not pane.sweep_running()


def test_working_on_hidden_pane_defers_animation(qtbot):
    widget = TempogramPane()
    qtbot.addWidget(widget)
    widget.resize(*PANE_SIZE)
    widget.set_working(True)  # pane never shown — nothing must tick
    assert not widget.sweep_running()
    with qtbot.waitExposed(widget):
        widget.show()
    assert widget.sweep_running()
    widget.set_working(False)
    assert not widget.sweep_running()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_set_view_is_idempotent(pane):
    vm = make_vm(primary_bpm=205.15, felt_bpm=102.57)
    pane.set_view(vm)
    viewbox = pane._plot.getPlotItem().getViewBox()
    items_before = len(viewbox.addedItems)
    chips_before = len(pane.findChildren(_MarkerChip))
    children_before = len(pane.findChildren(QObject))

    pane.set_view(vm)
    assert len(viewbox.addedItems) == items_before
    assert len(pane.findChildren(_MarkerChip)) == chips_before
    assert len(pane.findChildren(QObject)) == children_before

    chips = visible_chips(pane)
    assert set(chips) == {"primary", "felt"}
    assert chips["primary"].label() == "205.15 · PRIMARY"
