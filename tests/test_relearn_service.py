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

import json
import os

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


# The QThread worker/controller tests live in
# tests/ui/test_relearn_controller.py (module-level PySide6/pytestqt skips —
# the engine venv has no qtbot fixture, so they cannot share this module).
