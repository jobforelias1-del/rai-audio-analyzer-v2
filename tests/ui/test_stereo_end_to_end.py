"""End-to-end stereo coverage: a REAL stereo WAV through the REAL worker.

Adversarial-review defect 2: every prior end-to-end surface (smoke fixture,
preview shots, worker tests) is mono, so the stereo path — file intake with
channels preserved, ``compute_stereo`` on the native 2-channel signal, the
width card rendering a real percentage — was proven only with synthetic
arrays at unit level. This test writes a genuinely stereo WAV (drill pattern
left, a delayed/attenuated variant right — a Haas-style offset that
guarantees real side energy), runs the shell's real analysis pipeline
(``MainWindow.open_path`` → ``AnalysisWorker`` on a QThread with generation
gating, the ``tests/ui/test_worker.py`` pattern), and asserts the stereo
metrics and the Signal section's width card carry measurements, not the mono
"0 %" or the absence dash.

Deterministic: seeded synthesis, fixed delay, PCM_16 — the measured values
are stable (width ≈ 53.4 %, correlation ≈ −0.07 at authoring time), so the
asserted windows are wide but honest.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytest.importorskip("soundfile")  # write_wav dependency

from PySide6.QtCore import QSettings

from rai_analyzer.config import ANALYSIS_SR
from rai_analyzer.synthetic import drill_pattern, write_wav

ANALYSIS_TIMEOUT_MS = 120_000

STEREO_BPM = 150.0
STEREO_DURATION_S = 8.0  # fast, and long enough for a stable analysis
STEREO_DELAY_S = 0.012  # inter-channel delay: decorrelates the transients
STEREO_RIGHT_GAIN = 0.85  # level offset so L/R differ in gain too, not just time


@pytest.fixture
def stereo_drill_wav(tmp_path):
    """A genuinely stereo WAV: L = seeded drill pattern, R = delayed variant.

    ``np.roll`` plus a zeroed head makes R a true 12 ms delay of L (no
    wraparound), attenuated to 0.85 — different content per channel, so
    mid/side has real side energy and Pearson r is defined and well below 1.
    """
    left = drill_pattern(STEREO_BPM, duration=STEREO_DURATION_S, seed=0)
    delay = int(round(STEREO_DELAY_S * ANALYSIS_SR))
    right = (STEREO_RIGHT_GAIN * np.roll(left, delay)).astype(np.float32)
    right[:delay] = 0.0
    y = np.stack([left, right], axis=1).astype(np.float32)
    assert y.ndim == 2 and y.shape[1] == 2
    assert not np.allclose(y[:, 0], y[:, 1])  # the fixture is REALLY stereo
    return write_wav(str(tmp_path / "drill150_stereo.wav"), y)


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )


def test_stereo_wav_end_to_end_measures_width_and_correlation(
    qtbot, stereo_drill_wav, isolated_settings
):
    from rai_ui.main_window import MainWindow
    from rai_ui.state.signal_view import build_signal_view

    window = MainWindow()
    qtbot.addWidget(window)
    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_path(stereo_drill_wav)

    session = window.session
    result = session.last_result
    assert result is not None
    assert result.channels == 2  # intake preserved both channels

    sig = session.last_signal_result
    assert sig is not None, "metrics layer degraded to None on a stereo file"

    # R-M2-4 on real stereo content: width is a finite, positive measurement
    # (a delayed copy sits near the uncorrelated 50 — never mono's 0.0) ...
    width = float(sig.stereo.width_pct)
    assert math.isfinite(width) and width > 0.0
    assert 20.0 < width < 80.0

    # ... and correlation is DEFINED (mono's None would be a stereo-path leak).
    corr = sig.stereo.correlation
    assert corr is not None
    assert math.isfinite(float(corr)) and -1.0 <= float(corr) <= 1.0
    assert float(corr) < 0.99  # genuinely decorrelated channels, not L==R

    # Through the real view-model builder the width card shows a measurement:
    # not the absence dash, not mono's "0 %", and the gauge actually fills.
    vm = build_signal_view(result, sig, session.verdict_state)
    dash = "—"  # em dash — absence, never a measurement
    assert vm.width_card.value_text != dash
    assert vm.width_card.value_text != "0 %"
    assert vm.width_card.value_text.endswith(" %")
    assert vm.width_card.gauge_frac is not None and vm.width_card.gauge_frac > 0.0
