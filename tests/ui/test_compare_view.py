"""Tests for the pure Compare view-model (rai_ui.state.compare_view).

Pure Python + numpy — no Qt anywhere, so every table string, reading
sentence, and overlay array is asserted headless and the module collects in
the Qt-less engine CI venv. Payloads are REAL engine contracts
(``AnalysisResult``/``LoudnessResult``/``SignalResult``), builders shared
with test_tempo_view / test_signal_view.

Matrix under test (R-M4-4/5/6/13):

* the approved demo's six rows verbatim (04:804–811) — metric set, per-metric
  precision, Δ B−A sign convention, reading tone;
* the full R-M4-5 reading rulebook per metric, including every "equal …"
  branch (keyed off the DISPLAYED delta, so number and sentence agree);
* absence on either side → Δ/Reading em-dash, absent value cell a bare ``—``;
* −∞ stays a measurement (``−∞ LUFS`` value cell) while its *difference*
  honestly em-dashes and the loudness reading degrades to the magnitude-free
  comparative;
* B-empty / B-working / B-loaded chip states, pill + hint copy verbatim,
  slot-status-over-stale-payload truth;
* joint spectrum normalization to one shared dB reference (R-M4-6).
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

from rai_analyzer.contracts import AnalysisResult, LoudnessResult, TempoResult
from rai_ui.state import compare_view
from rai_ui.state.compare_view import (
    B_EMPTY_CHIP_TEXT,
    B_EMPTY_PILL_TEXT,
    B_WORKING_CHIP_TEXT,
    EMPTY_COMPARE_VIEW,
    HINT_CHIP_TEXT,
    METRIC_LABELS,
    PROFILE_NOTE_TEXT,
    BStatus,
    build_compare_view,
)
from tests.ui.test_signal_view import make_signal_result, silent_signal_result, make_spectrum
from tests.ui.test_tempo_view import make_tempo

EM_DASH = "—"
MINUS = "−"
NEG_INF = float("-inf")
NAN = float("nan")


# ---------------------------------------------------------------------------
# Builders — real engine contracts
# ---------------------------------------------------------------------------


def make_loudness(
    lufs: float = -9.8, tp: float = -0.6, sample_peak: float = -1.0
) -> LoudnessResult:
    return LoudnessResult(lufs_i=lufs, true_peak_dbtp=tp, sample_peak_dbfs=sample_peak)


def no_tempo() -> TempoResult:
    """The resolver's exact no-tempo shape."""
    return TempoResult(
        primary_bpm=0.0,
        felt_bpm=None,
        candidates=[],
        ambiguous=True,
        ambiguity_reason="No tempo detected (signal too quiet or too short).",
    )


def make_result(
    lufs: float = -9.8,
    tp: float = -0.6,
    bpm: float | None = 155.25,
    path: str = "/tmp/beat.wav",
    loudness: LoudnessResult | None = None,
    with_loudness: bool = True,
) -> AnalysisResult:
    if loudness is None and with_loudness:
        loudness = make_loudness(lufs=lufs, tp=tp)
    return AnalysisResult(
        path=path,
        duration=6.0,
        sr=44100,
        channels=2,
        tempo=make_tempo(primary_bpm=bpm) if bpm is not None else no_tempo(),
        loudness=loudness,
    )


# The approved demo's exact numbers (04:804–811).
DEMO_A = make_result(lufs=-9.8, tp=-0.6, bpm=155.25, path="/tmp/gwmstem.wav")
DEMO_A_SIG = make_signal_result(crest=8.2, sub=21.0, width=62.0)
DEMO_B = make_result(lufs=-8.4, tp=-0.9, bpm=154.90, path="/tmp/ref_commercial.wav")
DEMO_B_SIG = make_signal_result(crest=6.9, sub=24.0, width=55.0)


def demo_view():
    return build_compare_view(DEMO_A, DEMO_A_SIG, DEMO_B, DEMO_B_SIG, BStatus.LOADED)


def view_for(a=None, a_sig=None, b=None, b_sig=None, status=BStatus.LOADED):
    return build_compare_view(a, a_sig, b, b_sig, status)


def row(vm, i):
    return vm.rows[i]


# ---------------------------------------------------------------------------
# Module purity (same AST gate as tempo_view / signal_view)
# ---------------------------------------------------------------------------


def test_module_is_qt_free():
    """PySide6/pyqtgraph imports are forbidden in compare_view (pure doctrine)."""
    import ast

    source = Path(compare_view.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PySide6" not in imported
    assert "pyqtgraph" not in imported


# ---------------------------------------------------------------------------
# Shape + fixed copy
# ---------------------------------------------------------------------------


def test_always_exactly_six_rows_in_table_order():
    for vm in (EMPTY_COMPARE_VIEW, demo_view()):
        assert len(vm.rows) == 6
        assert tuple(r.metric for r in vm.rows) == METRIC_LABELS


def test_metric_labels_are_the_design_set():
    assert METRIC_LABELS == (
        "Integrated",
        "Primary BPM",
        "True peak",
        "Dynamic range",
        "Sub/bass energy",
        "Stereo width",
    )


def test_fixed_copy_verbatim():
    assert B_EMPTY_CHIP_TEXT == "B · drop a reference WAV — or Browse…"
    assert HINT_CHIP_TEXT == "drop a WAV to replace B"
    assert PROFILE_NOTE_TEXT == "same profile · drill 140–170"
    assert B_EMPTY_PILL_TEXT == "reference (B) not loaded — A shown alone"
    assert B_WORKING_CHIP_TEXT == "B · analyzing…"


def test_view_model_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        demo_view().has_a = False


def test_empty_view_shape():
    vm = EMPTY_COMPARE_VIEW
    assert vm.has_a is False
    assert vm.a_chip_text == f"A · {EM_DASH}"
    assert vm.b_status is BStatus.EMPTY
    assert vm.b_chip_text == B_EMPTY_CHIP_TEXT
    assert vm.show_hint_chip is False
    assert vm.b_empty is True
    assert vm.b_working is False
    assert vm.b_empty_pill_text == B_EMPTY_PILL_TEXT
    assert vm.a_freqs is None and vm.a_db is None
    assert vm.b_freqs is None and vm.b_db is None
    for r in vm.rows:
        assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
            EM_DASH,
            EM_DASH,
            EM_DASH,
            EM_DASH,
        )


# ---------------------------------------------------------------------------
# Demo parity — the approved table verbatim (04:804–811)
# ---------------------------------------------------------------------------


def test_demo_row_integrated():
    r = row(demo_view(), 0)
    assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
        f"{MINUS}9.8 LUFS",
        f"{MINUS}8.4 LUFS",
        "+1.4",
        "B is 1.4 dB louder",
    )


def test_demo_row_primary_bpm():
    r = row(demo_view(), 1)
    assert (r.a_text, r.b_text) == ("155.25", "154.90")
    # Sign convention is B−A: 154.90 − 155.25 = −0.35 (04's JS is the truth;
    # the wireframe's +0.35 was a stale sign).
    assert r.delta_text == f"{MINUS}0.35"
    assert r.reading == f"same grid — B drifts {MINUS}0.2 %"


def test_demo_row_true_peak():
    r = row(demo_view(), 2)
    assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
        f"{MINUS}0.6 dBTP",
        f"{MINUS}0.9 dBTP",
        f"{MINUS}0.3",
        "both clear of 0 dBTP",
    )


def test_demo_row_dynamic_range():
    r = row(demo_view(), 3)
    assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
        "8.2 dB",
        "6.9 dB",
        f"{MINUS}1.3",
        "B is more compressed",
    )


def test_demo_row_sub_bass():
    r = row(demo_view(), 4)
    assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
        "21 %",
        "24 %",
        "+3",
        "B carries more sub at this tempo",
    )


def test_demo_row_stereo_width():
    r = row(demo_view(), 5)
    assert (r.a_text, r.b_text, r.delta_text, r.reading) == (
        "62 %",
        "55 %",
        f"{MINUS}7",
        "A is wider",
    )


# ---------------------------------------------------------------------------
# Δ formatting law (R-M4-4)
# ---------------------------------------------------------------------------


def test_delta_uses_unicode_minus_never_hyphen():
    for r in demo_view().rows:
        assert "-" not in r.delta_text


def test_delta_positive_gets_explicit_plus():
    vm = view_for(a=make_result(lufs=-10.0), b=make_result(lufs=-8.0))
    assert row(vm, 0).delta_text == "+2.0"


def test_delta_sign_flips_when_sides_swap():
    a, b = make_result(lufs=-9.8), make_result(lufs=-8.4)
    fwd = row(view_for(a=a, b=b), 0).delta_text
    rev = row(view_for(a=b, b=a), 0).delta_text
    assert fwd == "+1.4"
    assert rev == f"{MINUS}1.4"


def test_delta_zero_renders_unsigned():
    same = make_result(lufs=-9.8, tp=-0.6, bpm=150.0)
    same_sig = make_signal_result(crest=8.2, sub=21.0, width=62.0)
    vm = view_for(a=same, a_sig=same_sig, b=same, b_sig=same_sig)
    assert row(vm, 0).delta_text == "0.0"  # LUFS, 1 dp
    assert row(vm, 1).delta_text == "0.00"  # BPM, 2 dp
    assert row(vm, 4).delta_text == "0"  # pct, trimmed
    for r in vm.rows:
        assert not r.delta_text.startswith("+")
        assert MINUS not in r.delta_text


def test_delta_rounded_away_negative_zero_normalizes():
    # −0.03 dB rounds to the displayed "0.0" — never "−0.0".
    vm = view_for(a=make_result(lufs=-9.80), b=make_result(lufs=-9.83))
    assert row(vm, 0).delta_text == "0.0"


def test_delta_pct_trims_trailing_zero_but_keeps_halves():
    vm = view_for(
        a_sig=make_signal_result(sub=21.0), b_sig=make_signal_result(sub=24.5)
    )
    assert row(vm, 4).delta_text == "+3.5"


def test_delta_is_unitless():
    for r in demo_view().rows:
        for unit in ("LUFS", "dBTP", "dB", "%"):
            assert unit not in r.delta_text


# ---------------------------------------------------------------------------
# Reading: Integrated (LUFS)
# ---------------------------------------------------------------------------


def test_lufs_quieter():
    vm = view_for(a=make_result(lufs=-8.4), b=make_result(lufs=-9.8))
    assert row(vm, 0).reading == "B is 1.4 dB quieter"


def test_lufs_equal_exact():
    vm = view_for(a=make_result(lufs=-9.8), b=make_result(lufs=-9.8))
    assert row(vm, 0).reading == "equal loudness"


def test_lufs_equal_when_displayed_delta_rounds_to_zero():
    # The sentence derives from the DISPLAYED delta (C-15: number first) —
    # a Δ cell of "0.0" must never sit beside "B is 0.0 dB quieter".
    vm = view_for(a=make_result(lufs=-9.80), b=make_result(lufs=-9.83))
    assert row(vm, 0).delta_text == "0.0"
    assert row(vm, 0).reading == "equal loudness"


def test_lufs_magnitude_is_one_decimal():
    vm = view_for(a=make_result(lufs=-12.0), b=make_result(lufs=-9.75))
    assert row(vm, 0).reading == "B is 2.2 dB louder"


def test_lufs_both_silent_is_equal_loudness():
    silent = make_loudness(lufs=NEG_INF, tp=NEG_INF, sample_peak=NEG_INF)
    vm = view_for(a=make_result(loudness=silent), b=make_result(loudness=silent))
    r = row(vm, 0)
    # −∞ is a measurement (C-06): the value cells keep it, unit and all.
    assert r.a_text == f"{MINUS}∞ LUFS"
    assert r.b_text == f"{MINUS}∞ LUFS"
    # …but a difference of two silence sentinels is not a finite measurement.
    assert r.delta_text == EM_DASH
    assert r.reading == "equal loudness"


def test_lufs_one_side_silent_degrades_to_comparative():
    silent = make_loudness(lufs=NEG_INF, tp=NEG_INF, sample_peak=NEG_INF)
    vm = view_for(a=make_result(loudness=silent), b=make_result(lufs=-9.8))
    r = row(vm, 0)
    assert r.a_text == f"{MINUS}∞ LUFS"
    assert r.delta_text == EM_DASH
    assert r.reading == "B is louder"

    vm = view_for(a=make_result(lufs=-9.8), b=make_result(loudness=silent))
    assert row(vm, 0).reading == "B is quieter"


def test_lufs_nan_is_absence():
    # Short-clip NaN LUFS: absence — bare em-dash cell, no unit, dashed row.
    short = make_loudness(lufs=NAN, tp=-0.6)
    vm = view_for(a=make_result(loudness=short), b=make_result(lufs=-9.8))
    r = row(vm, 0)
    assert r.a_text == EM_DASH
    assert r.b_text == f"{MINUS}9.8 LUFS"
    assert r.delta_text == EM_DASH
    assert r.reading == EM_DASH


def test_lufs_missing_loudness_is_absence():
    vm = view_for(a=make_result(with_loudness=False), b=make_result())
    r = row(vm, 0)
    assert r.a_text == EM_DASH
    assert r.delta_text == EM_DASH
    assert r.reading == EM_DASH


# ---------------------------------------------------------------------------
# Reading: Primary BPM
# ---------------------------------------------------------------------------


def test_bpm_same_grid_negative_drift_matches_demo():
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=154.90))
    assert row(vm, 1).reading == f"same grid — B drifts {MINUS}0.2 %"


def test_bpm_same_grid_positive_drift_gets_plus_and_trim():
    vm = view_for(a=make_result(bpm=150.0), b=make_result(bpm=151.5))
    assert row(vm, 1).reading == "same grid — B drifts +1 %"


def test_bpm_same_grid_zero_drift():
    vm = view_for(a=make_result(bpm=150.0), b=make_result(bpm=150.0))
    assert row(vm, 1).reading == "same grid — B drifts 0 %"


def test_bpm_half_time_uses_chip_vocabulary():
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=77.625))
    assert row(vm, 1).reading == "½× · half-time of A"


def test_bpm_double_time():
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=310.5))
    assert row(vm, 1).reading == "2× · double-time of A"


def test_bpm_dotted():
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=232.875))
    assert row(vm, 1).reading == "1½× · dotted of A"


def test_bpm_unrelated():
    # 140/155.25 ≈ 0.902 — outside 4% of every tabled ratio.
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=140.0))
    assert row(vm, 1).reading == "unrelated to A"


def test_bpm_no_tempo_on_b_is_absence():
    vm = view_for(a=make_result(bpm=155.25), b=make_result(bpm=None))
    r = row(vm, 1)
    assert r.a_text == "155.25"
    assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


def test_bpm_no_tempo_on_a_is_absence():
    # A 0.0 BPM must never render (the Overview probe, one truth).
    vm = view_for(a=make_result(bpm=None), b=make_result(bpm=155.25))
    r = row(vm, 1)
    assert (r.a_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)
    assert r.b_text == "155.25"


# ---------------------------------------------------------------------------
# Reading: True peak
# ---------------------------------------------------------------------------


def test_tp_both_clear():
    vm = view_for(a=make_result(tp=-0.6), b=make_result(tp=-0.9))
    assert row(vm, 2).reading == "both clear of 0 dBTP"


def test_tp_both_at_or_over():
    vm = view_for(a=make_result(tp=0.0), b=make_result(tp=0.2))
    assert row(vm, 2).reading == "both at or over 0 dBTP"


def test_tp_only_a_over():
    vm = view_for(a=make_result(tp=0.1), b=make_result(tp=-0.5))
    assert row(vm, 2).reading == "A at or over 0 dBTP — B clear"


def test_tp_only_b_over():
    vm = view_for(a=make_result(tp=-0.5), b=make_result(tp=0.1))
    assert row(vm, 2).reading == "B at or over 0 dBTP — A clear"


def test_tp_silent_side_is_clear_and_delta_dashes():
    silent = make_loudness(lufs=NEG_INF, tp=NEG_INF, sample_peak=NEG_INF)
    vm = view_for(a=make_result(tp=-0.6), b=make_result(loudness=silent))
    r = row(vm, 2)
    assert r.b_text == f"{MINUS}∞ dBTP"
    assert r.delta_text == EM_DASH
    assert r.reading == "both clear of 0 dBTP"


def test_tp_absence():
    vm = view_for(a=make_result(with_loudness=False), b=make_result(tp=-0.9))
    r = row(vm, 2)
    assert (r.a_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


# ---------------------------------------------------------------------------
# Reading: Dynamic range
# ---------------------------------------------------------------------------


def test_dr_less_compressed():
    vm = view_for(
        a_sig=make_signal_result(crest=6.9), b_sig=make_signal_result(crest=8.2)
    )
    assert row(vm, 3).reading == "B is less compressed"


def test_dr_equal_dynamics():
    vm = view_for(
        a_sig=make_signal_result(crest=8.2), b_sig=make_signal_result(crest=8.2)
    )
    r = row(vm, 3)
    assert r.delta_text == "0.0"
    assert r.reading == "equal dynamics"


def test_dr_equal_when_displayed_delta_rounds_to_zero():
    vm = view_for(
        a_sig=make_signal_result(crest=8.20), b_sig=make_signal_result(crest=8.23)
    )
    assert row(vm, 3).reading == "equal dynamics"


def test_dr_silence_nan_crest_is_absence():
    vm = view_for(a_sig=silent_signal_result(), b_sig=make_signal_result(crest=8.2))
    r = row(vm, 3)
    assert (r.a_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)
    assert r.b_text == "8.2 dB"


# ---------------------------------------------------------------------------
# Reading: Sub/bass energy
# ---------------------------------------------------------------------------


def test_sub_a_carries_more():
    vm = view_for(
        a_sig=make_signal_result(sub=24.0), b_sig=make_signal_result(sub=21.0)
    )
    assert row(vm, 4).reading == "A carries more sub at this tempo"


def test_sub_equal_weight():
    vm = view_for(
        a_sig=make_signal_result(sub=21.0), b_sig=make_signal_result(sub=21.0)
    )
    assert row(vm, 4).reading == "equal sub weight"


def test_sub_silence_is_absence():
    vm = view_for(a_sig=make_signal_result(sub=21.0), b_sig=silent_signal_result())
    r = row(vm, 4)
    assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


# ---------------------------------------------------------------------------
# Reading: Stereo width
# ---------------------------------------------------------------------------


def test_width_b_wider():
    vm = view_for(
        a_sig=make_signal_result(width=55.0), b_sig=make_signal_result(width=62.0)
    )
    assert row(vm, 5).reading == "B is wider"


def test_width_equal():
    vm = view_for(
        a_sig=make_signal_result(width=62.0), b_sig=make_signal_result(width=62.0)
    )
    assert row(vm, 5).reading == "equal width"


def test_width_mono_zero_is_a_measurement():
    # R-M2-4 carried forward: mono width 0 % is a measurement, never absence.
    vm = view_for(
        a_sig=make_signal_result(width=62.0),
        b_sig=make_signal_result(width=0.0, correlation=None),
    )
    r = row(vm, 5)
    assert r.b_text == "0 %"
    assert r.delta_text == f"{MINUS}62"
    assert r.reading == "A is wider"


# ---------------------------------------------------------------------------
# Chips + B slot states
# ---------------------------------------------------------------------------


def test_a_chip_carries_filename():
    assert demo_view().a_chip_text == "A · gwmstem.wav"


def test_b_chip_loaded_carries_filename_and_hint_shows():
    vm = demo_view()
    assert vm.b_status is BStatus.LOADED
    assert vm.b_chip_text == "B · ref_commercial.wav"
    assert vm.show_hint_chip is True
    assert vm.hint_chip_text == HINT_CHIP_TEXT
    assert vm.b_empty is False and vm.b_working is False
    assert vm.b_empty_pill_text is None


def test_b_empty_state():
    vm = view_for(a=DEMO_A, a_sig=DEMO_A_SIG, status=BStatus.EMPTY)
    assert vm.b_chip_text == B_EMPTY_CHIP_TEXT
    assert vm.show_hint_chip is False
    assert vm.b_empty is True and vm.b_working is False
    assert vm.b_empty_pill_text == B_EMPTY_PILL_TEXT
    # 04:813 verbatim: A column stays populated, B/Δ/Reading all em-dash.
    for r in vm.rows:
        assert r.a_text != EM_DASH
        assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


def test_b_working_state():
    vm = view_for(a=DEMO_A, a_sig=DEMO_A_SIG, status=BStatus.WORKING)
    assert vm.b_chip_text == B_WORKING_CHIP_TEXT
    assert vm.show_hint_chip is False
    assert vm.b_empty is False and vm.b_working is True
    assert vm.b_empty_pill_text is None  # in-flight indication is chip-only
    for r in vm.rows:
        assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


def test_slot_status_beats_stale_payload():
    # A stale B payload passed alongside EMPTY/WORKING must not leak numbers:
    # the slot status is the truth.
    for status in (BStatus.EMPTY, BStatus.WORKING):
        vm = view_for(
            a=DEMO_A, a_sig=DEMO_A_SIG, b=DEMO_B, b_sig=DEMO_B_SIG, status=status
        )
        for r in vm.rows:
            assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)
        assert vm.b_freqs is None and vm.b_db is None


def test_loaded_without_payload_is_defensive_dashes():
    vm = view_for(a=DEMO_A, a_sig=DEMO_A_SIG, status=BStatus.LOADED)
    assert vm.b_chip_text == f"B · {EM_DASH}"
    for r in vm.rows:
        assert (r.b_text, r.delta_text, r.reading) == (EM_DASH, EM_DASH, EM_DASH)


def test_a_absent_dashes_a_side_but_never_blanks_b():
    # M3 blank doctrine on A's side (caller passes None while A is
    # WORKING/ERROR); B is a persistent reference and keeps its numbers.
    vm = view_for(b=DEMO_B, b_sig=DEMO_B_SIG, status=BStatus.LOADED)
    assert vm.has_a is False
    assert vm.a_chip_text == f"A · {EM_DASH}"
    assert vm.b_chip_text == "B · ref_commercial.wav"
    for r in vm.rows:
        assert r.a_text == EM_DASH
        assert (r.delta_text, r.reading) == (EM_DASH, EM_DASH)
    assert row(vm, 0).b_text == f"{MINUS}8.4 LUFS"
    assert row(vm, 5).b_text == "55 %"
    # B's curve still draws (jointly normalized against itself).
    assert vm.b_db is not None


def test_profile_note_rides_every_state():
    for vm in (EMPTY_COMPARE_VIEW, demo_view()):
        assert vm.profile_note == PROFILE_NOTE_TEXT


# ---------------------------------------------------------------------------
# Spectrum overlay — joint normalization (R-M4-6)
# ---------------------------------------------------------------------------


def test_joint_normalization_shares_one_db_reference():
    a_sig = make_signal_result(spectrum=make_spectrum(lo_db=-60.0, hi_db=-30.0))
    b_sig = make_signal_result(spectrum=make_spectrum(lo_db=-55.0, hi_db=-25.0))
    vm = view_for(a=DEMO_A, a_sig=a_sig, b=DEMO_B, b_sig=b_sig)
    # Joint top is B's −25 dB: B peaks at 0, A honestly sits 5 dB below.
    assert vm.b_db.max() == pytest.approx(0.0)
    assert vm.a_db.max() == pytest.approx(-5.0)
    assert (vm.a_db <= 0.0).all() and (vm.b_db <= 0.0).all()


def test_joint_normalization_clips_to_floor():
    a_sig = make_signal_result(spectrum=make_spectrum(lo_db=-200.0, hi_db=-30.0))
    b_sig = make_signal_result(spectrum=make_spectrum(lo_db=-55.0, hi_db=-25.0))
    vm = view_for(a=DEMO_A, a_sig=a_sig, b=DEMO_B, b_sig=b_sig)
    assert vm.a_db.min() == pytest.approx(-90.0)
    assert (vm.a_db >= -90.0).all() and (vm.b_db >= -90.0).all()


def test_single_curve_degrades_to_own_max():
    vm = view_for(a=DEMO_A, a_sig=DEMO_A_SIG, status=BStatus.EMPTY)
    assert vm.a_db is not None
    assert vm.a_db.max() == pytest.approx(0.0)  # SpectrumPane's own rule
    assert vm.b_freqs is None and vm.b_db is None


def test_silent_side_draws_no_curve():
    vm = view_for(a=DEMO_A, a_sig=silent_signal_result(), b=DEMO_B, b_sig=DEMO_B_SIG)
    assert vm.a_freqs is None and vm.a_db is None
    assert vm.b_db is not None
    assert vm.b_db.max() == pytest.approx(0.0)


def test_no_signals_no_curves():
    vm = view_for(a=DEMO_A, b=DEMO_B)
    assert vm.a_freqs is None and vm.a_db is None
    assert vm.b_freqs is None and vm.b_db is None


def test_overlay_arrays_keep_full_resolution():
    # Decimation is the pane's job at paint time (R-M3-15) — the view-model
    # stays full-resolution, exactly like SignalViewModel.
    n = 4096
    a_sig = make_signal_result(spectrum=make_spectrum(n=n))
    vm = view_for(a=DEMO_A, a_sig=a_sig)
    assert vm.a_db.size == n
    assert vm.a_freqs.size == n
