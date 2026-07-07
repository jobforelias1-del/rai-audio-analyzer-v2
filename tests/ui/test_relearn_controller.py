"""QThread tests for the relearn worker/controller (R-M3-11, landmine-2).

The synchronous core has its own Qt-less suite in
``tests/test_relearn_service.py`` (both venvs); this module drives the REAL
thread pattern offscreen — bound-method connections, ``invokeMethod`` start,
generation gating, one-at-a-time refusal, cooperative cancellation, and the
bounded ``close()`` — against tiny synthetic WAVs in a temp store (the
tests/ui autouse isolation already redirects the store; the local fixture
re-redirects to this test's own temp dir for explicitness).

Controller API contract under test (the Wire stage gates the
analysis⇄relearn mutual exclusion on exactly this surface)::

    is_running() -> bool
    cancel()
    started                              # Signal()
    finished(ok: bool, message: str)     # every terminal path
    progress(done: int, total: int)
"""

from __future__ import annotations

import json
import os
import time

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


def slow_stub_pipeline(monkeypatch, build_seconds: float = 0.25) -> None:
    """Replace the per-file DSP with a deterministic sleep so cancellation
    timing is testable without real audio (house rule: fake streams only).
    ``learn_fingerprint`` stays real-shaped via a minimal valid profile."""
    import rai_analyzer.io_audio as io_audio
    import rai_analyzer.tempogram as tempogram
    from rai_analyzer.config import DEFAULT_CONFIG
    from rai_analyzer.evidence import fingerprint as fp_engine

    def fake_build(signal, cfg):
        time.sleep(build_seconds)
        return object()

    params = DEFAULT_CONFIG.fingerprint
    fake_profile = {
        band: [1.0] + [0.0] * (params.bins_per_bar - 1) for band in params.bands
    }
    fake_profile["_meta"] = {"source": "learned", "n_tracks": 3}

    monkeypatch.setattr(io_audio, "load_audio", lambda path: object())
    monkeypatch.setattr(tempogram, "build_features", fake_build)
    monkeypatch.setattr(
        fp_engine, "learn_fingerprint", lambda items, cfg: dict(fake_profile)
    )


# ---------------------------------------------------------------------------
# Round trip + terminal-signal shape
# ---------------------------------------------------------------------------


def test_controller_relearn_round_trip(tmp_path, qtbot):
    confirm_three(tmp_path)

    controller = relearn.RelearnController()
    progress: list[tuple[int, int]] = []
    controller.progress.connect(lambda d, t: progress.append((d, t)))

    with qtbot.waitSignal(controller.finished, timeout=120_000) as blocker:
        assert controller.start() is True
        # One relearn at a time: a second start while live is refused.
        assert controller.start() is False

    controller.close()
    ok, message = blocker.args
    assert ok is True
    assert message == relearn.RELEARN_DONE_MESSAGE_FMT.format(n=3)
    # Cross-thread progress arrived, ending on the full count.
    assert progress[-1] == (3, 3)
    assert os.path.exists(gts.user_profile_path())
    assert gts.validate_profile_file(gts.user_profile_path()) is True
    with open(gts.user_profile_path(), "r", encoding="utf-8") as fh:
        assert json.load(fh)["_meta"]["n_tracks"] == 3
    assert not controller.is_running()


def test_controller_failure_path_finishes_not_ok(qtbot):
    # Empty store -> RelearnError -> finished(False, message); never a raise
    # across the thread boundary, and nothing written.
    controller = relearn.RelearnController()
    with qtbot.waitSignal(controller.finished, timeout=60_000) as blocker:
        assert controller.start() is True
    controller.close()
    ok, message = blocker.args
    assert ok is False
    assert "relearn needs 3" in message
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
    assert blocker.args[0] is True
    assert os.path.exists(gts.user_profile_backup_path())


# ---------------------------------------------------------------------------
# Cancellation (adversarial-review fix): cancelled run writes NOTHING,
# terminates with (False, CANCELLED_MESSAGE), and the thread joins fast
# ---------------------------------------------------------------------------


def test_controller_cancel_mid_run(tmp_path, qtbot, monkeypatch):
    slow_stub_pipeline(monkeypatch, build_seconds=0.25)
    confirm_three(tmp_path)

    controller = relearn.RelearnController()
    with qtbot.waitSignal(controller.finished, timeout=30_000) as finish_blocker:
        with qtbot.waitSignal(controller.progress, timeout=30_000):
            assert controller.start() is True
        controller.cancel()  # lands between per-file feature builds

    ok, message = finish_blocker.args
    assert ok is False
    assert message == relearn.CANCELLED_MESSAGE
    # A cancelled run wrote NOTHING.
    assert not os.path.exists(gts.user_profile_path())
    assert not os.path.exists(gts.user_profile_backup_path())
    # The thread joins fast — well inside close()'s 2 s bound.
    t0 = time.monotonic()
    qtbot.waitUntil(lambda: not controller.is_running(), timeout=5_000)
    assert time.monotonic() - t0 < 2.0
    controller.close()


def test_controller_cancel_is_idempotent_and_safe_when_idle(qtbot):
    controller = relearn.RelearnController()
    controller.cancel()  # nothing running: a no-op, never a crash
    controller.cancel()
    assert not controller.is_running()
    controller.close()


def test_controller_close_cancels_and_joins_within_bound(tmp_path, qtbot, monkeypatch):
    slow_stub_pipeline(monkeypatch, build_seconds=0.25)
    confirm_three(tmp_path)

    controller = relearn.RelearnController()
    with qtbot.waitSignal(controller.progress, timeout=30_000):
        assert controller.start() is True

    t0 = time.monotonic()
    controller.close()  # cancel + bounded wait — never the old 10 s freeze
    elapsed = time.monotonic() - t0
    assert elapsed < relearn._CLOSE_WAIT_MS / 1000.0 + 1.0
    assert not controller.is_running()
    # close() during the run cancelled it before the write phase.
    assert not os.path.exists(gts.user_profile_path())


def test_is_running_is_false_inside_the_finished_handler(tmp_path, qtbot, monkeypatch):
    """The mutual-exclusion gate must admit work started FROM a finished
    handler (regression: thread-state gating refused an analysis begun right
    after the relearn toast — exposed by CI's slow runner, reachable by any
    user dropping a file the moment relearn completes)."""
    slow_stub_pipeline(monkeypatch, build_seconds=0.01)
    confirm_three(tmp_path)

    controller = relearn.RelearnController()
    seen: list[bool] = []
    controller.finished.connect(lambda ok, msg: seen.append(controller.is_running()))
    with qtbot.waitSignal(controller.finished, timeout=30_000):
        assert controller.start() is True
    assert seen == [False]  # not "running" at relay time — the gate is open
    controller.close()
