"""Build provenance constants, stamped at freeze time.

This file is the DEV STUB. ``build/build_macos_v3.sh`` overwrites it with the
real commit hash / tag / UTC timestamp for the duration of a frozen build,
then restores this stub (``git checkout -- rai_ui/_buildinfo.py``) so the
working tree stays clean.

WHY a module and not a runtime `git rev-parse`: there is no git (and no repo)
inside a frozen .app, and the v2 postmortem showed we must be able to prove
*which* commit a bundle was built from when a shipped build misbehaves. The
smoke probe reports ``COMMIT`` in its JSON and ``build/smoke_frozen.sh``
asserts it matches HEAD — a "dev" commit in a frozen bundle means the build
bypassed the build script.
"""

from __future__ import annotations

COMMIT = "dev"
TAG = ""
BUILD_UTC = ""
