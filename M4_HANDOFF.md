# M4 Handoff — Compare + CLI (built 2026-07-07 · awaiting operator acceptance)

**Branch:** `phase3/m4-compare-cli` @ `776505d` — **LOCAL-ONLY, not merged, not pushed.**
Merging and M5 both wait on Elias's explicit call. Baseline: `main` @ `f2e81fa` (M3 landed + accepted).

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| Compare A/B per the approved Console | ✅ hue-locked chips (drop-to-replace / Browse / ✕), 6-metric Δ table (B−A, never-tinted Δ, engine-written readings), A/B spectrum overlay (B on top, the one sanctioned legend, joint normalization), B-empty state verbatim |
| CLI `--profile` | ✅ `rai_analyzer/profiles.py` registry (packaged-only — the plan's hard wall) + the plan-scheduled MINIMAL `cli.py` diff (the first-ever edit to a pre-existing engine file); **default byte-identity subprocess-pinned** (no-flag ≡ `--profile drill` ≡ pre-M4, text + JSON); Copy-CLI now emits `--profile drill` |
| Report confirmed-line decision (§6.2 CLOSED) | ✅ **GUI banner** above the report text on CONFIRMED·HUMAN; copyable/exported bytes stay verbatim `to_report()` — deliberate divergence from 04's in-text line, doctrine over pixels |
| Full matrix | ✅ v3 **1403 passed** · engine **834 passed + 43 skipped** (new baselines) |
| Gate | ✅ byte-identical (validation provably never imports cli.py; `test_engine_boundary` auto-covers profiles.py) |
| Frozen smoke | ✅ both probes PASS @ `776505d` (smoke unchanged per R-M4-12 — no write-only keys, Compare owned by pytest e2e) |
| Adversarial review (lean) | ✅ 18 agents (3 lenses → 3 skeptics): 5 raw → **2 confirmed, both fixed + pinned** (B-lane straggler detach — quit during an in-flight reference was a qFatal; Δ-table row chrome restored per 04:471), 3 refuted |

**The demo:** `dist-v3/RAI Audio Analyzer.app` @ `776505d`. Analyze a track, go to **Compare**, drop (or Browse via the dashed B chip) a reference WAV — while on the Compare page, drops load B; anywhere else they stay A. The Δ table reads B−A with plain-language readings; the overlay draws B (rose) over A (cyan). B persists across A re-analyses (compare candidates against one reference — the TRUCK workflow); ✕ clears it. Confirm a tiebreak and open Report: the confirmed banner sits above the text while the copyable report stays byte-identical to the CLI. Try `rai-analyze <file> --profile drill` vs no flag: identical output by test-pinned construction.

## Rulings of record (R-M4-1..14 in the brief + ratified in-flight)

Drop routing by active page (NO_FILE drops fall through to A — builder guard, ratified) · B persistent/reference semantics, own worker lane, zero session/GT/recents contact · four mutual-exclusion gates (B⇄A-analysis, B⇄relearn) · reading sentences = deterministic pure formatter (unrelated pairs say "unrelated to A", never a fake drift %) · Δ never tinted (C-15 law) · cli.py's "v2" parser description left as-is (diff discipline; M5 owns cosmetic renames) · smoke untouched (landmine 14: no write-only keys) · WorkingOverlay promoted to `plots/overlay.py` (landmine 16 closed — 4 importers, one truth) · B failure keeps the previous reference + RC toast copy `Reference analysis failed — {message}`.

## Notes for acceptance

- **Copy-CLI is argument-parity, not turnkey** (clarified with Elias at acceptance): the copied `rai-analyze … --profile drill` command requires the package installed (`pip install -e .` / the repo venv — today only `.venv/bin/rai-analyze` exists on this machine; it is not on the login PATH). The button's guarantee is same-file/same-profile/byte-identical output, not distribution. M5 owns making it out-of-the-box (shell shim beside the .app, or a headless passthrough on the frozen binary — same engine either way).

- Two API-server-error agent deaths occurred mid-build (transient platform instability); both recovered via transcript resume with zero lost work — worth knowing only because the build narrative in the session log looks bumpier than the result.
- Builder divergences ratified as non-issues by the review: em-dash cells stay `text.primary` (colors-set-once beats C-15's muted grey here), reading text 12.5→12px (integer Qt floor, queued to the design punch list), no hover on chips' decorative rides, no gridlines in the Compare overlay (04 draws none).
- Budget: M4 landed at roughly **a quarter of M3's agent volume** (lean recon/build/review shapes).

## Next — M5 (HELD): hardening + cutover
Per `docs/PHASE3_PLAN.md` §4: bundle polish (icns/plist/bloat asserts), full manual pass, the deliberate tkinter-retirement commit (gui.py + tkdnd spec paths + GUI extra deps), lockfile regeneration, tag `v3.0.0`, ship; the two old Desktop .apps retire. Do not start without Elias's explicit go.
