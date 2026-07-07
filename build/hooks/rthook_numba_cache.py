"""PyInstaller runtime hook: give numba a writable JIT-cache directory.

The frozen .app bundle is codesigned and must be treated as read-only; numba's
default cache location is *next to the source file that owns the jitted
function*, which lands inside the bundle and fails (or, worse, invalidates the
signature). Runtime hooks execute before any application import, so setting
NUMBA_CACHE_DIR here wins over numba's import-time configuration read.

An explicit NUMBA_CACHE_DIR already present in the environment is respected —
that is the documented escape hatch for debugging cache problems.
"""

import os

_CACHE_DIR = os.path.join(
    os.path.expanduser("~"), "Library", "Caches", "RAIAudioAnalyzer"
)

if "NUMBA_CACHE_DIR" not in os.environ:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    os.environ["NUMBA_CACHE_DIR"] = _CACHE_DIR
