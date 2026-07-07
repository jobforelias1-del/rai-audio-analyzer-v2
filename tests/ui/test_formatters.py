"""Tests for the pure UI string formatters (rai_ui.state.formatters).

Pure Python — no Qt imports, safe for the engine CI environment. The
relationship-chip tests deliberately import the engine's ratio table
(rai_analyzer.contracts) and check agreement in BOTH directions, so any
drift between the engine's classification and the UI's chips fails loudly
here instead of shipping a chip that contradicts the JSON report.
"""

from __future__ import annotations

import math

import pytest

from rai_analyzer.contracts import _RATIO_TABLE, Relationship
from rai_ui.state import formatters as fm

PRIMARY = 120.0


# ---------------------------------------------------------------------------
# relationship_chip — every table entry
# ---------------------------------------------------------------------------

CHIP_CASES = [
    (1.0, "×1 · primary", "×1 · primary"),
    (1.0 / 2.0, "½× · half-time", "1/2× · half-time"),
    (2.0, "2× · double-time", "2× · double-time"),
    (3.0 / 2.0, "1½× · dotted", "3/2× · dotted"),
    (2.0 / 3.0, "⅔× · dotted", "2/3× · dotted"),
    (3.0 / 4.0, "¾× · cross", "3/4× · cross"),
    (4.0 / 3.0, "1⅓× · cross", "4/3× · cross"),
    (1.0 / 3.0, "⅓× · triplet", "1/3× · triplet"),
    (3.0, "3× · triplet", "3× · triplet"),
    (5.0 / 8.0, "⅝× · cross", "5/8× · cross"),
    (8.0 / 5.0, "1⅗× · cross", "8/5× · cross"),
    (5.0 / 4.0, "1¼× · cross", "5/4× · cross"),
    (4.0 / 5.0, "⅘× · cross", "4/5× · cross"),
    (5.0 / 6.0, "⅚× · cross", "5/6× · cross"),
    (6.0 / 5.0, "1⅕× · cross", "6/5× · cross"),
]


@pytest.mark.parametrize("ratio,chip,ascii_", CHIP_CASES)
def test_every_table_entry(ratio, chip, ascii_):
    candidate = PRIMARY * ratio
    assert fm.relationship_chip(candidate, PRIMARY) == chip
    assert fm.ascii_chip(candidate, PRIMARY) == ascii_


def test_spec_sanity_anchor():
    # The one worked example from the design spec.
    assert fm.relationship_chip(155.25, 205.15) == "¾× · cross"
    assert fm.ascii_chip(155.25, 205.15) == "3/4× · cross"


def test_ascii_example_from_spec():
    assert fm.ascii_chip(75.0, 120.0) == "5/8× · cross"  # ratio exactly 5/8


# ---------------------------------------------------------------------------
# Tolerance edges (default tol = 0.04, strict <, mirrors the engine)
# ---------------------------------------------------------------------------


def test_tolerance_39_in():
    # ratio 0.5195 -> 3.9% from ½, well clear of ⅝ -> matches half-time.
    assert fm.relationship_chip(51.95, 100.0) == "½× · half-time"


def test_tolerance_41_out():
    # ratio 0.5205 -> 4.1% from ½; nearest other entry (⅝) is ~17% away.
    assert fm.relationship_chip(52.05, 100.0) == "unrelated"


def test_tolerance_41_out_at_top_of_table():
    # ratio 3.123 -> 4.1% above 3 with no larger neighbour to catch it.
    assert fm.relationship_chip(312.3, 100.0) == "unrelated"


def test_min_relative_error_tiebreak():
    # ratio 0.775 is equidistant from ¾ and ⅘ in ABSOLUTE terms (0.025 each),
    # but relative error favours ⅘ (3.125% vs 3.33%) — the chip must use
    # relative error, same as the engine.
    assert fm.relationship_chip(77.5, 100.0) == "⅘× · cross"


def test_custom_tolerance_respected():
    # 2% ratio error: inside the default 4% but outside tol=0.01.
    assert fm.relationship_chip(102.0, 100.0) == "×1 · primary"
    assert fm.relationship_chip(102.0, 100.0, tol=0.01) == "unrelated"


# ---------------------------------------------------------------------------
# Degenerate inputs (mirror the engine's guard)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate,primary",
    [(0.0, 120.0), (-75.0, 120.0), (120.0, 0.0), (120.0, -1.0), (math.nan, 120.0), (math.inf, 120.0)],
)
def test_degenerate_bpms_are_unrelated(candidate, primary):
    assert fm.relationship_chip(candidate, primary) == "unrelated"
    assert fm.ascii_chip(candidate, primary) == "unrelated"


# ---------------------------------------------------------------------------
# Engine agreement — both directions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target,rel", _RATIO_TABLE, ids=[rel.value + f"@{t:.3f}" for t, rel in _RATIO_TABLE]
)
def test_every_engine_ratio_has_a_chip(target, rel):
    # Every non-self/unrelated ratio the engine can emit must map to a real
    # chip, never "unrelated" (the UI would contradict the JSON report).
    chip = fm.relationship_chip(PRIMARY * target, PRIMARY)
    if rel is Relationship.SELF:
        assert chip == "×1 · primary"
    else:
        assert chip != "unrelated"


def test_ratio_sets_match_exactly():
    # Drift tripwire in the other direction too: the UI must not invent
    # ratios the engine does not classify.
    engine = sorted(t for t, _ in _RATIO_TABLE)
    ui = sorted(t for t, _, _ in fm._CHIP_TABLE)
    assert ui == pytest.approx(engine)


# ---------------------------------------------------------------------------
# Measurement formatting
# ---------------------------------------------------------------------------

ALL_FMT = [fm.fmt_bpm, fm.fmt_lufs, fm.fmt_db, fm.fmt_dbtp, fm.fmt_dbfs]


def test_fmt_bpm_basic():
    assert fm.fmt_bpm(205.153) == "205.15"
    assert fm.fmt_bpm(205.0) == "205.00"


def test_negative_uses_real_minus_sign():
    out = fm.fmt_lufs(-14.056)
    assert out == "−14.06"
    assert "−" in out and "-" not in out  # U+2212, never the hyphen


@pytest.mark.parametrize("f", ALL_FMT, ids=lambda f: f.__name__)
def test_infinity_policy(f):
    # −∞ is a measurement (digital silence), rendered as such; any infinite
    # input collapses to the silence sentinel per the C-06 policy.
    assert f(float("-inf")) == "−∞"
    assert f(math.inf) == "−∞"


@pytest.mark.parametrize("f", ALL_FMT, ids=lambda f: f.__name__)
def test_absence_policy(f):
    # — is absence: not measured is not a number at all.
    assert f(None) == "—"
    assert f(float("nan")) == "—"


@pytest.mark.parametrize("f", ALL_FMT, ids=lambda f: f.__name__)
def test_all_formatters_share_the_policy(f):
    assert f(-9.005e0) == fm.fmt_db(-9.005)
    assert f(0.0) == "0.00"


# ---------------------------------------------------------------------------
# M2 signal-metric formatters (fmt_pct / fmt_dr / fmt_mmss)
# ---------------------------------------------------------------------------


def test_fmt_pct_demo_values_verbatim():
    # Console demo strings (04:682/690/699): 62 % · 21 % · 10.5 % · 0 %.
    assert fm.fmt_pct(62.0) == "62 %"
    assert fm.fmt_pct(21.0) == "21 %"
    assert fm.fmt_pct(10.5) == "10.5 %"
    assert fm.fmt_pct(0.0) == "0 %"


def test_fmt_pct_rounds_to_one_decimal_then_trims():
    assert fm.fmt_pct(61.96) == "62 %"
    assert fm.fmt_pct(61.94) == "61.9 %"
    assert fm.fmt_pct(-0.04) == "0 %"  # never a signed zero


def test_fmt_pct_absence_policy():
    # A NaN share (silence) is absence — it must never render "0 %".
    assert fm.fmt_pct(None) == "—"
    assert fm.fmt_pct(float("nan")) == "—"


def test_fmt_dr_demo_values_verbatim():
    # Console demo DR strings: 8.2 · 15.6 (1 dp, no trim — "8.0" stays "8.0").
    assert fm.fmt_dr(8.21) == "8.2"
    assert fm.fmt_dr(15.6) == "15.6"
    assert fm.fmt_dr(8.0) == "8.0"


def test_fmt_dr_doubles_as_rms_formatter():
    # The DR card caption's RMS value uses the same 1 dp form: −16.4.
    assert fm.fmt_dr(-16.42) == "−16.4"
    assert "-" not in fm.fmt_dr(-16.42)  # U+2212, never the hyphen


def test_fmt_dr_silence_policy():
    # Crest is NaN on silence → absence; RMS is −∞ → a measurement.
    assert fm.fmt_dr(float("nan")) == "—"
    assert fm.fmt_dr(None) == "—"
    assert fm.fmt_dr(float("-inf")) == "−∞"


def test_fmt_mmss_basic():
    assert fm.fmt_mmss(194.9) == "3:14"  # floored, never rounded up
    assert fm.fmt_mmss(6.0) == "0:06"
    assert fm.fmt_mmss(0.0) == "0:00"
    assert fm.fmt_mmss(60.0) == "1:00"


def test_fmt_mmss_minutes_unbounded():
    assert fm.fmt_mmss(4499.0) == "74:59"  # no h:mm:ss form in the design


def test_fmt_mmss_absence_policy():
    assert fm.fmt_mmss(None) == "—"
    assert fm.fmt_mmss(float("nan")) == "—"
    assert fm.fmt_mmss(float("inf")) == "—"
    assert fm.fmt_mmss(-1.0) == "—"


# ---------------------------------------------------------------------------
# Unavailability chips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,text",
    [
        ("silence", "silent file"),
        ("short", "undefined below 0.4 s"),
        ("failed", "unavailable for this file"),
    ],
)
def test_unavailability_reasons(kind, text):
    assert fm.unavailability_reason(kind) == text


def test_unavailability_unknown_kind_raises():
    with pytest.raises(ValueError):
        fm.unavailability_reason("mystery")


# ---------------------------------------------------------------------------
# CLI copy target
# ---------------------------------------------------------------------------


def test_cli_command_basic():
    assert fm.cli_command("/Users/e/track.wav") == 'rai-analyze "/Users/e/track.wav" --json'


def test_cli_command_quotes_spaces():
    cmd = fm.cli_command("/My Music/final mix 2.wav")
    assert cmd == 'rai-analyze "/My Music/final mix 2.wav" --json'


def test_cli_command_escapes_embedded_quotes():
    cmd = fm.cli_command('/mix/take "b".wav')
    assert cmd == 'rai-analyze "/mix/take \\"b\\".wav" --json'


def test_cli_command_has_no_profile_flag_until_m4():
    # The M0 CLI does not accept --profile; a copied command must never error.
    assert "--profile" not in fm.cli_command("/a.wav")
