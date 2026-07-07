"""Pure view-model for the M1 Tempo section — one truth for three widgets.

The tempogram pane, the candidate table, and the rail/bridge readout all
render the same analysis; if each derived its own strings the app could show
"205.15" on the plot chip and "205.2" in the table. This module is the single
derivation point: ``build_tempo_view`` turns the engine payload
(``AnalysisResult`` + ``Features``) and the reduced ``VerdictState`` into one
frozen ``TempoViewModel`` that every tempo widget consumes verbatim.

Doctrine enforced here (so the widgets cannot get it wrong):

* All number/chip formatting goes through ``rai_ui.state.formatters`` — BPM
  2 dp with U+2212 minus, salience 3 dp, score 2 dp, chips computed from
  candidate ÷ primary (never hand-authored), em-dash for absence (C-06).
* Candidates display as-is: coarse 0.25-grid BPMs for non-primary rows,
  byte-matching ``AnalysisResult.to_report()`` — one truth (ruling R5). The
  felt marker draws at ``TempoResult.felt_bpm`` independently and need not
  equal any table row.
* Marker label sides come from ``rai_ui.plots.helpers.marker_label_side``
  over the fixed 40–240 BPM axis (labels flip left at >=72% of the span).
* The genre band is read from the analysis config when one is reachable on
  the result, else from the engine's ``DEFAULT_CONFIG`` — never hardcoded
  downstream of this module.
* Verdict words are a fixed vocabulary. The leading glyphs the design shows
  (drawn ✓/◆ icons, the "— " prefix on the neutral words) are presentation
  and belong to the widgets; ``VerdictView.word`` carries the bare word.
* No-tempo is a neutral state, never error styling (ruling R14): copy is the
  computed ``no periodicity — {sub}`` form.
* CONFIRMED · HUMAN is a display overlay (R-M3-4 / plan D7): the confirmed
  bpm from ``verdict_state.confirmed_bpm`` becomes the effective primary for
  chips, markers, and the readout — recomputed HERE with pure formatter math
  over the UNTOUCHED engine result. Felt stays the engine value (04
  executable truth over wireframe F4); only its relation chip recomputes.

Pure Python + numpy only: PySide6/pyqtgraph imports are FORBIDDEN here so the
module is unit-testable headless and collectable by the Qt-less engine CI
job. The engine (``rai_analyzer``) is imported lazily for its config
constants — reading engine constants is allowed, editing engine files is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from rai_ui.plots.helpers import marker_label_side
from rai_ui.state.formatters import (
    EM_DASH,
    UNRELATED_CHIP,
    fmt_bpm,
    fmt_dbfs,
    fmt_dbtp,
    fmt_dr,
    fmt_lufs,
    fmt_pct,
    relationship_chip,
)
from rai_ui.state.verdict import INITIAL, VerdictKind, VerdictState

if TYPE_CHECKING:  # engine objects appear in annotations only — no runtime dep
    import numpy as np

# The WORKING/ERROR blank rule's kinds (rulings R-M1-3 / R-M2-16), shared with
# rai_ui.state.signal_view so the Overview/Signal builders blank on exactly
# the same states as the tempo surfaces — one truth, one instrument doctrine.
BLANK_VERDICT_KINDS: tuple[VerdictKind, ...] = (VerdictKind.WORKING, VerdictKind.ERROR)

# The tempogram's fixed x-domain: the engine's BPM grid (config.bpm_grid_min/
# max, 40–240 step 0.25 → 801 points). The axis never zooms or pans (C-16),
# so marker-side math always measures against this span.
BPM_AXIS_MIN = 40.0
BPM_AXIS_MAX = 240.0

# Fixed axis ticks per the approved Console: 40..240 every 40 BPM; only the
# last tick carries the "BPM" unit (the widget's job).
AXIS_TICKS: tuple[float, ...] = (40.0, 80.0, 120.0, 160.0, 200.0, 240.0)

# Verdict word vocabulary (fixed — see module docstring on glyph prefixes).
_VERDICT_WORDS: dict[VerdictKind, str] = {
    VerdictKind.NO_FILE: EM_DASH,
    VerdictKind.WORKING: "WORKING…",
    VerdictKind.CONFIDENT: "CONFIDENT",
    VerdictKind.AMBIGUOUS: "AMBIGUOUS",
    VerdictKind.CONFIRMED_HUMAN: "CONFIRMED · HUMAN",
    VerdictKind.NO_TEMPO: "NO TEMPO",
    VerdictKind.ERROR: "ERROR",
}

# Neutral sub-lines (design's fixed copy strings).
_SUB_AMBIGUOUS = "HUMAN TIEBREAK NEEDED"
_SUB_WORKING = "full-track analysis · ~1 s"
_SUB_NO_FILE = "drop a WAV anywhere in this window"
_SUB_NO_TEMPO = "silent file — nothing to track"

# Ambiguity reasons arrive from the engine as one string, multiple reasons
# joined by "; " (rai_analyzer/resolver.py). Split back for per-line display.
_REASON_JOINER = "; "


@dataclass(frozen=True)
class ChipView:
    """A relationship chip: computed text plus a styling kind.

    ``kind`` is a styling channel, not a re-derivation surface: "primary" is
    reserved for the primary candidate row's own chip (amber per design);
    every other in-tolerance relation is "related"; "unrelated" mutes. The
    felt chip in the rail is always neutral, so it never carries "primary"
    even when felt == primary.
    """

    text: str  # e.g. "×1 · primary", "⅔× · dotted", "unrelated"
    kind: str  # "primary" | "related" | "unrelated"


@dataclass(frozen=True)
class CandidateRowView:
    """One candidate-table row, fully formatted."""

    bpm: float
    bpm_text: str  # "205.15" style, 2dp, U+2212 for negatives (never happens, but policy)
    salience: float  # 0..1 for the bar width
    salience_text: str  # 3dp
    score_text: str  # 2dp
    chip: ChipView
    is_primary: bool
    confirmed_human: bool  # True on the confirmed row (M3) — the HumanPill row


@dataclass(frozen=True)
class MarkerView:
    """A full-height tempogram marker plus its label chip placement."""

    bpm: float
    kind: str  # "primary" | "felt"
    label: str  # "205.15 · PRIMARY" / "102.57 · FELT"
    side: str  # "right" | "left" — via plots.helpers.marker_label_side(bpm, 40.0, 240.0)


@dataclass(frozen=True)
class VerdictView:
    """The verdict card's content (C-05) — word, sub-line, reasons, actions."""

    kind: str  # VerdictKind value string from state/verdict.py
    word: str  # "CONFIDENT" / "AMBIGUOUS" / "CONFIRMED · HUMAN" / "NO TEMPO" / "WORKING…" / "ERROR" / "—"
    sub: Optional[str]  # e.g. "HUMAN TIEBREAK NEEDED"
    reasons: tuple[str, ...]  # split result.ambiguity_reason on "; " — full strings, no truncation here
    show_tiebreak: bool  # True only for ambiguous
    show_undo: bool  # True only for confirmed-human (M3; False in M1 flows)


@dataclass(frozen=True)
class ReadoutView:
    """Everything the rail AND bridge need — one truth for both surfaces."""

    verdict: VerdictView
    primary_text: str  # "—" when absent
    felt_text: str  # "—" when absent
    felt_chip: Optional[ChipView]
    lufs_text: str
    dbtp_text: str
    dbfs_text: str
    dr_text: str  # M2: crest 1 dp ("8.2"); "—" without a SignalResult
    sub_text: str  # M2: "21 %"; "—" absent (NaN share on silence is absence)
    width_text: str  # M2: "62 %" / mono "0 %" (a measurement); "—" absent


@dataclass(frozen=True)
class TempoViewModel:
    """The complete render input for the Tempo section."""

    has_result: bool
    no_tempo: bool
    no_tempo_text: Optional[str]
    band: tuple[float, float]  # (140.0, 170.0) from result config — do not hardcode elsewhere
    axis_ticks: tuple[float, ...]  # (40, 80, 120, 160, 200, 240)
    curve_bpms: "Optional[np.ndarray]"  # (801,)
    curve_salience: "Optional[np.ndarray]"  # (801,)
    candidates: tuple[CandidateRowView, ...]
    markers: tuple[MarkerView, ...]  # primary first; felt only if primary exists and felt_bpm present
    readout: ReadoutView


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _band_bounds(result) -> tuple[float, float]:
    """Genre-band (min, max) BPM from the config that produced ``result``.

    ``AnalysisResult`` does not carry its config today, so this probes for a
    ``config`` attribute (future-proof, and testable) and otherwise falls back
    to the engine's ``DEFAULT_CONFIG`` — the exact object the worker's
    pipeline ran with. Imported lazily so importing this module stays cheap.
    """
    cfg = getattr(result, "config", None)
    if cfg is None:
        from rai_analyzer.config import DEFAULT_CONFIG

        cfg = DEFAULT_CONFIG
    return (float(cfg.ambiguity.genre_band_min), float(cfg.ambiguity.genre_band_max))


def _row_chip(candidate_bpm: float, primary_bpm: float, is_primary: bool) -> ChipView:
    text = relationship_chip(candidate_bpm, primary_bpm)
    if is_primary:
        kind = "primary"
    elif text == UNRELATED_CHIP:
        kind = "unrelated"
    else:
        kind = "related"
    return ChipView(text=text, kind=kind)


def _felt_chip(felt_bpm: float, primary_bpm: float) -> ChipView:
    # The rail's felt chip is always neutral styling (design C-07): "related"
    # unless out of tolerance — never "primary", even when felt == primary.
    text = relationship_chip(felt_bpm, primary_bpm)
    kind = "unrelated" if text == UNRELATED_CHIP else "related"
    return ChipView(text=text, kind=kind)


# The 04 demo's confirmed-row detector: |candidate − confirmed| < 0.01
# (Console CO:737). The confirmed bpm comes from a tiebreak card, i.e. one of
# the ranked candidates, so a real confirmation always matches a row.
_CONFIRMED_ROW_TOL = 0.01


def _candidate_rows(tempo, confirmed_bpm: Optional[float] = None) -> tuple[CandidateRowView, ...]:
    """Candidate rows; with a confirmed bpm the display recomputes (R-M3-4).

    Confirmed state is a VIEW-layer overlay over the untouched engine result
    (D7): the confirmed bpm becomes the effective primary — every chip is
    recomputed against it (pure formatter math), the raised/amber primary
    styling and the ✓ HUMAN pill move to the confirmed row, and the engine's
    original primary row renders like any other relation of the new primary.
    """
    effective_primary = confirmed_bpm if confirmed_bpm is not None else tempo.primary_bpm
    rows = []
    for i, c in enumerate(tempo.candidates):
        # Ranked, primary first, is the resolver's ordering guarantee;
        # non-primary rows keep their coarse 0.25-grid BPMs (ruling R5).
        if confirmed_bpm is None:
            is_primary = i == 0
            confirmed_human = False
        else:
            is_primary = abs(float(c.bpm) - confirmed_bpm) < _CONFIRMED_ROW_TOL
            confirmed_human = is_primary  # 04:737 — human pill on the confirmed row only
        salience = min(1.0, max(0.0, float(c.salience)))  # defensive clamp for the bar
        rows.append(
            CandidateRowView(
                bpm=float(c.bpm),
                bpm_text=fmt_bpm(c.bpm),
                salience=salience,
                salience_text=f"{salience:.3f}",
                score_text=f"{float(c.score):.2f}",
                chip=_row_chip(c.bpm, effective_primary, is_primary),
                is_primary=is_primary,
                confirmed_human=confirmed_human,
            )
        )
    return tuple(rows)


def _markers(tempo, confirmed_bpm: Optional[float] = None) -> tuple[MarkerView, ...]:
    # R-M3-4: the tempogram's primary marker moves to the confirmed bpm; the
    # felt marker stays at the ENGINE's felt value (04 executable truth).
    primary_bpm = confirmed_bpm if confirmed_bpm is not None else tempo.primary_bpm
    markers = [
        MarkerView(
            bpm=float(primary_bpm),
            kind="primary",
            label=f"{fmt_bpm(primary_bpm)} · PRIMARY",
            side=marker_label_side(primary_bpm, BPM_AXIS_MIN, BPM_AXIS_MAX),
        )
    ]
    if tempo.felt_bpm is not None:
        markers.append(
            MarkerView(
                bpm=float(tempo.felt_bpm),
                kind="felt",
                label=f"{fmt_bpm(tempo.felt_bpm)} · FELT",
                side=marker_label_side(tempo.felt_bpm, BPM_AXIS_MIN, BPM_AXIS_MAX),
            )
        )
    return tuple(markers)


def _confident_reasons(result) -> tuple[str, ...]:
    """Computed reason line for a CONFIDENT verdict.

    Design rule (C-05): a reason ALWAYS accompanies the verdict word, but the
    engine only writes ``ambiguity_reason`` when it flags. Every clause here
    is computed from the result — stated only when true, omitted otherwise
    (a confident-but-out-of-band result must never read "sits in the drill
    band"). Demo copy of record: "155.25 sits in the drill band · felt ½×
    agrees" (Console CO:773 scenario data).
    """
    tempo = getattr(result, "tempo", None)
    if tempo is None or not tempo.candidates or tempo.primary_bpm <= 0:
        return ()

    lo, hi = _band_bounds(result)
    primary = tempo.primary_bpm
    place = "in" if lo <= primary <= hi else "outside"
    clauses = [f"{fmt_bpm(primary)} sits {place} the drill band"]

    felt = tempo.felt_bpm
    if felt is not None and felt > 0:
        chip = _felt_chip(felt, primary)
        if chip.kind != "unrelated":
            # "½× · half-time" → the ratio part only, per the demo copy.
            clauses.append(f"felt {chip.text.split(' · ')[0]} agrees")

    return (" · ".join(clauses),)


def _verdict_view(verdict_state: VerdictState, result) -> VerdictView:
    kind = verdict_state.kind
    sub: Optional[str] = None
    reasons: tuple[str, ...] = ()

    if kind is VerdictKind.AMBIGUOUS:
        sub = _SUB_AMBIGUOUS
    elif kind is VerdictKind.WORKING:
        sub = _SUB_WORKING
    elif kind is VerdictKind.NO_FILE:
        sub = _SUB_NO_FILE
    elif kind is VerdictKind.NO_TEMPO:
        sub = _SUB_NO_TEMPO

    if kind in (VerdictKind.CONFIDENT, VerdictKind.AMBIGUOUS):
        reason = getattr(getattr(result, "tempo", None), "ambiguity_reason", None)
        if reason:
            reasons = tuple(reason.split(_REASON_JOINER))
        elif kind is VerdictKind.CONFIDENT:
            reasons = _confident_reasons(result)
    elif kind is VerdictKind.CONFIRMED_HUMAN:
        if verdict_state.confirmed_bpm is not None:
            # Design's computed confirmed copy (Console CO:773).
            reasons = (
                f"you chose {fmt_bpm(verdict_state.confirmed_bpm)} — saved as ground truth",
            )
    elif kind is VerdictKind.ERROR:
        if verdict_state.error_msg:
            reasons = (verdict_state.error_msg,)

    return VerdictView(
        kind=kind.value,
        word=_VERDICT_WORDS[kind],
        sub=sub,
        reasons=reasons,
        show_tiebreak=kind is VerdictKind.AMBIGUOUS,
        show_undo=kind is VerdictKind.CONFIRMED_HUMAN,
    )


def _readout(
    verdict_view: VerdictView,
    result,
    has_tempo: bool,
    signal_result,
    confirmed_bpm: Optional[float] = None,
) -> ReadoutView:
    tempo = getattr(result, "tempo", None)
    primary = tempo.primary_bpm if (tempo is not None and has_tempo) else None
    felt = tempo.felt_bpm if (tempo is not None and has_tempo) else None
    if confirmed_bpm is not None and primary is not None:
        # R-M3-4: the confirmed bpm is the readout's primary; FELT stays the
        # engine measurement, but its relation chip recomputes against the
        # new primary (04:850) — pure formatter math, engine untouched.
        primary = confirmed_bpm

    loudness = getattr(result, "loudness", None)

    # M2 metrics from the worker-composed SignalResult (R-M2-16). Absence is
    # an em-dash until a fresh SignalResult exists; the formatters carry the
    # C-06 policy for the values themselves (crest NaN on silence → "—",
    # mono width 0.0 → "0 %" — a measurement, never absence).
    if signal_result is not None:
        dr_text = fmt_dr(signal_result.dynamics.crest_db)
        sub_text = fmt_pct(signal_result.bands.sub_pct)
        width_text = fmt_pct(signal_result.stereo.width_pct)
    else:
        dr_text = sub_text = width_text = EM_DASH

    return ReadoutView(
        verdict=verdict_view,
        primary_text=fmt_bpm(primary),  # em-dash when absent (C-06)
        felt_text=fmt_bpm(felt),
        felt_chip=_felt_chip(felt, primary) if (primary is not None and felt is not None) else None,
        lufs_text=fmt_lufs(loudness.lufs_i if loudness is not None else None),
        dbtp_text=fmt_dbtp(loudness.true_peak_dbtp if loudness is not None else None),
        dbfs_text=fmt_dbfs(loudness.sample_peak_dbfs if loudness is not None else None),
        dr_text=dr_text,
        sub_text=sub_text,
        width_text=width_text,
    )


def build_tempo_view(
    result, features, verdict_state: Optional[VerdictState], signal_result=None
) -> TempoViewModel:
    """Build the Tempo section's complete view-model.

    ``result`` is an ``rai_analyzer.contracts.AnalysisResult`` (or ``None``
    before the first analysis), ``features`` the matching ``Features`` payload
    the worker delivered (or ``None`` — e.g. shell tests drive the session
    with bare results), ``verdict_state`` the session's reduced
    ``VerdictState`` (``None`` falls back to the reducer's INITIAL), and
    ``signal_result`` the worker-composed ``SignalResult`` metrics record (or
    ``None`` — metrics are best-effort and every pre-M2 caller passes three
    arguments, which must keep working).
    """
    if verdict_state is None:
        verdict_state = INITIAL

    # RC ruling (M1): WORKING and ERROR blank everything. The session keeps
    # the PREVIOUS result across begin() and fail() — rendering it under
    # either state would attribute the old file's measurements to the new
    # file (the rail numerals have no covering overlay, and a failed
    # analysis of file B must not resurrect file A's numbers under B's
    # name). Absence (—) until a fresh measurement lands; the instrument
    # never shows a number it didn't just measure. The M2 signal_result is
    # nulled in the same breath (R-M2-16) — file B's failure must not wear
    # file A's DR/Sub/Width either.
    if verdict_state.kind in BLANK_VERDICT_KINDS:
        result = None
        features = None
        signal_result = None

    # M3 confirmed overlay (R-M3-4): only a CONFIRMED · HUMAN verdict carries
    # an effective confirmed bpm into the display math — a stale
    # ``confirmed_bpm`` on a hand-built state of any other kind is inert, and
    # the WORKING/ERROR blank above already nulled the payload it would need.
    confirmed_bpm: Optional[float] = None
    if (
        verdict_state.kind is VerdictKind.CONFIRMED_HUMAN
        and verdict_state.confirmed_bpm is not None
    ):
        confirmed_bpm = float(verdict_state.confirmed_bpm)

    tempo = getattr(result, "tempo", None)
    has_result = result is not None
    # The resolver's no-tempo shape: empty candidates and primary_bpm == 0.0.
    has_tempo = bool(
        tempo is not None and tempo.candidates and tempo.primary_bpm > 0
    )
    no_tempo = has_result and not has_tempo

    curve = getattr(features, "tempo_curve", None)
    verdict_view = _verdict_view(verdict_state, result)

    return TempoViewModel(
        has_result=has_result,
        no_tempo=no_tempo,
        no_tempo_text=f"no periodicity — {_SUB_NO_TEMPO}" if no_tempo else None,
        band=_band_bounds(result),
        axis_ticks=AXIS_TICKS,
        curve_bpms=curve.bpms if curve is not None else None,
        curve_salience=curve.salience if curve is not None else None,
        candidates=_candidate_rows(tempo, confirmed_bpm) if has_tempo else (),
        markers=_markers(tempo, confirmed_bpm) if has_tempo else (),
        readout=_readout(verdict_view, result, has_tempo, signal_result, confirmed_bpm),
    )


# The no-file state every tempo widget starts from (page-0 hero showing).
EMPTY_VIEW: TempoViewModel = build_tempo_view(None, None, INITIAL)
