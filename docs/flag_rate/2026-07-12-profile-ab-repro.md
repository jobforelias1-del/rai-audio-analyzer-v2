# Packaged-vs-profile flag-rate A/B — 2026-07-12 reproduction of the M5 run

The M5 (2026-07-07) A/B table was printed to stdout and never persisted; this is the same command re-run on the corpus at its post-sweep location. Every verdict and BPM matches the M5 transcript table digit-for-digit — corpus integrity proven, and the M5 decision data (11/16 = 68.8 % honest baseline, 0 profile flips) is now on the record.

# Flag-rate A/B — packaged fingerprint vs user profile

- profile: `/Users/eliasyoung/Library/Application Support/RAI Audio Analyzer/fingerprints/drill.user.json` (injected via temp copy)
- corpus: 16 file(s)

| File | Packaged | Profiled | Flipped |
|---|---|---|---|
| freeze_corleone_cartier.wav | AMBIGUOUS · 138.33 | AMBIGUOUS · 138.33 | no |
| freeze_rael.wav | AMBIGUOUS · 136.81 | AMBIGUOUS · 136.81 | no |
| ledger_en_acier.wav | confident · 166.10 | confident · 166.10 | no |
| mathematics_of_the_menace.wav | AMBIGUOUS · 192.66 | AMBIGUOUS · 192.66 | no |
| taco_puttin_on_the_ritz.wav | AMBIGUOUS · 204.55 | AMBIGUOUS · 204.55 | no |
| ziak_fixette.wav | confident · 146.57 | confident · 146.57 | no |
| 0 Lead Vocal.wav | confident · 144.32 | confident · 144.32 | no |
| BTSFX.wav | confident · 140.16 | confident · 140.16 | no |
| Excision & Level Up - Club XL ｜ Subsidia [Kfb4HhDv1uw].wav | confident · 144.61 | confident · 144.61 | no |
| Freeze Corleone 667 feat. Ashe22 - Scellé part.4 [J-RCWiX2fm8].wav | AMBIGUOUS · 166.71 | AMBIGUOUS · 166.71 | no |
| GAZO x Freeze Corleone 667 - DRILL FR 4 [lbeUyW6axeA].wav | AMBIGUOUS · 135.85 | AMBIGUOUS · 135.85 | no |
| MW2 [Sepi1NFW6_0].wav | AMBIGUOUS · 119.59 | AMBIGUOUS · 119.59 | no |
| Poundz - Fake Love [Music Video] ｜ GRM Daily [5ODBlf36p7M].wav | AMBIGUOUS · 140.10 | AMBIGUOUS · 140.10 | no |
| Voldemort [mLH6chE9miQ].wav | AMBIGUOUS · 127.96 | AMBIGUOUS · 127.96 | no |
| Ziak - C'est la vie (Prod. Devil) [9OoDlRJOpW8].wav | AMBIGUOUS · 143.76 | AMBIGUOUS · 143.76 | no |
| gwmstem.wav | AMBIGUOUS · 205.15 | AMBIGUOUS · 205.15 | no |

**Flag rate:** packaged 11/16 (68.8 %) → profiled 11/16 (68.8 %) · 0 flip(s)

