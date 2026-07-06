# Changelog

All notable changes to RAI Audio Analyzer v2 are recorded here. Dates are in
ISO-8601. The acceptance gate (`python -m validation`) is the source of truth
for behavioural changes; unit tests guard the mechanisms.

## [Unreleased]

### Fixed — octave/alias recall + confidently-wrong detection

Two distinct structural failures, both surfaced by the variant Ledger/Mathematics
runs against the DAW-warp-confirmed ground truth:

- **The 5:4-family alias miss (recall).** Candidate generation could not reach a
  5:4-family ratio of the dominant lock, so `mathematics_of_the_menace.wav`
  (true **153.85 BPM**) was never even surfaced as a candidate: 153.85 is `4/5`
  of a 192 BPM lock, and no octave/dotted/triplet multiplier can produce a
  4-against-5 ratio. The multiplier set is extended from
  `(1/3, 1/2, 2/3, 1, 3/2, 2, 3)` to
  `(1/3, 1/2, 5/8, 2/3, 3/4, 4/5, 1, 5/4, 4/3, 3/2, 8/5, 2, 3)` — adding the 5:4
  family (`4/5`, `5/4`) that the gate needs and the 5:8 hemiola family
  (`5/8`, `8/5`) that maps the documented `96 -> 153.6` tresillo alias. The
  candidate ceiling was lifted `200 -> 240 BPM` so a `5/4` alias of a fast lock
  (e.g. `5/4 * 192 = 240`) survives range-filtering to be scored and rejected
  rather than truncated away.

- **Confidently-wrong-not-flagged (reliability).** The variant runs reported
  primaries of `132.05` (Ledger) and `140.82` (Mathematics) — below the drill
  canonical band (140–170 BPM) — yet were **not flagged ambiguous**. The two
  existing triggers both assume *competition* (a prior fighting the raw signal,
  or a close-scoring octave runner-up); they are blind to a *single* dominant
  peak parked in a genre-implausible place with weak competition. Added a third
  ambiguity trigger: the result is flagged when the primary sits outside the
  genre band **and** a salient candidate sits inside it
  (`ambiguous = competitor_within_threshold OR primary_outside_genre_band`). The
  in-band salience floor keeps clean non-drill material (e.g. a 120 BPM
  metronome, whose only in-band candidates are zero-salience multiplier ghosts)
  from being reflexively flagged.

### Fixed — build-pipeline reproducibility (the 2026-05-30 local-only patches, committed)

The macOS `.app` built and launched on the producer's Apple Silicon Mac
(macOS 26.5, Python 3.14) only after a chain of **local-only** patches applied
during a 2026-05-30 session. None of those patches were committed, so a fresh
clone of `main` reproduced every failure they fixed. These entries commit them:

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
- **"Fixette-shape" ambiguity trigger widened** (`rai_analyzer/resolver.py`,
  `rai_analyzer/config.py`). In the 2026-05-30 held-out commercial-drill test,
  Ziak — *Fixette* produced a primary of 146.57 BPM against an ear-anchored
  DAW-warp truth of 140.99 BPM. Both sit inside the drill canonical band
  (140–170), so the out-of-band trigger never fired, and the score-clustering
  trigger only fired for octave/fractional runner-ups. `SELF` (near-unison) is
  now counted among the ambiguity-triggering relations.
  **Accuracy note (measured 2026-07-06):** this does *not* yet flag the real
  Fixette case — its actual runner-up (134.69 BPM, ~8% off the 146.57 primary)
  classifies as `UNRELATED` under the 4% ratio tolerance, outside the widened
  relation set. Extending the set to `UNRELATED` runners has been measured to
  flag Fixette (and the variant-bounce gate misses) but changes flag rates on
  otherwise-confident material; that extension is deferred to dedicated engine
  work with a corpus-wide flag-rate analysis. The widened trigger and tightened
  threshold below are kept as safe, monotone-toward-flagging groundwork.

### Added

- **Application icon** (`build/RAIAudioAnalyzer.icns`) and its wiring in the
  spec's `BUNDLE` block (previously `icon=None`). The committed icon is a valid
  multi-resolution `.icns` (32–1024 px, including the `ic12` 64 px type) with an
  on-brand tempogram motif; replace it byte-for-byte with final art at any time.
- **Unit tests for the Fixette shape** (`tests/test_resolver.py`): one asserting
  a near-unison in-band competitor at ~86% of the primary's score is flagged
  ambiguous, and a regression guard asserting a confident in-band primary whose
  competitor sits at ~72% stays unflagged. (These cover the trigger semantics
  with synthetic candidates; a test against the real Fixette shape is future
  work alongside the `UNRELATED` extension above.)

### Changed

- **Genre prior re-tuned for drill.** The soft log-normal prior kept its shape
  and 145 BPM centre, but the shoulders were tightened (`sigma 0.30 -> 0.24`,
  `floor 0.12 -> 0.10`; `fit_prior` clamp `min_sigma 0.18 -> 0.14`). The old
  broad tails handed a genre-implausible peak (~132 BPM) nearly as much prior
  weight as the notated band, which blunted the raw-vs-priored divergence
  trigger.
- **Score-clustering ambiguity threshold** tightened `0.82 → 0.80`
  (`AmbiguityParams.score_close_frac`) so a near-unison competitor at ~0.85 of
  the primary's score is flagged with margin while legitimately confident cases
  (competitor ≤ ~0.75; clean clicks ~0.59) stay unflagged. (The trigger flags
  when `runner / primary ≥ frac`, so the threshold must sit *below* the target
  ratio.)

### Notes

- No public API changes: `TempoResult`/`Candidate` shapes, the CLI, and the GUI
  surface are unchanged. New knobs (`AmbiguityParams.genre_band_min/max`,
  `band_evidence_floor`) are additive with drill-sensible defaults.
- Tests: `tests/test_candidates.py` asserts a 192 BPM base surfaces both the
  `4/5` (≈154) and `5/4` (240) aliases; `tests/test_resolver_ambiguity.py`
  covers the new out-of-band trigger, the click-safe salience floor, and a
  regression guard on the existing competitor-score trigger. The synthetic
  acceptance gate remains 3/3 PASS.
- No fingerprint, dependency, or public-API changes from the build-pipeline
  work; `tkinterdnd2` is retained (it still works on Python 3.12 / Tcl 8.6,
  and the fallback covers 3.13+).
