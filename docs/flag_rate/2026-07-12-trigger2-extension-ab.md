# Trigger-2 UNRELATED-runner extension A/B — 2026-07-12

- command: `.venv/bin/python tools/flag_rate_ab.py --trigger2-ab validation/fixtures "/Users/eliasyoung/Desktop/july 9th overflow/test tracks from july 7 "`
- corpus: the exact 16-track M5 corpus (6 repo fixtures + the July-7 drop folder, relocated intact by the 07-09 Desktop sweep; corpus integrity proven same day by reproducing the M5 packaged-vs-profile table digit-for-digit — see 2026-07-12-profile-ab-repro.md)
- engine: main + count_unrelated_runner knob (default False; gate byte-identical with knob off)

# Flag-rate A/B — stock trigger 2 vs UNRELATED-runner extension

- both lanes: packaged fingerprint (no profile injection)
- extension: `AmbiguityParams.count_unrelated_runner=True`
- corpus: 16 file(s)

| File | Stock | +UNRELATED runner | Flipped |
|---|---|---|---|
| freeze_corleone_cartier.wav | AMBIGUOUS · 138.33 | AMBIGUOUS · 138.33 | no |
| freeze_rael.wav | AMBIGUOUS · 136.81 | AMBIGUOUS · 136.81 | no |
| ledger_en_acier.wav | confident · 166.10 | AMBIGUOUS · 166.10 | YES |
| mathematics_of_the_menace.wav | AMBIGUOUS · 192.66 | AMBIGUOUS · 192.66 | no |
| taco_puttin_on_the_ritz.wav | AMBIGUOUS · 204.55 | AMBIGUOUS · 204.55 | no |
| ziak_fixette.wav | confident · 146.57 | AMBIGUOUS · 146.57 | YES |
| 0 Lead Vocal.wav | confident · 144.32 | AMBIGUOUS · 144.32 | YES |
| BTSFX.wav | confident · 140.16 | AMBIGUOUS · 140.16 | YES |
| Excision & Level Up - Club XL ｜ Subsidia [Kfb4HhDv1uw].wav | confident · 144.61 | confident · 144.61 | no |
| Freeze Corleone 667 feat. Ashe22 - Scellé part.4 [J-RCWiX2fm8].wav | AMBIGUOUS · 166.71 | AMBIGUOUS · 166.71 | no |
| GAZO x Freeze Corleone 667 - DRILL FR 4 [lbeUyW6axeA].wav | AMBIGUOUS · 135.85 | AMBIGUOUS · 135.85 | no |
| MW2 [Sepi1NFW6_0].wav | AMBIGUOUS · 119.59 | AMBIGUOUS · 119.59 | no |
| Poundz - Fake Love [Music Video] ｜ GRM Daily [5ODBlf36p7M].wav | AMBIGUOUS · 140.10 | AMBIGUOUS · 140.10 | no |
| Voldemort [mLH6chE9miQ].wav | AMBIGUOUS · 127.96 | AMBIGUOUS · 127.96 | no |
| Ziak - C'est la vie (Prod. Devil) [9OoDlRJOpW8].wav | AMBIGUOUS · 143.76 | AMBIGUOUS · 143.76 | no |
| gwmstem.wav | AMBIGUOUS · 205.15 | AMBIGUOUS · 205.15 | no |

**Flag rate:** stock 11/16 (68.8 %) → extended 15/16 (93.8 %) · 4 flip(s)

**Flip reasons (extended lane):**

- ledger_en_acier.wav: 180 (unrelated) scores within 82% of 166
- ziak_fixette.wav: 135 (unrelated) scores within 82% of 147
- 0 Lead Vocal.wav: 162 (unrelated) scores within 87% of 144
- BTSFX.wav: 128 (unrelated) scores within 98% of 140

