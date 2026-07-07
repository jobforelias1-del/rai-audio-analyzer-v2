# M2 Handoff — Phase 3 Engine-Additive DSP (built 2026-07-07 · awaiting operator acceptance)

**Branch:** `phase3/m2-engine-dsp` @ `8842fbe` — **LOCAL-ONLY, not merged, not pushed.**
Merging and M3 both wait on Elias's explicit call.
Baseline underneath: `main` @ `b9d6568` (M1 landed + operator-accepted 2026-07-07).
**Existing engine files byte-untouched since `v3-baseline-phase0`** — M2 added only NEW files under `rai_analyzer/` (metrics/, beatgrid.py) + packaging metadata.

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| All v1 metrics live in v3 with v2-canonical definitions | ✅ spectrum (Welch @ native, per-channel power-avg), dynamics (peak ≡ loudness sample-peak, whole-file RMS, crest NaN-on-silence), band energy (sub/bass + 6-band map), stereo (width % + Pearson correlation) — Overview + Signal sections + rail/bridge consume them |
| Full test matrix | ✅ v3 venv **920 passed** · engine venv **650 passed + 29 skipped** (fixture-less CI reads ~6 lower on the D2 disk tests — expected, not a regression) |
| Acceptance gate | ✅ `python -m validation` **byte-identical** (proven again at every stage — validation's import set cannot see the new modules) |
| Frozen smoke — STRENGTHENED | ✅ both probes PASS at `8842fbe`; exit code now REQUIRES `tempo_ok` AND `signal_ok` (a dead metrics layer can no longer ship green — the failure direction is test-proven) |
| D2 cross-check | ✅ metrics peak ≡ loudness sample-peak, exact equality on 6 synthetics + all 6 disk fixtures |
| Beatgrid spec (±10 ms) | ✅ worst 6.06 ms across 5 click shapes × 4 BPMs after the review-driven estimator rework; confidence null-normalized (noise ≤0.165, clicks ~0.7, silence 0.0) |
| Latency budget (≤0.5 s) | ✅ 0.19 s for the whole metrics layer on a 103 s stereo fixture |
| Adversarial review | ✅ 38-agent workflow (5 lenses → 3 skeptics/finding): 11 raw → **9 confirmed (7 distinct, all fixed + test-pinned)**, 2 refuted |
| Real-stereo end-to-end | ✅ new worker-chain test: width 53.4 %, correlation −0.069 on a decorrelated stereo synth |

**The demo:** `dist-v3/RAI Audio Analyzer.app` (right-click → Open). Drop a WAV: **Overview** (tempo/loudness/dynamics/file cards + full-track waveform) and **Signal** (log-frequency spectrum + stereo width / sub-bass / dynamic range cards) are live; the rail's Dyn range / Sub-bass / Stereo width rows now show real measurements. Compare remains the last designed placeholder (M4).

## Rulings of record

R-M2-1..21 in the architecture brief (key ones): 04's Overview/Signal hi-fi screens ruled binding · sub_pct = 20–60 Hz share ("share of energy below 60 Hz" is the caption truth) · width = mid/side energy ratio, mono width 0 % is a measurement · six-band map defined (sub/bass/low-mid/mid/high-mid/air), engine-only · DR computes whenever defined (demo's short-clip "—" was scenario fiction — logged divergence) · spectrum has no y-axis labels by design · waveform #3E97AB became token `plot.waveform` (v0.1.3) · Report stays verbatim `to_report()` · JSON-strict metrics contracts (non-finite → None) · WORKING/ERROR blank extends to all signal data.
Agent rulings ratified by RC: NO_TEMPO renders muted em-dash on the Overview tempo card (full block stays rail-only) · silence chips ride every absent card (mock showed only LUFS — logged divergence) · chip font 10.5→10 px (integer Qt sizes) · DR unit renders "— dB" on absence (matches the 04 template).

## New landmines (M2-verified)

12. **A DSP constant calibrated on one fixture shape encodes that fixture** — the beatgrid lag constant was ~60 % fixture-decay artifact; the estimator (leading edge), not a constant, is what makes onset placement shape-robust. Calibrate on near-impulses, verify across shapes.
13. **`fold_to_grid`'s best-of-32-phases selection inflates sharpness on short noise** — any confidence built on folded-profile sharpness needs null-normalization (detuned-period folds), or 4 s of white noise reads "confident".
14. **Additive smoke keys must be load-bearing** — `signal_ok` was write-only for one commit; the worker's deliberate degrade-to-None meant the whole M2 layer could die with every gate green. Smoke exit now gates on it (`exit_code_for` + REQUIRED_TRUE_KEYS in rai_ui/smoke.py).
15. **Welch's detrend eats DC** — a finite-peak file can have zero audible-band PSD (broken-export DC offset); `silent` (peak −inf) and `unmeasurable` (no finite bins) are distinct states with distinct copy.
16. `_WorkingOverlay` is still module-private in tempogram.py, imported by spectrum/waveform panes — tolerated three-importer state; promote to a shared plots module in an M3 cleanup if touched anyway. Same for `type_pin` living in verdict_block (plots → widgets import).

## Environment quick reference

Unchanged from M0/M1. Suites expect: v3 **920**, engine **650 + 29 skipped** (local, with fixture WAVs on disk). `tools/preview_shots.py <outdir>` now renders 01–09 + gate shots (M2 appended 07-overview / 08-signal / 09-signal-silence). Frozen build: `bash build/build_macos_v3.sh` (smoke gates on tempo_ok + signal_ok).

## Next milestone — M3: the flagship (NOT started; do not start without Elias's go)

Scope per `docs/PHASE3_PLAN.md` §4 (now in-repo), order within the milestone: (a) ground-truth JSONL store + confirm/undo + CONFIRMED·HUMAN + md5 display-overlay (no audio needed); (b) click-preview on the M0-proven sounddevice spike + `estimate_beat_phase` (now shape-robust and honestly confident); (c) explicit relearn with backup/revert. Exit: tiebreak round-trip persists and relearns; **gate byte-identical with a populated user store** (the boundary test). M3 note from the beatgrid work: guard `estimate_beat_phase` against unresolved/None bpm (it raises ValueError by contract), and ear-check the click lock on real material (landmine 12).

**To begin:** Elias says **"start M3"**. First command of a fresh session:
```bash
cd ~/Projects/rai-audio-analyzer-v2 && git log --oneline -3 && QT_QPA_PLATFORM=offscreen .venv-v3/bin/python -m rai_ui --smoke
```
(expect `8842fbe` at HEAD — or the post-merge main equivalent — smoke exit 0 with tempo_ok/signal_ok true.)
