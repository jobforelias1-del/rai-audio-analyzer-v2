# M5 Handoff — Hardening + Cutover: the v3.0.0 candidate (built 2026-07-07 · awaiting operator acceptance)

**Branch:** `phase3/m5-cutover` @ `2bd317a` — **LOCAL-ONLY, not merged, not pushed, NOT yet tagged.**
On Elias's acceptance: merge → push → **tag `v3.0.0`** → rebuild at the tag (self-stamps via `git describe`) → ship. Baseline: `main` @ `b96f1da` (M0–M4 all landed + accepted).

## Exit criteria — all PASS

| Criterion | Result |
|---|---|
| tkinter retirement (D13's deliberate commit) | ✅ `35101fe` stands alone: gui.py (512 lines), the v2 spec, and the v2 build script deleted; GUI extras retired; nothing imported any of it; Tcl/Tk-9 postmortem preserved as history |
| Version truth | ✅ 3.0.0 in pyproject / `__version__` / CLI description / spec short-string / CHANGELOG; status bar reads `engine v3.0.0 · build {sha7}`; gate output carries no version string (proven before bumping) |
| Turnkey CLI (closes the M4 gap) | ✅ the frozen binary IS a headless CLI: `…/MacOS/RAIAudioAnalyzer <file> --json --profile drill` output **byte-identical to the venv CLI** (live-proven twice); `--smoke` reserved by prefix; Copy CLI emits the absolute bundle path when frozen |
| Engine venv cutover | ✅ `.venv` rebuilt **uv-managed** CPython 3.14.5 (Homebrew drift resolved; old venv parked as `.venv-old-homebrew` for close-out deletion); `requirements.lock.txt` regenerated (40 pins, installs cleanly from scratch); numba≥0.65 floor documented (resolver trap) |
| Full matrix | ✅ v3 **1454 passed** · engine **882 passed + 44 skipped** (final baselines) |
| Gate | ✅ byte-identical — proven after the retirement, after the version bump, on the rebuilt venv pre- and post-swap, and after the review fixes |
| Frozen smoke | ✅ both probes PASS @ `2bd317a` |
| Adversarial review (lean) | ✅ 23 agents (2 lenses → 3 skeptics): **7 confirmed, 0 rejected, all fixed + pinned** — headline: the D10 cmap gate had silently lost ALL CI enforcement when fonttools left with matplotlib (now in the ui-offscreen job); the startup sweep could eat a second instance's live staging temp (pid-liveness probe added); dispatch prefix/`--` edges; quoting backslash escape; README GUI-install pointer |
| Flag-rate question (Elias's 4-ambiguous note) | ✅ ANSWERED WITH DATA — see below |

## The flag-rate A/B (tools/flag_rate_ab.py — now a permanent instrument)

Run over 16 tracks (6 pinned fixtures + the July-7 real drops), packaged fingerprint vs a temp copy of Elias's live 3-confirm relearned profile:
- **Zero flips. The relearned profile is innocent** — identical verdicts AND BPMs on every track.
- **The honest baseline flag rate is 11/16 (68.8%)** on hard drill material. The 4-in-a-row was the instrument being consistently unsure where drill is genuinely half-time-ambiguous — the tiebreak flagship exists for exactly this.
- Secondary finding: a 3-track fingerprint is too weak to move the evidence blend at all — relearn earns its keep with a bigger journal.
- **This is the corpus data the Phase-0 DEFERRED trigger-2 fix was waiting for.** `AmbiguityParams` stayed frozen all phase (plan hard wall), so the decision — does the UNRELATED-runner-up fix graduate, possibly cutting the flag rate — is the first **post-v3.0.0** engine conversation, now with numbers.

## Acceptance checklist (the human pass — shots can't cover these)

1. Fresh instance discipline: quit ALL running RAI windows first, launch `dist-v3/RAI Audio Analyzer.app`, confirm the status bar reads `build 2bd317a`.
2. Real Finder drag → analysis; nav all five sections; a tiebreak confirm/undo round-trip; click preview lock (ears); Compare A/B with a reference.
3. Terminal: paste the Report screen's **Copy CLI** command into a bare Terminal (no venv) — it must run and print JSON.
4. Relearn popover: state line, revert path.
5. **Old Desktop .apps** (`~/Desktop/july 2nd 26/Desktop Apps/RAI Audio Analyzer v2.app` + the backup in the Land fill): keep-archived or delete — YOUR call, nothing auto-deleted.
6. On acceptance say the word: merge → push → CI → tag `v3.0.0` → final tag-stamped rebuild → RC deletes `.venv-old-homebrew` + stale `egg-info` + the old 510 MB `dist/`.

## Post-v3.0.0 backlog (inherited, none blocking)

Trigger-2 flag-rate decision (data above) · design punch lists (tokens v0.1.2/0.1.3 reconciliation, chip 10px, reading 12px floors) · `_ORPHANED_THREADS`-style shared promotion if a 5th WorkingOverlay importer appears · relearn skip-report accessor for the popover · Compare readings for future metrics · Study Mode (nav slot reserved).

**Phase 3 complete pending this acceptance: M0 → M5, all six milestones built, adversarially reviewed, and operator-accepted in two days.**
