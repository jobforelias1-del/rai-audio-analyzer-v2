# RAI Audio Analyzer v3

Octave-resistant tempo analysis and loudness metering for drill/trap production.
Built to fix the one failure mode that matters: confidently reporting the wrong
BPM because the algorithm silently picked an octave.

v3 pairs the proven v2 tempo engine (`rai_analyzer/` — byte-identical
acceptance-gate output) with a native PySide6 desktop app (`rai_ui/`): tempo
tiebreak with audible click-grid preview, human ground-truth confirmation and
profile relearning, signal metrics, and A/B compare. The v2 tkinter GUI was
retired in the v3 cutover (its Tcl/Tk 9 postmortem lives in
`docs/ENVIRONMENT.md`).

---

## 1. What It Is — And the Octave Problem

Every major tempo-detection tool (including RAI v1 and Moises) shares the same
failure mode on drill and trap: the algorithm picks a peak on a tempo-salience
curve that is exactly half or double the notated tempo, reports it confidently,
and gives the producer no indication that anything is wrong.

This is not a bug in any one tool; it is a fundamental property of how
autocorrelation-based tempograms and Fourier-based tempograms alias:

- The **ACF tempogram** aliases *down* — a 160 BPM track produces a strong peak
  at 80 BPM because the beat period is also a period of the autocorrelation.
- The **Fourier tempogram** aliases *up* — a strong 80 BPM kick grid also lights
  up 160 BPM (the first harmonic).

Drill and trap are the worst case because half-time feel is load-bearing: the
snare sits on beat 3 (not 2 and 4), the 808 lopes below the kick, and the
hi-hats run at a density that is rhythmically consistent with *both* the notated
tempo and half of it.  Tools trained on pop/rock learn a prior that resolves the
ambiguity toward the "normal" 90–120 BPM range; applied to 140–175 BPM drill
material, that prior fires in the wrong direction and the tool confidently
reports 70–87 BPM.

This is a **known open problem in music information retrieval (MIR)**.  No
general-purpose tool solves it reliably.  RAI Audio Analyzer v2 is a
drill/trap-specific answer.

---

## 2. The Approach

### Multiband onset detection

The signal is split into three perceptual bands before onset detection:

| Band  | Frequency range           | Carries                              |
|-------|---------------------------|--------------------------------------|
| low   | DC – 200 Hz               | kick, 808, low transients            |
| mid   | 200 Hz – 8 kHz            | snare, clap, body of the groove      |
| high  | 8 kHz+                    | hi-hats, clicks, shakers             |

Each band produces an independent onset-strength envelope.  The low and mid
bands are the primary tempo evidence; the high band drives the separate
hi-hat-density evidence term.

### The product tempogram (octave-resistant base evidence)

The ACF and DFT tempograms are computed over the combined (low + mid weighted)
onset envelope and then **multiplied** together:

    salience(BPM) = ACF_salience(BPM) × DFT_salience(BPM)

Because the ACF aliases *down* and the DFT aliases *up*, the product suppresses
both directions of octave aliasing.  A tempo that is genuinely present at one
octave will appear as a local maximum in both factors and therefore in the
product; a spurious octave will appear strongly in only one factor and be
suppressed in the product.

### Named evidence terms

Four independently testable evidence terms are combined by a weighted sum to
score each candidate BPM:

| Term               | What it measures                                              | Default weight |
|--------------------|---------------------------------------------------------------|----------------|
| **fingerprint**    | Metrical-profile match against the learned drill/trap pattern | 1.0            |
| **hihat_density**  | Whether the high-band tatum parses as plausible subdivisions  | 0.7            |
| **tempogram**      | Product-tempogram salience at the candidate BPM               | 0.6            |
| **prior**          | Soft log-normal prior centred on the drill/trap notated range | 0.4            |

The fingerprint is the strongest term: genre rhythmic patterns learned from the
ground-truth tracks are folded into a 16th-note grid and compared to the
candidate's metrical profile.

The prior is deliberately the *lightest* scoring term.  Its primary job is the
**divergence ambiguity trigger** (see below), not to override strong rhythmic
evidence.

### The signature feature — it never silently picks an octave

RAI v2 does not force a single number.  It surfaces a **ranked candidate set**
and flags ambiguity for a human tiebreak.  Two triggers raise the ambiguity flag:

1. **Raw-vs-priored divergence** (most reliable): if the raw product-tempogram
   peak and the prior-weighted peak disagree by more than 3%, the prior is
   fighting the raw rhythmic evidence — this is the octave-ambiguous regime.

2. **Close runner-up**: if the second-ranked candidate is octave- or
   fractionally-related to the winner and scores within 82% of the winner's
   score, both hypotheses are plausible and the engine says so.

When the flag is raised, the output reads:

    TEMPO    ⚠  AMBIGUOUS — human tiebreak recommended

When the engine is confident:

    TEMPO    ✓  confident

**This number is reliable.**  A confidently-wrong BPM is the v1 failure mode;
it does not happen in v2.

---

## 3. Install

```bash
pip install -r requirements.txt
```

The requirements file pins floor versions for the **engine** (analysis, CLI,
validation gate). Python 3.10 or later is required. The Qt desktop app runs
from its own venv — `requirements-v3.lock.txt` under the uv-managed
interpreter discipline in `docs/ENVIRONMENT.md` — set that up before
`python -m rai_ui` in section 4 (M5 review finding: this file alone no
longer installs the GUI).

---

## 4. Running the Analyzer

### GUI — the v3 desktop app

```bash
python -m rai_ui        # dev run (PySide6, .venv-v3)
```

Or launch the frozen `RAI Audio Analyzer.app` (see section 7). Drop a WAV
anywhere on the window (or click **Browse…**): Overview, Tempo (candidate
table, tiebreak with click-grid preview, ground-truth confirm), Signal,
Compare, and the verbatim Report.

### CLI

Analyze a file and print the text report:

```bash
python -m rai_analyzer.cli track.wav
```

Emit machine-readable JSON instead:

```bash
python -m rai_analyzer.cli track.wav --json
```

Skip loudness measurement (faster; tempo only):

```bash
python -m rai_analyzer.cli track.wav --no-loudness
```

The JSON output shape (`AnalysisResult.to_dict()`) is defined in
`rai_analyzer/contracts.py`.  Key fields:

```json
{
  "tempo": {
    "primary_bpm": 166.01,
    "felt_bpm": 83.00,
    "ambiguous": false,
    "ambiguity_reason": null,
    "candidates": [
      { "bpm": 166.01, "salience": 0.912, "score": 0.847, "relationship": "self" },
      { "bpm": 83.00,  "salience": 0.761, "score": 0.621, "relationship": "octave_down" }
    ]
  },
  "loudness": {
    "lufs_i": -9.42,
    "true_peak_dbtp": -0.31,
    "sample_peak_dbfs": -0.32
  }
}
```

---

## 5. The Acceptance Gate

### What the gate is

Unit tests are *not* the gate.  The gate is three producer-confirmed tracks
("DAW-warp confirmed" — each was warped to a grid in a DAW to confirm the
notated tempo).  The gate criterion for each track:

    recall            — the true BPM was surfaced as a candidate at all
    avoided_v1_error  — the primary BPM did NOT reproduce v1's confident-wrong number
    hit               — the primary BPM matched the truth within 2%
    flagged           — the engine flagged the result ambiguous

    PASS  ⟺  recall AND avoided_v1_error AND (hit OR flagged)

Rationale: the signature feature is *reliability*, not always being exactly
right.  Nailing the truth is best; but honestly flagging ambiguity with the
truth in the candidate set (for a human tiebreak) is equally trustworthy — the
inverse of v1's failure mode.

### Dropping in the fixture WAVs

The ground-truth WAVs are large binaries and are `.gitignored`.  Drop all three
into the fixtures directory using **exactly** these filenames:

```
validation/fixtures/ledger_en_acier.wav
validation/fixtures/mathematics_of_the_menace.wav
validation/fixtures/taco_puttin_on_the_ritz.wav
```

### Running the harness

```bash
python -m validation
```

The harness auto-detects which fixtures are present and runs the gate over
them.  If no fixtures are present it prints instructions and falls back to a
**synthetic self-test** — three synthesized drill beats at known tempos run
through the same gate logic and format — so the pipeline and gate can always be
exercised end-to-end.

---

## 6. Tuning Against the Gate

All tunable parameters live in `rai_analyzer/config.py`.  No engine code
changes are needed to tune the analyzer — edit the values in config.py and
re-run the harness.

Key parameters to tune first:

| Parameter / dataclass             | What it controls                                              |
|-----------------------------------|---------------------------------------------------------------|
| `ResolverWeights.fingerprint`     | Weight of the metrical-profile fingerprint term (default 1.0) |
| `ResolverWeights.hihat_density`   | Weight of the hi-hat subdivision-density term (default 0.7)  |
| `ResolverWeights.tempogram`       | Weight of the product-tempogram salience term (default 0.6)  |
| `ResolverWeights.prior`           | Weight of the log-normal tempo prior (default 0.4)           |
| `PriorParams.center_bpm`         | Geometric centre of the prior bump (default 145.0 BPM)       |
| `PriorParams.sigma`              | Width of the prior in ln-BPM units (default 0.30; wider = softer) |
| `AmbiguityParams.divergence_tol` | Raw-vs-priored divergence threshold (default 0.03 = 3%)      |
| `AmbiguityParams.score_close_frac`| Runner-up closeness threshold (default 0.82)                |
| `HihatParams.implausible_ratio`  | Tatum:beat ratio above which hats are "too fine" (default 6.5)|
| `TempoConfig.band_weights`       | (low, mid, high) weights in the combined tempogram           |

Example — softening the prior so it nudges less aggressively:

```python
# rai_analyzer/config.py
@dataclass
class PriorParams:
    center_bpm: float = 145.0
    sigma:      float = 0.40   # wider — prior fires more softly
    floor:      float = 0.10
```

Then re-run: `python -m validation`.

---

## 7. Building the macOS .app

**This must be run on a Mac** — PyInstaller produces a `.app` for the OS on
which it runs.  The Linux container (CI / dev environment) cannot produce a
valid macOS bundle.

### Prerequisites (on the Mac)

- macOS 13 Ventura or later (Qt 6.8+ floor)
- The uv-managed v3 UI venv (`.venv-v3` — see `docs/ENVIRONMENT.md`; **never
  Homebrew Python**, per the build policy)
- A **clean git tree** — the build script hard-aborts otherwise

### Build

From the repository root:

```bash
bash build/build_macos_v3.sh
```

The script (the ONLY supported freeze path — it stamps build provenance and
smoke-tests the result):
1. Guards the interpreter (uv-managed, non-Homebrew) and the clean tree
2. Stamps the commit hash into `rai_ui/_buildinfo.py` and the Info.plist
3. Runs `pyinstaller build/RAIv3.spec`
4. Asserts the bundle carries no Qt/sklearn bloat, ad-hoc signs it
5. Runs BOTH frozen smoke probes (direct `--smoke` exec and the `open -n`
   LaunchServices launch + crash-report scan)

The finished app lands at:

```
dist-v3/RAI Audio Analyzer.app
```

Drag it into `/Applications` or distribute as a ZIP.

### Gatekeeper / First Launch

macOS Gatekeeper blocks un-notarized apps.  With ad-hoc signing (what the
build script applies automatically):

1. **Right-click** the `.app` → **Open**
2. In the Gatekeeper dialog, click **Open** again
3. The app launches; subsequent double-clicks work normally

### Real notarization (for mass distribution)

To ship to end users without the right-click workaround, you need an Apple
Developer Program membership ($99/year) and a **Developer ID Application**
certificate.  The entitlements file at `build/entitlements.plist`
grants the hardened-runtime permissions required by numba's JIT compiler
(`com.apple.security.cs.allow-jit` and
`com.apple.security.cs.allow-unsigned-executable-memory`); pass it to
`codesign --entitlements` when doing a real Developer ID sign.

---

## 8. Architecture / Module Map

```
rai_analyzer/          THE ENGINE (UI-free; never imports rai_ui or Qt)
  __init__.py          Public API: analyze_file, TempoConfig, contracts re-exported
  analyzer.py          Top-level orchestrator: load → build_features → resolve_tempo → loudness
  cli.py               CLI entry point (python -m rai_analyzer.cli)
  profiles.py          Packaged --profile registry ("drill" = the default config)
  config.py            ALL tunable weights and parameters (TempoConfig + sub-dataclasses)
  contracts.py         Data shapes: AnalysisResult, TempoResult, Candidate, LoudnessResult, etc.
  io_audio.py          Audio loading + resampling (returns AudioSignal)
  onsets.py            Multiband onset-strength envelope computation (BandEnvelopes)
  tempogram.py         Product tempogram construction + Features assembly
  resolver.py          Candidate scoring + weighted sum + ambiguity logic → TempoResult
  candidates.py        Candidate BPM generation (multipliers + independent tempogram peaks)
  loudness.py          ITU-R BS.1770 / EBU R128 loudness (pyloudnorm wrapper)
  synthetic.py         Synthetic drill beat generator (used by the validation self-test)
  beatgrid.py          Beat-phase estimation for the click-grid preview (M2)
  metrics/             Engine-additive signal metrics: spectrum, dynamics, bands, stereo (M2)
  fingerprints/        Bundled genre fingerprint JSON files (e.g. drill.json)
  evidence/
    __init__.py        Evidence sub-package
    fingerprint.py     Metrical-profile fingerprint evidence term
    hihat_density.py   Hi-hat subdivision-density evidence term
    prior.py           Soft log-normal tempo prior evidence term (+ fit_prior utility)
    tempogram_strength.py  Product-tempogram salience evidence term

rai_ui/                THE v3 DESKTOP APP (PySide6; imports the engine, never
                       the reverse — AST-enforced by tests/test_engine_boundary.py)
  __main__.py          python -m rai_ui: GUI / smoke probe / headless CLI dispatch
  main_window.py       Shell: chrome, sections, drag-drop, analysis wiring
  sections/ widgets/ plots/ state/ services/ theme/   see docs/PHASE3_PLAN.md §1

validation/
  __init__.py          Package init (exposes run_gate)
  __main__.py          python -m validation entry point
  harness.py           Acceptance gate logic: evaluate, print, aggregate
  ground_truth.py      Ground-truth truth table (true BPM, v1 wrong BPM, filenames)
  fixtures/            Drop ground-truth WAVs here (.gitignored; see section 5)
```

---

## 9. Contract Notes

**Dynamic range / crest factor** — deferred in v2, closed by v3's
engine-additive metrics layer (`rai_analyzer/metrics/`): crest, whole-file
RMS, band energy, and stereo width are computed for the app's Overview and
Signal sections.  The CLI/report contract is deliberately unchanged:
`AnalysisResult` (`rai_analyzer/contracts.py`) still carries tempo + loudness
only, so `python -m rai_analyzer.cli` output and the acceptance-gate bytes
are identical to the shipped v2 engine.
