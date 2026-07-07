"""Pure view-model for the M4 Compare section — one truth for A vs B.

Same doctrine as :mod:`rai_ui.state.tempo_view` / ``signal_view``: the
Compare widgets render this frozen view-model verbatim and derive NOTHING
themselves. ``build_compare_view`` feeds the whole section — identity chips,
the Δ table's six rows (metric / A / B / Δ B−A / Reading), and the spectrum
overlay's jointly-normalized curves. Every number goes through
:mod:`rai_ui.state.formatters`; every copy string is a constant here.

Doctrine and rulings enforced in this module:

* **Sign convention is B−A** (R-M4-4; the Δ column header literally reads
  ``Δ B−A``). Deltas are signed unitless numbers: explicit ``+`` on
  positives, U+2212 on negatives, no unit ever. The demo's per-metric
  precision is binding: LUFS/true-peak/DR at 1 dp, BPM at 2 dp, the
  percentage metrics 1 dp with the ``fmt_pct`` trailing-zero trim (``+3``,
  not ``+3.0``).
* **The Reading sentence derives from the DISPLAYED delta** ("number first —
  the sentence sits beside it, never instead of it", C-15): when the Δ cell
  rounds to zero the sentence says "equal …", so the number and the sentence
  can never disagree. Reading vocabulary per metric is R-M4-5's rulebook,
  matching the approved demo's tone (04:804–811).
* **−∞ is a measurement, — is absence** (C-06): a silent side renders
  ``−∞ LUFS`` in its value cell. But a *difference* against the silence
  sentinel is not a finite measurement, so the Δ cell reads ``—`` and the
  loudness Reading degrades to the magnitude-free comparative ("B is
  louder") — honest without inventing an infinite dB figure. Both-silent
  reads ``equal loudness`` (true by measurement). Authored extension: the
  design never drew a silent Compare side (recon §8 gap, flagged).
* **Absence on either side → row Δ and Reading em-dash** (R-M4-5); the
  absent value cell is a bare ``—`` (no unit — em-dash never carries one
  here, matching the demo's B-empty rows, 04:813). The B-empty and
  B-analyzing states em-dash the whole B/Δ/Reading side while A stays
  populated (04:813 verbatim for B-empty; the analyzing variant is the
  R-M4-3 gap fill — in-flight indication is confined to the chip).
* **Δ is never semantically tinted** (C-15 law) — nothing here carries a
  color for exactly that reason; the widgets tint only the A/B hue-locked
  chrome (cyan/rose), never off string contents.
* **Joint spectrum normalization** (R-M4-6): both curves are display-
  normalized against ONE shared dB reference — the max finite bin across A
  and B together sits at 0 dB, floor −90 — so the relative level between the
  curves is honest. A side with no finite bins (silence / pure DC) draws no
  curve. Arrays stay full-resolution here; the pane decimates for paint
  (R-M3-15 doctrine, exactly like SpectrumPane).
* **B is a persistent reference** (R-M4-2): this module knows nothing about
  stores, verdicts or sessions — it is handed A's payload, B's payload and
  B's slot status, and formats. A absent (blanked WORKING/ERROR per the M3
  doctrine, or nothing analyzed yet) dashes the A side without touching B.

Pure Python + numpy only: PySide6/pyqtgraph imports are FORBIDDEN
(AST-pinned by tests) so this module is unit-testable headless and
collectable by the Qt-less engine CI job.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from rai_ui.state.formatters import (
    EM_DASH,
    MINUS_SIGN,
    UNRELATED_CHIP,
    fmt_bpm,
    fmt_dr,
    fmt_pct,
    relationship_chip,
)
from rai_ui.state.signal_view import SPECTRUM_FLOOR_DB, SPECTRUM_TOP_DB

# --- fixed copy (design 04:445–501 verbatim where the design wrote it) --------

#: The dashed B-empty chip (04:456, verbatim — the whole chip is the Browse
#: click target).
B_EMPTY_CHIP_TEXT = "B · drop a reference WAV — or Browse…"

#: B chip while B's analysis is in flight (R-M4-3 — the sanctioned minimal
#: fill for the design's in-flight gap; indication confined to this chip).
B_WORKING_CHIP_TEXT = "B · analyzing…"

#: The non-interactive hint chip next to a loaded B chip (04:453, verbatim).
HINT_CHIP_TEXT = "drop a WAV to replace B"

#: Right side of the chip row (04:459, verbatim, static).
PROFILE_NOTE_TEXT = "same profile · drill 140–170"

#: Centered pill over the overlay plot in the B-empty state (04:489–493,
#: verbatim).
B_EMPTY_PILL_TEXT = "reference (B) not loaded — A shown alone"

#: The chip vocabulary's SELF relationship — R-M4-5's "same grid" probe.
_SELF_CHIP = "×1 · primary"

#: The six metrics, in table order (04:804–811 — the set is closed).
METRIC_LABELS = (
    "Integrated",
    "Primary BPM",
    "True peak",
    "Dynamic range",
    "Sub/bass energy",
    "Stereo width",
)


class BStatus(Enum):
    """The Compare B slot's lifecycle (owned by services.compare_slot)."""

    EMPTY = "empty"
    WORKING = "working"
    LOADED = "loaded"


# ---------------------------------------------------------------------------
# View dataclasses (shared contract — the Stage-2 widgets build against these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompareRowView:
    """One Δ-table row: metric / A / B / Δ B−A / Reading — strings only."""

    metric: str
    a_text: str
    b_text: str
    delta_text: str
    reading: str


@dataclass(frozen=True)
class CompareViewModel:
    """The complete render input for the Compare section."""

    has_a: bool  # an A analysis is present (not blanked WORKING/ERROR)
    a_chip_text: str  # "A · <filename>"; "A · —" while A is blanked
    b_status: BStatus
    b_chip_text: str  # per-state chip copy (loaded: "B · <filename>" + ✕)
    show_hint_chip: bool  # the dashed drop-to-replace hint (loaded B only)
    hint_chip_text: str  # fixed copy (HINT_CHIP_TEXT)
    profile_note: str  # fixed copy (PROFILE_NOTE_TEXT)
    rows: tuple[CompareRowView, ...]  # exactly the 6 metrics, table order
    a_freqs: "Optional[np.ndarray]"  # (k,) Hz — A overlay curve domain
    a_db: "Optional[np.ndarray]"  # (k,) jointly-normalized dB (max 0, floor −90)
    b_freqs: "Optional[np.ndarray]"
    b_db: "Optional[np.ndarray]"
    b_empty: bool  # B slot empty → pill + dashed chip
    b_working: bool  # B analysis in flight → chip copy only (R-M4-3)
    b_empty_pill_text: Optional[str]  # B_EMPTY_PILL_TEXT when b_empty


# ---------------------------------------------------------------------------
# Value extraction (duck-typed, exactly like signal_view — annotations only)
# ---------------------------------------------------------------------------


def _finite_or_none(x) -> Optional[float]:
    """None for absent/NaN; the float otherwise (±∞ pass through — they are
    measurements, C-06; callers decide what a difference against them means)."""
    if x is None:
        return None
    x = float(x)
    if math.isnan(x):
        return None
    return x


def _lufs(result) -> Optional[float]:
    loudness = getattr(result, "loudness", None) if result is not None else None
    return _finite_or_none(loudness.lufs_i) if loudness is not None else None


def _true_peak(result) -> Optional[float]:
    loudness = getattr(result, "loudness", None) if result is not None else None
    return _finite_or_none(loudness.true_peak_dbtp) if loudness is not None else None


def _bpm(result) -> Optional[float]:
    """The resolver's no-tempo shape (empty candidates, primary 0.0) is
    absence — a 0.0 BPM must never render (same probe as the Overview card)."""
    tempo = getattr(result, "tempo", None) if result is not None else None
    if tempo is None or not tempo.candidates or not tempo.primary_bpm > 0:
        return None
    return _finite_or_none(tempo.primary_bpm)


def _crest(signal_result) -> Optional[float]:
    if signal_result is None:
        return None
    return _finite_or_none(signal_result.dynamics.crest_db)


def _sub(signal_result) -> Optional[float]:
    if signal_result is None:
        return None
    return _finite_or_none(signal_result.bands.sub_pct)


def _width(signal_result) -> Optional[float]:
    if signal_result is None:
        return None
    return _finite_or_none(signal_result.stereo.width_pct)


# ---------------------------------------------------------------------------
# Cell formatting
# ---------------------------------------------------------------------------


def _value_with_unit(text: str, unit: str) -> str:
    """Unit-carrying value cell: the unit rides with every MEASUREMENT
    (including ``−∞ LUFS`` — silence is a measurement) but never with the
    bare absence em-dash (the demo's B-empty cells are ``—`` alone)."""
    if text == EM_DASH:
        return text
    return f"{text} {unit}" if unit else text


def _signed(text: str) -> str:
    """Explicit ``+`` on positives, U+2212 on negatives, bare zero. ``text``
    is a plain ``%f``-style rendering; ``-0.0``/``-0``/``-0.00`` normalize to
    unsigned zero first (a rounded-away difference has no direction)."""
    if text.lstrip("-").strip("0") in ("", "."):  # "0", "0.0", "-0.0", …
        return text.lstrip("-")
    if text.startswith("-"):
        return text.replace("-", MINUS_SIGN, 1)
    return "+" + text


def _delta_text(
    a: Optional[float], b: Optional[float], decimals: int, trim: bool = False
) -> str:
    """The Δ cell: B−A at the metric's display precision, signed, unitless.

    Either side absent → ``—``. A non-finite difference (any ±∞ operand,
    i.e. the silence sentinel) → ``—`` too: the VALUE cells keep their
    ``−∞`` measurement, but the difference itself is not a finite number and
    the Δ column never lies (C-06 applied to derived figures).
    """
    if a is None or b is None:
        return EM_DASH
    d = b - a
    if not math.isfinite(d):
        return EM_DASH
    text = f"{d:.{decimals}f}"
    if trim and text.endswith(".0"):
        text = text[:-2]
    return _signed(text)


def _is_zero_delta(delta_text: str) -> bool:
    """True when the DISPLAYED delta is (rounded to) zero — the one probe
    every "equal …" reading keys off, so sentence and number always agree."""
    return delta_text.strip("0") in ("", ".")


# ---------------------------------------------------------------------------
# Reading sentences (R-M4-5 rulebook — engine-derived, deterministic)
# ---------------------------------------------------------------------------


def _reading_lufs(a: Optional[float], b: Optional[float], delta_text: str) -> str:
    if a is None or b is None:
        return EM_DASH
    a_inf, b_inf = math.isinf(a), math.isinf(b)
    if a_inf and b_inf:
        return "equal loudness"  # both digitally silent — measured equal
    if a_inf or b_inf:
        # One side is the −∞ silence sentinel: the comparative is decidable,
        # the dB magnitude is not — degrade honestly (authored, recon §8 gap).
        return "B is quieter" if b_inf else "B is louder"
    if _is_zero_delta(delta_text):
        return "equal loudness"
    mag = f"{abs(b - a):.1f}"
    return f"B is {mag} dB louder" if b > a else f"B is {mag} dB quieter"


def _drift_pct_text(a: float, b: float) -> str:
    """Same-grid drift: (B/A − 1)·100 with the fmt_pct trim + explicit sign
    (demo: ``−0.2 %``)."""
    drift = (b / a - 1.0) * 100.0
    text = f"{drift:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return _signed(text) + " %"


def _reading_bpm(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return EM_DASH
    chip = relationship_chip(b, a)
    if chip == _SELF_CHIP:
        return f"same grid — B drifts {_drift_pct_text(a, b)}"
    if chip == UNRELATED_CHIP:
        return "unrelated to A"
    return f"{chip} of A"


def _reading_true_peak(a: Optional[float], b: Optional[float]) -> str:
    if a is None or b is None:
        return EM_DASH
    # −∞ (silence) is a measurement and is trivially clear of 0 dBTP.
    a_over, b_over = a >= 0.0, b >= 0.0
    if not a_over and not b_over:
        return "both clear of 0 dBTP"
    if a_over and b_over:
        return "both at or over 0 dBTP"
    # Honest per-side statement (authored — the design never drew this).
    return "A at or over 0 dBTP — B clear" if a_over else "B at or over 0 dBTP — A clear"


def _reading_dr(a: Optional[float], b: Optional[float], delta_text: str) -> str:
    if a is None or b is None or delta_text == EM_DASH:
        return EM_DASH
    if _is_zero_delta(delta_text):
        return "equal dynamics"
    # Less dynamic range = more compressed (R-M4-5).
    return "B is more compressed" if b < a else "B is less compressed"


def _reading_sub(a: Optional[float], b: Optional[float], delta_text: str) -> str:
    if a is None or b is None or delta_text == EM_DASH:
        return EM_DASH
    if _is_zero_delta(delta_text):
        return "equal sub weight"
    side = "B" if b > a else "A"
    return f"{side} carries more sub at this tempo"


def _reading_width(a: Optional[float], b: Optional[float], delta_text: str) -> str:
    if a is None or b is None or delta_text == EM_DASH:
        return EM_DASH
    if _is_zero_delta(delta_text):
        return "equal width"
    return "B is wider" if b > a else "A is wider"


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _fmt_1dp(x: Optional[float]) -> str:
    """One-decimal measurement (C-06 policy) — ``fmt_dr`` IS the house 1 dp
    measurement formatter (its own docstring covers generic dB figures); the
    Compare table's LUFS/dBTP/dB cells are 1 dp per the binding demo values."""
    return fmt_dr(x)


def _build_rows(a_result, a_signal, b_result, b_signal) -> tuple[CompareRowView, ...]:
    a_lufs, b_lufs = _lufs(a_result), _lufs(b_result)
    a_bpm, b_bpm = _bpm(a_result), _bpm(b_result)
    a_tp, b_tp = _true_peak(a_result), _true_peak(b_result)
    a_dr, b_dr = _crest(a_signal), _crest(b_signal)
    a_sub, b_sub = _sub(a_signal), _sub(b_signal)
    a_w, b_w = _width(a_signal), _width(b_signal)

    lufs_delta = _delta_text(a_lufs, b_lufs, 1)
    bpm_delta = _delta_text(a_bpm, b_bpm, 2)
    tp_delta = _delta_text(a_tp, b_tp, 1)
    dr_delta = _delta_text(a_dr, b_dr, 1)
    sub_delta = _delta_text(a_sub, b_sub, 1, trim=True)
    w_delta = _delta_text(a_w, b_w, 1, trim=True)

    return (
        CompareRowView(
            metric=METRIC_LABELS[0],
            a_text=_value_with_unit(_fmt_1dp(a_lufs), "LUFS"),
            b_text=_value_with_unit(_fmt_1dp(b_lufs), "LUFS"),
            delta_text=lufs_delta,
            reading=_reading_lufs(a_lufs, b_lufs, lufs_delta),
        ),
        CompareRowView(
            metric=METRIC_LABELS[1],
            a_text=fmt_bpm(a_bpm),
            b_text=fmt_bpm(b_bpm),
            delta_text=bpm_delta,
            reading=_reading_bpm(a_bpm, b_bpm),
        ),
        CompareRowView(
            metric=METRIC_LABELS[2],
            a_text=_value_with_unit(_fmt_1dp(a_tp), "dBTP"),
            b_text=_value_with_unit(_fmt_1dp(b_tp), "dBTP"),
            delta_text=tp_delta,
            reading=_reading_true_peak(a_tp, b_tp),
        ),
        CompareRowView(
            metric=METRIC_LABELS[3],
            a_text=_value_with_unit(_fmt_1dp(a_dr), "dB"),
            b_text=_value_with_unit(_fmt_1dp(b_dr), "dB"),
            delta_text=dr_delta,
            reading=_reading_dr(a_dr, b_dr, dr_delta),
        ),
        CompareRowView(
            metric=METRIC_LABELS[4],
            a_text=fmt_pct(a_sub),
            b_text=fmt_pct(b_sub),
            delta_text=sub_delta,
            reading=_reading_sub(a_sub, b_sub, sub_delta),
        ),
        CompareRowView(
            metric=METRIC_LABELS[5],
            a_text=fmt_pct(a_w),
            b_text=fmt_pct(b_w),
            delta_text=w_delta,
            reading=_reading_width(a_w, b_w, w_delta),
        ),
    )


# ---------------------------------------------------------------------------
# Spectrum overlay — joint normalization (R-M4-6)
# ---------------------------------------------------------------------------


def _raw_spectrum(signal_result) -> tuple["Optional[np.ndarray]", "Optional[np.ndarray]"]:
    """A side's raw Welch arrays, or (None, None) when there is nothing to
    draw: absent result, empty arrays, or no finite bins (silence / pure DC
    — the exact ``signal_view`` no-curve conditions)."""
    if signal_result is None:
        return None, None
    freqs = np.asarray(signal_result.spectrum.freqs, dtype=np.float64)
    db = np.asarray(signal_result.spectrum.psd_db, dtype=np.float64)
    if freqs.size == 0 or db.size == 0:
        return None, None
    if not np.isfinite(db).any():
        return None, None
    return freqs, db


def _joint_normalized(
    a_signal, b_signal
) -> tuple[
    "Optional[np.ndarray]",
    "Optional[np.ndarray]",
    "Optional[np.ndarray]",
    "Optional[np.ndarray]",
]:
    """Both curves normalized to ONE shared dB reference: the max finite bin
    across A and B jointly sits at 0 dB, everything clips to the −90 floor —
    so the on-screen level difference between the curves is honest (R-M4-6).
    With only one curve present this degrades to that curve's own max
    (exactly the single-file SpectrumPane normalization)."""
    a_freqs, a_db = _raw_spectrum(a_signal)
    b_freqs, b_db = _raw_spectrum(b_signal)

    tops = []
    if a_db is not None:
        tops.append(float(a_db[np.isfinite(a_db)].max()))
    if b_db is not None:
        tops.append(float(b_db[np.isfinite(b_db)].max()))
    if not tops:
        return None, None, None, None
    top = max(tops)

    if a_db is not None:
        a_db = np.clip(a_db - top, SPECTRUM_FLOOR_DB, SPECTRUM_TOP_DB)
    if b_db is not None:
        b_db = np.clip(b_db - top, SPECTRUM_FLOOR_DB, SPECTRUM_TOP_DB)
    return a_freqs, a_db, b_freqs, b_db


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------


def _basename(result) -> str:
    path = getattr(result, "path", None) if result is not None else None
    name = os.path.basename(str(path)) if path else ""
    return name or EM_DASH


def _b_chip_text(b_status: BStatus, b_result) -> str:
    if b_status is BStatus.EMPTY:
        return B_EMPTY_CHIP_TEXT
    if b_status is BStatus.WORKING:
        return B_WORKING_CHIP_TEXT
    return f"B · {_basename(b_result)}"


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_compare_view(
    a_result, a_signal, b_result, b_signal, b_status: BStatus
) -> CompareViewModel:
    """Build the Compare section's complete view-model.

    ``a_result``/``b_result`` are ``AnalysisResult`` objects (or ``None``),
    ``a_signal``/``b_signal`` the worker-composed ``SignalResult`` records
    (or ``None``), ``b_status`` the B slot's lifecycle state. The caller owns
    the M3 blank doctrine for A (pass ``None`` while A is WORKING/ERROR —
    the A side dashes, B's side is never touched) and the section-visibility
    gate (Compare renders only when a file is loaded, R-M4-13).

    While B is EMPTY or WORKING the whole B/Δ/Reading side em-dashes and no
    B curve is drawn regardless of any stale payload passed in — the slot
    status is the truth (04:813's B-empty rendering; R-M4-3's in-flight
    confinement).
    """
    if b_status is not BStatus.LOADED:
        b_result = None
        b_signal = None

    a_freqs, a_db, b_freqs, b_db = _joint_normalized(a_signal, b_signal)

    b_empty = b_status is BStatus.EMPTY
    b_working = b_status is BStatus.WORKING

    return CompareViewModel(
        has_a=a_result is not None,
        a_chip_text=f"A · {_basename(a_result)}",
        b_status=b_status,
        b_chip_text=_b_chip_text(b_status, b_result),
        show_hint_chip=b_status is BStatus.LOADED,
        hint_chip_text=HINT_CHIP_TEXT,
        profile_note=PROFILE_NOTE_TEXT,
        rows=_build_rows(a_result, a_signal, b_result, b_signal),
        a_freqs=a_freqs,
        a_db=a_db,
        b_freqs=b_freqs,
        b_db=b_db,
        b_empty=b_empty,
        b_working=b_working,
        b_empty_pill_text=B_EMPTY_PILL_TEXT if b_empty else None,
    )


#: The no-file state every Compare widget starts from.
EMPTY_COMPARE_VIEW: CompareViewModel = build_compare_view(
    None, None, None, None, BStatus.EMPTY
)
