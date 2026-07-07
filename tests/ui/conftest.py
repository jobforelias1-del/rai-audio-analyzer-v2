"""Shared fixtures for the UI test tree.

One job (M3, hard rule R-M3-2): NO test may ever read or write the user's
real ``~/Library/Application Support/RAI Audio Analyzer/``. Real-worker tests
now hash files, look up stored ground truth on completion, and probe for a
user fingerprint before every analysis — so the store's injectable directory
factory is redirected to a per-test temp dir for EVERY test in this tree,
autouse. Tests that need their own store simply monkeypatch the same factory
again (nesting is fine); tests that never touch the store pay one lambda.

Second job (adversarial-review finding 16 — the tripwire): the isolation
above is pure CONVENTION — every harness monkeypatches the one ``_store_dir``
symbol, and a future edit that resolves the path without the factory (a
direct ``expanduser``, ``QStandardPaths``, an import-time-cached
``journal_path()``) would write into Elias's real journal with every gate
green. ``_real_app_support_tripwire`` below turns that convention into a
detector: it stats the REAL directory (read-only) at session start and fails
the run at session end if the suite CREATED it. tests/conftest.py carries
the engine-venv mirror of the same tripwire.

``rai_ui.services.ground_truth_store`` is pure stdlib, so this conftest
imports cleanly in the Qt-less engine venv too.
"""

from __future__ import annotations

import os

import pytest

# The REAL per-user store location, computed independently of the store
# module (which tests monkeypatch) so the tripwire cannot be fooled by the
# very redirection it polices. Mirrors ground_truth_store._store_dir().
_REAL_APP_SUPPORT = os.path.expanduser(
    os.path.join("~", "Library", "Application Support", "RAI Audio Analyzer")
)


@pytest.fixture(autouse=True, scope="session")
def _real_app_support_tripwire():
    """Fail the session if the suite CREATED the real App Support dir.

    Read-only stats only — the tripwire itself must never touch the real
    directory (R-M3-2). If the directory legitimately exists before the run
    (the shipped app has been used on this machine), existence can't detect
    contamination; the per-test temp-dir isolation remains the defense and
    this fixture stays silent rather than false-positive on real user data.
    """
    existed_before = os.path.exists(_REAL_APP_SUPPORT)
    yield
    if not existed_before:
        assert not os.path.exists(_REAL_APP_SUPPORT), (
            "HARD DEFECT (R-M3-2): this test run CREATED the user's real "
            f"ground-truth store at {_REAL_APP_SUPPORT!r} — some code path "
            "resolved the store location without going through the "
            "monkeypatched ground_truth_store._store_dir factory."
        )


@pytest.fixture(autouse=True)
def _isolated_ground_truth_store(tmp_path, monkeypatch):
    from rai_ui.services import ground_truth_store

    store_dir = str(tmp_path / "gt-store")
    monkeypatch.setattr(ground_truth_store, "_store_dir", lambda: store_dir)
    return store_dir
