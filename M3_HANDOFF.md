# M3 Handoff — Phase 3 Flagship (built 2026-07-07 · awaiting operator acceptance)

**Branch:** `phase3/m3-flagship` @ `1683b4d` — **LOCAL-ONLY, not merged, not pushed.**
Merging and M4 both wait on Elias's explicit call.
Baseline underneath: `main` @ `be0688a` (M2 landed + accepted 2026-07-07).
Pre-M2 engine files byte-untouched since `v3-baseline-phase0`; M2's metrics/beatgrid unchanged this milestone.

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| Tiebreak round-trip persists and relearns | ✅ confirm → JSONL journal (md5-keyed) → re-analysis boots CONFIRMED·HUMAN → undo retracts (works across sessions) → relearn (≥3 confirms) writes an atomic user profile the worker injects; backup + one-step revert |
| **Gate byte-identical WITH a populated user store + active user profile** | ✅ boundary test (subprocess gate under a temp HOME with populated journal + divergent user profile → stdout byte-equals the pinned baseline) + re-proven at the end of the e2e suite; the analyze path meanwhile provably CHANGES under the injected profile (the deliberate visible act) |
| Full test matrix | ✅ v3 venv **1238 passed** · engine venv **759 passed + 38 skipped** (new baselines; fixture-less CI reads lower on D2-fixture skips) |
| Frozen smoke — strengthened again | ✅ both probes PASS at `1683b4d`; exit now gates on analysis_ok + tempo_ok + signal_ok + **truth_ok** (confirm→persist→lookup→undo round-trip proven inside the frozen bundle) |
| Adversarial review | ✅ 71-agent workflow (5 lenses → 3 skeptics/finding): 22 raw → **19 confirmed (6 root causes, all fixed + regression-pinned with the reviewers' own live repros)**, 3 refuted |
| Store isolation | ✅ every test/smoke/shot runs against temp dirs; contamination tripwires in both conftests; the real `~/Library/Application Support/RAI Audio Analyzer/` does not exist after the full matrix + smoke + shots |
| Overview lag (Elias-flagged at M2 acceptance) | ✅ recon-measured root cause (1.2 px antialiased pen → Qt raster cliff, ~167 ms EVERY paint, not warmup); fixed to ~2 ms (waveform per-item antialias off, width untouched) + spectrum decimated ≤2048 pts (67→~17 ms) |

**The demo:** `dist-v3/RAI Audio Analyzer.app` @ `1683b4d`. Drop an ambiguous track → **Open tiebreak** (rail, bridge, or candidates header) → three cards, **▶ preview click grid** on each (2 kHz click over the music, A/B swap keeps the playhead), pick the grid that locks → **Set {bpm} — save as ground truth**. Everything recomputes around your choice; ✓ HUMAN pill on your row. Re-drop the same file later — it boots confirmed. Undo from rail/bridge/header. ▶ hear on any table row previews that row's grid. Click the **DRILL · 140–170** chip for the profile popover: relearn (≥3 confirmed) / revert.

## ⚠ Operator acceptance needs EARS, not just eyes

1. **Click-grid lock** on real material (landmine 12 debt): the beatgrid estimator is shape-robust on synthetics (≤6 ms) but real-mix onset character varies — preview a few known tracks (Ledger = 166.01 truth) and judge whether the click sits ON the groove.
2. **A/B level continuity**: swapping candidate grids mid-play should hold a steady music bed (the per-file level plan). Also note the effective duck is ≈−5.2 dB on hot-mastered tracks (deliberate: constant bed beats a literal −3 dB; D4 letter-drift logged).
3. **EOF behavior**: a track ending on the grid drops its final tick rather than popping — should be inaudible as a defect.

## Key rulings this milestone (R-M3-1..20 in the brief + ratified in-flight)

Journal schema carries a `path` field (relearn needs real paths; ratified) · relearn aborts writing NOTHING under 3 md5-verified survivors (ratified, honest-instrument) · NO confidence gate on click preview (real-material confidence measures 0.10–0.43 — a gate kills the feature) · confirmed recompute is view-layer only (D7 honored; felt stays engine truth — 04 executable demo wins) · Report stays verbatim `to_report()` (04's confirmed reason line deferred to the M4 open item) · Enter selects, never confirms (ground truth = deliberate visible act) · unpersisted confirms toast "session only" honesty · keyboard: Space preview / ←→ move / Enter choose / Esc close.

## New landmines (M3-verified)

17. **"Never fatal" replay claims need hostile bytes**: decode-in-iteration escapes per-line try blocks (UnicodeDecodeError is not OSError); append-mode writers must heal missing trailing newlines or a crash eats the NEXT record. Both were live-reproduced by review skeptics before fixing.
18. **In-place profile writes race live readers** — publish via temp + `os.replace` in the same dir, validate the staged file, clear the path-keyed engine cache exactly once AFTER replace. The engine's load_fingerprint TOCTOU is narrowed, not eliminated — the main_window mutual-exclusion gates (no analysis during relearn and vice versa) are load-bearing; do not remove them.
19. **Audio callbacks are another thread**: never emit Qt signals from the PortAudio callback — the ClickPreview `stopped` signal is driven by a main-thread QTimer poll. And PortAudio init hangs silently under the sandboxed shell; only smoke real audio unsandboxed.
20. **Playback state must be read back, not assumed** — any UI showing "playing" needs a feedback path (natural EOF, device death). `ClickPreview.stopped` is the contract.
21. QVariantAnimation-entrance widgets must stop the animation before same-cycle grabs (preview_shots does).

## Environment quick reference

Suites: v3 **1238** · engine **759 + 38 skipped** (local, fixtures on disk). Smoke required-true keys: window_shown, accepts_drops, dnd_delivered, analysis_ok, tempo_ok, signal_ok, **truth_ok**. Shots 01–11 + gate. **CI gained the plan-§3 `ui-offscreen` job** (ubuntu, PySide6 offscreen, tests/ui) — first remote run happens at merge push; if it needs iteration, fix-forward or mark deferred with a note.

## Next milestone — M4: Compare + CLI (NOT started; needs Elias's go)

Scope per `docs/PHASE3_PLAN.md` §4: Compare A/B + B-empty state (design 1f already approved; C-cards exist), `profiles.py` + CLI `--profile` (default = byte-identical output; Copy-CLI string aligns — the M1 nit closes), decide the `to_report()` confirmed-truth line (open item §6.2, leaning GUI-overlay-only). Entry command unchanged (`git log`, smoke exit 0, expect `1683b4d` or post-merge main).
