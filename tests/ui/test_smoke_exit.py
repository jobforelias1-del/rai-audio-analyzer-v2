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
    reopen the write-only hole, so the set is pinned verbatim. ``truth_ok``
    joined in M3 (R-M3-14) — the ground-truth lane degrades to logged no-ops
    by design, so only the exit code catches its silent death."""
    assert REQUIRED_TRUE_KEYS == (
        "window_shown",
        "accepts_drops",
        "dnd_delivered",
        "analysis_ok",
        "tempo_ok",
        "signal_ok",
        "truth_ok",
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
    # ... and the M3 truth lane is independent of the metrics lane ...
    assert report["truth_ok"] is True
    # ... but the Signal section rendered absence, and THAT fails the probe.
    assert report["signal_ok"] is False
    assert exit_code == EXIT_FAILED


# ---------------------------------------------------------------------------
# M3 truth_ok: healthy round-trip + failure direction (landmine 14)
# ---------------------------------------------------------------------------


def _run_real_probe(tmp_path, monkeypatch, json_name="smoke_report.json"):
    """Shared real-probe driver (the metrics-death test's setup, factored)."""
    pytest.importorskip("PySide6")
    pytest.importorskip("soundfile")

    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    import rai_ui.app as app_module
    from rai_ui.services import recent_files
    from rai_ui.smoke import run_smoke

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(app_module, "create_app", lambda argv=None: app)
    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )

    json_path = tmp_path / json_name
    args = types.SimpleNamespace(smoke_json=str(json_path), smoke_audio=False)
    exit_code = run_smoke(args)
    return exit_code, json.loads(json_path.read_text(encoding="utf-8"))


def test_probe_truth_roundtrip_passes_and_restores_store_factory(
    tmp_path, monkeypatch
):
    """Healthy probe: the posed confirm/undo round-trip passes against the
    probe's own isolated temp store, the probe exits 0, and the store
    directory factory is restored afterwards (the probe may run inside a
    test process — a leaked redirect would silently re-point later store
    users at a deleted temp dir)."""
    pytest.importorskip("PySide6")
    from rai_ui.services import ground_truth_store

    factory_before = ground_truth_store._store_dir
    exit_code, report = _run_real_probe(tmp_path, monkeypatch)

    assert report["truth_ok"] is True, report.get("truth_error")
    assert exit_code == EXIT_OK
    # Exception-safe restore, and the probe's journal never landed in the
    # ambient (test-isolated) store dir.
    assert ground_truth_store._store_dir is factory_before
    import os

    assert not os.path.exists(ground_truth_store.journal_path())


def test_probe_fails_when_truth_lane_dies(tmp_path, monkeypatch):
    """Failure direction (landmine 14): kill the store lookup so the posed
    confirm can never round-trip — the analysis stays green, but truth_ok
    must fail the probe. Without truth_ok in REQUIRED_TRUE_KEYS this exact
    death would ship exit 0."""
    pytest.importorskip("PySide6")
    from rai_ui.services import ground_truth_store

    monkeypatch.setattr(ground_truth_store, "lookup", lambda md5: None)

    exit_code, report = _run_real_probe(tmp_path, monkeypatch)

    assert report["analysis_ok"] is True
    assert report["tempo_ok"] is True
    assert report["signal_ok"] is True
    assert report["truth_ok"] is False
    assert report["truth_error"]["store_write_roundtrip"] is False
    assert exit_code == EXIT_FAILED
