"""M3 gate-boundary test — ruling R-M3-13 (the M3 exit criterion).

Three walls, each proven from a different angle:

1. **AST fence** — ``validation/`` and ``rai_analyzer/`` never import
   ``rai_ui`` (so the gate CANNOT reach the store/profile machinery even by
   accident). Source-level, no imports executed: the Qt-less engine venv
   collects and runs this.
2. **Byte-identical gate under a populated user store** — a subprocess
   ``python -m validation`` runs with ``HOME`` pointed at a temp home whose
   ``Library/Application Support/RAI Audio Analyzer/`` contains a populated
   ground-truth journal AND an active (valid, packaged-divergent) user
   fingerprint; its stdout must equal ``docs/baselines/
   gate-reference-v3baseline.txt`` byte for byte. If the gate ever grew a
   read of the App Support dir, this is the test that turns red.
3. **The analyze path DOES change** — the same features resolve differently
   under an injected user profile (fresh ``TempoConfig``), proving the
   user-profile mechanism is live while the gate stays sealed; and
   ``DEFAULT_CONFIG`` is not mutated in the process.

Pure engine + stdlib imports (``rai_ui.services.ground_truth_store`` is
stdlib-only) — runs in both venvs.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_BASELINE = os.path.join(
    _REPO_ROOT, "docs", "baselines", "gate-reference-v3baseline.txt"
)

_FORBIDDEN = ("rai_ui",)  # any submodule too — rai_ui.services especially


# ---------------------------------------------------------------------------
# 1. AST fence
# ---------------------------------------------------------------------------


def _py_files(tree_root: str) -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(tree_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        out.extend(
            os.path.join(dirpath, n) for n in filenames if n.endswith(".py")
        )
    return sorted(out)


_GATE_FILES = _py_files(os.path.join(_REPO_ROOT, "validation")) + _py_files(
    os.path.join(_REPO_ROOT, "rai_analyzer")
)


def test_gate_trees_were_found():
    assert any(p.endswith("harness.py") for p in _GATE_FILES)
    assert any(p.endswith("resolver.py") for p in _GATE_FILES)


@pytest.mark.parametrize(
    "path", _GATE_FILES, ids=[os.path.relpath(p, _REPO_ROOT) for p in _GATE_FILES]
)
def test_gate_side_never_imports_rai_ui(path):
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    bad = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "rai_ui" or alias.name.startswith("rai_ui."):
                    bad.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "rai_ui" or node.module.startswith("rai_ui."):
                bad.add(node.module)
    assert not bad, f"{path} imports the UI layer: {sorted(bad)}"


# ---------------------------------------------------------------------------
# 2. Byte-identical gate with a populated store + active user profile
# ---------------------------------------------------------------------------


def _all_fixtures_present() -> bool:
    from validation.ground_truth import GROUND_TRUTH, available_tracks

    return len(available_tracks()) == len(GROUND_TRUTH)


def _populate_app_support(app_support_dir: str, monkeypatch) -> None:
    """A journal with effective confirmations + a valid, packaged-divergent
    user fingerprint, written through the real store APIs (same bytes a real
    confirm/relearn would produce)."""
    from rai_analyzer.config import DEFAULT_CONFIG
    from rai_analyzer.evidence.fingerprint import learn_fingerprint, save_fingerprint
    from rai_analyzer.synthetic import as_signal, drill_pattern
    from rai_analyzer.tempogram import build_features

    from rai_ui.services import ground_truth_store as gts

    monkeypatch.setattr(gts, "_store_dir", lambda: app_support_dir)
    gts.append_confirm(md5="a" * 32, bpm=155.25, name="one.wav", path="/x/one.wav")
    gts.append_confirm(md5="b" * 32, bpm=140.0, name="two.wav", path="/x/two.wav")
    gts.append_confirm(md5="c" * 32, bpm=166.0, name="three.wav", path="/x/three.wav")
    gts.append_retract("b" * 32)

    features = build_features(as_signal(drill_pattern(150.0, duration=8.0)), DEFAULT_CONFIG)
    profile = learn_fingerprint([(features, 100.0)], DEFAULT_CONFIG)
    save_fingerprint(profile, gts.user_profile_path())
    assert gts.validate_profile_file(gts.user_profile_path()) is True


@pytest.mark.skipif(
    not _all_fixtures_present(),
    reason="acceptance-gate fixtures not on disk — byte-compare undefined",
)
def test_gate_byte_identical_with_populated_user_store(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    app_support = fake_home / "Library" / "Application Support" / "RAI Audio Analyzer"
    _populate_app_support(str(app_support), monkeypatch)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)  # if the gate EVER reads ~, it reads THIS

    proc = subprocess.run(
        [sys.executable, "-m", "validation"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=600,
    )
    with open(_BASELINE, "rb") as fh:
        baseline = fh.read()

    assert proc.returncode == 0, proc.stdout.decode(errors="replace")
    assert proc.stdout == baseline, (
        "gate output drifted under a populated user store/profile — "
        "the M3 exit criterion is violated"
    )


# ---------------------------------------------------------------------------
# 3. The analyze path DOES change under an injected profile
# ---------------------------------------------------------------------------


def test_analyze_path_changes_under_injected_profile(tmp_path, features_drill_150):
    from rai_analyzer.config import DEFAULT_CONFIG, FingerprintParams, TempoConfig
    from rai_analyzer.evidence.fingerprint import (
        clear_fingerprint_cache,
        learn_fingerprint,
        save_fingerprint,
    )
    from rai_analyzer.resolver import resolve_tempo

    clear_fingerprint_cache()
    try:
        profile_path = str(tmp_path / "drill.user.json")
        save_fingerprint(
            learn_fingerprint([(features_drill_150, 100.0)], DEFAULT_CONFIG),
            profile_path,
        )

        packaged = resolve_tempo(features_drill_150, DEFAULT_CONFIG)
        injected_cfg = TempoConfig(
            fingerprint=FingerprintParams(fingerprint_path=profile_path)
        )
        injected = resolve_tempo(features_drill_150, injected_cfg)

        packaged_scores = [(c.bpm, c.score) for c in packaged.candidates]
        injected_scores = [(c.bpm, c.score) for c in injected.candidates]
        assert packaged_scores != injected_scores, (
            "an active user profile must change tempo scoring — "
            "otherwise relearning is theater"
        )
        # The deliberate visible act never mutates the shared singleton.
        assert DEFAULT_CONFIG.fingerprint.fingerprint_path is None
    finally:
        clear_fingerprint_cache()  # drop the temp profile from the path cache
