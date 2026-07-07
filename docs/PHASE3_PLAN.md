# RAI v3 — Phase 3 Implementation Plan

**Date:** 2026-07-06 · **Status: PLAN — awaiting sign-off, no implementation started**
**Inputs:** repo tag `v3-baseline-phase0` (main `399e775`, gate GREEN 3/3) · tokens v0.1.1 (+v0.1.2 punch list pending from design) · approved artifacts 01–05 · Phase 1/2 reports.
**Method:** four parallel engineering deep-dives (engine-additive design, Qt architecture, audio+ground-truth, packaging+risk), each grounded in file:line evidence from the actual repo and artifacts, each critiquing the draft landing sequence. Their consensus reshaped the sequence (see §4).

---

## §0 · The two facts that shaped everything

1. **Stereo needs ZERO intake changes.** `AudioSignal.y_native` already preserves channels (io_audio typed `(n,) or (n, ch)`; loudness already iterates channels; `test_io` asserts stereo shape). The one place "additive" work was going to brush proven engine code — the io_audio mono downmix — **does not need touching at all**. Every new metric consumes only `y_native`/`sr_native`; the tempo path consumes only the 22.05 kHz mono view. The regression guarantee is architectural, not aspirational. (Corollary: the spectrum *must* come from `y_native` anyway — the analysis view's Nyquist is 11 kHz.)
2. **Frozen-app failures don't reproduce in terminals** (proven twice by v2). Therefore packaging cannot be a final milestone: a walking-skeleton .app freezes in **M0** and the frozen smoke test stays green at every milestone thereafter. M5 becomes hardening, not discovery.

---

## §1 · Module boundaries

```
rai_analyzer/            ENGINE — existing files byte-untouched; additive only:
  metrics/               NEW  spectrum (Welch @ native rate), dynamics (RMS/peak/crest),
                              band energy % (sub 20–60 / bass 60–120 + 6-band map),
                              stereo (width ratio + correlation) — own params.py + contracts.py,
                              array-in signatures (cannot even see the mono tempo view)
  beatgrid.py            NEW  estimate_beat_phase(features, bpm) → BeatGrid — reuses fold_to_grid
                              over one beat (~6 ms resolution); calibrated onset-lag constant
  profiles.py            NEW  PROFILES registry ("drill" → TempoConfig()) for GUI + CLI --profile
  cli.py                 3-line additive diff at M4 (--profile, default drill = byte-identical output)

rai_ui/                  NEW top-level package — imports engine, NEVER imported by it (grep-test enforced)
  app.py, main_window.py, __main__.py       shell, nav→QStackedWidget, window-level native Qt DnD
  sections/  overview · tempo · signal · compare · report
  widgets/   header, nav_rail, status_bar, verdict_block, meter_bridge, chips,
             metric_readout, candidate_table (QTableView+model+delegates), tiebreak, empty_state, toast
  plots/     plot_frame, tempogram_plot, markers (label flip >72%), decimate (pure numpy min/max pyramid)
  state/     verdict.py (PURE reducer: NO_FILE/WORKING/CONFIDENT/AMBIGUOUS/CONFIRMED_HUMAN/NO_TEMPO/ERROR)
             formatters.py (PURE chip/numeral/unavailability formatting)
  services/  worker.py (QThread worker-object; load_audio→build_features→resolve_tempo→loudness;
             one-at-a-time + generation counter), recent_files.py (QSettings),
             ground_truth_store.py + click_preview.py (M3)
  theme/     _tokens_gen.py + app.qss (BUILD-TIME generated from rai.tokens.json, committed,
             CI sync-test), pens.py, fonts.py (vendored IBM Plex TTFs + OFL), icons.py (QPainter/SVG)
tools/gen_theme.py       tokens.json → theme artifacts; fails on unresolved placeholder

USER DATA (M3) ~/Library/Application Support/RAI Audio Analyzer/
  ground_truth.jsonl     append-only journal, keyed by file md5; undo = appended retraction
  fingerprints/drill.user.json   relearned profile — NEVER written into the repo/package
BUILD  build/RAIv3.spec + rewritten build_macos.sh + smoke_frozen.sh
```

**Hard walls:** engine→ui import direction; user ground truth vs repo gate fixtures (validation never imports rai_ui; gate always runs the packaged fingerprint — *"`python -m validation` output is byte-identical no matter what the user confirms or relearns"* is an M3 exit-criterion test); `AmbiguityParams` frozen all phase (the UNRELATED-trigger work stays deferred).

## §2 · Key decisions (with the why)

| # | Decision | Why |
|---|----------|-----|
| D1 | New metrics attach as a separate **`SignalResult`** composed by the UI worker — `AnalysisResult`/`to_dict`/`to_report` byte-frozen | Any field on AnalysisResult edits contracts.py and changes CLI `--json` output; gate/CLI/report stay byte-identical by construction |
| D2 | Metric definitions: v1's sub 20–60/bass 60–120 bands kept (continuity + 808 territory); Welch 16384\@native, per-channel PSD averaged in power domain (no downmix phase-cancel); crest = NaN on silence (v1's 0.0 lied); peak cross-checked equal to loudness sample-peak | v1 = feature checklist and cross-check oracle; v2 definitions canonical |
| D3 | Playback = **sounddevice** (PortAudio), offline per-candidate click premix, sample-aligned buffers, pointer-swap A/B with playhead preserved | Engine already holds decoded PCM; mixing is numpy addition; 106 KB wheel + existing PyInstaller hook vs PySide6-Addons (~150 MB) + ffmpeg dylibs + AVFoundation frozen quirks. Fallback documented: QAudioSink push-mode, zero new deps. **Decided at M0, not M3** — it shapes the spec |
| D4 | Click = 2 kHz sine-burst ticks, drift-free `phase + k·period` placement, music −3 dB under active click; rendered offline per candidate, cached | Cuts through a dense drill mix; renders in ms |
| D5 | Beat phase = additive `beatgrid.py` (engine exposes none today); lands in **M2** with the other DSP so M3 builds on tested math | fold_to_grid reused unmodified; onset-lag constant calibrated by synthetic test |
| D6 | Ground truth = append-only **JSONL journal** keyed by md5; undo = retraction record; relearn = **explicit button** (≥3 confirmed), md5-reverify, backup + one-step revert, `clear_fingerprint_cache()` after save; user profile injected via `FingerprintParams.fingerprint_path` (zero engine change); `fit_prior` NOT wired | Crash-safe, auditable, same md5 rationale as the gate pins; profile swap is a deliberate visible act |
| D7 | Confirmed truth affects future runs via **display overlay only** (md5 lookup → CONFIRMED·HUMAN + ✓HUMAN tag over the live engine result). No result cache, no pinned-prior re-resolve | Both alternatives mask engine drift or manufacture fake confidence — the v1 smell |
| D8 | Tokens→QSS generated at **build time**, artifacts committed, CI regenerate-and-diff sync test; pill radius 999 emitted as computed half-height (QSS ignores over-half radii); dynamic-property selectors (`[state="ambiguous"]`) | No startup failure mode in the frozen app; stale artifacts fail CI |
| D9 | Chip formatter = pure module, ratio computed vs table, **tolerance 4% to match the engine's `classify_relationship`** (design said ±2%; divergence would show `unrelated` chip against `fractional` report text); `tol` stays a parameter | One truth for chip and report; recorded here as the deciding note |
| D10 | Fraction glyphs: verified present in IBM Plex Mono 2.5.0 TTF cmap (⅓⅔¾⅝⅘… all covered); CI test walks every formatter-emittable glyph through the vendored cmap; ASCII "5/8×" fallback rule if a future glyph misses. UI symbols ◆⚠▶⏸▾ are NOT in Plex → drawn as QPainter/SVG icons (never OS emoji fallback); Compare header uses ∆ U+2206 (present) | Measured, not assumed; the coverage gate keeps it true |
| D11 | Interpreter = **uv-managed CPython 3.14.x** (baseline gate already green on 3.14.6); build script hard-guards `sys.base_prefix` against Homebrew; PySide6-**Essentials** ==6.11.1 (cp314 wheels verified on PyPI) + shiboken6, never the metapackage; `target_arch='arm64'`; `argv_emulation=False` (Qt handles Finder-open natively); drop sklearn collection (15 MB dead weight, grep-verified unused), drop UPX; `LSMinimumSystemVersion` 13.0; `NUMBA_CACHE_DIR`→user Caches (signed .app is read-only → silent JIT-every-launch otherwise); post-build bloat assert fails the build if QtQml/QtQuick/WebEngine/sklearn appear | Kills every identified v2 packaging failure mode + measured Qt prune: ~47 MB thinned keep-set; honest bundle estimate ~300 MB onedir (llvmlite 110 MB + scipy 38 MB are immovable) |
| D12 | Frozen smoke = **two probes**: direct-exec `--smoke` (window shown + acceptDrops + injected real QDropEvent → full analysis → JSON w/ commit stamp = git HEAD) AND `open -n` LaunchServices launch + crash-report scan. Never offscreen for this — offscreen masks the cocoa crash class | The `open -n` no-tty path is the only one that reproduced v2's SIGABRT |
| D13 | tkinter `gui.py` retired in a deliberate M5 commit only after frozen parity is confirmed; engine `requirements.lock.txt` untouched until that cutover (new `requirements-v3.lock.txt` from M0) | Reproducible engine baseline all phase |

## §3 · Test strategy

- **Engine-additive (pytest, existing style):** unit tests per metrics module against synthetic signals (sine/noise/silence edges — NaN policy, `json.dumps(allow_nan=False)` contract test); peak≡sample-peak cross-check; v1-oracle comparisons on the archived fixtures; beatgrid ±10 ms on `click_track` at {90, 120, 153.85, 166.01} BPM + lag calibration + silence→confidence-0.
- **The non-negotiables, run at every milestone:** full suite green · `python -m validation` **byte-identical** (script-diffed against a stored M0 reference run) · frozen smoke green.
- **Pure headless UI logic (no Qt):** formatters (ratio table, 4% tolerance edges, −∞/em-dash policy), verdict reducer (exhaustive transitions), theme sync, font cmap coverage, decimate, `marker_label_side`.
- **pytest-qt offscreen (CI `ui-offscreen` job, ubuntu + libegl/xkb apt set, py3.14):** boot with stylesheet-parse-warning-fails-test handler; nav/stack; rail⇄bridge; worker end-to-end on a `synthetic.py`-rendered WAV via `qtbot.waitSignal`; tiebreak select→confirm→chip recompute→undo with **faked player** (CI never opens an audio device); DnD via constructed QDropEvent; toast lifetime. Engine gate job stays byte-identical in CI.
- **Boundary tests:** grep-test (engine never imports rai_ui); populated user store + user fingerprint → subprocess gate run asserts identical output.
- **Manual (Mac, per milestone):** Finder drag, chrome/fonts/plot feel, audible click-lock on the Ledger fixture (166.01), frozen .app launch.

## §4 · Landing sequence (revised per deep-dive critiques)

Every milestone exits with: unit suite green · gate byte-identical · frozen smoke green · clean tree · demo to Elias.

- **M0 — Walking skeleton (the de-risker).** `rai_ui` scaffold; tokens→QSS generator + committed theme; vendored Plex + cmap gate; app shell (header/nav/status, native-titlebar fallback — unified traffic-light chrome is time-boxed); **QThread worker + Browse + native DnD**; Report section via `to_report()` (Copy-CLI string *without* `--profile` until M4); **first PyInstaller freeze + both smoke probes**; sounddevice-vs-QAudioSink decision spiked *frozen* (play 1 s of audio from the built .app). Exit: a real, frozen, non-Tk RAI window analyzes a dropped WAV on macOS 26.5.
- **M1 — Tempo section (v2 parity+).** pyqtgraph tempogram per C-16 (band region, markers, label-flip, no legend); candidate table (model+delegates) with computed chips; rail + bridge modes; verdict block + reasons; recents. Exit: v2 GUI functionally superseded on the Tempo lane.
- **M2 — Engine-additive DSP.** `metrics/` (spectrum/dynamics/band-energy/stereo + SignalResult) + `beatgrid.py` + decimation helpers, full unit coverage + v1-oracle cross-checks; worker composes SignalResult; **Overview + Signal sections** consume it. Exit: all v1 metrics live in v3 with v2-canonical definitions; gate byte-identical.
- **M3 — The flagship.** Order *within* the milestone: (a) ground-truth store + confirm/undo + CONFIRMED·HUMAN + md5 overlay (no audio needed — ships even if playback slips); (b) click-preview on the proven M0 audio spike + beatgrid phase; (c) explicit relearn with backup/revert. Exit: tiebreak round-trip persists and relearns; **gate byte-identical with a populated user store** (the boundary test).
- **M4 — Compare + CLI.** Compare A/B + B-empty; `profiles.py` + `--profile` (default = byte-identical); Copy-CLI string aligned; decide the `to_report()` confirmed-truth-line question (flagged open — leaning GUI-overlay-only to keep report byte-frozen).
- **M5 — Hardening + cutover.** Bundle polish (bloat asserts, icns, plist), full manual pass, **deliberate tkinter retirement commit** (gui.py + tkdnd spec paths + GUI extra deps), lockfile regeneration, tag `v3.0.0`, ship. The two old Desktop .apps retire.

## §5 · Risk register (top items)

| Risk | L×I | Mitigation |
|---|---|---|
| PySide6 6.11.1 × PyInstaller 6.20 × hooks-contrib pairing breaks at freeze | M×H | Pin the trio; M0 freeze + every-milestone smoke; fallback pin 6.10.3 |
| Frozen-only crash class (the v2 ghost) | M×H | M0 freeze; `open -n` probe + crash-report scan every milestone; never offscreen for the smoke |
| PortAudio/CoreAudio inside the frozen .app | M×M | M0 frozen audio spike (1 s playback from the built .app); QAudioSink fallback documented |
| User GT / relearn contaminates gate or packaged fingerprint | M×H | App Support-only writes; `fingerprint_path` injection; boundary test in CI; never write `rai_analyzer/fingerprints/` |
| Relearn shifts flag rates | M×M | Fingerprint-profile only (never AmbiguityParams); before/after flag-rate log on a fixed corpus; explicit button + revert |
| Scope creep into the deferred UNRELATED trigger | M×M | AmbiguityParams frozen rule in plan + config comment already documents deferral |
| numba JIT recompiles every launch in signed .app | H×M | `NUMBA_CACHE_DIR` runtime hook (first analysis +3–8 s once, then cached) |
| Chip/report vocabulary drift | L×M | One formatter module, 4% tolerance matching engine, CI-gated |
| Dirty-tree builds recur | M×M | Build script hard-aborts; commit stamped in Info.plist + asserted by smoke |
| Traffic-light unified chrome rabbit hole | M×L | Time-boxed in M0; native title bar is the approved fallback |

**Out of scope, restated:** UNRELATED-trigger extension (needs corpus flag-rate study) · `fit_prior` auto-retune · Study Mode (nav slot reserved only) · any edit to existing engine files · Windows/Linux packaging.

## §6 · Open items

1. **Design punch list (tokens v0.1.2)** — `ambiguous.hover`, `plot.band-edge`, traffic-light note, third/triple doc nit. Non-blocking; fold in whenever.
2. **`to_report()` confirmed-truth line** — decide at M4 (leaning: GUI-overlay only; report stays byte-frozen).
3. **Bundle id** — keep `com.siliconclick.rai-audio-analyzer` (recommended) or mint new.
4. **Elias sign-off on this plan** → M0 begins.
