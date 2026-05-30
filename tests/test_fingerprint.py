"""Tests for the metrical-profile fingerprint evidence term.

The whole point of this term is octave disambiguation: the true notated octave
must fold drill's metrical structure into a profile that matches the genre
fingerprint better than the half-time (and double-time) fold. The strict
true > half inequality at several tempos is the headline assertion here.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rai_analyzer.config import DEFAULT_CONFIG as C
from rai_analyzer.config import FingerprintParams, TempoConfig
from rai_analyzer.contracts import BandEnvelopes, Features, TempoCurve, TermScore
from rai_analyzer.evidence.fingerprint import (
    clear_fingerprint_cache,
    fold_to_grid,
    learn_fingerprint,
    load_fingerprint,
    save_fingerprint,
    score_fingerprint,
)
from rai_analyzer.synthetic import as_signal, click_track, drill_pattern
from rai_analyzer.tempogram import build_features


# ---------------------------------------------------------------------------
# Feature-building helpers (module-scoped caches: building features is slow).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def drill_features():
    """Cache one Features per true-bpm we test, keyed by bpm."""
    cache: dict[float, Features] = {}

    def _get(bpm: float, duration: float = 24.0) -> Features:
        if bpm not in cache:
            cache[bpm] = build_features(as_signal(drill_pattern(bpm, duration=duration)), C)
        return cache[bpm]

    return _get


@pytest.fixture(scope="module")
def click_features():
    return build_features(as_signal(click_track(120.0, duration=18.0)), C)


# ---------------------------------------------------------------------------
# fold_to_grid behaviour
# ---------------------------------------------------------------------------


def test_fold_returns_normalized_profile_of_right_shape(click_features):
    profile, phase = fold_to_grid(
        click_features.bands.full, click_features.bands.times, 120.0, bins_per_bar=16
    )
    assert profile.shape == (16,)
    assert np.all(np.isfinite(profile))
    # L2-normalised (unit) profile.
    assert np.isclose(np.linalg.norm(profile), 1.0, atol=1e-9)
    # Phase offset stays within one bin.
    bin_seconds = (4 * 60.0 / 120.0) / 16
    assert 0.0 <= phase < bin_seconds + 1e-9


def test_fold_concentrates_click_energy_on_beats(click_features):
    """A 120 BPM metronome has one transient per beat -> folded energy must
    concentrate in the four beat-aligned bins (0/4/8/12 of a 16-bin bar)."""
    profile, _ = fold_to_grid(
        click_features.bands.full, click_features.bands.times, 120.0, bins_per_bar=16
    )
    energy = profile**2  # unit profile, so this sums to 1
    beat_bins = [0, 4, 8, 12]
    beat_fraction = float(energy[beat_bins].sum())
    # Nearly all energy should sit on the beats.
    assert beat_fraction > 0.9, f"only {beat_fraction:.3f} of energy on beat bins"


def test_fold_sharper_at_true_than_half(drill_features):
    """The grid should lock tighter (higher peak-to-mean) at the true tempo
    than at the smeared half-time fold for the kick band."""
    feats = drill_features(150.0)
    low = feats.bands.low
    times = feats.bands.times
    p_true, _ = fold_to_grid(low, times, 150.0)
    p_half, _ = fold_to_grid(low, times, 75.0)
    # peak-to-mean of a unit profile == max * len.
    sharp_true = p_true.max() * p_true.size
    sharp_half = p_half.max() * p_half.size
    assert sharp_true > sharp_half


def test_fold_degenerate_inputs_never_crash():
    bins = 16
    # Empty envelope.
    p, ph = fold_to_grid(np.array([]), np.array([]), 150.0, bins_per_bar=bins)
    assert p.shape == (bins,) and np.linalg.norm(p) == 0.0 and ph == 0.0
    # Silent (all-zero) envelope.
    t = np.linspace(0, 5, 200)
    p, ph = fold_to_grid(np.zeros_like(t), t, 150.0, bins_per_bar=bins)
    assert np.all(p == 0.0) and np.all(np.isfinite(p))
    # Non-positive bpm.
    p, _ = fold_to_grid(np.ones(50), np.linspace(0, 5, 50), 0.0, bins_per_bar=bins)
    assert np.all(np.isfinite(p))
    p, _ = fold_to_grid(np.ones(50), np.linspace(0, 5, 50), -100.0, bins_per_bar=bins)
    assert np.all(np.isfinite(p))
    # Single frame.
    p, _ = fold_to_grid(np.array([1.0]), np.array([0.3]), 150.0, bins_per_bar=bins)
    assert p.shape == (bins,) and np.isclose(np.linalg.norm(p), 1.0)


# ---------------------------------------------------------------------------
# The headline contract: octave disambiguation.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_true_octave_beats_half_time(drill_features, true_bpm):
    """THE disambiguation guarantee: the true notated octave matches the drill
    fingerprint strictly better than the half-time fold."""
    feats = drill_features(true_bpm)
    s_true = score_fingerprint(true_bpm, feats, C.fingerprint)
    s_half = score_fingerprint(true_bpm / 2.0, feats, C.fingerprint)
    assert s_true.value > s_half.value, (
        f"true {true_bpm} ({s_true.value:.4f}) must beat half "
        f"{true_bpm/2} ({s_half.value:.4f})"
    )


@pytest.mark.parametrize("true_bpm", [150.0, 154.0, 166.0])
def test_true_octave_beats_double_time(drill_features, true_bpm):
    """The true octave should also beat the double-time fold (aliased pattern)."""
    feats = drill_features(true_bpm)
    s_true = score_fingerprint(true_bpm, feats, C.fingerprint)
    s_double = score_fingerprint(true_bpm * 2.0, feats, C.fingerprint)
    assert s_true.value > s_double.value, (
        f"true {true_bpm} ({s_true.value:.4f}) must beat double "
        f"{true_bpm*2} ({s_double.value:.4f})"
    )


def test_spec_exact_snippet():
    """The exact self-verification snippet from the build spec."""
    feats = build_features(as_signal(drill_pattern(150.0, 24.0)), C)
    assert (
        score_fingerprint(150.0, feats, C.fingerprint).value
        > score_fingerprint(75.0, feats, C.fingerprint).value
    )


def test_disambiguation_margin_is_meaningful(drill_features):
    """Margin must be a real gap, not a coin-flip rounding artefact."""
    feats = drill_features(150.0)
    margin = (
        score_fingerprint(150.0, feats, C.fingerprint).value
        - score_fingerprint(75.0, feats, C.fingerprint).value
    )
    assert margin > 0.03, f"disambiguation margin too small: {margin:.4f}"


# ---------------------------------------------------------------------------
# score_fingerprint output contract.
# ---------------------------------------------------------------------------


def test_score_returns_valid_termscore(drill_features):
    feats = drill_features(150.0)
    score = score_fingerprint(150.0, feats, C.fingerprint)
    assert isinstance(score, TermScore)
    assert 0.0 <= score.value <= 1.0
    assert np.isfinite(score.value)
    assert "per_band" in score.detail


def test_score_detail_reports_per_band(drill_features):
    feats = drill_features(150.0)
    detail = score_fingerprint(150.0, feats, C.fingerprint).detail
    for band in C.fingerprint.bands:
        assert band in detail["per_band"]
        assert 0.0 <= detail["per_band"][band] <= 1.0


# ---------------------------------------------------------------------------
# Graceful handling of degenerate Features (zero / short / silent).
# ---------------------------------------------------------------------------


def _make_features(low, mid, high, full, times, sr=22050, hop=512, duration=None):
    bpms = np.linspace(40.0, 240.0, 10)
    z = np.zeros_like(bpms)
    curve = TempoCurve(bpms=bpms, salience=z, acf=z.copy(), dft=z.copy())
    bands = BandEnvelopes(
        sr=sr,
        hop_length=hop,
        times=np.asarray(times, dtype=np.float64),
        low=np.asarray(low, dtype=np.float64),
        mid=np.asarray(mid, dtype=np.float64),
        high=np.asarray(high, dtype=np.float64),
        full=np.asarray(full, dtype=np.float64),
    )
    if duration is None:
        duration = float(times[-1]) if len(times) else 0.0
    return Features(
        sr=sr, hop_length=hop, duration=duration, bands=bands, tempo_curve=curve, high_curve=curve
    )


def test_score_on_silent_features_is_low_but_valid():
    """Silent input -> low (zero-ish) but finite, in-range score; no crash."""
    t = np.linspace(0.0, 10.0, 430)
    z = np.zeros_like(t)
    feats = _make_features(z, z, z, z, t)
    score = score_fingerprint(150.0, feats, C.fingerprint)
    assert isinstance(score, TermScore)
    assert 0.0 <= score.value <= 1.0
    assert np.isfinite(score.value)
    assert score.value < 0.2  # silence carries essentially no fingerprint evidence


def test_score_on_empty_features_never_crashes():
    feats = _make_features([], [], [], [], [], duration=0.0)
    score = score_fingerprint(150.0, feats, C.fingerprint)
    assert isinstance(score, TermScore)
    assert 0.0 <= score.value <= 1.0
    assert np.isfinite(score.value)


def test_score_on_very_short_features_never_crashes():
    t = np.array([0.0, 0.01, 0.02])
    e = np.array([0.0, 1.0, 0.0])
    feats = _make_features(e, e, e, e, t)
    score = score_fingerprint(150.0, feats, C.fingerprint)
    assert isinstance(score, TermScore)
    assert 0.0 <= score.value <= 1.0
    assert np.isfinite(score.value)


def test_score_zero_and_negative_bpm(drill_features):
    feats = drill_features(150.0)
    for bad_bpm in (0.0, -120.0):
        score = score_fingerprint(bad_bpm, feats, C.fingerprint)
        assert isinstance(score, TermScore)
        assert 0.0 <= score.value <= 1.0
        assert np.isfinite(score.value)


# ---------------------------------------------------------------------------
# Fingerprint IO: load packaged default, save/load round-trip, caching.
# ---------------------------------------------------------------------------


def test_load_packaged_default():
    fp = load_fingerprint(None)
    for band in ("low", "mid", "high"):
        assert band in fp
        assert fp[band].shape == (16,)
        # Stored profiles are unit-normalised.
        assert np.isclose(np.linalg.norm(fp[band]), 1.0, atol=1e-6)
    assert fp["_meta"]["source"].startswith("bootstrap")


def test_save_load_round_trip(tmp_path):
    rng = np.random.default_rng(7)
    original = {
        "low": rng.random(16),
        "mid": rng.random(16),
        "high": rng.random(16),
        "_meta": {"source": "test"},
    }
    path = str(tmp_path / "fp.json")
    save_fingerprint(original, path)
    clear_fingerprint_cache()
    loaded = load_fingerprint(path)
    for band in ("low", "mid", "high"):
        # Saved normalised; compare against normalised original.
        norm_orig = original[band] / np.linalg.norm(original[band])
        np.testing.assert_allclose(loaded[band], norm_orig, atol=1e-6)
    assert loaded["_meta"]["source"] == "test"
    # On-disk profiles are L2-normalised.
    raw = json.loads((tmp_path / "fp.json").read_text())
    assert np.isclose(np.linalg.norm(raw["low"]), 1.0, atol=1e-6)


def test_load_is_cached(tmp_path):
    """A second load of the same path must not re-read disk."""
    fp = {"low": np.ones(16), "mid": np.ones(16), "high": np.ones(16)}
    path = str(tmp_path / "cached.json")
    save_fingerprint(fp, path)
    clear_fingerprint_cache()
    first = load_fingerprint(path)
    # Corrupt the file on disk; a cached load must still succeed unchanged.
    (tmp_path / "cached.json").write_text("THIS IS NOT JSON")
    second = load_fingerprint(path)
    assert second is first  # identical cached object


def test_score_uses_custom_fingerprint_path(tmp_path, drill_features):
    """params.fingerprint_path overrides the packaged default."""
    fp = {"low": np.ones(16), "mid": np.ones(16), "high": np.ones(16), "_meta": {"source": "flat"}}
    path = str(tmp_path / "flat.json")
    save_fingerprint(fp, path)
    clear_fingerprint_cache()
    feats = drill_features(150.0)
    params = FingerprintParams(fingerprint_path=path)
    score = score_fingerprint(150.0, feats, params)
    assert score.detail["fingerprint_source"] == "flat"
    assert 0.0 <= score.value <= 1.0


def test_score_with_missing_fingerprint_file_does_not_crash(tmp_path, drill_features):
    feats = drill_features(150.0)
    params = FingerprintParams(fingerprint_path=str(tmp_path / "does_not_exist.json"))
    clear_fingerprint_cache()
    score = score_fingerprint(150.0, feats, params)
    assert isinstance(score, TermScore)
    assert score.value == 0.0
    assert "error" in score.detail


# ---------------------------------------------------------------------------
# learn_fingerprint.
# ---------------------------------------------------------------------------


def test_learn_fingerprint_shapes_and_meta(drill_features):
    items = [(drill_features(bpm), bpm) for bpm in (150.0, 154.0, 166.0)]
    learned = learn_fingerprint(items, C)
    for band in C.fingerprint.bands:
        assert learned[band].shape == (16,)
        assert np.all(np.isfinite(learned[band]))
        assert np.isclose(np.linalg.norm(learned[band]), 1.0, atol=1e-6)
    assert learned["_meta"]["n_tracks"] == 3
    assert learned["_meta"]["source"] == "learned"


def test_learned_fingerprint_also_disambiguates(tmp_path, drill_features):
    """A fingerprint re-learned from folded audio must disambiguate at least as
    well as the bootstrap default — the learn->save->score loop is sound."""
    items = [(drill_features(bpm), bpm) for bpm in (150.0, 154.0, 166.0)]
    learned = learn_fingerprint(items, C)
    path = str(tmp_path / "learned_drill.json")
    save_fingerprint(learned, path)
    clear_fingerprint_cache()
    params = FingerprintParams(fingerprint_path=path)

    for true_bpm in (150.0, 154.0, 166.0):
        feats = drill_features(true_bpm)
        s_true = score_fingerprint(true_bpm, feats, params)
        s_half = score_fingerprint(true_bpm / 2.0, feats, params)
        assert s_true.value > s_half.value


def test_learn_skips_invalid_bpm(drill_features):
    items = [
        (drill_features(150.0), 150.0),
        (drill_features(154.0), 0.0),  # skipped
        (drill_features(166.0), None),  # skipped
    ]
    learned = learn_fingerprint(items, C)
    assert learned["_meta"]["n_tracks"] == 1


# ---------------------------------------------------------------------------
# Reset shared disk cache so test order can't leak a custom fingerprint into
# the packaged-default tests.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cache_after_each_test():
    yield
    clear_fingerprint_cache()
