"""Worker profile-injection tests — ruling R-M3-12.

The worker builds a FRESH ``TempoConfig`` around a validated user fingerprint
(found via the store's injectable directory factory) and NEVER mutates
``DEFAULT_CONFIG`` — that singleton is shared with ``tempo_view`` and
``beatgrid``. An invalid-but-present profile falls back to the packaged
fingerprint and announces itself over the additive ``profile_fallback``
signal; an absent profile is the silent normal case.

Real analyses on the synthetic drill WAV, run same-thread for determinism
(the ``test_worker.py`` convention).
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("soundfile")

from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.evidence.fingerprint import (
    clear_fingerprint_cache,
    learn_fingerprint,
    save_fingerprint,
)
from rai_analyzer.synthetic import drill_pattern, write_wav

from rai_ui.services import ground_truth_store as gts
from rai_ui.services.worker import PROFILE_FALLBACK_MESSAGE, AnalysisWorker

ANALYSIS_TIMEOUT_MS = 120_000


@pytest.fixture
def drill_wav(tmp_path):
    y = drill_pattern(150.0, duration=6.0)
    return write_wav(str(tmp_path / "drill150.wav"), y)


@pytest.fixture(autouse=True)
def _fresh_fingerprint_cache():
    """The engine caches fingerprints by absolute path with no mtime check;
    per-test temp profile paths are unique, but clear anyway so no test can
    ever see another's profile bytes."""
    clear_fingerprint_cache()
    yield
    clear_fingerprint_cache()


def _run_worker(qtbot, wav_path):
    worker = AnalysisWorker()
    received = []
    fallbacks = []
    worker.profile_fallback.connect(lambda msg: fallbacks.append(msg))
    worker.finished.connect(
        lambda r, f, s, secs, sig, md5: received.append((r, f, s, secs, sig, md5))
    )
    with qtbot.waitSignal(worker.finished, timeout=ANALYSIS_TIMEOUT_MS):
        worker.run(wav_path)  # direct call — same thread, deterministic
    return received[0], fallbacks


def _write_learned_profile(features) -> str:
    """A VALID user profile that provably disagrees with the packaged one:
    learned from the drill features at a deliberately wrong tempo."""
    profile = learn_fingerprint([(features, 100.0)], DEFAULT_CONFIG)
    path = gts.user_profile_path()
    save_fingerprint(profile, path)
    assert gts.validate_profile_file(path) is True  # ties store + engine formats
    return path


def _scores(result) -> tuple:
    return tuple((c.bpm, c.score) for c in result.tempo.candidates)


def test_no_profile_runs_packaged_and_stays_silent(qtbot, drill_wav):
    (result, *_rest), fallbacks = _run_worker(qtbot, drill_wav)
    assert result.tempo.candidates
    assert fallbacks == []


def test_valid_profile_changes_analyze_path_results(qtbot, drill_wav, features_drill_150):
    """The deliberate visible act (R-M3-13): the same bytes analyze
    DIFFERENTLY once a user profile is active — and DEFAULT_CONFIG is
    untouched by the injection."""
    (packaged_result, *_), _ = _run_worker(qtbot, drill_wav)

    _write_learned_profile(features_drill_150)
    (user_result, *_), fallbacks = _run_worker(qtbot, drill_wav)

    assert fallbacks == []  # a VALID profile is not a fallback
    assert _scores(user_result) != _scores(packaged_result)
    # The injection is a fresh TempoConfig, never a DEFAULT_CONFIG mutation.
    assert DEFAULT_CONFIG.fingerprint.fingerprint_path is None


def test_invalid_profile_falls_back_with_one_signal(qtbot, drill_wav):
    (packaged_result, *_), _ = _run_worker(qtbot, drill_wav)

    path = gts.user_profile_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{this is not a fingerprint")

    (fallback_result, *_), fallbacks = _run_worker(qtbot, drill_wav)

    assert fallbacks == [PROFILE_FALLBACK_MESSAGE]  # exactly one, exact copy
    # The analysis itself is byte-for-byte the packaged behavior.
    assert _scores(fallback_result) == _scores(packaged_result)
    assert DEFAULT_CONFIG.fingerprint.fingerprint_path is None


def test_fallback_copy_is_the_r_m3_12_string():
    assert (
        PROFILE_FALLBACK_MESSAGE
        == "user profile unreadable — using packaged fingerprint"
    )
