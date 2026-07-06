# RAI Audio Analyzer v1 — archived source & provenance

Archived 2026-07-06 during the v3 Phase 0 stabilization. This directory is a
**read-only historical reference**: the complete application source of RAI
Audio Analyzer v1, preserved because the v3 merge treats v1 as the feature
checklist and cross-check oracle for the metrics the v2 engine does not yet
compute (Welch spectrum, RMS, dynamic range, sub/bass band energy %, stereo
width, Compare/A-B mode). **Do not port this code wholesale** — v1's
measurement definitions demonstrably disagree with v2's (v1 `compute_lufs_approx`
vs v2's gated BS.1770; v1's single "Peak" vs v2's dBTP/dBFS distinction), and
v1's BPM estimator is the confident-wrong failure v2 exists to replace.
Re-implement features under v2's contracts; v2's definitions are canonical.

## Where this came from

Live original (left untouched, still in place):

    /Users/eliasyoung/RAI_PROECTS/PromptEngine/rai_audio_analyzer/

(The `RAI_PROECTS` folder-name typo is real.) A full-tree archival tarball —
including the `.venv`, `build/`, and `dist/` that this reference copy omits —
is at:

    /Users/eliasyoung/Projects/rai-archives/rai-v1-source-full-20260706.tar.gz
    sha256: 082242c816713e4a8ab5d4436a21e9ad0bb11b529cca2e517f72acdc7485fb04
    (14,814 entries, ~210 MB)

## Proof this is the tree that built the shipped app

The PyInstaller executable inside the source tree's `dist/` is SHA-256
identical to the executable inside the deployed app
`…/Desktop/july 2nd 26/Desktop Apps/June 1st Land fill /RAI Audio Analyzer v1 (LEGACY).app`:

    63ea0474b0a17967fc407ea5d2988e95356dc87b8ce887a310c93b59223e021c  (both)

Verified independently twice on 2026-07-06. The bundle's Python is **3.14**
(no bytecode decompiler supports ≥3.13), so had this source been lost it would
have been effectively unrecoverable — hence the belt-and-braces archiving.

## File inventory (sha256 of the archived copies)

| file | sha256 | note |
| --- | --- | --- |
| `main.py` | `a5de35be4e5c9e306ccaa528c7b729ed2bf8430f5a2d7ec9c20b03f3fd278539` | entry point ("Entry point for RAI Audio Analyzer v1.") |
| `analyzer.py` | `4471007071c4e9ad86e14dc25f5d7fea3011baf518615f8e539ea62e5296f1dd` | all DSP: peak/RMS dBFS, estimate_bpm (envelope autocorrelation), compute_lufs_approx, compute_dynamic_range, compute_spectrum (Welch), compute_band_energies (Sub 20–60 Hz / Bass 60–120 Hz), compute_stereo_width, compare_tracks |
| `app.py` | `ee6ca424f925284dc7ec7f6619dc2dfc530d18e34a699132db94f3c8f9ff31a9` | tkinter UI: Single Track + Compare tabs, tkinterdnd2 drag-drop, metrics rows, waveform + spectrum plots |
| `RAI Audio Analyzer.spec` | `90958b15e676c650b71fe503809fe9c0a39bc8ac6ae7511bac5e670dd2e793d6` | PyInstaller spec (bundle id `com.rai.audioanalyzer`) |
| `requirements.txt` | `a8053a8db6d25679a2ac43c81bfd9dfa1f7629c324cb629c90a55486f2876d7c` | numpy, scipy, matplotlib, tkinterdnd2 |
| `icon/` | — | rai.icns is md5-identical (`0e0fa3ae69840d4979b0ccb9841bcdf9`) to the v2 build icon `build/RAIAudioAnalyzer.icns` — the "final art" icon IS v1's icon, carried forward |

Internal comments in `app.py` mark in-place growth stages ("v1 + v2 UI",
"v2: Spectrum plot", "Compare tab (v3)") — the file evolved through three
internal revisions before being frozen as the app now labelled "v1 (LEGACY)".
The Apr 8 2026 08:06 state archived here is the final, most complete one.
