# Ground-truth fixtures — the acceptance gate

> **The gate is here.** Per the build spec: *green unit tests are not the gate.
> Passing the ground-truth tracks is the gate.* Dropping these three WAVs into
> this directory is what turns `python3 -m validation` from a **synthetic
> self-test** into the **real acceptance gate**.

## What to drop here, and where

Put these three audio files in **this exact directory**:

```
validation/fixtures/
```

(absolute path is printed by the harness when it can't find them, and is also
available programmatically as `validation.ground_truth.FIXTURES_DIR`.)

| filename                          | true BPM | v1's wrong answer | v1 error type                          |
| --------------------------------- | -------- | ----------------- | -------------------------------------- |
| `ledger_en_acier.wav`             | 166.01   | 83.0              | octave (×2)                            |
| `mathematics_of_the_menace.wav`   | 153.85   | 96.0              | fractional (~5:8)                      |
| `taco_puttin_on_the_ritz.wav`     | 99.0     | — (none recorded) | external cross-check (Google-confirmed)|

These true tempos are **DAW-warp confirmed** (each track was warped to a grid in
a DAW; the Taco track was additionally cross-checked against an external,
Google-confirmed value). They are the single source of truth in
[`../ground_truth.py`](../ground_truth.py) — do not edit the numbers here; edit
them there if they ever change.

WAV is the primary intake format. The loader (`rai_analyzer.io_audio.load_audio`)
will tolerate `.aiff` / `.flac` / `.mp3` if soundfile/audioread can open them,
but the harness only auto-detects the `.wav` filenames in the table above.

## Why they aren't in git

These are large binary masters. They are **`.gitignored`** — see the repo-root
`.gitignore`, which excludes `validation/fixtures/*.wav` (and `*.aiff`,
`*.flac`, `*.mp3`). The repo ships the harness and the truth *table*; the
producer supplies the audio out-of-band. This README and any non-audio files in
this directory **are** committed.

## How the harness auto-detects and consumes them

`run_gate()` (in [`../harness.py`](../harness.py)) calls
`ground_truth.available_tracks()`, which returns exactly the ground-truth tracks
whose WAV is present on disk. Then, for **each present fixture**, it:

1. runs the real pipeline — `rai_analyzer.analyze_file(path)` — to get an
   `AnalysisResult`;
2. computes, against the confirmed `true_bpm`:
   - **hit** — `|primary − true| ≤ tol·true` (default `tol = 2%`),
   - **recall** — any candidate within `recall_tol` of the truth (default `3%`):
     *was the truth surfaced at all?*,
   - **avoided_v1_error** — the primary did **not** reproduce v1's confident-wrong
     number (trivially true for Taco, which has none recorded),
   - **flagged** — `result.tempo.ambiguous`;
3. prints a per-track block (true vs predicted vs felt, the flags, the
   `ambiguity_reason`, and the full ranked candidate list with the truth marked),
   then the aggregate rates (recall / ambiguity / hit / v1-avoidance).

**Per-track gate:** `recall AND avoided_v1_error AND (hit OR flagged)`. The
signature feature is *reliability*: a confidently-wrong octave fails, but either
nailing the truth **or** honestly flagging ambiguity (with the truth surfaced for
a human tiebreak) passes. The **overall gate passes iff every present track
passes**, and the process exit code is that verdict (`0` pass / `1` fail).

No fixtures present? The harness prints these same instructions and then runs a
labelled **SYNTHETIC SELF-TEST** (synthesised drill beats through the identical
gate logic + format) so it always produces visible three-track output and proves
the pipeline and gate both work — just re-run `python3 -m validation` after
dropping the files in, no flags or config needed.

## Re-learning the drill fingerprint from these tracks

The fingerprint evidence term — the strongest genre-specific weapon — scores a
candidate by folding each band's onset energy into a 16th-note bar grid and
comparing it to a learned drill fingerprint. Once these real fixtures are in
place, that fingerprint can be **re-learned from them** (instead of the packaged
default) via:

```python
from rai_analyzer.evidence.fingerprint import learn_fingerprint
```

Averaging the folded per-band profiles of these ground-truth tracks produces the
genre fingerprint cached at `rai_analyzer/fingerprints/drill.json` (override the
path with `FingerprintParams.fingerprint_path`). A wrong-octave candidate folds
the pattern at the wrong resolution and matches poorly — which is exactly how
this term breaks the octave tie. Re-run `python3 -m validation` afterwards to
re-evaluate the gate against the freshly-learned fingerprint.
