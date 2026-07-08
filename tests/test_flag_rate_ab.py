"""Tests for tools/flag_rate_ab.py (M5) — synthetic WAVs, temp profiles only.

HARD RULES under test, not just honored: the given profile JSON must never be
opened for write (proven by handing the tool a chmod-0o444 file and pinning
its bytes), and the engine must only ever read a TEMP COPY of it. Everything
runs against pytest temp dirs — never the real App Support store (the
session tripwire in tests/conftest.py detects violations independently).

The tool is loaded by file path (the tests/ui/test_theme.py precedent) so the
import works identically in both venvs regardless of namespace-package
resolution. Engine-venv collectable: no Qt anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat

import pytest

from rai_analyzer.config import DEFAULT_CONFIG
from rai_analyzer.evidence.fingerprint import learn_fingerprint, save_fingerprint
from rai_analyzer.io_audio import load_audio
from rai_analyzer.synthetic import click_track, write_wav
from rai_analyzer.tempogram import build_features

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "flag_rate_ab", os.path.join(_REPO_ROOT, "tools", "flag_rate_ab.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ab = _load_tool()

_CORPUS_BPMS = (140.0, 150.0, 165.0)


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Three tiny synthetic click WAVs in one directory."""
    d = tmp_path_factory.mktemp("ab-corpus")
    paths = [
        write_wav(str(d / f"click{int(bpm)}.wav"), click_track(bpm, duration=6.0))
        for bpm in _CORPUS_BPMS
    ]
    return str(d), paths


@pytest.fixture(scope="module")
def learned_profile(tmp_path_factory, corpus):
    """A REAL learn_fingerprint-built profile (never the user's) on disk."""
    _, paths = corpus
    items = []
    for path, bpm in zip(paths, _CORPUS_BPMS):
        items.append((build_features(load_audio(path), DEFAULT_CONFIG), bpm))
    out = str(tmp_path_factory.mktemp("ab-profile") / "learned.user.json")
    save_fingerprint(learn_fingerprint(items, DEFAULT_CONFIG), out)
    return out


@pytest.fixture(scope="module")
def report(corpus, learned_profile):
    """One shared A/B run (module-scoped: 2N analyses are the slow part)."""
    _, paths = corpus
    return ab.run_ab(paths, learned_profile)


# ---------------------------------------------------------------------------
# run_ab — shape, consistency, and the hard rules
# ---------------------------------------------------------------------------


def test_report_shape_and_flip_consistency(report, corpus, learned_profile):
    _, paths = corpus
    assert report["profile_json"] == os.path.abspath(learned_profile)
    assert len(report["rows"]) == len(paths)
    for row in report["rows"]:
        assert "error" not in row, row
        assert set(row) == {
            "name",
            "path",
            "packaged_ambiguous",
            "packaged_bpm",
            "profiled_ambiguous",
            "profiled_bpm",
            "flipped",
        }
        assert row["flipped"] == (row["packaged_ambiguous"] != row["profiled_ambiguous"])
        assert row["packaged_bpm"] > 0 and row["profiled_bpm"] > 0

    s = report["summary"]
    rows = report["rows"]
    assert s["files"] == s["analyzed"] == len(rows) and s["errors"] == 0
    assert s["packaged_flagged"] == sum(r["packaged_ambiguous"] for r in rows)
    assert s["profiled_flagged"] == sum(r["profiled_ambiguous"] for r in rows)
    assert s["flips"] == sum(r["flipped"] for r in rows)


def test_report_is_json_serializable(report):
    parsed = json.loads(json.dumps(report))
    assert parsed["summary"]["files"] == len(parsed["rows"])


def test_packaged_lane_matches_a_direct_default_analysis(report, corpus):
    """The A lane must be exactly what the CLI/gate would say (fresh default
    TempoConfig) — pin one file against a direct analyze_file run."""
    from rai_analyzer.analyzer import analyze_file
    from rai_analyzer.config import TempoConfig

    _, paths = corpus
    direct = analyze_file(paths[0], cfg=TempoConfig(), with_loudness=False)
    row = report["rows"][0]
    assert row["packaged_bpm"] == float(direct.tempo.primary_bpm)
    assert row["packaged_ambiguous"] == bool(direct.tempo.ambiguous)


def test_profile_source_is_never_opened_for_write(corpus, learned_profile, tmp_path):
    """A read-only (0o444) profile must work — copyfile reads it — and its
    bytes must be identical afterwards. This is the R-M5 hard rule: the tool
    may only inject a temp COPY, never touch the given file."""
    _, paths = corpus
    guarded = str(tmp_path / "readonly.user.json")
    with open(learned_profile, "rb") as fh:
        original = fh.read()
    with open(guarded, "wb") as fh:
        fh.write(original)
    os.chmod(guarded, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 0o444

    try:
        out = ab.run_ab(paths[:1], guarded)
    finally:
        os.chmod(guarded, stat.S_IRUSR | stat.S_IWUSR)  # restorable temp cleanup
    assert "error" not in out["rows"][0]
    with open(guarded, "rb") as fh:
        assert fh.read() == original


def test_injected_path_is_a_temp_copy_not_the_original(
    corpus, learned_profile, monkeypatch
):
    """Spy on FingerprintParams: the fingerprint_path the engine receives must
    never be the given profile path (it must be the private temp copy)."""
    from rai_analyzer import config as config_mod

    seen: list[str] = []
    real_params = config_mod.FingerprintParams

    def spying_params(*args, **kwargs):
        params = real_params(*args, **kwargs)
        if params.fingerprint_path is not None:
            seen.append(params.fingerprint_path)
        return params

    monkeypatch.setattr(config_mod, "FingerprintParams", spying_params)
    _, paths = corpus
    ab.run_ab(paths[:1], learned_profile)
    assert seen, "the profiled lane never injected a fingerprint_path"
    for injected in seen:
        assert injected != os.path.abspath(learned_profile)
        assert os.path.basename(injected) == "profile-under-test.json"
        assert not os.path.exists(injected)  # temp dir is gone after the run


def test_missing_profile_raises_filenotfound(corpus):
    _, paths = corpus
    with pytest.raises(FileNotFoundError):
        ab.run_ab(paths[:1], "/nonexistent/profile.json")


def test_unreadable_wav_is_a_row_error_not_a_crash(tmp_path, learned_profile):
    bad = str(tmp_path / "not-audio.wav")
    with open(bad, "wb") as fh:
        fh.write(b"RIFFgarbage")
    out = ab.run_ab([bad], learned_profile)
    assert "error" in out["rows"][0]
    assert out["summary"] == {
        "files": 1,
        "analyzed": 0,
        "errors": 1,
        "packaged_flagged": 0,
        "profiled_flagged": 0,
        "flips": 0,
    }


# ---------------------------------------------------------------------------
# corpus collection + default profile path
# ---------------------------------------------------------------------------


def test_collect_wavs_expands_dirs_files_and_dedups(corpus, tmp_path):
    corpus_dir, paths = corpus
    (tmp_path / "notes.txt").write_text("not audio")
    got = ab.collect_wavs([corpus_dir, paths[0], str(tmp_path)])
    assert [os.path.abspath(p) for p in got] == [os.path.abspath(p) for p in paths]


def test_default_profile_path_respects_injected_store_dir(monkeypatch, tmp_path):
    # The default must resolve through the store's injectable factory
    # (R-M3-2) — same seam every store consumer uses, so tests/verify runs
    # can redirect it away from the real App Support dir.
    from rai_ui.services import ground_truth_store as gts

    monkeypatch.setattr(gts, "_store_dir", lambda: str(tmp_path / "store"))
    assert ab.default_profile_path() == str(
        tmp_path / "store" / "fingerprints" / "drill.user.json"
    )


# ---------------------------------------------------------------------------
# rendering + CLI surface
# ---------------------------------------------------------------------------


def test_markdown_render(report):
    md = ab.render_markdown(report)
    for row in report["rows"]:
        assert row["name"] in md
    assert "| File | Packaged | Profiled | Flipped |" in md
    assert "**Flag rate:**" in md
    assert "flip(s)" in md


def test_main_json_mode_and_exit_codes(corpus, learned_profile, capsys, tmp_path):
    corpus_dir, paths = corpus
    rc = ab.main([paths[0], "--profile-json", learned_profile, "--json"])
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["summary"]["files"] == 1

    # No WAVs found → 2, and a missing profile → 2 (both usage errors).
    empty = tmp_path / "empty"
    empty.mkdir()
    assert ab.main([str(empty), "--profile-json", learned_profile]) == 2
    assert ab.main([paths[0], "--profile-json", "/nope.json"]) == 2
