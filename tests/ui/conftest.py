"""Shared fixtures for the UI test tree.

One job (M3, hard rule R-M3-2): NO test may ever read or write the user's
real ``~/Library/Application Support/RAI Audio Analyzer/``. Real-worker tests
now hash files, look up stored ground truth on completion, and probe for a
user fingerprint before every analysis — so the store's injectable directory
factory is redirected to a per-test temp dir for EVERY test in this tree,
autouse. Tests that need their own store simply monkeypatch the same factory
again (nesting is fine); tests that never touch the store pay one lambda.

``rai_ui.services.ground_truth_store`` is pure stdlib, so this conftest
imports cleanly in the Qt-less engine venv too.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolated_ground_truth_store(tmp_path, monkeypatch):
    from rai_ui.services import ground_truth_store

    store_dir = str(tmp_path / "gt-store")
    monkeypatch.setattr(ground_truth_store, "_store_dir", lambda: store_dir)
    return store_dir
