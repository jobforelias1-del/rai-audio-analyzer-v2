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

### Changed

- **Genre prior re-tuned for drill.** The soft log-normal prior kept its shape
  and 145 BPM centre, but the shoulders were tightened (`sigma 0.30 -> 0.24`,
  `floor 0.12 -> 0.10`; `fit_prior` clamp `min_sigma 0.18 -> 0.14`). The old
  broad tails handed a genre-implausible peak (~132 BPM) nearly as much prior
  weight as the notated band, which blunted the raw-vs-priored divergence
  trigger.

### Notes

- No public API changes: `TempoResult`/`Candidate` shapes, the CLI, and the GUI
  surface are unchanged. New knobs (`AmbiguityParams.genre_band_min/max`,
  `band_evidence_floor`) are additive with drill-sensible defaults.
- Tests: `tests/test_candidates.py` asserts a 192 BPM base surfaces both the
  `4/5` (≈154) and `5/4` (240) aliases; `tests/test_resolver_ambiguity.py`
  covers the new out-of-band trigger, the click-safe salience floor, and a
  regression guard on the existing competitor-score trigger. The synthetic
  acceptance gate remains 3/3 PASS.
