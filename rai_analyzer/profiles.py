"""Packaged tempo-profile registry — the CLI's ``--profile`` vocabulary.

PACKAGED profiles only (ruling R-M4-9): every entry here ships inside the
package and builds a plain :class:`~rai_analyzer.config.TempoConfig` from
code. User-learned profiles (the relearn flow's ``drill.user.json`` under
App Support) are GUI-worker territory — ``rai_ui.services.worker`` injects
them per analysis — and must NEVER appear here: the CLI and the validation
gate read no user data, ever (the Phase 3 plan's hard wall).

The registry maps a profile name to a zero-argument factory (not a shared
instance) so every caller gets a fresh, mutation-safe config. ``"drill"`` is
the packaged default and builds ``TempoConfig()`` — value-identical to
``DEFAULT_CONFIG`` by construction, which is what pins the CLI's
no-flag / ``--profile drill`` byte-identity (tests/test_cli_profile.py).
"""

from __future__ import annotations

from typing import Callable

from .config import TempoConfig

#: name -> zero-argument TempoConfig factory. Packaged-only; see module
#: docstring. ``TempoConfig`` itself is the drill factory: all-default
#: fields ARE the drill 140–170 tuning the engine shipped with.
PROFILES: dict[str, Callable[[], TempoConfig]] = {
    "drill": TempoConfig,
}

#: The CLI's default ``--profile`` choice.
DEFAULT_PROFILE = "drill"
