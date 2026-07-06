# Environment & build policy (v3 baseline, 2026-07-06)

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
| `requirements.lock.txt` | **The reproducible truth.** `pip freeze` of the verified working env (gate 3/3 green, 162 unit tests, 2026-07-06). Rebuild with `pip install -r requirements.lock.txt`. |
| `requirements.txt` | Human-maintained floors for the reference environment (includes GUI + packaging extras). |
| `pyproject.toml` | Loose library-style floors for installing `rai_analyzer` as a package (engine core only; GUI is the `[gui]` extra). |

When these disagree, the lockfile wins for reproducing the baseline; the
others are compatibility metadata.

## The verified baseline environment (2026-07-06)

- Interpreter: CPython **3.14.6** (`.venv`; originally created from Homebrew
  3.14.3 — see caveat below). Fine for **headless engine work and the
  validation gate**; the Tcl/Tk 9 poison only affects GUI/frozen builds.
- Key packages: numpy 2.4.6, scipy 1.17.1, librosa 0.11.0, soundfile 0.13.1,
  pyloudnorm 0.2.0, numba 0.65.1, matplotlib 3.10.9, tkinterdnd2 0.4.3,
  pyinstaller 6.20.0, pytest (added 2026-07-06 for the suite).
- Verified in this env: full unit suite green (162), real acceptance gate
  **3/3 PASS** on the md5-pinned fixtures, headless CLI ~1.7 s on a 7.5 s WAV.

**Caveat — venv drift under Homebrew:** `.venv/pyvenv.cfg` records 3.14.3 but
the interpreter now reports 3.14.6, because Homebrew upgraded Python underneath
the venv. This is exactly the class of silent environment change the lockfile
exists to survive; a from-scratch rebuild should prefer a uv/python.org
interpreter that nothing upgrades behind your back.

## Known-good commands

```bash
# unit suite
.venv/bin/python -m pytest -q

# real acceptance gate (exit code = verdict; md5-checks fixtures first)
.venv/bin/python -m validation

# headless analysis
.venv/bin/python -m rai_analyzer.cli path/to/track.wav --json
```
