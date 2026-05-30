"""Unit tests for the top-level orchestration (rai_analyzer.analyzer.analyze_file).

CONCURRENCY: loudness is owned by another agent and may be None, NaN, or a real
LoudnessResult depending on stub/implementation state. These tests therefore
assert only that the loudness *attribute exists* and that the result's dict /
report round-trips work — never an exact loudness value. Tempo is asserted only
for structural population (populated TempoResult), not exact numbers.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rai_analyzer.analyzer import analyze_file
from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.contracts import AnalysisResult, LoudnessResult, TempoResult
from rai_analyzer.synthetic import drill_pattern


@pytest.fixture
def drill_wav(tmp_wav):
    """A written 24 s, 150 BPM drill WAV on disk (analysis sample rate)."""
    y = drill_pattern(150.0, duration=24.0)
    return tmp_wav(y, 22050, "drill_150.wav")


def test_analyze_file_returns_analysis_result_with_tempo(drill_wav):
    res = analyze_file(drill_wav, DEFAULT_CONFIG)
    assert isinstance(res, AnalysisResult)
    # Tempo must be populated.
    assert isinstance(res.tempo, TempoResult)
    assert res.tempo.primary_bpm > 0
    assert res.tempo.candidates  # non-empty for a real beat
    # File metadata round-trips from the written WAV.
    assert res.path == drill_wav
    assert res.sr == 22050
    assert res.channels == 1
    assert res.duration == pytest.approx(24.0, abs=0.1)


def test_analyze_file_loudness_attribute_exists_and_is_tolerated(drill_wav):
    # Another agent owns loudness; it may be None, or a LoudnessResult that even
    # carries NaN. We only require: the attribute exists and is one of those.
    res = analyze_file(drill_wav, DEFAULT_CONFIG, with_loudness=True)
    assert hasattr(res, "loudness")
    assert res.loudness is None or isinstance(res.loudness, LoudnessResult)
    # Whatever it is, to_dict() must not blow up.
    d = res.to_dict()
    assert d["loudness"] is None or isinstance(d["loudness"], dict)


def test_analyze_file_to_dict_has_expected_keys(drill_wav):
    res = analyze_file(drill_wav, DEFAULT_CONFIG)
    d = res.to_dict()
    assert set(d.keys()) == {"path", "duration", "sr", "channels", "tempo", "loudness"}
    assert d["path"] == drill_wav
    assert d["sr"] == 22050
    assert d["channels"] == 1
    assert isinstance(d["tempo"], dict)
    assert "primary_bpm" in d["tempo"]


def test_analyze_file_to_report_is_nonempty_str(drill_wav):
    res = analyze_file(drill_wav, DEFAULT_CONFIG)
    report = res.to_report()
    assert isinstance(report, str)
    assert report  # non-empty
    assert "TEMPO" in report
    assert "CANDIDATES" in report


def test_analyze_file_with_loudness_false_yields_none(drill_wav):
    res = analyze_file(drill_wav, DEFAULT_CONFIG, with_loudness=False)
    assert res.loudness is None
    # And the dict reflects that.
    assert res.to_dict()["loudness"] is None


def test_analyze_file_default_config_is_usable(drill_wav):
    # Calling without an explicit cfg uses DEFAULT_CONFIG and still works.
    res = analyze_file(drill_wav)
    assert isinstance(res, AnalysisResult)
    assert res.tempo.primary_bpm > 0
