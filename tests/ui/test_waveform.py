"""Tests for the waveform pane (Overview well, R-M2-9).

Everything runs offscreen against hand-built ``OverviewViewModel`` instances
(``dataclasses.replace`` over ``EMPTY_OVERVIEW_VIEW``), so the widget is
exercised in isolation from the engine — the view-model builder has its own
suite in ``test_signal_view.py``.

What matters here, per the M2 manifest:

* envelope mapping — the min/max arrays render as per-column vertical
  strokes (``connect="pairs"``) plus the midpoint spine, under the 1.2px
  #3E97AB ``PEN_WAVEFORM`` (tokens v0.1.3), in the locked 0..1 × ±1.05 frame,
* the center zero-line is always visible and paints above the envelope
  (the mock draws it second — 04:392),
* silence renders an honest flat line at zero with NO copy (R-M2-8 gives
  prose to the spectrum well only),
* the axis row shows exactly the endpoints: ``0:00`` and the view-model's
  mm:ss length,
* the working sweep starts/stops with effective visibility (shared C-17
  overlay — no timer leaks),
* ``set_view`` is idempotent and resizing is sane.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QLabel

from rai_ui.plots.waveform import (
    AMP_LIMIT,
    AXIS_START_TEXT,
    WAVEFORM_TITLE,
    WaveformPane,
    envelope_xy,
)
from rai_ui.state.formatters import EM_DASH
from rai_ui.state.signal_view import EMPTY_OVERVIEW_VIEW

PANE_SIZE = (900, 300)


# ---------------------------------------------------------------------------
# View-model builders (hand-built: this file tests the widget, not the builder)
# ---------------------------------------------------------------------------


def make_vm(mins: np.ndarray, maxs: np.ndarray, len_text: str = "3:14"):
    return dataclasses.replace(
        EMPTY_OVERVIEW_VIEW,
        has_result=True,
        wave_mins=np.asarray(mins, dtype=np.float64),
        wave_maxs=np.asarray(maxs, dtype=np.float64),
        wave_len_text=len_text,
    )


def make_audio_vm(n: int = 64) -> object:
    rng = np.random.default_rng(7)
    maxs = rng.uniform(0.1, 0.9, n)
    mins = -rng.uniform(0.1, 0.9, n)
    return make_vm(mins, maxs)


def make_silent_vm(n: int = 64) -> object:
    """A digitally silent file's envelope: minmax_decimate of zeros is zeros."""
    return make_vm(np.zeros(n), np.zeros(n), len_text="0:12")


@pytest.fixture
def pane(qtbot):
    widget = WaveformPane()
    qtbot.addWidget(widget)
    widget.resize(*PANE_SIZE)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


# ---------------------------------------------------------------------------
# Pure envelope → plot-array mapping
# ---------------------------------------------------------------------------


def test_envelope_xy_pairs_layout():
    mins = np.array([-0.5, -0.2, -0.8])
    maxs = np.array([0.4, 0.9, 0.1])
    x, xs, ys = envelope_xy(mins, maxs)
    # Bin i of n sits at i/(n-1): endpoints touch the well edges (mock 04:671).
    assert x == pytest.approx([0.0, 0.5, 1.0])
    # Each bin contributes one vertical (x, min) -> (x, max) stroke.
    assert xs == pytest.approx([0.0, 0.0, 0.5, 0.5, 1.0, 1.0])
    assert ys == pytest.approx([-0.5, 0.4, -0.2, 0.9, -0.8, 0.1])


def test_envelope_xy_single_bin_degenerates_to_origin():
    x, xs, ys = envelope_xy(np.array([-0.3]), np.array([0.3]))
    assert x == pytest.approx([0.0])
    assert xs == pytest.approx([0.0, 0.0])
    assert ys == pytest.approx([-0.3, 0.3])


# ---------------------------------------------------------------------------
# Envelope rendering
# ---------------------------------------------------------------------------


def test_envelope_items_carry_the_view_model_data(pane):
    mins = np.array([-0.5, -0.2, -0.8, -0.1])
    maxs = np.array([0.4, 0.9, 0.1, 0.2])
    pane.set_view(make_vm(mins, maxs))

    _, xs, ys = envelope_xy(mins, maxs)
    got_x, got_y = pane._envelope.getData()
    assert got_x == pytest.approx(xs)
    assert got_y == pytest.approx(ys)
    assert pane._envelope.isVisible()
    assert pane._envelope.opts["connect"] == "pairs"

    # The spine runs through the bin midpoints — inside the columns for real
    # audio, THE flat line for silence, the sample polyline for passthroughs.
    spine_x, spine_y = pane._spine.getData()
    assert spine_x == pytest.approx([0.0, 1 / 3, 2 / 3, 1.0])
    assert spine_y == pytest.approx((mins + maxs) / 2.0)
    assert pane._spine.isVisible()


def test_passthrough_envelope_spine_is_the_sample_polyline(pane):
    # minmax_decimate passthrough: len(y) <= bins -> mins == maxs == y.
    y = np.array([0.0, 0.5, -0.5, 0.25])
    pane.set_view(make_vm(y, y))
    _, spine_y = pane._spine.getData()
    assert spine_y == pytest.approx(y)


def test_waveform_pen_is_the_v013_token_at_1_2px(pane):
    pane.set_view(make_audio_vm())
    for item in (pane._envelope, pane._spine):
        pen = item.opts["pen"]
        # token: color.plot.waveform (v0.1.3) — the deliberate context dim,
        # NOT plot.data-a; width 1.2 is the approved-screen literal (04:391).
        assert pen.color().name().upper() == "#3E97AB"
        assert pen.widthF() == pytest.approx(1.2)
        assert pen.isCosmetic()


def test_ranges_locked_and_mouse_disabled(pane):
    pane.set_view(make_audio_vm())
    viewbox = pane._plot.getPlotItem().getViewBox()
    (x_lo, x_hi), (y_lo, y_hi) = viewbox.viewRange()
    assert (x_lo, x_hi) == pytest.approx((0.0, 1.0))
    # Amplitude-honest frame: full scale ±1 with the 1.05 headroom — a quiet
    # file renders small, never autoscaled into a lie.
    assert (y_lo, y_hi) == pytest.approx((-AMP_LIMIT, AMP_LIMIT))
    assert viewbox.state["mouseEnabled"] == [False, False]
    assert pane._plot.getPlotItem().legend is None  # no legend widget — ever


# ---------------------------------------------------------------------------
# Zero-line
# ---------------------------------------------------------------------------


def test_zero_line_centered_horizontal_and_always_visible(pane):
    assert pane._zero_line.isVisible()  # even with no file
    assert pane._zero_line.value() == pytest.approx(0.0)
    assert pane._zero_line.angle == 0
    # token: color.plot.grid at hairline width (04:392).
    assert pane._zero_line.pen.color().name().upper() == "#1B2129"
    assert pane._zero_line.pen.widthF() == pytest.approx(1.0)

    pane.set_view(make_audio_vm())
    assert pane._zero_line.isVisible()
    # The mock paints the zero-line AFTER the waveform path (04:391-392):
    # it must sit above the envelope so the center stays legible.
    assert pane._zero_line.zValue() > pane._envelope.zValue()


# ---------------------------------------------------------------------------
# Silence — honest flat line, no copy (R-M2-8)
# ---------------------------------------------------------------------------


def test_silence_renders_flat_line_at_zero(pane):
    pane.set_view(make_silent_vm())
    assert pane._envelope.isVisible()
    assert pane._spine.isVisible()
    _, env_y = pane._envelope.getData()
    _, spine_y = pane._spine.getData()
    assert np.all(env_y == 0.0)
    assert np.all(spine_y == 0.0)  # the mock's 'flat' path: a line on center


def test_silence_shows_no_copy_anywhere(pane):
    pane.set_view(make_silent_vm())
    # The R-M2-8 prose belongs to the spectrum well; this pane owns no copy
    # widget at all — its only QLabel is the pane title.
    labels = [w.text() for w in pane.findChildren(QLabel)]
    assert labels == [WAVEFORM_TITLE]


# ---------------------------------------------------------------------------
# Empty view + axis row
# ---------------------------------------------------------------------------


def test_empty_view_shows_bed_only(pane):
    pane.set_view(EMPTY_OVERVIEW_VIEW)
    assert not pane._envelope.isVisible()
    assert not pane._spine.isVisible()
    assert pane._zero_line.isVisible()
    assert pane._axis.length_text() == EM_DASH


def test_axis_row_shows_only_the_endpoints(pane):
    assert AXIS_START_TEXT == "0:00"
    pane.set_view(make_vm(np.zeros(8), np.ones(8), len_text="3:14"))
    assert pane._axis.length_text() == "3:14"
    pane.set_view(EMPTY_OVERVIEW_VIEW)
    assert pane._axis.length_text() == EM_DASH


def test_title_label_is_pinned_designed_type(pane):
    assert pane._title.text() == WAVEFORM_TITLE
    # setFont + type_pin pair (M1 landmine 8): the widget-level pin restates
    # the 11px/500 label style so the app QSS cannot wipe it.
    style = pane._title.styleSheet()
    assert "font-size: 11px" in style
    assert "font-weight: 500" in style
    assert pane._title.font().pixelSize() == 11


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
    widget = WaveformPane()
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
# Idempotency + resize sanity
# ---------------------------------------------------------------------------


def test_set_view_is_idempotent(pane):
    vm = make_audio_vm()
    pane.set_view(vm)
    viewbox = pane._plot.getPlotItem().getViewBox()
    items_before = len(viewbox.addedItems)
    children_before = len(pane.findChildren(QObject))

    pane.set_view(vm)
    assert len(viewbox.addedItems) == items_before
    assert len(pane.findChildren(QObject)) == children_before


def test_resize_keeps_overlay_and_axis_in_step(pane, qtbot):
    pane.set_view(make_audio_vm())
    pane.set_working(True)
    for size in ((1400, 480), (420, 160)):
        pane.resize(*size)
        qtbot.waitUntil(lambda s=size: pane.size().toTuple() == s, timeout=1000)
        inset = pane.rect().adjusted(1, 1, -1, -1)
        assert pane._overlay.geometry() == inset
        assert pane._axis.width() == pane.width() - 2  # inside the 1px inset
    pane.set_working(False)
    # And a resize while idle must not resurrect the overlay.
    pane.resize(*PANE_SIZE)
    assert not pane._overlay.isVisible()
