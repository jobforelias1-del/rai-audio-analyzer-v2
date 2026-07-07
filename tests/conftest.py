"""Shared pytest fixtures for the RAI Audio Analyzer test suite.

Owned by the foundation so no individual test module has to re-derive these.
Building features is the expensive step, so the feature fixtures are
session-scoped and cached.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.io_audio import AudioSignal
from rai_analyzer.synthetic import as_signal, click_track, drill_pattern, write_wav
from rai_analyzer.tempogram import build_features

# --- R-M3-2 tripwire (root/engine mirror of tests/ui/conftest.py's) ---------
# The real per-user store dir, computed independently of
# rai_ui.services.ground_truth_store (whose factory tests monkeypatch), so
# the tripwire cannot be fooled by the very redirection it polices.
_REAL_APP_SUPPORT = os.path.expanduser(
    os.path.join("~", "Library", "Application Support", "RAI Audio Analyzer")
)


@pytest.fixture(autouse=True, scope="session")
def _real_app_support_tripwire_root():
    """Fail the session if any test CREATED the real App Support dir.

    Writing the user's real ground-truth store from a test is branded a hard
    defect (R-M3-2); before this fixture the defense was pure convention
    (every harness monkeypatching one ``_store_dir`` symbol) with zero
    detectors. Read-only stats only — if the dir legitimately pre-exists
    (the shipped app has been used on this machine), existence cannot detect
    contamination and the fixture stays silent instead of false-positiving.
    """
    existed_before = os.path.exists(_REAL_APP_SUPPORT)
    yield
    if not existed_before:
        assert not os.path.exists(_REAL_APP_SUPPORT), (
            "HARD DEFECT (R-M3-2): this test run CREATED the user's real "
            f"ground-truth store at {_REAL_APP_SUPPORT!r} — some code path "
            "resolved the store location without the injectable "
            "ground_truth_store._store_dir factory."
        )


@pytest.fixture(scope="session")
def cfg():
    return DEFAULT_CONFIG


@pytest.fixture
def make_drill():
    """Factory: make_drill(bpm, duration=24) -> AudioSignal of a synthetic drill beat."""

    def _make(bpm: float, duration: float = 24.0, **kw) -> AudioSignal:
        return as_signal(drill_pattern(bpm, duration=duration, **kw))

    return _make


@pytest.fixture
def make_click():
    """Factory: make_click(bpm, duration=18) -> AudioSignal of a metronome."""

    def _make(bpm: float, duration: float = 18.0, **kw) -> AudioSignal:
        return as_signal(click_track(bpm, duration=duration, **kw))

    return _make


@pytest.fixture(scope="session")
def features_drill_150():
    """Cached Features for a synthetic 150 BPM drill beat (true tempo 150, felt 75)."""
    return build_features(as_signal(drill_pattern(150.0, duration=24.0)), DEFAULT_CONFIG)


@pytest.fixture(scope="session")
def features_click_120():
    """Cached Features for a clean 120 BPM metronome."""
    return build_features(as_signal(click_track(120.0, duration=18.0)), DEFAULT_CONFIG)


@pytest.fixture
def tmp_wav(tmp_path):
    """Factory: tmp_wav(y, sr) -> path to a written WAV in a temp dir."""

    def _write(y: np.ndarray, sr: int = 22050, name: str = "fixture.wav") -> str:
        return write_wav(str(tmp_path / name), y, sr)

    return _write
