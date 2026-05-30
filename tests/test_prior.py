"""Unit tests for the soft tempo prior (rai_analyzer.evidence.prior).

The prior is stable foundation logic (it is not one of the concurrently-built
evidence terms), so these assert its mathematical shape directly: peaked at the
center, monotone decreasing away from it, floored, vectorised-consistent, and a
sane geometric-mean fit with sigma clamping.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rai_analyzer.config import PriorParams
from rai_analyzer.contracts import TermScore
from rai_analyzer.evidence.prior import (
    fit_prior,
    prior_weight,
    prior_weight_array,
    score_prior,
)


# ---------------------------------------------------------------------------
# prior_weight shape
# ---------------------------------------------------------------------------


def test_prior_weight_maximized_at_center():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    center = prior_weight(p.center_bpm, p)
    # At the center the log-normal bump is exactly 1 -> weight is the maximum.
    assert center == pytest.approx(1.0)
    for bpm in (60.0, 90.0, 120.0, 170.0, 200.0):
        assert prior_weight(bpm, p) <= center + 1e-12


def test_prior_weight_decreases_away_from_center():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    # Walk outward on both sides (in log-BPM) and confirm strict monotone decrease.
    below = [prior_weight(b, p) for b in (145.0, 130.0, 110.0, 90.0, 70.0)]
    above = [prior_weight(b, p) for b in (145.0, 160.0, 180.0, 200.0, 230.0)]
    for seq in (below, above):
        assert all(seq[i] > seq[i + 1] for i in range(len(seq) - 1))


def test_prior_weight_stays_at_or_above_floor_everywhere():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    grid = np.linspace(1.0, 400.0, 800)
    for bpm in grid:
        assert prior_weight(float(bpm), p) >= p.floor - 1e-12
    # Far away the weight asymptotes toward (but never below) the floor.
    assert prior_weight(5.0, p) == pytest.approx(p.floor, abs=2e-3)


def test_prior_weight_nonpositive_bpm_returns_floor():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    assert prior_weight(0.0, p) == pytest.approx(p.floor)
    assert prior_weight(-10.0, p) == pytest.approx(p.floor)


def test_prior_weight_symmetric_in_log_bpm():
    # Equal log-distance either side of center yields equal weight.
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    lo = p.center_bpm / 1.5
    hi = p.center_bpm * 1.5
    assert prior_weight(lo, p) == pytest.approx(prior_weight(hi, p), rel=1e-9)


# ---------------------------------------------------------------------------
# prior_weight_array vs scalar
# ---------------------------------------------------------------------------


def test_prior_weight_array_matches_scalar_elementwise():
    p = PriorParams(center_bpm=152.0, sigma=0.25, floor=0.1)
    grid = np.linspace(40.0, 240.0, 401)
    arr = prior_weight_array(grid, p)
    assert arr.shape == grid.shape
    expected = np.array([prior_weight(float(b), p) for b in grid])
    np.testing.assert_allclose(arr, expected, rtol=1e-9, atol=1e-12)


def test_prior_weight_array_floored_and_peaked():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    grid = np.linspace(20.0, 300.0, 281)
    arr = prior_weight_array(grid, p)
    assert float(np.min(arr)) >= p.floor - 1e-12
    assert float(np.max(arr)) <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# fit_prior
# ---------------------------------------------------------------------------


def test_fit_prior_center_is_geometric_mean():
    bpms = [150.0, 160.0, 140.0]
    p = fit_prior(bpms)
    geo = math.exp(np.mean(np.log(bpms)))
    assert p.center_bpm == pytest.approx(geo, rel=1e-9)


def test_fit_prior_sigma_clamped_for_tiny_sets():
    # A near-degenerate set has tiny log-std; sigma must be clamped to min_sigma.
    p = fit_prior([150.0, 151.0], min_sigma=0.18)
    assert p.sigma >= 0.18
    assert p.sigma == pytest.approx(0.18)
    # A single value -> sigma falls back to min_sigma too.
    p1 = fit_prior([150.0], min_sigma=0.18)
    assert p1.sigma == pytest.approx(0.18)


def test_fit_prior_wide_set_keeps_measured_sigma():
    # A genuinely spread set should keep its (larger) measured sigma.
    bpms = [70.0, 110.0, 150.0, 190.0, 230.0]
    p = fit_prior(bpms, min_sigma=0.05)
    measured = float(np.std(np.log(bpms)))
    assert p.sigma == pytest.approx(measured, rel=1e-9)
    assert p.sigma > 0.05


def test_fit_prior_empty_returns_valid_params():
    p = fit_prior([])
    assert isinstance(p, PriorParams)
    # Defaults intact and usable.
    assert p.center_bpm > 0
    assert p.sigma > 0
    assert 0.0 <= p.floor < 1.0
    # The returned params must produce a finite, in-range weight.
    w = prior_weight(145.0, p)
    assert math.isfinite(w) and p.floor <= w <= 1.0


def test_fit_prior_ignores_nonpositive_entries():
    # Zeros / negatives are filtered before fitting.
    p = fit_prior([0.0, -5.0, 150.0, 160.0, 140.0])
    geo = math.exp(np.mean(np.log([150.0, 160.0, 140.0])))
    assert p.center_bpm == pytest.approx(geo, rel=1e-9)


def test_fit_prior_all_invalid_returns_default():
    p = fit_prior([0.0, -1.0])
    assert isinstance(p, PriorParams)
    assert p.center_bpm > 0 and p.sigma > 0


def test_fit_prior_respects_floor_argument():
    p = fit_prior([150.0, 160.0], floor=0.2)
    assert p.floor == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# score_prior
# ---------------------------------------------------------------------------


def test_score_prior_returns_termscore_in_range():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    for bpm in (60.0, 75.0, 145.0, 150.0, 200.0):
        ts = score_prior(bpm, features=None, params=p)
        assert isinstance(ts, TermScore)
        assert 0.0 <= ts.value <= 1.0


def test_score_prior_value_tracks_prior_weight():
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    ts = score_prior(150.0, features=None, params=p)
    assert ts.value == pytest.approx(prior_weight(150.0, p))


def test_score_prior_prefers_center_over_half_time():
    # The whole point of the prior: notated (~center) beats half-time feel.
    p = PriorParams(center_bpm=145.0, sigma=0.30, floor=0.12)
    full = score_prior(150.0, features=None, params=p).value
    half = score_prior(75.0, features=None, params=p).value
    assert full > half
