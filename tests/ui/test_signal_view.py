"""Tests for the pure Overview/Signal view-models (rai_ui.state.signal_view).

Pure Python + numpy — no Qt anywhere, so every card string and every edge
state is asserted headless and the module collects in the Qt-less engine CI
venv. Payloads are REAL ``rai_analyzer.metrics.contracts`` dataclasses (the
exact objects the worker composes), and the AnalysisResult builders are
shared with tests/ui/test_tempo_view.py — one set of fakes, three sections.

Edge-state matrix under test (design recon §3 + rulings):

* silence: −∞ loudness/RMS are MEASUREMENTS, crest/sub/width are absence
  (``—``) chip-explained ``silent file``; the spectrum well shows copy, not a
  curve (R-M2-8).
* unmeasurable: a NON-silent file with no finite spectrum bins (canonical
  case: pure DC offset) — the well shows the unmeasurable copy, the NaN
  shares chip ``no audible-band energy``, and the TRUE measurements (0.0 dB
  crest, finite RMS/peak) render untouched.
* mono: stereo width ``0 %`` — a measurement, no chip (R-M2-4).
* short clip: LUFS ``—`` + ``undefined below 0.4 s``; DR still renders (the
  R-M2-6 divergence from the demo's scenario data).
* metrics degraded to None on a real analysis (R-M2-15): dashes +
  ``unavailable for this file`` chips.
* WORKING and ERROR blank everything, chips included (R-M2-16 / R-M1-3).
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rai_analyzer.metrics.contracts import (
    BandEnergyResult,
    DynamicsResult,
    SignalResult,
    SpectrumData,
    StereoResult,
)
from rai_ui.state import signal_view
from rai_ui.state.signal_view import (
    AMBIGUOUS_VERDICT_WORD,
    EMPTY_OVERVIEW_VIEW,
    EMPTY_SIGNAL_VIEW,
    SILENT_SPECTRUM_TEXT,
    SPECTRUM_FLOOR_DB,
    UNMEASURABLE_REASON,
    UNMEASURABLE_SPECTRUM_TEXT,
    WAVEFORM_BINS,
    ChipNote,
    build_overview_view,
    build_signal_view,
)
from rai_ui.state.verdict import VerdictKind, VerdictState
from rai_ui.theme._tokens_gen import (
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_CONFIDENT_BASE,
    COLOR_TEXT_MUTED,
)
from tests.ui.test_tempo_view import make_result, make_tempo, no_tempo_result

from rai_analyzer.contracts import LoudnessResult

EM_DASH = "—"
NEG_INF = float("-inf")
NAN = float("nan")


# ---------------------------------------------------------------------------
# Builders — real metrics contracts, engine-shaped values
# ---------------------------------------------------------------------------


def make_spectrum(n: int = 64, lo_db: float = -60.0, hi_db: float = -30.0) -> SpectrumData:
    freqs = np.geomspace(20.0, 20000.0, n)
    return SpectrumData(freqs=freqs, psd_db=np.linspace(lo_db, hi_db, n))


def silent_spectrum(n: int = 64) -> SpectrumData:
    freqs = np.geomspace(20.0, 20000.0, n)
    return SpectrumData(freqs=freqs, psd_db=np.full(n, NEG_INF))


def make_bands(sub: float = 21.0, bass: float = 9.0) -> BandEnergyResult:
    rest = (100.0 - sub - bass) / 4.0 if math.isfinite(sub) else NAN
    return BandEnergyResult(
        sub_pct=sub,
        bass_pct=bass,
        six_band={
            "sub": sub,
            "bass": bass,
            "low_mid": rest,
            "mid": rest,
            "high_mid": rest,
            "air": rest,
        },
    )


def make_signal_result(
    peak: float = -1.1,
    rms: float = -16.4,
    crest: float = 8.2,
    sub: float = 21.0,
    width: float = 62.0,
    correlation: float | None = 0.41,
    spectrum: SpectrumData | None = None,
) -> SignalResult:
    return SignalResult(
        spectrum=spectrum if spectrum is not None else make_spectrum(),
        dynamics=DynamicsResult(peak_dbfs=peak, rms_dbfs=rms, crest_db=crest),
        bands=make_bands(sub=sub),
        stereo=StereoResult(width_pct=width, correlation=correlation),
    )


def silent_signal_result(width: float = NAN) -> SignalResult:
    """The engine's exact silence shape: −∞ peaks/RMS, NaN crest/shares,
    NaN width (stereo container) or 0.0 (mono), None correlation."""
    return SignalResult(
        spectrum=silent_spectrum(),
        dynamics=DynamicsResult(peak_dbfs=NEG_INF, rms_dbfs=NEG_INF, crest_db=NAN),
        bands=make_bands(sub=NAN, bass=NAN),
        stereo=StereoResult(width_pct=width, correlation=None),
    )


def mono_signal_result(**kw) -> SignalResult:
    return make_signal_result(width=0.0, correlation=None, **kw)


def dc_signal_result() -> SignalResult:
    """The engine's exact pure-DC shape (runtime-verified on
    ``compute_signal_result`` with a constant 0.5 mono buffer): FINITE peak
    and RMS (−6.02 dBFS), a TRUE 0.0 dB crest, but Welch's constant detrend
    leaves every PSD bin −∞ → NaN band shares. NOT silent — the peak probe
    is finite — yet nothing in the audible band measures."""
    return SignalResult(
        spectrum=silent_spectrum(),  # all-−∞ psd_db — no finite bins
        dynamics=DynamicsResult(peak_dbfs=-6.02, rms_dbfs=-6.02, crest_db=0.0),
        bands=make_bands(sub=NAN, bass=NAN),
        stereo=StereoResult(width_pct=0.0, correlation=None),
    )


def state(kind: VerdictKind, **kw) -> VerdictState:
    return VerdictState(kind=kind, **kw)


CONFIDENT = state(VerdictKind.CONFIDENT, path="/tmp/beat.wav")


# ---------------------------------------------------------------------------
# Module purity (same AST gate as tempo_view)
# ---------------------------------------------------------------------------


def test_module_is_qt_free():
    """PySide6/pyqtgraph imports are forbidden in signal_view (pure doctrine)."""
    import ast

    source = Path(signal_view.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PySide6" not in imported
    assert "pyqtgraph" not in imported


# ---------------------------------------------------------------------------
# EMPTY views (the no-file state every widget starts from)
# ---------------------------------------------------------------------------


class TestEmptySignalView:
    def test_shape(self):
        v = EMPTY_SIGNAL_VIEW
        assert v.has_signal is False
        assert v.silent is False
        assert v.silent_text is None
        assert v.unmeasurable is False
        assert v.unmeasurable_text is None
        assert v.spectrum_freqs is None and v.spectrum_db is None

    def test_cards_all_absence_no_chips(self):
        for card in (EMPTY_SIGNAL_VIEW.width_card, EMPTY_SIGNAL_VIEW.sub_card):
            assert card.value_text == EM_DASH
            assert card.gauge_frac == 0.0
            assert card.chip is None
        dr = EMPTY_SIGNAL_VIEW.dr_card
        assert dr.value_text == EM_DASH
        assert dr.gauge_frac is None  # the DR card never grows a gauge
        assert dr.chip is None

    def test_fixed_captions_survive_absence(self):
        assert EMPTY_SIGNAL_VIEW.width_card.caption == "mid/side correlation, whole file"
        assert EMPTY_SIGNAL_VIEW.sub_card.caption == "share of energy below 60 Hz"
        assert EMPTY_SIGNAL_VIEW.dr_card.caption == "crest-based, whole file · RMS —"

    def test_none_verdict_state_falls_back_to_initial(self):
        vm = build_signal_view(None, None, None)
        assert vm == EMPTY_SIGNAL_VIEW


class TestEmptyOverviewView:
    def test_shape(self):
        v = EMPTY_OVERVIEW_VIEW
        assert v.has_result is False
        assert v.wave_mins is None and v.wave_maxs is None
        assert v.wave_len_text == EM_DASH

    def test_tempo_card_dash_muted(self):
        card = EMPTY_OVERVIEW_VIEW.tempo_card
        assert card.primary_text == EM_DASH
        assert card.felt_text == EM_DASH
        assert card.verdict_word == EM_DASH
        assert card.verdict_tint == COLOR_TEXT_MUTED

    def test_rows_all_absence_no_chips(self):
        for card in (
            EMPTY_OVERVIEW_VIEW.loudness_card,
            EMPTY_OVERVIEW_VIEW.dynamics_card,
            EMPTY_OVERVIEW_VIEW.file_card,
        ):
            assert card.chip is None
            assert all(row.value_text == EM_DASH for row in card.rows)

    def test_row_labels_and_units_verbatim(self):
        loud = EMPTY_OVERVIEW_VIEW.loudness_card
        assert [(r.label, r.unit) for r in loud.rows] == [
            ("Integrated", "LUFS"),
            ("True peak", "dBTP"),
            ("Sample peak", "dBFS"),
        ]
        dyn = EMPTY_OVERVIEW_VIEW.dynamics_card
        assert [(r.label, r.unit) for r in dyn.rows] == [
            ("Dyn range", "dB"),
            ("Sub/bass", None),
            ("Stereo width", None),
        ]
        file_card = EMPTY_OVERVIEW_VIEW.file_card
        assert [r.label for r in file_card.rows] == ["Name", "Length", "Rate", "Channels"]
        assert all(r.unit is None for r in file_card.rows)

    def test_card_labels_verbatim(self):
        assert EMPTY_OVERVIEW_VIEW.loudness_card.label == "Loudness"
        assert EMPTY_OVERVIEW_VIEW.dynamics_card.label == "Dynamics"
        assert EMPTY_OVERVIEW_VIEW.file_card.label == "File"


# ---------------------------------------------------------------------------
# Signal section — populated
# ---------------------------------------------------------------------------


class TestSignalPopulated:
    @pytest.fixture()
    def vm(self):
        return build_signal_view(make_result(), make_signal_result(), CONFIDENT)

    def test_flags(self, vm):
        assert vm.has_signal is True
        assert vm.silent is False
        assert vm.silent_text is None

    def test_demo_values_verbatim(self, vm):
        # Console confident scenario (04:682): dr 8.2 · rms −16.4 dB · sub
        # 21 % · width 62 %.
        assert vm.width_card.value_text == "62 %"
        assert vm.sub_card.value_text == "21 %"
        assert vm.dr_card.value_text == "8.2"
        assert vm.dr_card.caption == "crest-based, whole file · RMS −16.4 dB"

    def test_gauge_fractions(self, vm):
        assert vm.width_card.gauge_frac == pytest.approx(0.62)
        assert vm.sub_card.gauge_frac == pytest.approx(0.21)
        assert vm.dr_card.gauge_frac is None

    def test_no_chips_on_healthy_values(self, vm):
        assert vm.width_card.chip is None
        assert vm.sub_card.chip is None
        assert vm.dr_card.chip is None

    def test_labels_verbatim(self, vm):
        assert vm.width_card.label == "Stereo width"
        assert vm.sub_card.label == "Sub/bass energy"
        assert vm.dr_card.label == "Dynamic range"

    def test_spectrum_normalized_max_zero_floor_minus_90(self, vm):
        assert vm.spectrum_freqs is not None and vm.spectrum_db is not None
        assert vm.spectrum_freqs.shape == vm.spectrum_db.shape
        assert float(vm.spectrum_db.max()) == 0.0
        assert float(vm.spectrum_db.min()) >= SPECTRUM_FLOOR_DB

    def test_spectrum_freqs_pass_through_values(self, vm):
        np.testing.assert_allclose(vm.spectrum_freqs, make_spectrum().freqs)

    def test_fractional_pct_keeps_one_decimal(self):
        # Ambiguous demo scenario (04:690): sub 10.5 %.
        vm = build_signal_view(
            make_result(), make_signal_result(sub=10.5, width=48.0), CONFIDENT
        )
        assert vm.sub_card.value_text == "10.5 %"
        assert vm.width_card.value_text == "48 %"

    def test_gauge_frac_clamped(self):
        vm = build_signal_view(
            make_result(), make_signal_result(sub=150.0, width=-5.0), CONFIDENT
        )
        assert vm.sub_card.gauge_frac == 1.0
        assert vm.width_card.gauge_frac == 0.0

    def test_neg_inf_spectrum_bins_clip_to_floor(self):
        freqs = np.geomspace(20.0, 20000.0, 8)
        db = np.array([NEG_INF, -300.0, -60.0, -50.0, -40.0, -35.0, -32.0, -30.0])
        sr = make_signal_result(spectrum=SpectrumData(freqs=freqs, psd_db=db))
        vm = build_signal_view(make_result(), sr, CONFIDENT)
        assert float(vm.spectrum_db[0]) == SPECTRUM_FLOOR_DB
        assert float(vm.spectrum_db[1]) == SPECTRUM_FLOOR_DB
        assert float(vm.spectrum_db.max()) == 0.0

    def test_empty_spectrum_arrays_mean_no_curve(self):
        # A <2-sample clip measures an empty spectrum (engine contract); the
        # cards still render. No finite bins means the well is UNMEASURABLE —
        # it shows the explanatory copy rather than a mute blank bed.
        empty = SpectrumData(freqs=np.zeros(0), psd_db=np.zeros(0))
        vm = build_signal_view(
            make_result(), make_signal_result(spectrum=empty), CONFIDENT
        )
        assert vm.spectrum_freqs is None and vm.spectrum_db is None
        assert vm.silent is False  # not silence — there was signal, just no FFT
        assert vm.unmeasurable is True
        assert vm.unmeasurable_text == UNMEASURABLE_SPECTRUM_TEXT
        assert vm.dr_card.value_text == "8.2"
        # Finite values never grow the chip — it rides only with "—".
        assert vm.dr_card.chip is None
        assert vm.sub_card.value_text == "21 %"
        assert vm.sub_card.chip is None


# ---------------------------------------------------------------------------
# Signal section — edge states
# ---------------------------------------------------------------------------


class TestSignalSilence:
    @pytest.fixture()
    def vm(self):
        return build_signal_view(no_tempo_result(), silent_signal_result(), CONFIDENT)

    def test_silent_flag_and_copy(self, vm):
        assert vm.has_signal is True
        assert vm.silent is True
        assert vm.silent_text == SILENT_SPECTRUM_TEXT
        assert vm.silent_text == "no signal — silent file — nothing to measure"

    def test_silence_wins_over_unmeasurable(self, vm):
        # A silent file also has zero finite spectrum bins, but the two
        # states are mutually exclusive — silence takes precedence and the
        # well shows the R-M2-8 silent copy, not the unmeasurable copy.
        assert vm.unmeasurable is False
        assert vm.unmeasurable_text is None

    def test_no_curve_on_silence(self, vm):
        assert vm.spectrum_freqs is None and vm.spectrum_db is None

    def test_undefined_shares_are_absence_with_silent_chip(self, vm):
        # "−∞ is a measurement, — is absence, always chip-explained" (C-06).
        for card in (vm.width_card, vm.sub_card, vm.dr_card):
            assert card.value_text == EM_DASH
            assert card.chip == ChipNote(text="silent file")
        assert vm.width_card.gauge_frac == 0.0  # the demo's "— (bar 0)"
        assert vm.sub_card.gauge_frac == 0.0

    def test_rms_neg_inf_is_a_measurement_in_the_caption(self, vm):
        # Silence prints a bare −∞ (no dB unit — demo table), never a dash.
        assert vm.dr_card.caption == "crest-based, whole file · RMS −∞"

    def test_silent_mono_width_is_still_a_measurement(self):
        # Stage-1 handoff caution: NaN width (silent stereo) is absence, but
        # mono's structural width 0.0 stays "0 %" even on silence.
        vm = build_signal_view(
            no_tempo_result(), silent_signal_result(width=0.0), CONFIDENT
        )
        assert vm.width_card.value_text == "0 %"
        assert vm.width_card.chip is None
        assert vm.sub_card.value_text == EM_DASH  # shares stay undefined


class TestSignalUnmeasurable:
    """The unmeasurable state: non-silent file, zero finite spectrum bins.

    Canonical case is a pure DC offset — the file is NOT silent (finite
    −6.02 dBFS peak), but Welch's constant detrend leaves no finite PSD bins
    and the band shares NaN. Pre-fix this rendered a BLANK well with no
    explanatory copy and a chip-less ``—`` on the Sub/bass card."""

    @pytest.fixture()
    def vm(self):
        return build_signal_view(make_result(), dc_signal_result(), CONFIDENT)

    def test_flags_and_copy_verbatim(self, vm):
        assert vm.has_signal is True
        assert vm.silent is False
        assert vm.silent_text is None
        assert vm.unmeasurable is True
        assert vm.unmeasurable_text == UNMEASURABLE_SPECTRUM_TEXT
        assert (
            vm.unmeasurable_text
            == "no measurable signal — nothing in the audible band"
        )

    def test_no_curve(self, vm):
        assert vm.spectrum_freqs is None and vm.spectrum_db is None

    def test_nan_share_gets_the_reason_chip(self, vm):
        # R-M2-10: the genuinely-NaN sub share reads "—" AND carries the
        # C-06 chip explaining why (pre-fix it was a bare chip-less dash).
        assert vm.sub_card.value_text == EM_DASH
        assert vm.sub_card.chip == ChipNote(text=UNMEASURABLE_REASON)
        assert vm.sub_card.chip == ChipNote(text="no audible-band energy")
        assert vm.sub_card.gauge_frac == 0.0  # the demo's "— (bar 0)"

    def test_true_measurements_are_never_suppressed(self, vm):
        # A constant signal's 0.0 dB crest is TRUE (peak == RMS) — it renders
        # as a measurement, no chip; ditto the finite RMS in the caption and
        # the mono file's structural 0 % width.
        assert vm.dr_card.value_text == "0.0"
        assert vm.dr_card.chip is None
        assert vm.dr_card.caption == "crest-based, whole file · RMS −6.0 dB"
        assert vm.width_card.value_text == "0 %"
        assert vm.width_card.chip is None

    def test_dc_wav_end_to_end_through_real_engine(self):
        # Same defect, zero fakes: a DC buffer through the REAL
        # compute_signal_result (engine imported read-only), then the builder.
        from rai_analyzer.metrics.compute import compute_signal_result

        signal = SimpleNamespace(
            y_native=np.full(48000, 0.5, dtype=np.float32), sr_native=48000
        )
        sr = compute_signal_result(signal)
        assert math.isfinite(float(sr.dynamics.peak_dbfs))  # NOT silent
        assert not np.isfinite(np.asarray(sr.spectrum.psd_db)).any()

        vm = build_signal_view(make_result(), sr, CONFIDENT)
        assert vm.silent is False
        assert vm.unmeasurable is True
        assert vm.unmeasurable_text == UNMEASURABLE_SPECTRUM_TEXT
        assert vm.spectrum_freqs is None and vm.spectrum_db is None
        assert vm.sub_card.value_text == EM_DASH
        assert vm.sub_card.chip == ChipNote(text="no audible-band energy")
        assert vm.dr_card.value_text == "0.0"  # crest is TRUE on a constant
        assert vm.dr_card.chip is None


class TestSignalMono:
    def test_mono_width_zero_percent_no_chip(self):
        # 04:699 — the mono kick test renders width "0 %" (bar 0), no chip.
        vm = build_signal_view(make_result(), mono_signal_result(), CONFIDENT)
        assert vm.width_card.value_text == "0 %"
        assert vm.width_card.gauge_frac == 0.0
        assert vm.width_card.chip is None


class TestSignalMetricsDegraded:
    def test_result_without_metrics_gets_unavailable_chips(self):
        # R-M2-15: a metrics exception degrades to None — the analysis
        # succeeded, so the absence is real and chip-explained.
        vm = build_signal_view(make_result(), None, CONFIDENT)
        assert vm.has_signal is False
        for card in (vm.width_card, vm.sub_card, vm.dr_card):
            assert card.value_text == EM_DASH
            assert card.chip == ChipNote(text="unavailable for this file")

    def test_no_result_no_chips(self):
        # No analysis at all: plain absence, nothing to explain.
        vm = build_signal_view(None, None, CONFIDENT)
        assert vm.width_card.chip is None
        assert vm.sub_card.chip is None
        assert vm.dr_card.chip is None


class TestSignalBlankRule:
    """WORKING and ERROR blank the Signal section exactly like Tempo —
    including the metrics of a PREVIOUS result still stored in the session."""

    @pytest.mark.parametrize("kind", [VerdictKind.WORKING, VerdictKind.ERROR])
    def test_blank_kinds_null_everything(self, kind):
        vm = build_signal_view(make_result(), make_signal_result(), state(kind))
        assert vm.has_signal is False
        assert vm.silent is False
        assert vm.unmeasurable is False
        assert vm.unmeasurable_text is None
        assert vm.spectrum_freqs is None and vm.spectrum_db is None
        for card in (vm.width_card, vm.sub_card, vm.dr_card):
            assert card.value_text == EM_DASH
            assert card.chip is None  # dashes with NO chips (R-M2-10)

    @pytest.mark.parametrize("kind", [VerdictKind.WORKING, VerdictKind.ERROR])
    def test_blank_kinds_null_the_unmeasurable_state_too(self, kind):
        # The new state must blank like everything else: a stored DC result
        # shows NO copy and NO chips while WORKING/ERROR (R-M2-16 / R-M1-3).
        vm = build_signal_view(make_result(), dc_signal_result(), state(kind))
        assert vm.unmeasurable is False
        assert vm.unmeasurable_text is None
        assert vm.silent is False and vm.silent_text is None
        assert vm.sub_card.chip is None
        assert vm.dr_card.value_text == EM_DASH

    def test_non_blank_states_render(self):
        vm = build_signal_view(make_result(), make_signal_result(), CONFIDENT)
        assert vm.has_signal is True
        assert vm.width_card.value_text == "62 %"


# ---------------------------------------------------------------------------
# Overview — tempo card verdict line (R-M2-20)
# ---------------------------------------------------------------------------


class TestOverviewTempoCard:
    def test_confident(self):
        vm = build_overview_view(make_result(), None, None, CONFIDENT)
        card = vm.tempo_card
        assert card.primary_text == "205.15"
        assert card.felt_text == "102.57"
        assert card.verdict_word == "✓ confident"
        assert card.verdict_tint == COLOR_SEMANTIC_CONFIDENT_BASE

    def test_ambiguous_word_has_no_diamond_glyph(self):
        # The ◆ is a DRAWN icon (never a font glyph); widgets key it off the
        # exported constant.
        vm = build_overview_view(
            make_result(make_tempo(ambiguous=True)),
            None,
            None,
            state(VerdictKind.AMBIGUOUS),
        )
        assert vm.tempo_card.verdict_word == AMBIGUOUS_VERDICT_WORD
        assert vm.tempo_card.verdict_word == "ambiguous — human tiebreak"
        assert "◆" not in vm.tempo_card.verdict_word
        assert vm.tempo_card.verdict_tint == COLOR_SEMANTIC_AMBIGUOUS_BASE

    def test_confirmed_human(self):
        vm = build_overview_view(
            make_result(),
            None,
            None,
            state(VerdictKind.CONFIRMED_HUMAN, confirmed_bpm=155.25),
        )
        assert vm.tempo_card.verdict_word == "✓ confirmed · human"
        assert vm.tempo_card.verdict_tint == COLOR_SEMANTIC_CONFIDENT_BASE

    @pytest.mark.parametrize(
        "kind",
        [VerdictKind.NO_FILE, VerdictKind.NO_TEMPO, VerdictKind.WORKING, VerdictKind.ERROR],
    )
    def test_outside_vocabulary_falls_back_to_muted_dash(self, kind):
        # The design's short-word vocabulary has exactly four forms; every
        # other kind renders the muted em-dash (the full verdict block with
        # NO TEMPO / WORKING… / ERROR stays rail-only).
        vm = build_overview_view(make_result(), None, None, state(kind))
        assert vm.tempo_card.verdict_word == EM_DASH
        assert vm.tempo_card.verdict_tint == COLOR_TEXT_MUTED

    def test_no_tempo_result_dashes_bpm_texts(self):
        vm = build_overview_view(
            no_tempo_result(), None, None, state(VerdictKind.NO_TEMPO)
        )
        assert vm.tempo_card.primary_text == EM_DASH
        assert vm.tempo_card.felt_text == EM_DASH

    def test_felt_absent_dashes_felt_only(self):
        vm = build_overview_view(
            make_result(make_tempo(felt_bpm=None)), None, None, CONFIDENT
        )
        assert vm.tempo_card.primary_text == "205.15"
        assert vm.tempo_card.felt_text == EM_DASH


# ---------------------------------------------------------------------------
# Overview — loudness card chips (existing loudness behavior, C-06 verbatim)
# ---------------------------------------------------------------------------


class TestOverviewLoudnessCard:
    def test_values_with_units(self):
        loud = LoudnessResult(lufs_i=-9.8, true_peak_dbtp=-0.6, sample_peak_dbfs=-1.1)
        vm = build_overview_view(make_result(loudness=loud), None, None, CONFIDENT)
        rows = vm.loudness_card.rows
        assert [(r.value_text, r.unit) for r in rows] == [
            ("−9.80", "LUFS"),
            ("−0.60", "dBTP"),
            ("−1.10", "dBFS"),
        ]
        assert vm.loudness_card.chip is None

    def test_silence_neg_inf_is_measurement_no_chip(self):
        # R-M2-10: chips ride ONLY with "—". −∞ LUFS is a measurement.
        loud = LoudnessResult(lufs_i=NEG_INF, true_peak_dbtp=NEG_INF, sample_peak_dbfs=NEG_INF)
        vm = build_overview_view(make_result(loudness=loud), None, None, CONFIDENT)
        assert vm.loudness_card.rows[0].value_text == "−∞"
        assert vm.loudness_card.chip is None

    def test_short_clip_nan_lufs_gets_undefined_chip(self):
        # kick_test.wav (0.31 s): pyloudnorm cannot gate below its 0.4 s
        # block → NaN → "—" + the C-06 copy verbatim.
        loud = LoudnessResult(lufs_i=NAN, true_peak_dbtp=-2.8, sample_peak_dbfs=-3.1)
        result = make_result(loudness=loud)
        result.duration = 0.31
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.loudness_card.rows[0].value_text == EM_DASH
        assert vm.loudness_card.chip == ChipNote(text="undefined below 0.4 s")
        # Peaks survive even when LUFS can't — never collapse the trio.
        assert vm.loudness_card.rows[1].value_text == "−2.80"
        assert vm.loudness_card.rows[2].value_text == "−3.10"

    def test_nan_lufs_on_long_clip_is_meter_failure(self):
        loud = LoudnessResult(lufs_i=NAN, true_peak_dbtp=-0.6, sample_peak_dbfs=-1.1)
        vm = build_overview_view(make_result(loudness=loud), None, None, CONFIDENT)
        assert vm.loudness_card.chip == ChipNote(text="unavailable for this file")

    def test_loudness_none_dashes_trio_with_chip(self):
        vm = build_overview_view(make_result(loudness=None), None, None, CONFIDENT)
        assert all(r.value_text == EM_DASH for r in vm.loudness_card.rows)
        assert vm.loudness_card.chip == ChipNote(text="unavailable for this file")


# ---------------------------------------------------------------------------
# Overview — dynamics card
# ---------------------------------------------------------------------------


class TestOverviewDynamicsCard:
    def test_values(self):
        vm = build_overview_view(
            make_result(), None, make_signal_result(), CONFIDENT
        )
        rows = vm.dynamics_card.rows
        assert [(r.value_text, r.unit) for r in rows] == [
            ("8.2", "dB"),
            ("21 %", None),
            ("62 %", None),
        ]
        assert vm.dynamics_card.chip is None

    def test_metrics_degraded_gets_unavailable_chip(self):
        vm = build_overview_view(make_result(), None, None, CONFIDENT)
        assert all(r.value_text == EM_DASH for r in vm.dynamics_card.rows)
        assert vm.dynamics_card.chip == ChipNote(text="unavailable for this file")

    def test_silence_gets_silent_chip(self):
        vm = build_overview_view(
            no_tempo_result(), None, silent_signal_result(), state(VerdictKind.NO_TEMPO)
        )
        assert vm.dynamics_card.rows[0].value_text == EM_DASH  # crest NaN
        assert vm.dynamics_card.chip == ChipNote(text="silent file")

    def test_dc_file_keeps_chip_off_the_finite_dr_row(self):
        # One chip slot, keyed off the DR row (the card's headline absence).
        # On a DC file DR is a TRUE 0.0 measurement, so the card stays
        # chip-less even though the sub share is "—" — the Signal section's
        # Sub/bass GaugeCard is where that absence carries its chip.
        vm = build_overview_view(
            make_result(), None, dc_signal_result(), CONFIDENT
        )
        assert vm.dynamics_card.rows[0].value_text == "0.0"
        assert vm.dynamics_card.rows[1].value_text == EM_DASH
        assert vm.dynamics_card.chip is None

    def test_agrees_with_tempo_view_rail_strings(self):
        # The rail (tempo_view) and the Overview dynamics card format the
        # same SignalResult through the same formatters — byte-identical.
        from rai_ui.state.tempo_view import build_tempo_view

        sr = make_signal_result(crest=15.6, sub=10.5, width=48.0)
        rail = build_tempo_view(make_result(), None, CONFIDENT, sr).readout
        card = build_overview_view(make_result(), None, sr, CONFIDENT).dynamics_card
        assert rail.dr_text == card.rows[0].value_text == "15.6"
        assert rail.sub_text == card.rows[1].value_text == "10.5 %"
        assert rail.width_text == card.rows[2].value_text == "48 %"


# ---------------------------------------------------------------------------
# Overview — file card
# ---------------------------------------------------------------------------


class TestOverviewFileCard:
    def test_stereo_file_formatting(self):
        # make_result: /tmp/beat.wav · 6.0 s · 44100 Hz · 2 channels.
        vm = build_overview_view(make_result(), None, None, CONFIDENT)
        assert [(r.label, r.value_text) for r in vm.file_card.rows] == [
            ("Name", "beat.wav"),
            ("Length", "6.0 s"),
            ("Rate", "44 100 Hz"),  # space-grouped thousands (04:384)
            ("Channels", "2 (stereo)"),
        ]

    def test_mono_channels_word(self):
        result = make_result()
        result.channels = 1
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[3].value_text == "1 (mono)"

    def test_multichannel_word(self):
        result = make_result()
        result.channels = 6
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[3].value_text == "6 (multichannel)"

    def test_length_one_decimal(self):
        result = make_result()
        result.duration = 194.94
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[1].value_text == "194.9 s"

    def test_length_sub_second_keeps_two_decimals(self):
        # The approved Console's short-clip edge state (04:699,
        # kick_test.wav) prints "0.31 s" — 1 dp would collapse it to a
        # near-meaningless "0.3 s".
        result = make_result()
        result.duration = 0.31
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[1].value_text == "0.31 s"

    def test_length_at_and_above_one_second_stays_one_decimal(self):
        result = make_result()
        result.duration = 8.0
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[1].value_text == "8.0 s"
        result.duration = 1.0
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.file_card.rows[1].value_text == "1.0 s"


# ---------------------------------------------------------------------------
# Overview — waveform envelope + length label (R-M2-9)
# ---------------------------------------------------------------------------


def fake_signal_obj(y_native: np.ndarray) -> SimpleNamespace:
    return SimpleNamespace(y_native=y_native, sr_native=44100)


class TestOverviewWaveform:
    def test_envelope_from_channel_mean(self):
        rng = np.random.default_rng(7)
        y = rng.standard_normal((10_000, 2)).astype(np.float32)
        vm = build_overview_view(make_result(), fake_signal_obj(y), None, CONFIDENT)
        assert vm.wave_mins.shape == (WAVEFORM_BINS,)
        assert vm.wave_maxs.shape == (WAVEFORM_BINS,)
        # Envelope must match a direct decimation of the display downmix.
        from rai_ui.plots.decimate import minmax_decimate

        want_mins, want_maxs = minmax_decimate(
            y.astype(np.float64).mean(axis=1), WAVEFORM_BINS
        )
        np.testing.assert_array_equal(vm.wave_mins, want_mins)
        np.testing.assert_array_equal(vm.wave_maxs, want_maxs)
        assert bool(np.all(vm.wave_mins <= vm.wave_maxs))

    def test_mono_signal_passes_straight_through(self):
        y = np.linspace(-1.0, 1.0, 500)  # <= 2048 samples: passthrough
        vm = build_overview_view(make_result(), fake_signal_obj(y), None, CONFIDENT)
        np.testing.assert_array_equal(vm.wave_mins, y)
        np.testing.assert_array_equal(vm.wave_maxs, y)

    def test_no_signal_obj_means_no_envelope(self):
        vm = build_overview_view(make_result(), None, None, CONFIDENT)
        assert vm.wave_mins is None and vm.wave_maxs is None
        assert vm.wave_len_text == "0:06"  # duration still real (6.0 s)

    def test_empty_audio_means_no_envelope(self):
        vm = build_overview_view(
            make_result(), fake_signal_obj(np.zeros(0)), None, CONFIDENT
        )
        assert vm.wave_mins is None and vm.wave_maxs is None

    def test_wave_len_text_mmss(self):
        result = make_result()
        result.duration = 194.9
        vm = build_overview_view(result, None, None, CONFIDENT)
        assert vm.wave_len_text == "3:14"


# ---------------------------------------------------------------------------
# Overview — blank rule (WORKING/ERROR)
# ---------------------------------------------------------------------------


class TestOverviewBlankRule:
    @pytest.mark.parametrize("kind", [VerdictKind.WORKING, VerdictKind.ERROR])
    def test_blank_kinds_null_everything(self, kind):
        y = np.linspace(-1.0, 1.0, 500)
        vm = build_overview_view(
            make_result(), fake_signal_obj(y), make_signal_result(), state(kind)
        )
        assert vm.has_result is False
        assert vm.tempo_card.verdict_word == EM_DASH
        assert vm.tempo_card.primary_text == EM_DASH
        assert vm.wave_mins is None and vm.wave_maxs is None
        assert vm.wave_len_text == EM_DASH
        for card in (vm.loudness_card, vm.dynamics_card, vm.file_card):
            assert card.chip is None
            assert all(row.value_text == EM_DASH for row in card.rows)

    def test_non_blank_states_render(self):
        vm = build_overview_view(
            make_result(), None, make_signal_result(), CONFIDENT
        )
        assert vm.has_result is True
        assert vm.dynamics_card.rows[0].value_text == "8.2"

    def test_none_verdict_state_falls_back_to_initial(self):
        vm = build_overview_view(None, None, None, None)
        assert vm == EMPTY_OVERVIEW_VIEW
