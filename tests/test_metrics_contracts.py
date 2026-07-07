"""Tests for the M2 metrics contracts — ruling R-M2-12 (JSON-strict).

The law: ``json.dumps(result.to_dict(), allow_nan=False)`` must succeed for
EVERY input the layer can produce — silence, empty, mono, stereo — because
every non-finite measurement serializes to ``None``. Also pins the composed
``compute_signal_result`` entry point, the array-exclusion policy, rounding,
and immutability.
"""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest

from rai_analyzer.io_audio import AudioSignal
from rai_analyzer.metrics.compute import compute_signal_result
from rai_analyzer.metrics.contracts import (
    BandEnergyResult,
    DynamicsResult,
    SignalResult,
    SpectrumData,
    StereoResult,
)


def _signal(data: np.ndarray, sr_native: int = 48000) -> AudioSignal:
    data = np.asarray(data, dtype=np.float32)
    channels = 1 if data.ndim == 1 else data.shape[1]
    n = data.shape[0]
    return AudioSignal(
        path="<test>",
        y=data.reshape(-1)[: max(n, 1)].astype(np.float32, copy=False),
        sr=22050,
        y_native=data,
        sr_native=sr_native,
        channels=channels,
        duration=n / float(sr_native),
    )


def _sine(freq: float, amp: float, dur: float, sr: int) -> np.ndarray:
    t = np.arange(int(round(dur * sr))) / float(sr)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


# ---------------------------------------------------------------------------
# JSON-strict on every edge input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        _sine(1000.0, 0.5, 2.0, 48000),
        np.stack([_sine(440.0, 0.5, 1.0, 48000), -_sine(440.0, 0.5, 1.0, 48000)], axis=1),
        np.zeros(48000, dtype=np.float32),  # silence: -inf peaks, NaN crest/bands
        np.zeros((48000, 2), dtype=np.float32),  # stereo silence: NaN width too
        np.zeros(0, dtype=np.float32),  # empty
    ],
    ids=["sine", "stereo-antiphase", "silence", "silence-2ch", "empty"],
)
def test_to_dict_is_json_strict(data):
    result = compute_signal_result(_signal(data))
    d = result.to_dict()
    # THE contract: strict JSON never sees NaN/Infinity.
    s = json.dumps(d, allow_nan=False)
    assert json.loads(s) == d


def test_silence_serializes_non_finite_to_none():
    d = compute_signal_result(_signal(np.zeros((48000, 2), dtype=np.float32))).to_dict()
    assert d["dynamics"]["peak_dbfs"] is None  # -inf -> None
    assert d["dynamics"]["rms_dbfs"] is None
    assert d["dynamics"]["crest_db"] is None  # NaN -> None
    assert d["bands"]["sub_pct"] is None
    assert all(v is None for v in d["bands"]["six_band"].values())
    assert d["stereo"]["width_pct"] is None
    assert d["stereo"]["correlation"] is None


def test_mono_measurement_stays_a_number():
    # Mono width 0.0 is a MEASUREMENT (R-M2-4): it must serialize as 0.0,
    # never None.
    d = compute_signal_result(_signal(_sine(1000.0, 0.5, 1.0, 48000))).to_dict()
    assert d["stereo"]["width_pct"] == 0.0
    assert d["stereo"]["correlation"] is None


# ---------------------------------------------------------------------------
# Shape / rounding / array policy
# ---------------------------------------------------------------------------


def test_to_dict_shape_and_rounding():
    d = compute_signal_result(_signal(_sine(1000.0, 0.5, 2.0, 48000))).to_dict()
    assert set(d) == {"spectrum", "dynamics", "bands", "stereo"}
    assert set(d["dynamics"]) == {"peak_dbfs", "rms_dbfs", "crest_db"}
    assert set(d["bands"]) == {"sub_pct", "bass_pct", "six_band"}
    assert set(d["stereo"]) == {"width_pct", "correlation"}
    # Pre-rounded plain floats (engine to_dict doctrine): 2 decimals.
    assert d["dynamics"]["peak_dbfs"] == round(d["dynamics"]["peak_dbfs"], 2)
    assert d["dynamics"]["peak_dbfs"] == pytest.approx(-6.02, abs=0.02)


def test_spectrum_arrays_are_excluded_summary_included():
    result = compute_signal_result(_signal(_sine(1000.0, 0.5, 2.0, 48000)))
    d = result.to_dict()["spectrum"]
    # Array-exclusion policy: plot payload lives on the object, not in JSON.
    assert "freqs" not in d and "psd_db" not in d
    assert d["n_points"] == int(result.spectrum.freqs.size) > 0
    assert d["fmin_hz"] >= 20.0
    assert d["fmax_hz"] <= 20000.0


def test_empty_spectrum_summary_is_none():
    d = compute_signal_result(_signal(np.zeros(0, dtype=np.float32))).to_dict()["spectrum"]
    assert d == {"n_points": 0, "fmin_hz": None, "fmax_hz": None}


# ---------------------------------------------------------------------------
# Composition + immutability
# ---------------------------------------------------------------------------


def test_compute_signal_result_composes_all_parts():
    result = compute_signal_result(_signal(_sine(50.0, 0.5, 2.0, 48000)))
    assert isinstance(result, SignalResult)
    assert isinstance(result.spectrum, SpectrumData)
    assert isinstance(result.dynamics, DynamicsResult)
    assert isinstance(result.bands, BandEnergyResult)
    assert isinstance(result.stereo, StereoResult)
    # The parts agree with each other (shared PSD): a 50 Hz sine is all sub
    # and its spectrum peak sits at 50 Hz.
    assert result.bands.sub_pct > 99.0
    peak_freq = float(result.spectrum.freqs[int(np.argmax(result.spectrum.psd_db))])
    assert peak_freq == pytest.approx(50.0, abs=6.0)


def test_result_dataclasses_are_frozen():
    result = compute_signal_result(_signal(_sine(1000.0, 0.5, 0.5, 48000)))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.dynamics = None  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.dynamics.peak_dbfs = 0.0  # type: ignore[misc]


def test_measurements_never_lie_in_the_dataclass():
    # -inf / NaN live honestly in the dataclass; None is serialization-only.
    result = compute_signal_result(_signal(np.zeros(48000, dtype=np.float32)))
    assert result.dynamics.peak_dbfs == float("-inf")
    assert np.isnan(result.dynamics.crest_db)
    assert np.isnan(result.bands.sub_pct)
