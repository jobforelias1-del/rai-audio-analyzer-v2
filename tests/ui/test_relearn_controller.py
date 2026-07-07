"""QThread tests for the relearn worker/controller (R-M3-11, landmine-2).

The synchronous core has its own Qt-less suite in
``tests/test_relearn_service.py`` (both venvs); this module drives the REAL
thread pattern offscreen — bound-method connections, ``invokeMethod`` start,
generation gating, one-at-a-time refusal — against tiny synthetic WAVs in a
temp store (the tests/ui autouse isolation already redirects the store; the
local fixture re-redirects to this test's own temp dir for explicitness).
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from rai_analyzer.evidence.fingerprint import clear_fingerprint_cache
from rai_analyzer.synthetic import click_track, write_wav
from rai_ui.services import ground_truth_store as gts
from rai_ui.services import relearn


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    store_dir = str(tmp_path / "gt-store")
    monkeypatch.setattr(gts, "_store_dir", lambda: store_dir)
    assert gts.journal_path().startswith(store_dir)
    clear_fingerprint_cache()
    yield store_dir
    clear_fingerprint_cache()


def confirm_three(tmp_path) -> None:
    for name, bpm in (
        ("click140.wav", 140.0),
        ("click150.wav", 150.0),
        ("click165.wav", 165.0),
    ):
        path = write_wav(str(tmp_path / name), click_track(bpm, duration=6.0))
        gts.append_confirm(gts.file_md5(path), bpm, name, path)


def test_controller_relearn_round_trip(tmp_path, qtbot):
    confirm_three(tmp_path)

    controller = relearn.RelearnController()
    progress: list[tuple[int, int]] = []
    controller.progress.connect(lambda d, t: progress.append((d, t)))
    reports: list[object] = []
    controller.finished.connect(reports.append)

    with qtbot.waitSignal(controller.finished, timeout=120_000):
        assert controller.start() is True
        # One relearn at a time: a second start while live is refused.
        assert controller.start() is False

    controller.close()
    assert len(reports) == 1
    report = reports[0]
    assert report.learned == 3
    assert report.skipped == ()
    # Cross-thread progress arrived, ending on the full count.
    assert progress[-1] == (3, 3)
    assert os.path.exists(gts.user_profile_path())
    assert gts.validate_profile_file(gts.user_profile_path()) is True
    assert not controller.is_running()


def test_controller_failure_path_emits_failed(qtbot):
    # Empty store -> RelearnError -> failed(message); never a raise across
    # the thread boundary, and nothing written.
    controller = relearn.RelearnController()
    with qtbot.waitSignal(controller.failed, timeout=60_000) as blocker:
        assert controller.start() is True
    controller.close()
    assert "relearn needs 3" in blocker.args[0]
    assert not os.path.exists(gts.user_profile_path())
    assert not controller.is_running()


def test_controller_can_run_again_after_completion(tmp_path, qtbot):
    confirm_three(tmp_path)
    controller = relearn.RelearnController()
    with qtbot.waitSignal(controller.finished, timeout=120_000):
        assert controller.start() is True
    # The thread wound down (worker.finished -> thread.quit); a fresh start
    # is accepted and the second run backs up the first profile.
    qtbot.waitUntil(lambda: not controller.is_running(), timeout=10_000)
    with qtbot.waitSignal(controller.finished, timeout=120_000) as blocker:
        assert controller.start() is True
    controller.close()
    assert blocker.args[0].backup_path == gts.user_profile_backup_path()
    assert os.path.exists(gts.user_profile_backup_path())
