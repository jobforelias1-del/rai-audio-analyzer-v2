# Changelog

All notable changes to RAI Audio Analyzer v2 are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project aims to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 2026-05-30

Build-pipeline reproducibility + the "Fixette-shape" ambiguity fix. The macOS
`.app` built and launched on the producer's Apple Silicon Mac (macOS 26.5,
Python 3.14) only after a chain of six **local-only** patches applied during a
2026-05-30 session. None of those patches were committed, so a fresh clone of
`main` reproduced every failure they fixed. This release commits them and adds
the held-out-test fix below.

### Fixed

- **PyInstaller spec path resolution** (`build/RAIAudioAnalyzer.spec`).
  PyInstaller resolves relative paths in a spec file relative to the spec
  file's own directory (`build/`), not the current working directory, so the
  repo-root-relative paths (`rai_analyzer/gui.py`, `pathex=['.']`,
  `entitlements.plist`, the fingerprints glob) all failed to resolve. A `_ROOT`
  helper now derives the repo root from the injected `SPEC` global and every
  repo-root-relative path is joined onto it.
- **Cross-arch / cross-platform tkdnd bundling** (`build/RAIAudioAnalyzer.spec`).
  `tkinterdnd2` ships `tkdnd` libraries for every platform. Bundling them all
  let Tcl's un-pinned `package require tkdnd` pick the highest version it found
  — the wrong-architecture `osx-x64` build (2.9.4 > arm64's 2.9.3) — which
  crashed at launch on Apple Silicon. The spec now bundles only the
  host-matching macOS subdirectory (`osx-arm64` / `osx-x64`).
- **Drag-and-drop fallback on Python 3.13+** (`rai_analyzer/gui.py`).
  tkdnd 2.9.x is built against **Tcl/Tk 8.x** and does not load against the
  **Tcl/Tk 9.x** that ships with Python 3.13+. The loader raises
  `RuntimeError: Unable to load tkdnd library`, not `ImportError`, so the
  narrow `except ImportError` never caught it and the app crashed at startup.
  The bootstrap now catches `Exception`, so drag-drop is cleanly disabled on
  Tcl/Tk 9 while the app still launches and works via the file picker.
- **Relative imports under PyInstaller script-mode** (`rai_analyzer/gui.py`).
  PyInstaller runs `gui.py` as a top-level script with no parent package, so
  the lazy relative imports in `_run_analysis()` raised
  `ImportError: attempted relative import with no known parent package` the
  first time a file was loaded. They are now absolute
  (`from rai_analyzer.… import …`), which behaves identically under
  `python -m rai_analyzer.gui` and additionally works in the frozen app.
- **"Fixette-shape" ambiguity hole** (`rai_analyzer/resolver.py`,
  `rai_analyzer/config.py`). In the 2026-05-30 held-out commercial-drill test,
  Ziak — *Fixette* produced a primary of 146.57 BPM against an ear-anchored
  DAW-warp truth of 140.99 BPM. Both sit inside the drill canonical band
  (140–170), so the out-of-band trigger never fired; and the closest competitor
  scored ~85% of the primary — but the score-clustering trigger only fired for
  octave/fractional runner-ups, and a competitor only ~4% from the primary
  classifies as *near-unison* (`SELF`), not octave/fractional. The result was a
  confident-but-wrong primary, unflagged — a violation of the engine's
  never-silently-pick contract. The score-clustering trigger now also fires on
  a near-unison runner-up, closing the hole.

### Added

- **Application icon** (`build/RAIAudioAnalyzer.icns`) and its wiring in the
  spec's `BUNDLE` block (previously `icon=None`). The committed icon is a valid
  multi-resolution `.icns` (32–1024 px, including the `ic12` 64 px type) with an
  on-brand tempogram motif; replace it byte-for-byte with final art at any time.
- **Unit tests for the Fixette shape** (`tests/test_resolver.py`): one asserting
  a near-unison in-band competitor at ~86% of the primary's score is flagged
  ambiguous, and a regression guard asserting a confident in-band primary whose
  competitor sits at ~72% stays unflagged.

### Changed

- **Score-clustering ambiguity threshold** tightened `0.82 → 0.80`
  (`AmbiguityParams.score_close_frac`) so the Fixette shape (competitor at
  ~0.85 of the primary's score) is flagged with margin while legitimately
  confident cases (competitor ≤ ~0.75; clean clicks ~0.59) stay unflagged. (The
  trigger flags when `runner / primary ≥ frac`, so the threshold must sit *below*
  the Fixette ratio — a higher value would fail to flag it.)

### Notes

- No fingerprint, dependency, or public-API changes; `tkinterdnd2` is retained
  (it still works on Python 3.12 / Tcl 8.6, and the fallback covers 3.13+).
- Existing unit suite stays green and the synthetic acceptance gate stays 3/3.
- The macOS `.app` itself can only be produced on macOS; this environment
  verifies spec syntax, the gui import path, and the host-arch tkdnd selection.
