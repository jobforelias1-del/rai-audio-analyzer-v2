"""Ground-truth store unit tests (rulings R-M3-1/2/19).

Pure stdlib module — these tests run Qt-less (engine venv collects them).
Every test operates against the autouse per-test temp store dir from
``tests/ui/conftest.py``; the user's real App Support dir is asserted-on as a
STRING only, never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid as uuid_mod

import pytest

from rai_ui.services import ground_truth_store as gts


@pytest.fixture
def store_dir(_isolated_ground_truth_store):
    """The per-test temp store dir (autouse-isolated in conftest)."""
    return _isolated_ground_truth_store


def _journal_lines() -> list[dict]:
    with open(gts.journal_path(), "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_journal_raw(text: str) -> None:
    os.makedirs(os.path.dirname(gts.journal_path()), exist_ok=True)
    with open(gts.journal_path(), "w", encoding="utf-8") as fh:
        fh.write(text)


# ---------------------------------------------------------------------------
# Paths + factory (R-M3-1/2)
# ---------------------------------------------------------------------------


def test_default_store_dir_is_the_plan_path_orgless(monkeypatch):
    """The R-M3-1 path: App Support WITHOUT an org segment. String-level
    assertion only — the real dir is never opened."""
    monkeypatch.undo()  # drop the autouse isolation for this one string check
    default = gts._store_dir()
    assert default == os.path.expanduser(
        "~/Library/Application Support/RAI Audio Analyzer"
    )
    assert "SiliconClick" not in default  # NOT the QStandardPaths org form


def test_paths_route_through_the_injectable_factory(store_dir):
    assert gts.journal_path() == os.path.join(store_dir, "ground_truth.jsonl")
    assert gts.user_profile_path() == os.path.join(
        store_dir, "fingerprints", "drill.user.json"
    )
    assert gts.user_profile_backup_path() == os.path.join(
        store_dir, "fingerprints", "drill.user.backup.json"
    )


# ---------------------------------------------------------------------------
# md5 helper (R-M3-19: reimplemented, never imported from validation)
# ---------------------------------------------------------------------------


def test_file_md5_matches_hashlib_whole_file(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"drill" * 7)
    assert gts.file_md5(str(p)) == hashlib.md5(b"drill" * 7).hexdigest()


def test_file_md5_chunked_read_spans_chunk_boundary(tmp_path):
    data = os.urandom((1 << 20) + 12345)  # > one 1 MiB chunk
    p = tmp_path / "big.bin"
    p.write_bytes(data)
    assert gts.file_md5(str(p)) == hashlib.md5(data).hexdigest()


def test_file_md5_missing_file_raises():
    with pytest.raises(OSError):
        gts.file_md5("/nonexistent/nowhere.wav")


# ---------------------------------------------------------------------------
# Append + record shape (R-M3-1)
# ---------------------------------------------------------------------------


def test_confirm_record_shape(store_dir):
    gts.append_confirm(md5="abc123", bpm=155.25, name="beat.wav", path="/tmp/beat.wav")
    (rec,) = _journal_lines()
    assert rec["v"] == 1
    assert rec["kind"] == "confirm"
    uuid_mod.UUID(rec["id"])  # a real uuid, or this raises
    assert rec["md5"] == "abc123"
    assert rec["bpm"] == 155.25
    assert rec["name"] == "beat.wav"
    assert rec["path"] == "/tmp/beat.wav"  # additive over R-M3-1 — relearn needs it
    assert rec["at"].endswith("Z") and "T" in rec["at"]  # ISO-8601 UTC


def test_retract_record_shape(store_dir):
    gts.append_retract("abc123")
    (rec,) = _journal_lines()
    assert rec["v"] == 1
    assert rec["kind"] == "retract"
    uuid_mod.UUID(rec["id"])
    assert rec["retracts_md5"] == "abc123"
    assert rec["at"].endswith("Z")


def test_append_is_append_only(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    gts.append_confirm(md5="m2", bpm=120.0, name="b.wav")
    gts.append_retract("m1")
    kinds = [r["kind"] for r in _journal_lines()]
    assert kinds == ["confirm", "confirm", "retract"]  # nothing rewritten


# ---------------------------------------------------------------------------
# Replay: last-wins, retraction clears, corrupt tolerance
# ---------------------------------------------------------------------------


def test_missing_journal_is_empty_truth(store_dir):
    assert gts.effective_truths() == {}
    assert gts.lookup("anything") is None
    assert gts.confirmed_count() == 0


def test_lookup_roundtrip(store_dir):
    gts.append_confirm(md5="m1", bpm=155.25, name="beat.wav", path="/x/beat.wav")
    truth = gts.lookup("m1")
    assert truth is not None
    assert truth.bpm == 155.25
    assert truth.name == "beat.wav"
    assert truth.path == "/x/beat.wav"
    assert gts.confirmed_count() == 1


def test_last_record_per_md5_wins(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    gts.append_confirm(md5="m1", bpm=200.0, name="a.wav")
    assert gts.lookup("m1").bpm == 200.0
    assert gts.confirmed_count() == 1  # re-confirm is not a second file


def test_retract_clears_and_reconfirm_restores(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    gts.append_retract("m1")
    assert gts.lookup("m1") is None
    assert gts.confirmed_count() == 0
    gts.append_confirm(md5="m1", bpm=140.0, name="a.wav")
    assert gts.lookup("m1").bpm == 140.0


def test_retract_of_unknown_md5_is_harmless(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    gts.append_retract("never-confirmed")
    assert gts.lookup("m1").bpm == 100.0


def test_corrupt_lines_are_skipped_never_fatal(store_dir):
    good1 = json.dumps(
        {"v": 1, "kind": "confirm", "id": "x", "md5": "m1", "bpm": 100.0,
         "name": "a.wav", "at": "2026-07-07T00:00:00Z"}
    )
    good2 = json.dumps(
        {"v": 1, "kind": "confirm", "id": "y", "md5": "m2", "bpm": 120.0,
         "name": "b.wav", "at": "2026-07-07T00:00:01Z"}
    )
    corrupt = [
        "{not json at all",  # parse failure
        json.dumps({"v": 1, "kind": "confirm", "id": "z"}),  # missing md5/bpm
        json.dumps({"v": 1, "kind": "confirm", "md5": "m3", "bpm": -5.0}),  # bpm <= 0
        json.dumps({"v": 1, "kind": "confirm", "md5": "m4", "bpm": "NaN"}),
        json.dumps({"v": 1, "kind": "party", "md5": "m5"}),  # unknown kind
        json.dumps(["a", "list"]),  # not an object
        '{"v": 1, "kind": "conf',  # the crash-torn trailing write
    ]
    _write_journal_raw(
        good1 + "\n" + "\n".join(corrupt[:3]) + "\n" + good2 + "\n"
        + "\n".join(corrupt[3:]) + "\n"
    )
    truths = gts.effective_truths()
    assert set(truths) == {"m1", "m2"}
    assert truths["m1"].bpm == 100.0
    assert truths["m2"].bpm == 120.0


def test_blank_lines_tolerated(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    with open(gts.journal_path(), "a", encoding="utf-8") as fh:
        fh.write("\n\n")
    gts.append_confirm(md5="m2", bpm=120.0, name="b.wav")
    assert set(gts.effective_truths()) == {"m1", "m2"}


def test_record_without_path_tolerated(store_dir):
    """R-M3-1's literal schema has no ``path`` — readers must accept it."""
    _write_journal_raw(
        json.dumps(
            {"v": 1, "kind": "confirm", "id": "x", "md5": "m1", "bpm": 99.0,
             "name": "a.wav", "at": "2026-07-07T00:00:00Z"}
        )
        + "\n"
    )
    truth = gts.lookup("m1")
    assert truth.bpm == 99.0
    assert truth.path == ""


def test_lookup_empty_md5_is_none(store_dir):
    gts.append_confirm(md5="m1", bpm=100.0, name="a.wav")
    assert gts.lookup("") is None
    assert gts.lookup(None) is None


# ---------------------------------------------------------------------------
# User-profile validation (R-M3-12)
# ---------------------------------------------------------------------------


def _write_profile(payload) -> str:
    path = gts.user_profile_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh)
    return path


def _valid_profile() -> dict:
    bins = [0.0] * 16
    bins[0] = 1.0
    return {
        "low": list(bins),
        "mid": list(bins),
        "high": list(bins),
        "_meta": {"source": "test"},
    }


def test_validate_accepts_the_save_fingerprint_shape(store_dir):
    assert gts.validate_profile_file(_write_profile(_valid_profile())) is True


def test_validate_accepts_the_packaged_fingerprint(store_dir):
    """The engine's own drill.json must validate — same format contract."""
    packaged = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "rai_analyzer",
        "fingerprints",
        "drill.json",
    )
    assert gts.validate_profile_file(packaged) is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("low"),  # missing band
        lambda p: p.__setitem__("mid", "not-a-list"),
        lambda p: p.__setitem__("high", [0.5] * 15),  # wrong bin count
        lambda p: p["low"].__setitem__(0, float("nan")),
        lambda p: p["low"].__setitem__(0, float("inf")),
        lambda p: p["low"].__setitem__(0, -0.5),  # negative energy
        lambda p: p["mid"].__setitem__(3, "0.5"),  # stringly-typed bin
        lambda p: p["mid"].__setitem__(3, True),  # bool is not a number here
    ],
)
def test_validate_rejects_malformed_shapes(store_dir, mutate):
    profile = _valid_profile()
    mutate(profile)
    assert gts.validate_profile_file(_write_profile(profile)) is False


def test_validate_rejects_all_zero_profile(store_dir):
    profile = _valid_profile()
    for band in ("low", "mid", "high"):
        profile[band] = [0.0] * 16
    assert gts.validate_profile_file(_write_profile(profile)) is False


def test_validate_rejects_non_object_and_garbage_and_missing(store_dir):
    assert gts.validate_profile_file(_write_profile("[1, 2, 3]")) is False
    assert gts.validate_profile_file(_write_profile("{broken")) is False
    assert gts.validate_profile_file("/nonexistent/drill.user.json") is False
