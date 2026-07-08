"""Tests for the relearn service (R-M3-11/12) — temp dirs, tiny synthetic WAVs.

Runs in BOTH venvs: the synchronous core (`run_relearn` / `revert_profile` /
`profile_state`) is Qt-free by design, so the engine venv exercises the full
store → md5-reverify → features → learn → backup → save → cache-clear
pipeline; the QThread worker/controller tests importorskip PySide6/pytestqt.

HARD RULE (R-M3-2): nothing here may touch the real
``~/Library/Application Support/RAI Audio Analyzer/`` — the store's
injectable ``_store_dir`` factory is monkeypatched to a per-test temp dir
(autouse below, mirroring tests/ui/conftest.py which does not govern this
top-level module), and a guard asserts the redirection before every test
body runs. The packaged fingerprint must remain byte-identical throughout
(the R-M3-13 boundary: relearn writes ONLY under the injected store dir).
"""

from __future__ import annotations

import copy
import json
import os
import threading

import pytest

from rai_analyzer.evidence import fingerprint as fp_engine
from rai_analyzer.synthetic import click_track, write_wav
from rai_ui.services import ground_truth_store as gts
from rai_ui.services import relearn

REAL_STORE_FRAGMENT = os.path.join("Library", "Application Support")


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Redirect the store factory to a temp dir and prove the redirection."""
    store_dir = str(tmp_path / "gt-store")
    monkeypatch.setattr(gts, "_store_dir", lambda: store_dir)
    for path in (gts.journal_path(), gts.user_profile_path(), gts.user_profile_backup_path()):
        assert path.startswith(store_dir)
        assert REAL_STORE_FRAGMENT not in path
    # A pristine fingerprint cache per test: cache state must never leak
    # between tests (it is keyed by path, and tmp paths recycle rarely but
    # the packaged path is shared).
    fp_engine.clear_fingerprint_cache()
    yield store_dir
    fp_engine.clear_fingerprint_cache()


@pytest.fixture(autouse=True)
def packaged_fingerprint_untouched():
    """The R-M3-13 wall: relearn must never write rai_analyzer/fingerprints/."""
    packaged = os.path.join(
        os.path.dirname(fp_engine.__file__), "..", "fingerprints", "drill.json"
    )
    packaged = os.path.abspath(packaged)
    with open(packaged, "rb") as fh:
        before = fh.read()
    yield
    with open(packaged, "rb") as fh:
        assert fh.read() == before, "packaged drill.json was modified by relearn!"


def confirm_wav(tmp_path, name: str, bpm: float, duration: float = 6.0) -> str:
    """Write a tiny synthetic WAV, journal a confirmation for it, return path."""
    path = write_wav(str(tmp_path / name), click_track(bpm, duration=duration))
    gts.append_confirm(gts.file_md5(path), bpm, name, path)
    return path


def confirm_three(tmp_path) -> list[str]:
    return [
        confirm_wav(tmp_path, "click140.wav", 140.0),
        confirm_wav(tmp_path, "click150.wav", 150.0),
        confirm_wav(tmp_path, "click165.wav", 165.0),
    ]


# ---------------------------------------------------------------------------
# run_relearn — the happy path
# ---------------------------------------------------------------------------


def test_relearn_learns_from_three_confirmed(tmp_path, isolated_store):
    confirm_three(tmp_path)
    report = relearn.run_relearn()

    assert report.learned == 3
    assert report.skipped == ()
    assert report.backup_path is None  # no previous profile existed
    assert report.profile_path == gts.user_profile_path()
    assert report.profile_path.startswith(isolated_store)
    assert os.path.exists(report.profile_path)
    assert not os.path.exists(gts.user_profile_backup_path())

    # The written profile is exactly what the worker will accept (R-M3-12).
    assert gts.validate_profile_file(report.profile_path) is True


def test_relearned_profile_content_and_meta(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    with open(gts.user_profile_path(), "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    from rai_analyzer.config import DEFAULT_CONFIG

    for band in DEFAULT_CONFIG.fingerprint.bands:
        profile = raw[band]
        assert len(profile) == DEFAULT_CONFIG.fingerprint.bins_per_bar
        assert any(x > 0 for x in profile)
    meta = raw["_meta"]
    assert meta["source"] == "learned"
    assert meta["n_tracks"] == 3
    # The popover's source-line date (R-M3-11) rides _meta additively.
    assert isinstance(meta["relearned_at"], str)
    assert len(meta["relearned_at"]) >= 10


def test_relearn_reports_progress(tmp_path):
    confirm_three(tmp_path)
    seen: list[tuple[int, int]] = []
    relearn.run_relearn(progress=lambda done, total: seen.append((done, total)))
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# Backup + one-step revert
# ---------------------------------------------------------------------------


def test_second_relearn_backs_up_the_first_profile(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    with open(gts.user_profile_path(), "rb") as fh:
        first_bytes = fh.read()

    confirm_wav(tmp_path, "click120.wav", 120.0)
    report = relearn.run_relearn()
    assert report.learned == 4
    assert report.backup_path == gts.user_profile_backup_path()
    with open(report.backup_path, "rb") as fh:
        assert fh.read() == first_bytes  # the backup IS the previous profile
    with open(gts.user_profile_path(), "rb") as fh:
        assert fh.read() != first_bytes  # and the profile moved on


def test_revert_restores_previous_profile_and_consumes_backup(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    with open(gts.user_profile_path(), "rb") as fh:
        first_bytes = fh.read()
    confirm_wav(tmp_path, "click120.wav", 120.0)
    relearn.run_relearn()

    restored = relearn.revert_profile()
    assert restored == gts.user_profile_path()
    with open(restored, "rb") as fh:
        assert fh.read() == first_bytes
    # One-step means ONE step: the backup is consumed.
    assert not os.path.exists(gts.user_profile_backup_path())


def test_revert_without_backup_raises(tmp_path):
    with pytest.raises(relearn.RelearnError):
        relearn.revert_profile()


def test_relearn_and_revert_clear_the_fingerprint_cache(tmp_path):
    # The load cache is keyed by path, not content — a stale cache would keep
    # scoring against the old profile forever (recon §1). Prove both writes
    # invalidate it, through the engine's own load path.
    confirm_three(tmp_path)
    relearn.run_relearn()
    profile_path = gts.user_profile_path()
    first_loaded = fp_engine.load_fingerprint(profile_path)
    assert first_loaded["_meta"]["n_tracks"] == 3

    confirm_wav(tmp_path, "click120.wav", 120.0)
    relearn.run_relearn()
    second_loaded = fp_engine.load_fingerprint(profile_path)
    assert second_loaded["_meta"]["n_tracks"] == 4  # stale cache would say 3

    relearn.revert_profile()
    reverted_loaded = fp_engine.load_fingerprint(profile_path)
    assert reverted_loaded["_meta"]["n_tracks"] == 3


# ---------------------------------------------------------------------------
# md5 re-verify: skip + report (R-M3-11)
# ---------------------------------------------------------------------------


def test_changed_file_is_skipped_with_reason(tmp_path):
    confirm_three(tmp_path)
    tampered = confirm_wav(tmp_path, "click155.wav", 155.0)
    with open(tampered, "ab") as fh:
        fh.write(b"\x00\x00")  # any byte change re-keys the md5

    report = relearn.run_relearn()
    assert report.learned == 3
    assert len(report.skipped) == 1
    skip = report.skipped[0]
    assert skip.name == "click155.wav"
    assert skip.reason == relearn.SKIP_CHANGED


def test_missing_file_is_skipped_with_reason(tmp_path):
    confirm_three(tmp_path)
    gone = confirm_wav(tmp_path, "click160.wav", 160.0)
    os.remove(gone)

    report = relearn.run_relearn()
    assert report.learned == 3
    assert report.skipped[0].reason == relearn.SKIP_MISSING


def test_legacy_record_without_path_is_skipped(tmp_path):
    confirm_three(tmp_path)
    # A pre-path-schema confirm record (readers tolerate its absence; relearn
    # cannot re-open what it cannot locate).
    gts.append_confirm("d41d8cd98f00b204e9800998ecf8427e", 150.0, "legacy.wav")

    report = relearn.run_relearn()
    assert report.learned == 3
    assert report.skipped[0].reason == relearn.SKIP_NO_PATH


# ---------------------------------------------------------------------------
# The gate: abort writes NOTHING
# ---------------------------------------------------------------------------


def test_too_few_usable_truths_aborts_without_writing(tmp_path):
    # 3 confirmed, but one tampered -> 2 usable < 3: RelearnError, no files.
    paths = confirm_three(tmp_path)
    with open(paths[0], "ab") as fh:
        fh.write(b"\x00")

    with pytest.raises(relearn.RelearnError) as excinfo:
        relearn.run_relearn()
    assert "nothing was written" in str(excinfo.value)
    assert excinfo.value.skipped[0].reason == relearn.SKIP_CHANGED
    assert not os.path.exists(gts.user_profile_path())
    assert not os.path.exists(gts.user_profile_backup_path())


def test_empty_store_aborts(tmp_path):
    with pytest.raises(relearn.RelearnError):
        relearn.run_relearn()
    assert not os.path.exists(gts.user_profile_path())


def test_abort_leaves_an_existing_profile_untouched(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    with open(gts.user_profile_path(), "rb") as fh:
        before = fh.read()

    # Retract two truths -> 1 effective < 3: the relearn button would be
    # dark, but even a direct call must abort and leave the profile alone.
    truths = list(gts.effective_truths().values())
    gts.append_retract(truths[0].md5)
    gts.append_retract(truths[1].md5)
    with pytest.raises(relearn.RelearnError):
        relearn.run_relearn()
    with open(gts.user_profile_path(), "rb") as fh:
        assert fh.read() == before
    assert not os.path.exists(gts.user_profile_backup_path())


# ---------------------------------------------------------------------------
# Atomic publish: crash windows leave the previous state intact
# (adversarial-review fixes — non-atomic in-place write, no-rollback save)
# ---------------------------------------------------------------------------


def _profile_bytes() -> bytes:
    with open(gts.user_profile_path(), "rb") as fh:
        return fh.read()


def _store_tmp_files(store_dir: str) -> list[str]:
    if not os.path.isdir(store_dir):
        return []
    return [n for n in os.listdir(store_dir) if ".tmp-" in n]


def test_save_exception_mid_dump_leaves_previous_profile_intact(
    tmp_path, isolated_store, monkeypatch
):
    """Disk-full (or any exception) INSIDE save_fingerprint tears only the
    staged temp file — the live profile survives byte-identical (the review's
    live-repro: partial JSON prefix then OSError 28)."""
    confirm_three(tmp_path)
    relearn.run_relearn()
    before = _profile_bytes()

    confirm_wav(tmp_path, "click120.wav", 120.0)

    def torn_save(fingerprint, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"low": [0.1')  # a torn prefix, then the disk fills
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(fp_engine, "save_fingerprint", torn_save)
    with pytest.raises(OSError):
        relearn.run_relearn()

    assert _profile_bytes() == before  # live profile untouched
    assert gts.validate_profile_file(gts.user_profile_path()) is True
    assert not os.path.exists(gts.user_profile_backup_path())  # no half-transaction
    assert _store_tmp_files(isolated_store) == []  # staged temp cleaned up


def test_crash_between_temp_write_and_replace_leaves_old_profile(
    tmp_path, isolated_store
):
    """The review's demanded crash-window test: die between the staged write
    and the atomic replace — the old profile must still be the live one."""
    confirm_three(tmp_path)
    relearn.run_relearn()
    before = _profile_bytes()
    confirm_wav(tmp_path, "click120.wav", 120.0)

    class SimulatedCrash(RuntimeError):
        pass

    def crashing_replace(src, dst):
        raise SimulatedCrash("killed between temp-write and replace")

    # A scoped context (NOT the shared function monkeypatch — undoing that
    # would also undo the autouse store isolation) so os.replace is restored
    # before the post-crash assertions below.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(relearn.os, "replace", crashing_replace)
        with pytest.raises(SimulatedCrash):
            relearn.run_relearn()

    assert _profile_bytes() == before  # old profile intact, never torn
    assert gts.validate_profile_file(gts.user_profile_path()) is True
    # The backup (written just before the replace) is the same old profile,
    # so a revert after the crash is still safe and content-preserving.
    if os.path.exists(gts.user_profile_backup_path()):
        with open(gts.user_profile_backup_path(), "rb") as fh:
            assert fh.read() == before
    assert _store_tmp_files(isolated_store) == []


def test_staged_validation_failure_writes_nothing(tmp_path, isolated_store):
    """Validation now runs on the STAGED file: a failure means the live
    profile was never opened for writing, and no backup is created."""
    confirm_three(tmp_path)
    relearn.run_relearn()
    before = _profile_bytes()
    confirm_wav(tmp_path, "click120.wav", 120.0)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gts, "validate_profile_file", lambda path: False)
        with pytest.raises(relearn.RelearnError) as excinfo:
            relearn.run_relearn()

    assert "previous state untouched" in str(excinfo.value)
    assert _profile_bytes() == before
    assert not os.path.exists(gts.user_profile_backup_path())
    assert _store_tmp_files(isolated_store) == []


def test_cache_cleared_exactly_once_and_after_the_replace(tmp_path, monkeypatch):
    """clear_fingerprint_cache() must run exactly once per successful relearn,
    AFTER the atomic replace — the on-disk profile at clear time is already
    the new one (so a racing reader can never re-poison the cache with a
    profile the clear was meant to evict)."""
    confirm_three(tmp_path)
    relearn.run_relearn()

    confirm_wav(tmp_path, "click120.wav", 120.0)
    real_clear = fp_engine.clear_fingerprint_cache
    seen_n_tracks: list[int] = []

    def counting_clear():
        with open(gts.user_profile_path(), "r", encoding="utf-8") as fh:
            seen_n_tracks.append(json.load(fh)["_meta"]["n_tracks"])
        real_clear()

    monkeypatch.setattr(fp_engine, "clear_fingerprint_cache", counting_clear)
    relearn.run_relearn()

    assert seen_n_tracks == [4]  # exactly once, and the NEW profile is live


# ---------------------------------------------------------------------------
# Cancellation: a cancelled run writes NOTHING
# ---------------------------------------------------------------------------


def test_cancel_after_first_file_writes_nothing(tmp_path):
    state = {"done": 0}

    def progress(done: int, total: int) -> None:
        state["done"] = max(state["done"], done)

    confirm_three(tmp_path)
    with pytest.raises(relearn.RelearnCancelled):
        relearn.run_relearn(progress=progress, cancelled=lambda: state["done"] >= 1)

    assert state["done"] == 1  # cancelled between file 1 and file 2
    assert not os.path.exists(gts.user_profile_path())
    assert not os.path.exists(gts.user_profile_backup_path())


def test_cancel_after_last_build_still_writes_nothing(tmp_path):
    # The pre-write check: even a cancel that lands after ALL features are
    # built (but before the write phase) must leave the disk untouched.
    state = {"done": 0}

    def progress(done: int, total: int) -> None:
        state["done"] = max(state["done"], done)

    confirm_three(tmp_path)
    with pytest.raises(relearn.RelearnCancelled):
        relearn.run_relearn(progress=progress, cancelled=lambda: state["done"] >= 3)

    assert state["done"] == 3
    assert not os.path.exists(gts.user_profile_path())


def test_cancelled_rerun_leaves_existing_profile_and_backup_alone(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    before = _profile_bytes()

    with pytest.raises(relearn.RelearnCancelled) as excinfo:
        relearn.run_relearn(cancelled=lambda: True)

    assert str(excinfo.value) == relearn.CANCELLED_MESSAGE
    assert isinstance(excinfo.value, relearn.RelearnError)  # worker-catchable
    assert _profile_bytes() == before
    assert not os.path.exists(gts.user_profile_backup_path())


# ---------------------------------------------------------------------------
# Concurrent-reader safety: os.replace publishes old-or-new, never torn
# ---------------------------------------------------------------------------


def test_concurrent_reader_never_sees_torn_profile(tmp_path, monkeypatch):
    """Reader threads hammer validate_profile_file while relearn republishes
    the profile in a tight loop; with the atomic publish, every single read
    validates. (The DSP is stubbed so each iteration is milliseconds — the
    point is the write pattern, not the audio; no real audio runs, per the
    house rules.)"""
    confirm_three(tmp_path)
    relearn.run_relearn()  # a real seed profile to re-serialize
    profile_path = gts.user_profile_path()
    seed = copy.deepcopy(fp_engine.load_fingerprint(profile_path))

    import rai_analyzer.io_audio as io_audio
    import rai_analyzer.tempogram as tempogram

    monkeypatch.setattr(io_audio, "load_audio", lambda path: object())
    monkeypatch.setattr(tempogram, "build_features", lambda signal, cfg: object())
    monkeypatch.setattr(
        fp_engine, "learn_fingerprint", lambda items, cfg: copy.deepcopy(seed)
    )

    stop = threading.Event()
    invalid_reads: list[int] = []
    checks = {"n": 0}

    def reader() -> None:
        while not stop.is_set():
            if not gts.validate_profile_file(profile_path):
                invalid_reads.append(checks["n"])
            checks["n"] += 1

    readers = [threading.Thread(target=reader) for _ in range(2)]
    for t in readers:
        t.start()
    try:
        for _ in range(40):  # 40 atomic republishes under reader fire
            report = relearn.run_relearn()
            assert report.learned == 3
    finally:
        stop.set()
        for t in readers:
            t.join()

    assert invalid_reads == []  # never torn: old bytes or new bytes only
    assert checks["n"] > 100  # the hammer actually hammered
    assert gts.validate_profile_file(profile_path) is True


# ---------------------------------------------------------------------------
# profile_state — the popover payload
# ---------------------------------------------------------------------------


def test_profile_state_packaged_before_any_relearn(tmp_path):
    state = relearn.profile_state()
    assert state.kind == "packaged"
    assert state.relearned_at is None
    assert state.confirmed_count == 0
    assert state.backup_exists is False

    confirm_three(tmp_path)
    state = relearn.profile_state()
    assert state.kind == "packaged"  # confirmations alone don't switch source
    assert state.confirmed_count == 3


def test_profile_state_user_after_relearn(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    state = relearn.profile_state()
    assert state.kind == "user"
    assert state.relearned_at is not None
    assert len(state.relearned_at) == 10  # the ISO date part, YYYY-MM-DD
    assert state.confirmed_count == 3
    assert state.backup_exists is False

    confirm_wav(tmp_path, "click120.wav", 120.0)
    relearn.run_relearn()
    state = relearn.profile_state()
    assert state.backup_exists is True


def test_profile_state_invalid_user_file_reports_packaged(tmp_path):
    # The source line reports what the engine READS (R-M3-12): an invalid
    # user file falls back to packaged, and so must the popover.
    path = gts.user_profile_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    state = relearn.profile_state()
    assert state.kind == "packaged"
    assert state.relearned_at is None


# ---------------------------------------------------------------------------
# sweep_orphan_tmp_profiles (M5) — hard-kill hygiene, startup-only
# ---------------------------------------------------------------------------


def _fingerprints_dir() -> str:
    return os.path.dirname(gts.user_profile_path())


def _reaped_pid() -> int:
    """A pid guaranteed dead: spawn-and-reap a trivial subprocess."""
    import subprocess

    child = subprocess.Popen(["/usr/bin/true"])
    child.wait()
    return child.pid


def test_sweep_removes_planted_orphans_and_reports_count(isolated_store):
    fdir = _fingerprints_dir()
    os.makedirs(fdir, exist_ok=True)
    # Dead-pid + unparseable suffixes = the genuinely inert strays; a fixed
    # literal pid could be LIVE on a real machine (the sweep now probes
    # liveness — M5 review finding), so tests must plant provably-dead ones.
    orphans = [
        os.path.join(fdir, f"drill.user.json.tmp-{_reaped_pid()}"),
        os.path.join(fdir, "drill.user.json.tmp-notapid"),
    ]
    for path in orphans:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{}")

    assert relearn.sweep_orphan_tmp_profiles() == 2
    for path in orphans:
        assert not os.path.exists(path)
    # Idempotent: a second sweep finds nothing.
    assert relearn.sweep_orphan_tmp_profiles() == 0


def test_sweep_skips_a_live_owners_staging_temp(isolated_store):
    """Cross-instance safety (M5 review finding): a temp whose embedded pid
    is a LIVE process may be another instance's in-flight relearn staging —
    the sweep must leave it alone."""
    fdir = _fingerprints_dir()
    os.makedirs(fdir, exist_ok=True)
    live = os.path.join(fdir, f"drill.user.json.tmp-{os.getpid()}")
    with open(live, "w", encoding="utf-8") as fh:
        fh.write("{}")
    assert relearn.sweep_orphan_tmp_profiles() == 0
    assert os.path.exists(live)
    os.unlink(live)


def test_sweep_leaves_live_profile_and_backup_alone(tmp_path):
    confirm_three(tmp_path)
    relearn.run_relearn()
    confirm_wav(tmp_path, "click120.wav", 120.0)
    relearn.run_relearn()  # second run writes the backup too
    profile, backup = gts.user_profile_path(), gts.user_profile_backup_path()
    assert os.path.exists(profile) and os.path.exists(backup)

    orphan = os.path.join(_fingerprints_dir(), f"drill.user.json.tmp-{_reaped_pid()}")
    with open(orphan, "w", encoding="utf-8") as fh:
        fh.write("{}")

    assert relearn.sweep_orphan_tmp_profiles() == 1
    assert not os.path.exists(orphan)
    assert os.path.exists(profile) and os.path.exists(backup)
    assert relearn.profile_state().kind == "user"  # still valid, still read


def test_sweep_on_absent_store_is_a_quiet_noop_that_creates_nothing(isolated_store):
    # A fresh machine has no store at all; the sweep must neither raise nor
    # CREATE the directory (R-M3-2: only deliberate acts build the store).
    assert not os.path.exists(_fingerprints_dir())
    assert relearn.sweep_orphan_tmp_profiles() == 0
    assert not os.path.exists(_fingerprints_dir())


def test_sweep_single_call_site_is_mainwindow_init():
    """The mid-relearn-safety argument is STRUCTURAL: a live relearn's staged
    temp cannot be swept because the sweep's only call site runs before any
    relearn can exist (MainWindow.__init__ — no window, no controller, no
    relearn). This test turns that argument into a detector: relearn.py must
    define but never call the sweep (in particular, never from run_relearn or
    the worker), and main_window.py must call it exactly once, from inside
    ``MainWindow.__init__``. AST-only — no Qt import, runs in both venvs.
    """
    import ast
    import inspect

    def _sweep_calls(tree: ast.AST) -> list[ast.Call]:
        return [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                getattr(node.func, "id", None) == "sweep_orphan_tmp_profiles"
                or getattr(node.func, "attr", None) == "sweep_orphan_tmp_profiles"
            )
        ]

    # 1. The service module never calls its own sweep.
    relearn_tree = ast.parse(inspect.getsource(relearn))
    assert _sweep_calls(relearn_tree) == [], (
        "relearn.py must never call sweep_orphan_tmp_profiles — a sweep "
        "inside the relearn machinery could race its own staged temp"
    )

    # 2. main_window.py calls it exactly once, inside MainWindow.__init__.
    mw_path = os.path.join(
        os.path.dirname(os.path.abspath(relearn.__file__)), "..", "main_window.py"
    )
    with open(mw_path, "r", encoding="utf-8") as fh:
        mw_tree = ast.parse(fh.read(), filename=mw_path)
    all_calls = _sweep_calls(mw_tree)
    assert len(all_calls) == 1, "expected exactly ONE sweep call site app-wide"

    init_calls = []
    for node in ast.walk(mw_tree):
        if isinstance(node, ast.ClassDef) and node.name == "MainWindow":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    init_calls = _sweep_calls(item)
    assert len(init_calls) == 1, "the one sweep call must live in MainWindow.__init__"


# The QThread worker/controller tests live in
# tests/ui/test_relearn_controller.py (module-level PySide6/pytestqt skips —
# the engine venv has no qtbot fixture, so they cannot share this module).
