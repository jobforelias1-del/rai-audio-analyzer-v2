"""Tests for pure plot math (rai_ui.plots.helpers / rai_ui.plots.decimate).

Pure Python + numpy — no Qt imports, safe for the engine CI environment.
"""

from __future__ import annotations

import numpy as np
import pytest

from rai_ui.plots.decimate import minmax_decimate
from rai_ui.plots.helpers import DEFAULT_FLIP_FRACTION, marker_label_side


# ---------------------------------------------------------------------------
# marker_label_side
# ---------------------------------------------------------------------------


def test_default_flip_fraction_value():
    assert DEFAULT_FLIP_FRACTION == 0.72


def test_label_right_in_left_region():
    assert marker_label_side(10.0, 0.0, 100.0) == "right"


def test_label_left_in_right_region():
    assert marker_label_side(95.0, 0.0, 100.0) == "left"


def test_flip_boundary_exactly_at_072():
    # 72/100 is exactly the flip fraction: the boundary itself flips left.
    assert marker_label_side(72.0, 0.0, 100.0) == "left"
    assert marker_label_side(71.99, 0.0, 100.0) == "right"


def test_flip_respects_nonzero_xmin():
    # Span 100..300; 0.72 of the span is 244.
    assert marker_label_side(244.0, 100.0, 300.0) == "left"
    assert marker_label_side(243.0, 100.0, 300.0) == "right"


def test_custom_flip_fraction():
    assert marker_label_side(50.0, 0.0, 100.0, flip_frac=0.5) == "left"
    assert marker_label_side(49.0, 0.0, 100.0, flip_frac=0.5) == "right"


def test_degenerate_range_defaults_right():
    assert marker_label_side(120.0, 100.0, 100.0) == "right"
    assert marker_label_side(120.0, 200.0, 100.0) == "right"


# ---------------------------------------------------------------------------
# minmax_decimate — shapes
# ---------------------------------------------------------------------------


def test_shapes():
    rng = np.random.default_rng(7)
    y = rng.standard_normal(10_000)
    mins, maxs = minmax_decimate(y, 64)
    assert mins.shape == (64,)
    assert maxs.shape == (64,)


def test_uneven_division_still_yields_target_bins():
    y = np.arange(1000 + 7, dtype=float)  # 1007 % 64 != 0
    mins, maxs = minmax_decimate(y, 64)
    assert mins.shape == (64,) and maxs.shape == (64,)
    assert np.all(mins <= maxs)


# ---------------------------------------------------------------------------
# minmax_decimate — extremes are preserved (the whole point)
# ---------------------------------------------------------------------------


def test_exact_division_bins():
    # Unambiguous case: 8 samples into 4 bins of 2 — any contiguous equal
    # split agrees on these values.
    y = np.array([0.0, 9.0, 1.0, 8.0, 2.0, 7.0, 3.0, 6.0])
    mins, maxs = minmax_decimate(y, 4)
    assert mins.tolist() == [0.0, 1.0, 2.0, 3.0]
    assert maxs.tolist() == [9.0, 8.0, 7.0, 6.0]


def test_global_extremes_survive():
    rng = np.random.default_rng(42)
    y = rng.standard_normal(48_000)
    mins, maxs = minmax_decimate(y, 300)
    assert maxs.max() == y.max()
    assert mins.min() == y.min()
    assert np.all(mins <= maxs)


def test_single_sample_spike_stays_visible():
    # The failure mode of stride decimation: a one-sample clip between
    # strides. Min/max decimation must keep it in exactly one bin.
    y = np.zeros(44_100)
    y[31_337] = 1.0  # a lone clip peak
    _, maxs = minmax_decimate(y, 500)
    assert maxs.max() == 1.0
    assert np.count_nonzero(maxs == 1.0) == 1


def test_monotonic_input_keeps_order():
    y = np.arange(100, dtype=float)
    mins, maxs = minmax_decimate(y, 10)
    assert np.all(np.diff(mins) > 0)
    assert np.all(np.diff(maxs) > 0)
    assert mins[0] == 0.0
    assert maxs[-1] == 99.0


# ---------------------------------------------------------------------------
# minmax_decimate — passthrough and guards
# ---------------------------------------------------------------------------


def test_passthrough_below_target():
    y = np.array([3.0, -1.0, 2.0])
    mins, maxs = minmax_decimate(y, 10)
    assert mins.tolist() == y.tolist()
    assert maxs.tolist() == y.tolist()


def test_passthrough_at_exact_target():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    mins, maxs = minmax_decimate(y, 4)
    assert mins.tolist() == y.tolist()
    assert maxs.tolist() == y.tolist()


def test_empty_input_passthrough():
    mins, maxs = minmax_decimate(np.array([]), 16)
    assert mins.shape == (0,) and maxs.shape == (0,)


def test_integer_input_becomes_float():
    y = np.array([1, 5, -3, 2], dtype=np.int16)  # PCM-style input
    mins, maxs = minmax_decimate(y, 2)
    assert np.issubdtype(mins.dtype, np.floating)
    assert mins.tolist() == [1.0, -3.0]
    assert maxs.tolist() == [5.0, 2.0]


@pytest.mark.parametrize("bad", [0, -1])
def test_nonpositive_target_bins_raises(bad):
    with pytest.raises(ValueError):
        minmax_decimate(np.zeros(8), bad)


def test_non_1d_input_raises():
    with pytest.raises(ValueError):
        minmax_decimate(np.zeros((4, 2)), 2)
