# Environment & build policy (v3 baseline 2026-07-06 · engine venv rebuilt uv-managed 2026-07-07)

## The one rule that matters

**Never build a shipped .app from Homebrew Python.** Homebrew Python 3.13+
links Tcl/Tk 9, and Tk 9.0.x is the root cause of both 2026 incidents:

1. **Dead drag-drop in the shipped 2.0.0** — tkinterdnd2 ships `tkdnd`
   binaries built for Tcl/Tk 8.6; they can never load into a bundled Tcl 9
   (`dlsym: cannot find symbol "tkdnd_Init"`).
2. **Dead-on-arrival crash on macOS 26.5** (2026-07-03 crash reports) — Tk
   9.0.3's aqua menu code trips an AppKit `NSMenuItem` assertion during root-
   window creation, an uncatchable SIGABRT. The fatal path only runs in a
   frozen, no-tty .app — **terminal runs of the same stack work**, so a
   post-build launch smoke test of the actual .app is mandatory; terminal
   testing alone will keep lying.

For any future frozen build: use a python.org or uv-managed CPython (Tk 8.6
on the tkinter era; irrelevant once the frontend is PySide6), from a fresh
venv, from a **clean git tree**, and smoke-test the built .app itself.

## Dependency declarations — precedence

| file | role |
| --- | --- |
| `requirements.lock.txt` | **The reproducible truth.** `uv pip freeze` of the verified working env (gate 3/3 green + byte-identical, full suite green, 2026-07-07). Regenerate with `uv pip freeze --python .venv/bin/python \| grep -v '^-e ' > requirements.lock.txt` (the project's own editable line is excluded — it is machine-specific and installed separately with `-e .`). Rebuild with `uv pip install --python <venv>/bin/python -r requirements.lock.txt`. |
| `requirements.txt` | Human-maintained floors for the engine reference environment (+ PyInstaller for packaging). The tkinter-GUI extras (matplotlib, tkinterdnd2) were retired with `rai_analyzer/gui.py` in the v3 cutover. |
| `pyproject.toml` | Loose library-style floors for installing `rai_analyzer` as a package (engine core only). |

When these disagree, the lockfile wins for reproducing the baseline; the
others are compatibility metadata.

## The verified engine environment (rebuilt 2026-07-07, M5 cutover)

- Interpreter: **uv-managed CPython 3.14.5** (`.venv`; created with
  `uv venv --python 3.14 --python-preference only-managed .venv` — the same
  discipline as `.venv-v3`, M0 landmine 3: plain `--python 3.14` happily
  resolves to Homebrew). Verify with `sys.base_prefix` — it must point into
  `~/.local/share/uv/python/`, never Homebrew.
- Installed with `uv pip install --python .venv/bin/python -r
  requirements.txt -e . pytest "numba>=0.65"` (the numba floor is now in
  requirements.txt itself — without it the resolver can backtrack onto an
  ancient uncapped numba when the newest numpy excludes the modern ones).
- Key packages: numpy 2.4.6, scipy 1.18.0, librosa 0.11.0, soundfile 0.14.0,
  pyloudnorm 0.2.0, numba 0.66.0, pyinstaller 6.21.0, pytest 9.1.1.
- Verified in this env: full engine suite green, real acceptance gate
  **3/3 PASS byte-identical** to `docs/baselines/gate-reference-v3baseline.txt`
  on the md5-pinned fixtures, `rai-analyze` console script live.
- One suite delta vs the pre-rebuild env: `tests/ui/test_fonts_cmap.py` now
  SKIPs here (fontTools was only ever present as a matplotlib transitive,
  retired with the GUI extras); the D10 cmap gate still runs in `.venv-v3`,
  which pins fonttools.

**History — the Homebrew drift caveat (resolved 2026-07-07):** the previous
`.venv` was created from Homebrew 3.14.3 and silently became 3.14.6 when
Homebrew upgraded Python underneath it — exactly the class of change the
lockfile exists to survive. The M5 cutover replaced it with the uv-managed
env above (old env parked at `.venv-old-homebrew/` for rollback until
close-out; nothing upgrades a uv-managed interpreter behind your back).

## Known-good commands

```bash
# unit suite
.venv/bin/python -m pytest -q

# real acceptance gate (exit code = verdict; md5-checks fixtures first)
.venv/bin/python -m validation

# headless analysis
.venv/bin/python -m rai_analyzer.cli path/to/track.wav --json
```
