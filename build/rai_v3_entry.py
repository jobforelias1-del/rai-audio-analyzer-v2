"""PyInstaller entry script for the v3 (PySide6) app.

PyInstaller's Analysis wants a *script*, not a package, as its entry point;
the real program lives in ``rai_ui.__main__.main``. Keeping this shim exactly
one import deep means the frozen .app and a developer's ``python -m rai_ui``
run byte-identical application code — the v2 lesson is that any divergence
between "what the terminal runs" and "what the bundle runs" is where the
dead-on-arrival bugs hide.
"""

from __future__ import annotations

import sys

from rai_ui.__main__ import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
