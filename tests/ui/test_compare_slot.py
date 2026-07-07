"""Tests for the Compare B-lane service (rai_ui.services.compare_slot).

Real :class:`AnalysisWorker` runs on real QThreads against tiny synthetic
WAVs — the production launch recipe, nothing mocked but the R-M4-3 gate
callables (mutable flags). Coverage per the Stage-2 manifest:

* generation gating — a replace-while-working drop orphans the older worker,
  and ``clear()`` orphans an in-flight completion outright;
* refuse-while-A-working / refuse-while-relearn (toast-ready copy returned,
  nothing launched, nothing changed);
* ``clear()`` — the ONE emptying transition (R-M4-2);
* the landmine-22 discipline: status flips BEFORE the ``loaded``/``failed``/
  ``changed`` relays;
* R-M4-2 payload wall: the slot stores result + signal_result ONLY;
* a failed replacement restores the previous LOADED reference (or EMPTY).

The ground-truth store is a per-test temp dir (tests/ui conftest autouse
isolation — R-M3-2 hard rule); the B worker's md5/profile probes hit only
that. Qt-dependent — importorskip'd so the engine venv skips cleanly.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from rai_ui.services.compare_slot import (
    TOAST_B_BLOCKED_BY_ANALYSIS,
    TOAST_B_BLOCKED_BY_RELEARN,
    CompareSlot,
)
from rai_ui.state.compare_view import BStatus

ANALYSIS_TIMEOUT_MS = 60_000
_DRAIN_MS = 100  # post-thread-finish event drain for queued signal delivery


class _Gates:
    """Mutable stand-ins for the injected R-M4-3 gate callables."""

    def __init__(self) -> None:
        self.a_working = False
        self.relearn_running = False


@pytest.fixture
def gates():
    return _Gates()


@pytest.fixture
def slot(qtbot, gates):
    s = CompareSlot(
        a_working=lambda: gates.a_working,
        relearn_running=lambda: gates.relearn_running,
    )
    yield s
    s.close()


def _wav(tmp_path, name: str = "ref.wav", bpm: float = 140.0) -> str:
    from rai_analyzer.synthetic import click_track, write_wav

    return write_wav(str(tmp_path / name), click_track(bpm, duration=4.0))


def _wait_workers_done(qtbot, slot) -> None:
    """All launched threads finished AND their queued signals delivered."""
    qtbot.waitUntil(
        lambda: all(t.isFinished() for t, _w in slot._threads),
        timeout=ANALYSIS_TIMEOUT_MS,
    )
    qtbot.wait(_DRAIN_MS)


# ---------------------------------------------------------------------------
# Lifecycle basics
# ---------------------------------------------------------------------------


def test_boots_empty(slot):
    assert slot.status is BStatus.EMPTY
    assert slot.result is None
    assert slot.signal_result is None
    assert not slot.is_working()


def test_start_flips_working_then_loads(qtbot, slot, tmp_path):
    path = _wav(tmp_path)
    changed_states = []
    slot.changed.connect(lambda: changed_states.append(slot.status))

    assert slot.start(path) is None
    # Gate flipped synchronously and BEFORE the changed relay (landmine 22).
    assert changed_states == [BStatus.WORKING]
    assert slot.is_working()

    with qtbot.waitSignal(slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        pass
    assert slot.status is BStatus.LOADED
    assert slot.result is not None and slot.result.path == path
    assert changed_states[-1] is BStatus.LOADED


def test_status_flips_before_loaded_relay(qtbot, slot, tmp_path):
    """Landmine 22: a loaded-handler re-reading the slot sees LOADED."""
    seen = []
    slot.loaded.connect(lambda _r: seen.append(slot.status))
    slot.start(_wav(tmp_path))
    with qtbot.waitSignal(slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        pass
    assert seen == [BStatus.LOADED]


def test_stores_result_and_signal_result_only(qtbot, slot, tmp_path):
    """R-M4-2: the B payload wall — no features/signal/md5 ever stored."""
    slot.start(_wav(tmp_path))
    with qtbot.waitSignal(slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        pass
    assert slot.result is not None
    assert slot.signal_result is not None  # metrics are best-effort but real here
    stored = set(vars(slot))
    for forbidden in ("features", "signal_obj", "md5", "last_md5", "verdict_state"):
        assert forbidden not in stored, f"slot must never store {forbidden!r}"


# ---------------------------------------------------------------------------
# R-M4-3 refusal gates
# ---------------------------------------------------------------------------


def test_refuses_while_a_working(slot, gates, tmp_path):
    gates.a_working = True
    changed = []
    slot.changed.connect(lambda: changed.append(slot.status))
    assert slot.start(_wav(tmp_path)) == TOAST_B_BLOCKED_BY_ANALYSIS
    assert slot.status is BStatus.EMPTY
    assert changed == []  # nothing launched, nothing broadcast
    assert slot._threads == []


def test_refuses_while_relearn_running(slot, gates, tmp_path):
    gates.relearn_running = True
    assert slot.start(_wav(tmp_path)) == TOAST_B_BLOCKED_BY_RELEARN
    assert slot.status is BStatus.EMPTY
    assert slot._threads == []


# ---------------------------------------------------------------------------
# Generation gating
# ---------------------------------------------------------------------------


def test_replace_while_working_orphans_older_worker(qtbot, slot, tmp_path):
    """Two rapid B drops: only the SECOND completion lands (own counter)."""
    first = _wav(tmp_path, "first.wav", 140.0)
    second = _wav(tmp_path, "second.wav", 150.0)
    loaded_paths = []
    slot.loaded.connect(lambda r: loaded_paths.append(r.path))

    assert slot.start(first) is None
    assert slot.start(second) is None  # replace: B-working is not a refusal
    _wait_workers_done(qtbot, slot)

    assert loaded_paths == [second]
    assert slot.status is BStatus.LOADED
    assert slot.result.path == second


def test_clear_orphans_in_flight_completion(qtbot, slot, tmp_path):
    loaded = []
    slot.loaded.connect(lambda r: loaded.append(r.path))
    slot.start(_wav(tmp_path))
    slot.clear()  # user empties the slot while B is analyzing
    assert slot.status is BStatus.EMPTY

    _wait_workers_done(qtbot, slot)
    assert loaded == []  # the stale completion was dropped
    assert slot.status is BStatus.EMPTY
    assert slot.result is None and slot.signal_result is None


# ---------------------------------------------------------------------------
# clear() — the one emptying transition (R-M4-2)
# ---------------------------------------------------------------------------


def test_clear_empties_a_loaded_slot(qtbot, slot, tmp_path):
    slot.start(_wav(tmp_path))
    with qtbot.waitSignal(slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        pass
    changed = []
    slot.changed.connect(lambda: changed.append(slot.status))
    slot.clear()
    assert changed == [BStatus.EMPTY]
    assert slot.result is None and slot.signal_result is None
    assert not slot.is_working()


# ---------------------------------------------------------------------------
# Failure honesty — the previous reference persists
# ---------------------------------------------------------------------------


def test_failed_replacement_restores_previous_b(qtbot, slot, tmp_path):
    good = _wav(tmp_path, "good.wav")
    slot.start(good)
    with qtbot.waitSignal(slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        pass

    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"this is not audio")
    with qtbot.waitSignal(slot.failed, timeout=ANALYSIS_TIMEOUT_MS) as blocker:
        assert slot.start(str(bad)) is None
    assert isinstance(blocker.args[0], str) and blocker.args[0]
    # The old reference stands (R-M4-2 persistence over a failed replace).
    assert slot.status is BStatus.LOADED
    assert slot.result.path == good


def test_failure_with_no_previous_b_goes_empty(qtbot, slot, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"garbage")
    statuses_at_failed = []
    slot.failed.connect(lambda _m: statuses_at_failed.append(slot.status))
    with qtbot.waitSignal(slot.failed, timeout=ANALYSIS_TIMEOUT_MS):
        assert slot.start(str(bad)) is None
    # Landmine 22 again: the gate settled before the failed relay.
    assert statuses_at_failed == [BStatus.EMPTY]
    assert slot.result is None


def test_close_detaches_stragglers_instead_of_qfatal(qtbot, slot, tmp_path):
    """Quit during an in-flight B must never destroy a running QThread
    (Qt qFatal hard abort) — stragglers detach and park, the relearn recipe.
    Review finding M4 (3/3 verified)."""
    from rai_ui.services import compare_slot as cs

    assert slot.start(_wav(tmp_path)) is None  # accepted (no refusal copy)
    assert slot._threads, "worker lane should exist"
    thread, worker = slot._threads[0]
    thread.wait = lambda *_a, **_k: False  # simulate a compute-bound straggler

    slot.close()

    assert thread.parent() is None  # out of the destruction chain
    assert (thread, worker) in cs._ORPHANED_THREADS
    assert (thread, worker) not in slot._threads

    # Hygiene: let the real thread finish so it doesn't leak into other tests.
    del thread.wait
    thread.quit()
    assert thread.wait(30_000)
    cs._ORPHANED_THREADS.remove((thread, worker))
