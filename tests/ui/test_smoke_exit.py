"""Smoke exit-code contract tests — adversarial-review defect 1.

The review found ``tempo_ok``/``signal_ok`` were WRITE-ONLY: the probe exited
EXIT_OK on ``dnd_delivered and analysis_ok`` alone, and since the worker
deliberately degrades a metrics-layer crash to ``SignalResult=None`` while
``analysis_ok`` stays true (R-M2-15), the entire M2 layer could die with
every gate green. The fix routes the pass/fail decision through the pure
:func:`rai_ui.smoke.exit_code_for`, which requires ALL of
:data:`rai_ui.smoke.REQUIRED_TRUE_KEYS` to be truthy.

Two layers here:

* pure tests of ``exit_code_for`` — importable without Qt (``rai_ui.smoke``
  keeps its Qt imports inside ``_probe``), so the engine venv runs these too;
* one guarded integration test that runs the REAL probe with the metrics
  layer monkeypatched to raise — the exact silent-death scenario — and
  asserts the probe now exits EXIT_FAILED with ``analysis_ok`` still true
  and ``signal_ok`` false. Before the fix this scenario exited EXIT_OK.
"""

from __future__ import annotations

import json
import types

import pytest

from rai_ui.smoke import (
    EXIT_FAILED,
    EXIT_OK,
    EXIT_TIMEOUT,
    REQUIRED_TRUE_KEYS,
    exit_code_for,
)

# ---------------------------------------------------------------------------
# Pure exit-code policy (no Qt required)
# ---------------------------------------------------------------------------


def _passing_report() -> dict:
    report = {key: True for key in REQUIRED_TRUE_KEYS}
    report["bpm"] = 140.0
    report["audio_ok"] = None  # optional — never part of the exit decision
    return report


def test_required_keys_pin_the_strengthened_contract():
    """The contract itself is load-bearing: dropping a key here would quietly
    reopen the write-only hole, so the set is pinned verbatim."""
    assert REQUIRED_TRUE_KEYS == (
        "window_shown",
        "accepts_drops",
        "dnd_delivered",
        "analysis_ok",
        "tempo_ok",
        "signal_ok",
    )


def test_all_required_true_is_ok():
    assert exit_code_for(_passing_report(), timed_out=False) == EXIT_OK


def test_timeout_wins_even_when_everything_else_passed():
    assert exit_code_for(_passing_report(), timed_out=True) == EXIT_TIMEOUT


@pytest.mark.parametrize("key", REQUIRED_TRUE_KEYS)
def test_any_required_key_false_fails(key):
    report = _passing_report()
    report[key] = False
    assert exit_code_for(report, timed_out=False) == EXIT_FAILED


@pytest.mark.parametrize("key", REQUIRED_TRUE_KEYS)
def test_any_required_key_none_fails(key):
    """``None`` = never computed (e.g. analysis never produced a result) —
    must fail exactly like an explicit False."""
    report = _passing_report()
    report[key] = None
    assert exit_code_for(report, timed_out=False) == EXIT_FAILED


def test_missing_key_fails():
    report = _passing_report()
    del report["signal_ok"]
    assert exit_code_for(report, timed_out=False) == EXIT_FAILED


@pytest.mark.parametrize("audio_ok", [None, False, True])
def test_audio_spike_stays_optional(audio_ok):
    report = _passing_report()
    report["audio_ok"] = audio_ok
    assert exit_code_for(report, timed_out=False) == EXIT_OK


# ---------------------------------------------------------------------------
# Failure-direction integration: the silent M2 death now fails the probe
# ---------------------------------------------------------------------------


def test_probe_fails_when_metrics_layer_dies(tmp_path, monkeypatch):
    """Run the REAL smoke probe with ``compute_signal_result`` raising (the
    R-M2-15 degrade path): analysis stays green by design, but the probe must
    exit EXIT_FAILED because ``signal_ok`` is false. This is the exact
    scenario the write-only defect let through with exit 0."""
    pytest.importorskip("PySide6")
    pytest.importorskip("soundfile")  # smoke fixture dependency

    from PySide6.QtWidgets import QApplication

    import rai_analyzer.metrics.compute as metrics_compute
    import rai_ui.app as app_module
    from rai_ui.smoke import run_smoke

    # The probe calls create_app(); under a test process a QApplication may
    # already exist (and Qt allows only one) — reuse it either way.
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, "create_app", lambda argv=None: app)

    # Keep the probe's recent-files write out of the user's real QSettings.
    from PySide6.QtCore import QSettings

    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )

    def _boom(_signal):
        raise RuntimeError("metrics exploded")

    monkeypatch.setattr(metrics_compute, "compute_signal_result", _boom)

    json_path = tmp_path / "smoke_report.json"
    args = types.SimpleNamespace(smoke_json=str(json_path), smoke_audio=False)
    exit_code = run_smoke(args)

    report = json.loads(json_path.read_text(encoding="utf-8"))
    # The degrade is deliberate: the analysis itself still succeeded ...
    assert report["analysis_ok"] is True
    assert report["dnd_delivered"] is True
    assert report["tempo_ok"] is True
    # ... but the Signal section rendered absence, and THAT fails the probe.
    assert report["signal_ok"] is False
    assert exit_code == EXIT_FAILED
