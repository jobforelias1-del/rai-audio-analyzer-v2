# M1 Handoff — Phase 3 Tempo Section (built 2026-07-07 · awaiting Elias demo/approval)

**Branch:** `phase3/m1-tempo` @ `568d9fd` — **LOCAL-ONLY, not merged, not pushed.**
Merging to `main` and pushing happen only on Elias's explicit call, after his demo.
Baseline underneath: `main` @ `9ceb3a1` (M0 close-out, merged & pushed 2026-07-07, CI green).
Engine bytes untouched since `v3-baseline-phase0`.

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| v2 GUI functionally superseded on the Tempo lane | ✅ tempogram (C-16), candidate table w/ computed chips (C-13), verdict block w/ always-a-reason, rail⇄bridge (C-01/C-02/C-07), recents pills |
| Full test matrix | ✅ v3 venv **534 passed** · engine venv **375 passed + 20 skipped** (new engine-CI baseline; pure tempo_view tests run Qt-less) |
| Acceptance gate | ✅ `python -m validation` **byte-identical** to `docs/baselines/gate-reference-v3baseline.txt` |
| Frozen smoke | ✅ both probes PASS at `568d9fd`, incl. `open -n`; smoke JSON grew additive `tempo_ok: true` — the Tempo section provably renders in the frozen .app |
| pyqtgraph freeze risk (recon open item) | ✅ froze clean with ZERO spec changes — proven by `tempo_ok` in the frozen probe |
| Engine untouched | ✅ `git diff v3-baseline-phase0 -- rai_analyzer validation docs/baselines` is empty |
| Adversarial review | ✅ 31-agent workflow (4 lenses → 3 skeptics/finding): 9 raw → **3 confirmed (all fixed + test-pinned)**, 3 refuted |
| Design fidelity | ✅ offscreen shot review vs approved 04 Console across 9 states (hero/working/rail/bridge/no-tempo/report + 3 gate fixtures) |

**The demo:** `dist-v3/RAI Audio Analyzer.app` (ad-hoc signed — first launch: right-click → Open). Drop any WAV: analysis lands on the Tempo section — tempogram with drill-band shading and amber/violet markers, ranked candidate table (the table IS the legend), verdict card with reasons, persistent numeric rail (header button collapses it to the meter bridge; choice persists). Overview/Signal/Compare remain designed placeholders (M2/M4).

## Rulings of record (made this milestone)

- **R-M1-1** Chip tolerance 4% (engine) over design's ±2%; chip labels = design copy verbatim via `formatters.relationship_chip` (one truth, CI-pinned against every Relationship member).
- **R-M1-2** Approved-screen type sizes win over the token type-ramp (rail hero 40px etc.). Queued for design's tokens v0.1.2 punch list.
- **R-M1-3** WORKING **and ERROR** blank every tempo surface — the instrument never shows a number it didn't just measure (ERROR half found by review: fail() keeps the previous result; without the blank, file B's failure wore file A's numbers).
- **R-M1-4** Analysis lands on Tempo (was Report in M0).
- **R-M1-5** M3 actions (tiebreak/hear/undo) render present-but-inert with honest toasts ("… arrives in M3"). Never dead clicks, never greyed.
- **R-M1-6** M2 metrics (DR/Sub/Width) render as absence (—). −∞ is a measurement, — is absence, always.
- **R-M1-7** Confident verdicts get a **computed** reason (band membership + felt agreement, clauses stated only when true) — design's "a reason always accompanies the word" without inventing engine claims.
- **R-M1-8** Tokens v0.1.2 landed in-repo (`ambiguous.hover #EC6A60`, `plot.band-edge #1F2731` — design's own punch-list values).

## New landmines (M1-verified — add to the house rules)

8. **QSS font wipe (Landmine 6's sharp edge):** `setFont()` alone is DEAD under the app stylesheet — the app-wide `QWidget { font-size: 13px }` silently overrides family/size/weight on every label. Any designed type needs a widget-level QSS pin (see `verdict_block.type_pin` — derives the pin from the same QFont so they can't disagree). **Offscreen widget tests cannot catch this** (they run without the stylesheet); `tests/ui/test_type_ramp.py` applies the real QSS and is the regression gate.
9. **QScrollArea::setWidget re-enables autoFillBackground** on the content widget → palette-white paint-through under a dark theme. Re-clear AFTER setWidget. Similarly, QStyleSheetStyle paints unmatched QHeaderView strips and scrollbars palette-white once ANY app stylesheet is active — skin them widget-level.
10. **pyqtgraph 0.14.0 in the frozen app:** works with plain static analysis; global config (`antialias=True, useOpenGL=False`) lives in `create_app` — the single global-Qt-state site.
11. Preview-shot eyeballs lie about font sizes; **pixel-sample, don't squint** (`QImage.pixelColor` settled the skeleton-bar color in seconds).

## Environment quick reference

Unchanged from M0 (see `M0_HANDOFF.md`): `.venv-v3` = uv-managed CPython 3.14.5, offscreen pytest expects **534**, engine venv expects **375 + 20 skipped**, `bash build/build_macos_v3.sh` freezes + runs both probes. New tool: `tools/preview_shots.py <outdir>` renders all UI states + gate-fixture analyses to PNGs offscreen.

## Next milestone — M2: engine-additive DSP (NOT started; needs Elias's go)

Scope per Phase 3 plan §4: `rai_analyzer/metrics/` (spectrum @ native rate / dynamics / band-energy / stereo + SignalResult composed by the worker), `beatgrid.py`, decimation use, Overview + Signal sections consume it. Exit: all v1 metrics live with v2-canonical definitions; gate byte-identical; frozen smoke green. First command of a fresh session:

```bash
cd ~/Projects/rai-audio-analyzer-v2 && git log --oneline -3 && QT_QPA_PLATFORM=offscreen .venv-v3/bin/python -m rai_ui --smoke
```
(expect `568d9fd` at HEAD — or the post-merge main equivalent — and smoke exit 0.)
