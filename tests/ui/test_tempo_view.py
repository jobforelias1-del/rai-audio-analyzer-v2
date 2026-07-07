"""Tests for the pure Tempo view-model and the session's verdict wiring.

Two layers on purpose:

* ``rai_ui.state.tempo_view`` is pure (numpy only, no Qt), so everything down
  to the exact chip copy is asserted headless — these tests run in the
  Qt-less engine venv too.
* ``SessionState``'s verdict-reducer wiring is Qt (signals), so those tests
  importorskip PySide6 *inside the class* — the pure tests above must keep
  collecting and running without Qt. A bare QObject emits signals fine
  without a QApplication, so no pytest-qt fixture is needed.

The chip-copy test doubles as the R1 verbatim-design-copy gate: formatter
output for a candidate set covering every engine ``Relationship`` member must
match the design's computed strings character-for-character.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rai_analyzer.contracts import (
    AnalysisResult,
    Candidate,
    LoudnessResult,
    Relationship,
    TempoCurve,
    TempoResult,
    classify_relationship,
)
from rai_ui.state import tempo_view
from rai_ui.state.tempo_view import (
    AXIS_TICKS,
    BPM_AXIS_MAX,
    BPM_AXIS_MIN,
    EMPTY_VIEW,
    ChipView,
    build_tempo_view,
)
from rai_ui.state.verdict import INITIAL, VerdictKind, VerdictState

EM_DASH = "—"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def make_tempo(
    primary_bpm: float = 205.15,
    felt_bpm: float | None = 102.57,
    extra_bpms: tuple[float, ...] = (102.5,),
    ambiguous: bool = False,
    ambiguity_reason: str | None = None,
) -> TempoResult:
    """Ranked-primary-first TempoResult, engine-shaped (candidates[0] IS the
    primary; non-primary rows keep coarse-grid BPMs)."""
    candidates = [Candidate(bpm=primary_bpm, score=1.86, salience=0.912)]
    for i, bpm in enumerate(extra_bpms):
        candidates.append(Candidate(bpm=bpm, score=1.5 - 0.1 * i, salience=0.8 - 0.05 * i))
    return TempoResult(
        primary_bpm=primary_bpm,
        felt_bpm=felt_bpm,
        candidates=candidates,
        ambiguous=ambiguous,
        ambiguity_reason=ambiguity_reason,
    )


def make_result(tempo: TempoResult | None = None, loudness: LoudnessResult | None = None):
    return AnalysisResult(
        path="/tmp/beat.wav",
        duration=6.0,
        sr=44100,
        channels=2,
        tempo=tempo if tempo is not None else make_tempo(),
        loudness=loudness,
    )


def no_tempo_result():
    """The resolver's exact no-tempo shape (resolver.resolve_tempo)."""
    return make_result(
        TempoResult(
            primary_bpm=0.0,
            felt_bpm=None,
            candidates=[],
            ambiguous=True,
            ambiguity_reason="No tempo detected (signal too quiet or too short).",
        )
    )


def make_features():
    """Features stand-in carrying a real TempoCurve on the real 801-pt grid."""
    bpms = np.arange(40.0, 240.0 + 0.25, 0.25)
    assert bpms.shape == (801,)
    salience = np.linspace(0.0, 1.0, bpms.size)
    return SimpleNamespace(
        tempo_curve=TempoCurve(bpms=bpms, salience=salience, acf=salience, dft=salience)
    )


def state(kind: VerdictKind, **kw) -> VerdictState:
    return VerdictState(kind=kind, **kw)


CONFIDENT = state(VerdictKind.CONFIDENT, path="/tmp/beat.wav")
AMBIGUOUS = state(VerdictKind.AMBIGUOUS, path="/tmp/beat.wav")


# ---------------------------------------------------------------------------
# Module purity
# ---------------------------------------------------------------------------


def test_module_is_qt_free():
    """PySide6/pyqtgraph imports are forbidden in tempo_view (pure doctrine)."""
    import ast

    source = Path(tempo_view.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PySide6" not in imported
    assert "pyqtgraph" not in imported


# ---------------------------------------------------------------------------
# EMPTY_VIEW (the no-file state)
# ---------------------------------------------------------------------------


class TestEmptyView:
    def test_shape(self):
        assert EMPTY_VIEW.has_result is False
        assert EMPTY_VIEW.no_tempo is False
        assert EMPTY_VIEW.no_tempo_text is None
        assert EMPTY_VIEW.curve_bpms is None
        assert EMPTY_VIEW.curve_salience is None
        assert EMPTY_VIEW.candidates == ()
        assert EMPTY_VIEW.markers == ()

    def test_band_and_ticks(self):
        assert EMPTY_VIEW.band == (140.0, 170.0)
        assert EMPTY_VIEW.axis_ticks == (40.0, 80.0, 120.0, 160.0, 200.0, 240.0)
        assert EMPTY_VIEW.axis_ticks == AXIS_TICKS

    def test_readout_is_all_absence(self):
        r = EMPTY_VIEW.readout
        assert r.verdict.kind == VerdictKind.NO_FILE.value
        assert r.verdict.word == EM_DASH
        assert r.verdict.sub == "drop a WAV anywhere in this window"
        assert r.verdict.reasons == ()
        assert r.verdict.show_tiebreak is False
        assert r.verdict.show_undo is False
        assert r.primary_text == EM_DASH
        assert r.felt_text == EM_DASH
        assert r.felt_chip is None
        assert (r.lufs_text, r.dbtp_text, r.dbfs_text) == (EM_DASH, EM_DASH, EM_DASH)
        assert (r.dr_text, r.sub_text, r.width_text) == (EM_DASH, EM_DASH, EM_DASH)

    def test_none_verdict_state_falls_back_to_initial(self):
        vm = build_tempo_view(None, None, None)
        assert vm.readout.verdict.kind == VerdictKind.NO_FILE.value


# ---------------------------------------------------------------------------
# Verdict views — every kind
# ---------------------------------------------------------------------------


class TestVerdictView:
    def test_confident(self):
        vm = build_tempo_view(make_result(), None, CONFIDENT)
        v = vm.readout.verdict
        assert v.kind == "confident"
        assert v.word == "CONFIDENT"
        assert v.sub is None
        # A reason ALWAYS accompanies the word (C-05); the engine writes none
        # when confident, so the view computes one — every clause true-only:
        # the default fixture's 205.15 primary sits OUTSIDE the 140–170 band.
        assert v.reasons == ("205.15 sits outside the drill band · felt ½× agrees",)
        assert v.show_tiebreak is False
        assert v.show_undo is False

    def test_confident_reason_in_band_matches_design_demo_shape(self):
        # The Console demo's computed confident copy: in-band + felt agreement.
        result = make_result(make_tempo(primary_bpm=155.25, felt_bpm=77.63))
        v = build_tempo_view(result, None, CONFIDENT).readout.verdict
        assert v.reasons == ("155.25 sits in the drill band · felt ½× agrees",)

    def test_confident_reason_without_felt_is_band_only(self):
        result = make_result(make_tempo(primary_bpm=155.25, felt_bpm=None))
        v = build_tempo_view(result, None, CONFIDENT).readout.verdict
        assert v.reasons == ("155.25 sits in the drill band",)

    def test_confident_reason_omits_unrelated_felt(self):
        # 89.0/155.25 ≈ 0.573 — no ratio within the 4% tolerance → the felt
        # clause is omitted rather than claiming a false agreement.
        result = make_result(make_tempo(primary_bpm=155.25, felt_bpm=89.0))
        v = build_tempo_view(result, None, CONFIDENT).readout.verdict
        assert v.reasons == ("155.25 sits in the drill band",)

    def test_confident_engine_reason_takes_precedence_over_computed(self):
        # If the engine ever attaches a reason to a confident result, it wins.
        engine_reason = "prior override: fingerprint pinned 155.25"
        result = make_result(
            make_tempo(primary_bpm=155.25, ambiguity_reason=engine_reason)
        )
        v = build_tempo_view(result, None, CONFIDENT).readout.verdict
        assert v.reasons == (engine_reason,)

    def test_ambiguous_with_single_reason(self):
        reason = "primary 205 is outside the drill band [140-170], yet 155 sits inside it"
        result = make_result(make_tempo(ambiguous=True, ambiguity_reason=reason))
        v = build_tempo_view(result, None, AMBIGUOUS).readout.verdict
        assert v.word == "AMBIGUOUS"
        assert v.sub == "HUMAN TIEBREAK NEEDED"
        assert v.reasons == (reason,)
        assert v.show_tiebreak is True
        assert v.show_undo is False

    def test_ambiguous_reasons_split_on_semicolon_joiner_full_strings(self):
        r1 = "raw tempogram peaks at 205, prior favors 155 (dotted_down)"
        r2 = "155 (dotted_down) scores within 12% of 205"
        result = make_result(make_tempo(ambiguous=True, ambiguity_reason=f"{r1}; {r2}"))
        v = build_tempo_view(result, None, AMBIGUOUS).readout.verdict
        assert v.reasons == (r1, r2)  # full strings, no truncation here

    def test_confirmed_human(self):
        st = state(
            VerdictKind.CONFIRMED_HUMAN,
            path="/tmp/beat.wav",
            confirmed_bpm=155.25,
            prev_kind=VerdictKind.AMBIGUOUS,
        )
        v = build_tempo_view(make_result(), None, st).readout.verdict
        assert v.word == "CONFIRMED · HUMAN"
        assert v.reasons == ("you chose 155.25 — saved as ground truth",)
        assert v.show_undo is True
        assert v.show_tiebreak is False

    def test_working(self):
        v = build_tempo_view(None, None, state(VerdictKind.WORKING)).readout.verdict
        assert v.word == "WORKING…"
        assert v.sub == "full-track analysis · ~1 s"
        assert v.reasons == ()

    def test_error(self):
        st = state(VerdictKind.ERROR, error_msg="LibsndfileError: unknown format")
        v = build_tempo_view(None, None, st).readout.verdict
        assert v.word == "ERROR"
        assert v.sub is None
        assert v.reasons == ("LibsndfileError: unknown format",)

    def test_no_tempo(self):
        v = build_tempo_view(no_tempo_result(), None, state(VerdictKind.NO_TEMPO)).readout.verdict
        assert v.word == "NO TEMPO"
        assert v.sub == "silent file — nothing to track"
        assert v.show_tiebreak is False

    def test_kind_strings_match_reducer_enum(self):
        for kind in VerdictKind:
            v = build_tempo_view(None, None, state(kind)).readout.verdict
            assert v.kind == kind.value


# ---------------------------------------------------------------------------
# Chips — every engine Relationship member, design copy verbatim (R1)
# ---------------------------------------------------------------------------

# candidate BPM vs primary 150.0 → (engine Relationship, verbatim design chip)
CHIP_MATRIX = [
    (150.0, Relationship.SELF, "×1 · primary"),
    (75.0, Relationship.OCTAVE_DOWN, "½× · half-time"),
    (300.0, Relationship.OCTAVE_UP, "2× · double-time"),
    (225.0, Relationship.DOTTED_UP, "1½× · dotted"),
    (100.0, Relationship.DOTTED_DOWN, "⅔× · dotted"),
    (112.5, Relationship.FRACTIONAL, "¾× · cross"),
    (200.0, Relationship.FRACTIONAL, "1⅓× · cross"),
    (50.0, Relationship.THIRD, "⅓× · triplet"),
    (450.0, Relationship.TRIPLE, "3× · triplet"),
    (93.75, Relationship.FRACTIONAL, "⅝× · cross"),
    (240.0, Relationship.FRACTIONAL, "1⅗× · cross"),
    (187.5, Relationship.FRACTIONAL, "1¼× · cross"),
    (120.0, Relationship.FRACTIONAL, "⅘× · cross"),
    (125.0, Relationship.FRACTIONAL, "⅚× · cross"),
    (180.0, Relationship.FRACTIONAL, "1⅕× · cross"),
    (157.0, Relationship.UNRELATED, "unrelated"),
]


class TestChips:
    @pytest.fixture(scope="class")
    def vm(self):
        extra = tuple(bpm for bpm, _, _ in CHIP_MATRIX[1:])
        result = make_result(make_tempo(primary_bpm=150.0, felt_bpm=75.0, extra_bpms=extra))
        return build_tempo_view(result, None, CONFIDENT)

    def test_every_relationship_member_is_covered(self):
        assert {rel for _, rel, _ in CHIP_MATRIX} == set(Relationship)

    def test_matrix_agrees_with_engine_classifier(self):
        # SELF is an identity check in the resolver; classify_relationship
        # maps a same-BPM pair to the ×1 ratio, which the chip renders as
        # primary — the engine member for every other row must match.
        for bpm, rel, _ in CHIP_MATRIX[1:]:
            assert classify_relationship(bpm, 150.0) is rel, bpm

    def test_chip_copy_verbatim(self, vm):
        got = [(row.bpm, row.chip.text) for row in vm.candidates]
        want = [(bpm, chip) for bpm, _, chip in CHIP_MATRIX]
        assert got == want

    def test_chip_kinds(self, vm):
        assert vm.candidates[0].chip.kind == "primary"
        assert vm.candidates[0].is_primary is True
        for row in vm.candidates[1:]:
            assert row.is_primary is False
            expected = "unrelated" if row.chip.text == "unrelated" else "related"
            assert row.chip.kind == expected, row.bpm

    def test_confirmed_human_flag_always_false_in_m1(self, vm):
        assert all(row.confirmed_human is False for row in vm.candidates)


# ---------------------------------------------------------------------------
# Candidate row formatting
# ---------------------------------------------------------------------------


class TestRowFormatting:
    def test_number_formats(self):
        vm = build_tempo_view(make_result(), None, CONFIDENT)
        row = vm.candidates[0]
        assert row.bpm_text == "205.15"  # 2dp
        assert row.salience_text == "0.912"  # 3dp
        assert row.score_text == "1.86"  # 2dp

    def test_negative_bpm_uses_u2212_policy(self):
        # Never happens with real engine output — the policy is still pinned.
        result = make_result(make_tempo(primary_bpm=150.0, extra_bpms=(-5.0,)))
        row = build_tempo_view(result, None, CONFIDENT).candidates[1]
        assert row.bpm_text == "−5.00"
        assert row.chip.text == "unrelated"  # non-positive → unrelated (engine guard)

    def test_salience_clamped_for_bar_width(self):
        tempo = make_tempo(primary_bpm=150.0, extra_bpms=())
        tempo.candidates[0].salience = 1.7  # poisoned input
        vm = build_tempo_view(make_result(tempo), None, CONFIDENT)
        assert vm.candidates[0].salience == 1.0

    def test_rows_preserve_engine_order_and_coarse_bpms(self):
        result = make_result(make_tempo(primary_bpm=140.22, extra_bpms=(70.25, 280.5)))
        vm = build_tempo_view(result, None, CONFIDENT)
        assert [r.bpm for r in vm.candidates] == [140.22, 70.25, 280.5]


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------


class TestMarkers:
    def test_primary_first_then_felt_with_labels(self):
        vm = build_tempo_view(make_result(), make_features(), CONFIDENT)
        assert [m.kind for m in vm.markers] == ["primary", "felt"]
        assert vm.markers[0].label == "205.15 · PRIMARY"
        assert vm.markers[1].label == "102.57 · FELT"
        assert vm.markers[0].bpm == 205.15
        assert vm.markers[1].bpm == 102.57

    def test_no_felt_marker_without_felt_bpm(self):
        result = make_result(make_tempo(felt_bpm=None))
        vm = build_tempo_view(result, None, CONFIDENT)
        assert [m.kind for m in vm.markers] == ["primary"]

    def test_no_markers_without_tempo(self):
        vm = build_tempo_view(no_tempo_result(), None, state(VerdictKind.NO_TEMPO))
        assert vm.markers == ()

    def test_sides_flip_at_72_percent_boundary(self):
        # 72% of the 40–240 span = 184.0 BPM; the boundary itself flips left.
        flip_bpm = BPM_AXIS_MIN + 0.72 * (BPM_AXIS_MAX - BPM_AXIS_MIN)
        assert flip_bpm == 184.0
        at = build_tempo_view(
            make_result(make_tempo(primary_bpm=184.0, felt_bpm=92.0)), None, CONFIDENT
        )
        assert at.markers[0].side == "left"
        below = build_tempo_view(
            make_result(make_tempo(primary_bpm=183.9, felt_bpm=91.95)), None, CONFIDENT
        )
        assert below.markers[0].side == "right"

    def test_sides_computed_independently_per_marker(self):
        vm = build_tempo_view(
            make_result(make_tempo(primary_bpm=205.15, felt_bpm=102.57)), None, CONFIDENT
        )
        assert vm.markers[0].side == "left"  # 205.15 sits at 82.6% of the span
        assert vm.markers[1].side == "right"


# ---------------------------------------------------------------------------
# Band, curve, no-tempo
# ---------------------------------------------------------------------------


class TestBandCurveNoTempo:
    def test_band_defaults_to_engine_config(self):
        vm = build_tempo_view(make_result(), None, CONFIDENT)
        assert vm.band == (140.0, 170.0)

    def test_band_reads_config_reachable_on_result(self):
        result = make_result()
        result.config = SimpleNamespace(
            ambiguity=SimpleNamespace(genre_band_min=120.0, genre_band_max=150.0)
        )
        vm = build_tempo_view(result, None, CONFIDENT)
        assert vm.band == (120.0, 150.0)

    def test_curve_arrays_pass_through_by_identity(self):
        features = make_features()
        vm = build_tempo_view(make_result(), features, CONFIDENT)
        assert vm.curve_bpms is features.tempo_curve.bpms
        assert vm.curve_salience is features.tempo_curve.salience
        assert vm.curve_bpms.shape == (801,)

    def test_no_features_means_no_curve(self):
        vm = build_tempo_view(make_result(), None, CONFIDENT)
        assert vm.curve_bpms is None
        assert vm.curve_salience is None

    def test_no_tempo_state(self):
        vm = build_tempo_view(no_tempo_result(), make_features(), state(VerdictKind.NO_TEMPO))
        assert vm.has_result is True
        assert vm.no_tempo is True
        assert vm.no_tempo_text == "no periodicity — silent file — nothing to track"
        assert vm.candidates == ()
        assert vm.markers == ()
        assert vm.readout.primary_text == EM_DASH
        assert vm.readout.felt_text == EM_DASH
        assert vm.readout.felt_chip is None

    def test_result_with_tempo_is_not_no_tempo(self):
        vm = build_tempo_view(make_result(), None, CONFIDENT)
        assert vm.has_result is True
        assert vm.no_tempo is False
        assert vm.no_tempo_text is None


# ---------------------------------------------------------------------------
# Readout — numbers, felt chip, em-dash policy (C-06 / R12)
# ---------------------------------------------------------------------------


class TestReadout:
    def test_primary_and_felt_texts(self):
        r = build_tempo_view(make_result(), None, CONFIDENT).readout
        assert r.primary_text == "205.15"
        assert r.felt_text == "102.57"

    def test_felt_chip_present_and_neutral(self):
        r = build_tempo_view(make_result(), None, CONFIDENT).readout
        assert r.felt_chip == ChipView(text="½× · half-time", kind="related")

    def test_felt_chip_never_primary_kind_even_when_felt_equals_primary(self):
        result = make_result(make_tempo(primary_bpm=90.0, felt_bpm=90.0, extra_bpms=()))
        r = build_tempo_view(result, None, CONFIDENT).readout
        assert r.felt_chip.text == "×1 · primary"
        assert r.felt_chip.kind == "related"

    def test_felt_chip_absent_without_felt(self):
        r = build_tempo_view(make_result(make_tempo(felt_bpm=None)), None, CONFIDENT).readout
        assert r.felt_text == EM_DASH
        assert r.felt_chip is None

    def test_loudness_none_renders_em_dashes(self):
        r = build_tempo_view(make_result(loudness=None), None, CONFIDENT).readout
        assert (r.lufs_text, r.dbtp_text, r.dbfs_text) == (EM_DASH, EM_DASH, EM_DASH)

    def test_loudness_values_render_with_u2212(self):
        loud = LoudnessResult(lufs_i=-9.3, true_peak_dbtp=-0.82, sample_peak_dbfs=-1.24)
        r = build_tempo_view(make_result(loudness=loud), None, CONFIDENT).readout
        assert r.lufs_text == "−9.30"
        assert r.dbtp_text == "−0.82"
        assert r.dbfs_text == "−1.24"

    def test_silence_renders_neg_infinity_not_em_dash(self):
        # "−∞ is a measurement, — is absence" — the two must never conflate.
        loud = LoudnessResult(
            lufs_i=float("-inf"), true_peak_dbtp=float("-inf"), sample_peak_dbfs=float("-inf")
        )
        r = build_tempo_view(make_result(loudness=loud), None, CONFIDENT).readout
        assert r.lufs_text == "−∞"

    def test_m2_metrics_are_absence_never_zero(self):
        r = build_tempo_view(make_result(), None, CONFIDENT).readout
        assert (r.dr_text, r.sub_text, r.width_text) == (EM_DASH, EM_DASH, EM_DASH)


# ---------------------------------------------------------------------------
# SessionState verdict wiring (Qt — guarded per-class, R8)
# ---------------------------------------------------------------------------


class TestWorkingBlanksEverything:
    """RC ruling: WORKING renders absence, never the previous result.

    On a re-analysis the session still holds the old result until finish();
    the rail numerals have no covering overlay, so the view-model itself
    must refuse to render stale data as if current.
    """

    def test_working_with_stale_result_blanks_all_surfaces(self):
        vm = build_tempo_view(make_result(), make_features(), state(VerdictKind.WORKING))
        assert vm.has_result is False
        assert vm.candidates == ()
        assert vm.markers == ()
        assert vm.curve_bpms is None and vm.curve_salience is None
        r = vm.readout
        assert r.primary_text == EM_DASH and r.felt_text == EM_DASH
        assert r.felt_chip is None
        assert r.lufs_text == EM_DASH and r.dbtp_text == EM_DASH and r.dbfs_text == EM_DASH
        assert r.verdict.word == "WORKING…"

    def test_error_with_stale_result_blanks_all_surfaces(self):
        # analyze(A) succeeds, analyze(B) fails: the session still holds A's
        # result, but ERROR must not resurrect A's numbers under B's name
        # (review finding 2026-07-07, runtime-reproduced).
        st = state(VerdictKind.ERROR, error_msg="could not decode")
        vm = build_tempo_view(make_result(), make_features(), st)
        assert vm.has_result is False
        assert vm.candidates == () and vm.markers == ()
        assert vm.curve_bpms is None
        r = vm.readout
        assert r.primary_text == EM_DASH and r.felt_text == EM_DASH
        assert r.lufs_text == EM_DASH
        assert r.verdict.word == "ERROR"
        assert r.verdict.reasons == ("could not decode",)  # error copy survives

    def test_non_working_states_still_render_the_result(self):
        vm = build_tempo_view(make_result(), make_features(), CONFIDENT)
        assert vm.has_result is True
        assert vm.candidates and vm.markers
        assert vm.curve_bpms is not None


class TestSessionVerdictWiring:
    """The session feeds the untouched reducer and broadcasts VerdictState.

    tests/ui/test_session.py does not exist, so per the M1 manifest the
    session coverage lives here. Guarded inside the class so the pure tests
    above still run in the Qt-less engine venv.
    """

    @pytest.fixture(autouse=True)
    def _requires_qt(self):
        pytest.importorskip("PySide6")

    @pytest.fixture()
    def session(self):
        from rai_ui.state.session import SessionState

        return SessionState()

    def test_initial_state_is_reducer_initial(self, session):
        assert session.verdict_state is INITIAL

    def test_begin_reduces_open_file(self, session):
        seen = []
        session.verdict_changed.connect(seen.append)
        session.begin("/tmp/beat.wav")
        assert session.verdict_state.kind is VerdictKind.WORKING
        assert session.verdict_state.path == "/tmp/beat.wav"
        assert seen == [session.verdict_state]

    def test_finish_reduces_confident(self, session):
        session.begin("/tmp/beat.wav")
        session.finish(make_result(), None, None, 1.23)
        assert session.verdict_state.kind is VerdictKind.CONFIDENT

    def test_finish_reduces_ambiguous(self, session):
        session.begin("/tmp/beat.wav")
        session.finish(
            make_result(make_tempo(ambiguous=True, ambiguity_reason="x; y")), None, None, 1.0
        )
        assert session.verdict_state.kind is VerdictKind.AMBIGUOUS

    def test_finish_reduces_no_tempo(self, session):
        session.begin("/tmp/silent.wav")
        session.finish(no_tempo_result(), None, None, 0.4)
        assert session.verdict_state.kind is VerdictKind.NO_TEMPO

    def test_fail_reduces_error(self, session):
        session.begin("/tmp/beat.wav")
        session.fail("decode exploded")
        assert session.verdict_state.kind is VerdictKind.ERROR
        assert session.verdict_state.error_msg == "decode exploded"

    def test_finish_order_stores_then_reduces_then_result_ready(self, session):
        """Ordering contract: when result_ready fires, the payload fields AND
        the reduced verdict are already in place (R8 — order matters)."""
        features = make_features()
        observed = {}

        def on_result(result):
            observed["features_stored"] = session.last_features is features
            observed["verdict_kind"] = session.verdict_state.kind

        session.result_ready.connect(on_result)
        session.begin("/tmp/beat.wav")
        session.finish(make_result(), features, None, 1.23)
        assert observed == {
            "features_stored": True,
            "verdict_kind": VerdictKind.CONFIDENT,
        }

    def test_signal_sequence_on_finish(self, session):
        events = []
        session.verdict_changed.connect(lambda st: events.append(("verdict", st.kind)))
        session.result_ready.connect(lambda r: events.append(("result",)))
        session.working.connect(lambda w: events.append(("working", w)))
        session.begin("/tmp/beat.wav")
        session.finish(make_result(), None, None, 1.0)
        assert events == [
            ("verdict", VerdictKind.WORKING),
            ("working", True),
            ("verdict", VerdictKind.CONFIDENT),
            ("result",),
            ("working", False),
        ]

    def test_signal_sequence_on_fail(self, session):
        events = []
        session.verdict_changed.connect(lambda st: events.append(("verdict", st.kind)))
        session.analysis_failed.connect(lambda m: events.append(("failed", m)))
        session.working.connect(lambda w: events.append(("working", w)))
        session.begin("/tmp/beat.wav")
        session.fail("boom")
        assert events == [
            ("verdict", VerdictKind.WORKING),
            ("working", True),
            ("verdict", VerdictKind.ERROR),
            ("working", False),
            ("failed", "boom"),
        ]

    def test_finish_without_begin_hits_stale_guard_but_still_emits(self, session):
        """Completions outside WORKING are dropped by the reducer; the wiring
        still broadcasts (subscribers re-render idempotently)."""
        seen = []
        session.verdict_changed.connect(seen.append)
        session.finish(make_result(), None, None, 1.0)
        assert session.verdict_state.kind is VerdictKind.NO_FILE
        assert len(seen) == 1
        assert session.last_result is not None  # payload still stored

    def test_reopen_returns_to_working(self, session):
        session.begin("/tmp/a.wav")
        session.finish(make_result(), None, None, 1.0)
        session.begin("/tmp/b.wav")
        assert session.verdict_state.kind is VerdictKind.WORKING
        assert session.verdict_state.path == "/tmp/b.wav"

    def test_verdict_view_from_session_state(self, session):
        """End-to-end: session state feeds build_tempo_view directly."""
        session.begin("/tmp/beat.wav")
        result = make_result(make_tempo(ambiguous=True, ambiguity_reason="r1; r2"))
        session.finish(result, make_features(), None, 1.0)
        vm = build_tempo_view(session.last_result, session.last_features, session.verdict_state)
        assert vm.readout.verdict.word == "AMBIGUOUS"
        assert vm.readout.verdict.reasons == ("r1", "r2")
        assert vm.readout.verdict.show_tiebreak is True
        assert vm.curve_bpms is session.last_features.tempo_curve.bpms
