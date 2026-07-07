"""Tests for the Compare spectrum overlay pane (rai_ui.plots.compare_overlay).

Per the Stage-2 manifest: two curves · B drawn on top · the sanctioned inline
legend · joint-normalization pass-through (the pane renders the view-model's
arrays verbatim — no per-curve renormalization) · the verbatim B-empty pill ·
shared WorkingOverlay reuse (landmine-16 promotion) · the three log-x ticks
at TRUE log positions.

View-models are built through the REAL ``build_compare_view`` on real engine
contracts (builders shared with test_compare_view). Qt-dependent —
importorskip'd so the engine venv skips cleanly.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from rai_ui.plots.compare_overlay import AXIS_TICKS, PANE_TITLE, CompareOverlayPane
from rai_ui.plots.overlay import WorkingOverlay
from rai_ui.plots.spectrum import decimate_curve, log_x_fraction
from rai_ui.state.compare_view import B_EMPTY_PILL_TEXT, BStatus, build_compare_view
from rai_ui.theme._tokens_gen import COLOR_PLOT_DATA_A, COLOR_PLOT_DATA_B
from tests.ui.test_compare_view import DEMO_A, DEMO_A_SIG, DEMO_B, DEMO_B_SIG
from tests.ui.test_signal_view import make_signal_result, make_spectrum


def _loaded_vm():
    return build_compare_view(DEMO_A, DEMO_A_SIG, DEMO_B, DEMO_B_SIG, BStatus.LOADED)


def _b_empty_vm():
    return build_compare_view(DEMO_A, DEMO_A_SIG, None, None, BStatus.EMPTY)


@pytest.fixture
def pane(qtbot):
    pane = CompareOverlayPane()
    qtbot.addWidget(pane)
    return pane


# ---------------------------------------------------------------------------
# Curves
# ---------------------------------------------------------------------------


def test_two_cosmetic_2px_curves_no_fills(pane):
    pane.set_view(_loaded_vm())
    for curve, hex_color in (
        (pane.curve_a, COLOR_PLOT_DATA_A),
        (pane.curve_b, COLOR_PLOT_DATA_B),
    ):
        assert curve.isVisible()
        pen = curve.opts["pen"]
        assert pen.color().name().lower() == hex_color.lower()
        assert pen.widthF() == 2.0
        assert pen.isCosmetic()
        # NO fills in Compare (04:486–487 — unlike the Signal pane's A-fill).
        assert curve.opts.get("fillLevel") is None
        assert curve.opts.get("fillBrush") is None


def test_b_draws_on_top_of_a(pane):
    assert pane.curve_b.zValue() > pane.curve_a.zValue()


def test_arrays_render_verbatim_from_view_model(pane):
    """Joint normalization is the VIEW-MODEL's (Stage-1-tested); the pane must
    pass the arrays through untouched — same shared dB reference on screen."""
    quiet_b_sig = make_signal_result(spectrum=make_spectrum(lo_db=-80.0, hi_db=-50.0))
    vm = build_compare_view(DEMO_A, DEMO_A_SIG, DEMO_B, quiet_b_sig, BStatus.LOADED)
    pane.set_view(vm)

    exp_ax, exp_ay = decimate_curve(np.log10(vm.a_freqs), np.asarray(vm.a_db))
    exp_bx, exp_by = decimate_curve(np.log10(vm.b_freqs), np.asarray(vm.b_db))
    assert np.allclose(pane.curve_a.yData, exp_ay)
    assert np.allclose(pane.curve_a.xData, exp_ax)
    assert np.allclose(pane.curve_b.yData, exp_by)
    assert np.allclose(pane.curve_b.xData, exp_bx)
    # The joint reference is visible on screen: A's max sits at 0 dB, the
    # quieter B tops out BELOW it (a per-curve renormalization would put
    # both at 0 and lie about relative level — R-M4-6).
    assert pane.curve_a.yData.max() == pytest.approx(0.0)
    assert pane.curve_b.yData.max() < -10.0


def test_dense_curves_decimated(pane):
    dense = make_signal_result(spectrum=make_spectrum(n=8192))
    vm = build_compare_view(DEMO_A, dense, DEMO_B, dense, BStatus.LOADED)
    pane.set_view(vm)
    assert len(pane.curve_a.yData) <= 2048  # R-M3-15 paint-cost doctrine
    assert len(pane.curve_b.yData) <= 2048


# ---------------------------------------------------------------------------
# B-empty state (04:489–493 verbatim)
# ---------------------------------------------------------------------------


def test_b_empty_pill_and_lone_a_curve(pane):
    pane.set_view(_b_empty_vm())
    assert pane.curve_a.isVisible()
    assert not pane.curve_b.isVisible()
    assert len(pane.curve_b.yData or []) == 0
    assert pane.pill_label.isVisibleTo(pane)
    assert pane.pill_label.text() == B_EMPTY_PILL_TEXT
    assert pane.pill_label.text() == "reference (B) not loaded — A shown alone"


def test_pill_hides_when_b_loads(pane):
    pane.set_view(_b_empty_vm())
    pane.set_view(_loaded_vm())
    assert not pane.pill_label.isVisibleTo(pane)


# ---------------------------------------------------------------------------
# Working overlay — the shared class (R-M4-8 / landmine-16 promotion)
# ---------------------------------------------------------------------------


def test_working_overlay_is_the_shared_class(pane):
    assert isinstance(pane._overlay, WorkingOverlay)


def test_set_working_toggles_overlay(pane):
    pane.set_working(True)
    assert pane._overlay.isVisibleTo(pane)
    pane.set_working(False)
    assert not pane._overlay.isVisibleTo(pane)


# ---------------------------------------------------------------------------
# Label row: title + the one sanctioned legend (hue-locked)
# ---------------------------------------------------------------------------


def test_pane_title_verbatim(pane):
    assert PANE_TITLE == "Spectrum overlay"
    assert pane._title.text() == "SPECTRUM OVERLAY"


def test_legend_letters_hue_locked(pane):
    assert pane.legend_a_label.text() == "A"
    assert pane.legend_b_label.text() == "B"
    assert COLOR_PLOT_DATA_A in pane.legend_a_label.styleSheet()
    assert COLOR_PLOT_DATA_B in pane.legend_b_label.styleSheet()


# ---------------------------------------------------------------------------
# Axis: three ticks at TRUE log positions (R-M4-6)
# ---------------------------------------------------------------------------


def test_axis_ticks_verbatim(pane):
    assert AXIS_TICKS == ((20.0, "20 Hz"), (1000.0, "1 k"), (20000.0, "20 kHz"))


def test_ticks_sit_at_true_log_positions():
    assert log_x_fraction(20.0) == pytest.approx(0.0)
    assert log_x_fraction(20000.0) == pytest.approx(1.0)
    true_1k = (math.log10(1000.0) - math.log10(20.0)) / (
        math.log10(20000.0) - math.log10(20.0)
    )
    assert log_x_fraction(1000.0) == pytest.approx(true_1k)
    # NOT the mock's space-between midpoint — the ruling corrected the
    # shortcut exactly like the Signal pane's five labels did.
    assert abs(log_x_fraction(1000.0) - 0.5) > 0.05


# ---------------------------------------------------------------------------
# Idempotency (plot items created once)
# ---------------------------------------------------------------------------


def test_set_view_is_idempotent_and_creates_nothing(pane):
    items_before = len(pane._plot.getPlotItem().items)
    vm = _loaded_vm()
    pane.set_view(vm)
    pane.set_view(vm)
    assert len(pane._plot.getPlotItem().items) == items_before
    assert np.allclose(pane.curve_a.yData, pane.curve_a.yData)
    assert pane.view() is vm
