"""Tests for the spectrum pane (Signal section, C-16 idiom).

Everything runs offscreen against ``SignalViewModel`` instances — mostly
built through the real ``build_signal_view`` over the real metrics contracts
(the fakes are shared with ``tests/ui/test_signal_view.py`` — one set of
fakes, every section), so the normalization test exercises the actual
builder → widget pipeline.

What matters here, per the M2 SPECTRUM manifest:

* the five axis labels sit at TRUE log positions (the mock's even spacing
  was a shortcut — the log map is the binding intent, R-M2-7),
* curve normalization: the displayed curve's max sits at the 0 dB top and
  nothing dips below the −90 dB floor,
* silence renders the R-M2-8 copy and no curve; a later result recovers,
* the unmeasurable state (non-silent, no finite spectrum bins — pure DC)
  renders its own copy through the same label; WORKING/ERROR blank it,
* the working sweep starts/stops with effective visibility — no timer leaks,
* ``set_view`` is idempotent: a second identical call creates no duplicate
  plot items or child widgets.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("pyqtgraph")

from PySide6.QtCore import QObject

from rai_ui.plots.spectrum import (
    AXIS_TICKS,
    GRID_FRACS,
    PANE_CAPTION,
    PANE_TITLE,
    SPECTRUM_MAX_POINTS,
    Y_VIEW_BOTTOM_DB,
    Y_VIEW_TOP_DB,
    SpectrumPane,
    decimate_curve,
    log_x_fraction,
)
from rai_ui.state.signal_view import (
    EMPTY_SIGNAL_VIEW,
    SILENT_SPECTRUM_TEXT,
    SPECTRUM_FLOOR_DB,
    SPECTRUM_TOP_DB,
    UNMEASURABLE_SPECTRUM_TEXT,
    build_signal_view,
)
from rai_ui.state.verdict import VerdictKind
from tests.ui.test_signal_view import (
    CONFIDENT,
    dc_signal_result,
    make_signal_result,
    make_spectrum,
    silent_signal_result,
    state,
)

PANE_SIZE = (900, 320)

_LOG_SPAN = math.log10(20000.0) - math.log10(20.0)


def populated_vm(**signal_kw):
    """A real vm through the real builder — the exact worker-shaped payload."""
    return build_signal_view(None, make_signal_result(**signal_kw), CONFIDENT)


def silent_vm():
    return build_signal_view(None, silent_signal_result(), CONFIDENT)


def unmeasurable_vm():
    """The DC-offset defect shape: non-silent, zero finite spectrum bins."""
    return build_signal_view(None, dc_signal_result(), CONFIDENT)


@pytest.fixture
def pane(qtbot):
    widget = SpectrumPane()
    qtbot.addWidget(widget)
    widget.resize(*PANE_SIZE)
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


# ---------------------------------------------------------------------------
# Log-x map + axis labels
# ---------------------------------------------------------------------------


def test_log_x_fraction_true_positions():
    # The recon's point: even spacing is only a mock shortcut — 100 Hz sits
    # at ~23% of the log span, 1 k at ~57%, 10 k at ~90%.
    assert log_x_fraction(20.0) == pytest.approx(0.0)
    assert log_x_fraction(20000.0) == pytest.approx(1.0)
    assert log_x_fraction(100.0) == pytest.approx(math.log10(5.0) / _LOG_SPAN)
    assert log_x_fraction(1000.0) == pytest.approx(math.log10(50.0) / _LOG_SPAN)
    assert log_x_fraction(10000.0) == pytest.approx(math.log10(500.0) / _LOG_SPAN)
    assert log_x_fraction(100.0) == pytest.approx(0.233, abs=0.001)
    assert log_x_fraction(1000.0) == pytest.approx(0.566, abs=0.001)
    assert log_x_fraction(10000.0) == pytest.approx(0.900, abs=0.001)


def test_axis_labels_verbatim_units_only_at_ends():
    assert tuple(label for _f, label in AXIS_TICKS) == (
        "20 Hz",
        "100",
        "1 k",
        "10 k",
        "20 kHz",
    )
    assert tuple(freq for freq, _l in AXIS_TICKS) == (
        20.0,
        100.0,
        1000.0,
        10000.0,
        20000.0,
    )


def test_axis_row_places_ticks_at_log_positions(pane):
    for freq, _label in AXIS_TICKS:
        assert pane._axis._x_for(freq) == pytest.approx(
            log_x_fraction(freq) * pane._axis.width()
        )


def test_freq_to_x_maps_through_locked_domain(pane):
    plot_rect = pane._plot.geometry()
    for freq in (20.0, 100.0, 1000.0, 10000.0, 20000.0):
        assert pane.freq_to_x(freq) == pytest.approx(
            plot_rect.x() + log_x_fraction(freq) * plot_rect.width()
        )


# ---------------------------------------------------------------------------
# Locked window + chrome
# ---------------------------------------------------------------------------


def test_ranges_locked_and_mouse_disabled(pane):
    pane.set_view(populated_vm())
    viewbox = pane._plot.getPlotItem().getViewBox()
    (x_lo, x_hi), (y_lo, y_hi) = viewbox.viewRange()
    assert (x_lo, x_hi) == pytest.approx((math.log10(20.0), math.log10(20000.0)))
    assert (y_lo, y_hi) == pytest.approx((Y_VIEW_BOTTOM_DB, Y_VIEW_TOP_DB))
    assert viewbox.state["mouseEnabled"] == [False, False]
    assert pane._plot.getPlotItem().legend is None  # no legend widget — ever


def test_gridlines_horizontal_at_quarter_steps(pane):
    span = Y_VIEW_TOP_DB - Y_VIEW_BOTTOM_DB
    expected = [Y_VIEW_BOTTOM_DB + frac * span for frac in GRID_FRACS]
    assert sorted(line.value() for line in pane._grid_lines) == pytest.approx(expected)
    for line in pane._grid_lines:
        assert line.angle == 0  # horizontal — Signal flips the tempogram's grid


def test_label_row_copy(pane):
    assert pane._title.text() == PANE_TITLE
    assert pane._caption.text() == PANE_CAPTION


def test_curve_pen_and_fill_are_the_tokens(pane):
    pen = pane._curve.opts["pen"]
    assert pen.color().name().upper() == "#57C2D6"  # token: color.plot.data-a
    assert pen.widthF() == pytest.approx(2.0)
    assert pen.isCosmetic()
    brush = pane._curve.opts["fillBrush"]
    assert brush.color().name().upper() == "#123038"  # token: color.plot.data-a-fill
    assert pane._curve.opts["fillLevel"] == SPECTRUM_FLOOR_DB


# ---------------------------------------------------------------------------
# Curve data + normalization
# ---------------------------------------------------------------------------


def test_curve_renders_normalized_view_model(pane):
    vm = populated_vm()
    pane.set_view(vm)
    assert pane._curve.isVisible()
    x, y = pane._curve.getData()
    np.testing.assert_allclose(x, np.log10(vm.spectrum_freqs))
    np.testing.assert_allclose(y, vm.spectrum_db)


def test_curve_max_sits_at_zero_db_top(pane):
    # End-to-end through the real builder: unnormalized engine dB in,
    # max-at-0 out (R-M2-7), floor respected, peak inside the locked window.
    vm = populated_vm(spectrum=make_spectrum(lo_db=-60.0, hi_db=-30.0))
    pane.set_view(vm)
    _x, y = pane._curve.getData()
    assert float(y.max()) == pytest.approx(SPECTRUM_TOP_DB)
    assert float(y.min()) >= SPECTRUM_FLOOR_DB
    assert Y_VIEW_TOP_DB >= SPECTRUM_TOP_DB  # headroom: the peak never clips


# ---------------------------------------------------------------------------
# R-M3-15 display decimation — point ceiling, extremes contained, AA kept
# ---------------------------------------------------------------------------


def test_decimate_curve_passthrough_at_or_below_ceiling():
    x = np.linspace(0.0, 1.0, SPECTRUM_MAX_POINTS)
    y = np.sin(x * 40.0)
    got_x, got_y = decimate_curve(x, y)
    np.testing.assert_array_equal(got_x, x)
    np.testing.assert_array_equal(got_y, y)


def test_decimate_curve_caps_points_and_contains_every_extreme():
    rng = np.random.default_rng(11)
    n = 8178  # the recon-measured real-file Welch grid size
    x = np.linspace(0.0, 1.0, n)
    y = rng.uniform(-90.0, 0.0, n)
    # Plant a single-bin spike and a single-bin notch mid-curve: min/max
    # decimation exists exactly so these never vanish from the display.
    y[5000] = 3.0
    y[2222] = -120.0
    got_x, got_y = decimate_curve(x, y)
    assert got_x.size == got_y.size <= SPECTRUM_MAX_POINTS
    assert float(got_y.max()) == pytest.approx(3.0)
    assert float(got_y.min()) == pytest.approx(-120.0)
    # x endpoints exact, x monotone non-decreasing (a drawable polyline).
    assert got_x[0] == pytest.approx(x[0])
    assert got_x[-1] == pytest.approx(x[-1])
    assert np.all(np.diff(got_x) >= 0.0)
    # Every drawn y is a value the data actually contains — the decimated
    # curve never fabricates a level (minmax doctrine, decimate.py).
    assert np.isin(got_y, y).all()


def test_dense_curve_draws_capped_but_view_model_stays_full_res(pane):
    vm = populated_vm(spectrum=make_spectrum(n=8178))
    pane.set_view(vm)
    x, y = pane._curve.getData()
    assert x.size <= SPECTRUM_MAX_POINTS  # R-M3-15 ceiling on DRAWN points
    assert len(vm.spectrum_db) == 8178  # display-only: the truth is untouched
    # Normalization survives decimation: the max is an extreme, so the drawn
    # peak still kisses the 0 dB top exactly.
    assert float(y.max()) == pytest.approx(SPECTRUM_TOP_DB)
    assert float(y.min()) >= SPECTRUM_FLOOR_DB


def test_small_curve_renders_exact_data(pane):
    # Below the ceiling nothing is decimated — the existing exact-equality
    # contract (test_curve_renders_normalized_view_model) holds verbatim.
    vm = populated_vm(spectrum=make_spectrum(n=512))
    pane.set_view(vm)
    x, y = pane._curve.getData()
    np.testing.assert_allclose(x, np.log10(vm.spectrum_freqs))
    np.testing.assert_allclose(y, vm.spectrum_db)


def test_spectrum_curve_keeps_antialiasing(qtbot):
    # R-M3-15 draws the line here: the spectrum curve is DIAGONAL — item-level
    # AA-off (the waveform fix) would visibly stair-step it. The curve must
    # keep INHERITING the config option (create_app sets antialias=True,
    # app.py — bare test QApplications default it to False, so flip it for
    # the construction under test and prove the inheritance).
    import pyqtgraph as pg

    previous = pg.getConfigOption("antialias")
    pg.setConfigOptions(antialias=True)
    try:
        widget = SpectrumPane()
        qtbot.addWidget(widget)
        widget.set_view(populated_vm(spectrum=make_spectrum(n=8178)))
        assert widget._curve.opts["antialias"] is True
        assert widget._curve.curve.opts["antialias"] is True
    finally:
        pg.setConfigOptions(antialias=previous)


# ---------------------------------------------------------------------------
# Silence + empty states
# ---------------------------------------------------------------------------


def test_silence_shows_copy_and_no_curve(pane):
    vm = silent_vm()
    assert vm.silent
    pane.set_view(vm)
    assert pane._silent_label.isVisible()
    assert pane._silent_label.text() == SILENT_SPECTRUM_TEXT
    assert not pane._curve.isVisible()


def test_silence_copy_centered_on_bed(pane):
    pane.set_view(silent_vm())
    plot_rect = pane._plot.geometry()
    label = pane._silent_label
    assert label.x() == round(plot_rect.center().x() - label.width() / 2)
    assert label.y() == round(plot_rect.center().y() - label.height() / 2)


def test_empty_view_shows_bed_only(pane):
    pane.set_view(EMPTY_SIGNAL_VIEW)
    assert not pane._curve.isVisible()
    assert not pane._silent_label.isVisible()


def test_result_after_silence_recovers(pane):
    pane.set_view(silent_vm())
    pane.set_view(populated_vm())
    assert pane._curve.isVisible()
    assert not pane._silent_label.isVisible()


def test_silence_after_result_drops_curve(pane):
    pane.set_view(populated_vm())
    pane.set_view(silent_vm())
    assert not pane._curve.isVisible()
    assert pane._silent_label.isVisible()


def test_unmeasurable_shows_copy_and_no_curve(pane):
    # The DC-offset defect: pre-fix this state rendered a BLANK well. The
    # unmeasurable copy rides the same label (same neutral treatment) as the
    # R-M2-8 silent copy — the view-model owns the text.
    vm = unmeasurable_vm()
    assert vm.unmeasurable and not vm.silent
    pane.set_view(vm)
    assert pane._silent_label.isVisible()
    assert pane._silent_label.text() == UNMEASURABLE_SPECTRUM_TEXT
    assert not pane._curve.isVisible()


def test_result_after_unmeasurable_recovers(pane):
    pane.set_view(unmeasurable_vm())
    pane.set_view(populated_vm())
    assert pane._curve.isVisible()
    assert not pane._silent_label.isVisible()


@pytest.mark.parametrize("kind", [VerdictKind.WORKING, VerdictKind.ERROR])
def test_blank_kinds_hide_the_unmeasurable_copy(pane, kind):
    # WORKING/ERROR blank rule: the new state blanks like everything else —
    # a stored DC result must not leave its copy on a working/errored well.
    pane.set_view(unmeasurable_vm())
    assert pane._silent_label.isVisible()
    pane.set_view(build_signal_view(None, dc_signal_result(), state(kind)))
    assert not pane._silent_label.isVisible()
    assert not pane._curve.isVisible()


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
    widget = SpectrumPane()
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
    vm = populated_vm()
    pane.set_view(vm)
    viewbox = pane._plot.getPlotItem().getViewBox()
    items_before = len(viewbox.addedItems)
    children_before = len(pane.findChildren(QObject))

    pane.set_view(vm)
    assert len(viewbox.addedItems) == items_before
    assert len(pane.findChildren(QObject)) == children_before
    x, y = pane._curve.getData()
    np.testing.assert_allclose(y, vm.spectrum_db)


def test_view_transitions_create_no_items(pane):
    viewbox = pane._plot.getPlotItem().getViewBox()
    items_before = len(viewbox.addedItems)
    for vm in (populated_vm(), silent_vm(), EMPTY_SIGNAL_VIEW, populated_vm()):
        pane.set_view(vm)
    assert len(viewbox.addedItems) == items_before
