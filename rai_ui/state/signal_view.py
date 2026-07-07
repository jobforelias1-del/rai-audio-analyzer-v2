"""Pure view-models for the M2 Overview + Signal sections — one truth each.

Same doctrine as :mod:`rai_ui.state.tempo_view` (the M1 precedent): the
widgets render these frozen view-models verbatim and derive NOTHING
themselves. ``build_overview_view`` feeds the Overview section (summary cards
+ waveform well); ``build_signal_view`` feeds the Signal section (spectrum
well + the three metric cards). Every string goes through
``rai_ui.state.formatters``; every color is a token constant.

Doctrine enforced here (so the widgets cannot get it wrong):

* **WORKING and ERROR blank everything** — the exact
  ``tempo_view.BLANK_VERDICT_KINDS`` rule, imported so the three sections can
  never disagree about when the instrument shows numbers (R-M2-16 / R-M1-3).
* **−∞ is a measurement, — is absence** (C-06): silence renders ``−∞`` for
  RMS/peaks and ``—`` for the undefined shares/crest. A mono file's stereo
  width is ``0 %`` — a measurement, never absence (R-M2-4); a digitally
  silent STEREO file's width is NaN → ``—`` (nothing to measure).
* **Absence chips** (R-M2-10): a card grows a C-06 chip ONLY when its value
  is ``—`` AND a reason exists (``silent file`` / ``undefined below 0.4 s`` /
  ``unavailable for this file``). WORKING/ERROR dash everything with NO
  chips; captions are otherwise fixed copy.
* **Spectrum display normalization** (R-M2-7): the engine's ``psd_db`` is
  unnormalized; here it becomes max-at-0 dB with a −90 dB floor. Silence has
  no curve at all — the well shows :data:`SILENT_SPECTRUM_TEXT` (R-M2-8).
* **Waveform envelope** (R-M2-9): min/max decimation at 2048 bins over a
  DISPLAY-ONLY channel mean of ``y_native`` — measurements never use that
  downmix (the engine's metrics layer measures per-channel).
* **Overview verdict line** (R-M2-20): a short tinted word only. ``✓`` is in
  the vendored Plex cmap and rides in the text; the ``◆`` before the
  ambiguous word is a DRAWN icon and never appears here — widgets key the
  drawn mark off ``verdict_word == AMBIGUOUS_VERDICT_WORD``. Kinds outside
  the design's four-word vocabulary (no-file / working / error / no-tempo)
  fall back to the muted em-dash; the full verdict block with reasons stays
  rail-only.

Pure Python + numpy only: PySide6/pyqtgraph imports are FORBIDDEN (AST-pinned
by tests) so this module is unit-testable headless and collectable by the
Qt-less engine CI job. ``rai_ui.plots.decimate`` and
``rai_ui.theme._tokens_gen`` are both deliberately Qt-free.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np

from rai_ui.plots.decimate import minmax_decimate
from rai_ui.state.formatters import (
    EM_DASH,
    fmt_bpm,
    fmt_dbfs,
    fmt_dbtp,
    fmt_dr,
    fmt_lufs,
    fmt_mmss,
    fmt_pct,
    unavailability_reason,
)
from rai_ui.state.tempo_view import BLANK_VERDICT_KINDS
from rai_ui.state.verdict import INITIAL, VerdictKind, VerdictState
from rai_ui.theme._tokens_gen import (
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_CONFIDENT_BASE,
    COLOR_TEXT_MUTED,
)

if TYPE_CHECKING:  # engine objects appear in annotations only — no runtime dep
    pass

# Spectrum display range (R-M2-7): curve normalized so its max sits at the
# 0 dB top; everything below the floor (including silence's −∞ bins) clips
# to −90 dB.
SPECTRUM_TOP_DB = 0.0
SPECTRUM_FLOOR_DB = -90.0

# Waveform envelope resolution (R-M2-9).
WAVEFORM_BINS = 2048

# The spectrum well's silent-file copy (R-M2-8) — mirrors the tempogram's
# "no periodicity — silent file, nothing to track" pattern, C-17 neutral
# styling. Authored by RC (the design never wrote the spectrum variant).
SILENT_SPECTRUM_TEXT = "no signal — silent file — nothing to measure"

# Overview verdict-line vocabulary (R-M2-20, Console 04:816–817 verbatim).
# The ambiguous word is exported so the TempoCard widget keys its drawn ◆
# off this one constant instead of re-deriving state from a tint.
AMBIGUOUS_VERDICT_WORD = "ambiguous — human tiebreak"
_CHECK = "✓"  # in the vendored Plex cmap (P3:65) — safe as text, unlike ◆

# kind → (word, tint token hex). Anything absent falls back to (—, muted).
_OVERVIEW_VERDICT: dict[VerdictKind, tuple[str, str]] = {
    VerdictKind.CONFIDENT: (f"{_CHECK} confident", COLOR_SEMANTIC_CONFIDENT_BASE),
    VerdictKind.CONFIRMED_HUMAN: (
        f"{_CHECK} confirmed · human",
        COLOR_SEMANTIC_CONFIDENT_BASE,
    ),
    VerdictKind.AMBIGUOUS: (AMBIGUOUS_VERDICT_WORD, COLOR_SEMANTIC_AMBIGUOUS_BASE),
}

# Fixed card copy (design recon §7, verbatim).
_WIDTH_LABEL = "Stereo width"
_WIDTH_CAPTION = "mid/side correlation, whole file"
_SUB_LABEL = "Sub/bass energy"
_SUB_CAPTION = "share of energy below 60 Hz"
_DR_LABEL = "Dynamic range"
_DR_CAPTION_PREFIX = "crest-based, whole file · RMS "

# BS.1770 gating needs ~0.4 s of audio (see rai_analyzer/loudness.py — the
# pyloudnorm block size). A NaN LUFS on a clip at or under this length is the
# "short" absence; a NaN on anything longer is a meter failure.
_LUFS_GATE_SECONDS = 0.4


# ---------------------------------------------------------------------------
# View dataclasses (shared contract — the Stage-3 widgets build against these)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricRowView:
    """One label/value row on a Loudness/Dynamics/File card.

    ``unit`` is the 10px muted suffix ("LUFS"/"dBTP"/"dBFS"/"dB") — ``None``
    when the unit rides inside ``value_text`` ("21 %") or there is none
    (File rows print complete strings like "44 100 Hz" at row-value size).
    """

    label: str
    value_text: str
    unit: Optional[str]


@dataclass(frozen=True)
class ChipNote:
    """A C-06 absence chip: the fixed-vocabulary reason riding with a ``—``."""

    text: str


@dataclass(frozen=True)
class GaugeCardView:
    """A Signal metric card: 30px mono value + optional 8px gauge + caption.

    ``gauge_frac`` is 0..1 for the gauge fill; ``None`` means the card has NO
    gauge at all (the Dynamic-range card). An absent value keeps the gauge at
    0.0 — the demo's "— (bar 0)" silence rendering.
    """

    label: str
    value_text: str
    gauge_frac: Optional[float]
    caption: str
    chip: Optional[ChipNote]


@dataclass(frozen=True)
class RowsCardView:
    """A rows card (Loudness / Dynamics / File) with an optional chip slot."""

    label: str
    rows: tuple[MetricRowView, ...]
    chip: Optional[ChipNote]


@dataclass(frozen=True)
class TempoCardView:
    """Overview's wide Tempo card (R-M2-20).

    ``verdict_word`` carries the short design copy with the cmap-safe ``✓``
    included ("✓ confident" / "✓ confirmed · human" / "—"); the ambiguous
    word equals :data:`AMBIGUOUS_VERDICT_WORD` and the widget places the
    drawn ◆ before it. ``verdict_tint`` is the token hex for the word — the
    ONLY tinted text on the card (semantic color never tints a numeral).
    """

    primary_text: str
    felt_text: str
    verdict_word: str
    verdict_tint: str


@dataclass(frozen=True)
class SignalViewModel:
    """The complete render input for the Signal section."""

    has_signal: bool  # a SignalResult is present (and not blanked)
    silent: bool  # digitally silent file — spectrum shows copy, not a curve
    silent_text: Optional[str]  # SILENT_SPECTRUM_TEXT when silent (R-M2-8)
    spectrum_freqs: "Optional[np.ndarray]"  # (k,) Hz, log-x domain
    spectrum_db: "Optional[np.ndarray]"  # (k,) normalized: max 0 dB, floor −90
    width_card: GaugeCardView
    sub_card: GaugeCardView
    dr_card: GaugeCardView  # gauge_frac is always None here


@dataclass(frozen=True)
class OverviewViewModel:
    """The complete render input for the Overview section."""

    has_result: bool
    tempo_card: TempoCardView
    loudness_card: RowsCardView
    dynamics_card: RowsCardView
    file_card: RowsCardView
    wave_mins: "Optional[np.ndarray]"  # (<=2048,) envelope minima
    wave_maxs: "Optional[np.ndarray]"  # (<=2048,) envelope maxima
    wave_len_text: str  # mm:ss ("3:14"); "—" without a result


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _is_silent(signal_result) -> bool:
    """Digitally silent file: the sample peak is −∞ (nothing was measured
    above zero). Empty input measures the same way, so this one probe covers
    both — and it agrees with the spectrum (all-−∞ bins) by construction."""
    return not math.isfinite(float(signal_result.dynamics.peak_dbfs))


def _absence_reason(result, signal_result, silent: bool) -> Optional[str]:
    """The C-06 reason (if any) explaining why the M2 metrics read ``—``.

    * silent file → ``silent file`` (shares/crest are undefined on silence);
    * analysis succeeded but metrics degraded to None (R-M2-15) →
      ``unavailable for this file``;
    * no analysis at all (empty / WORKING / ERROR) → no reason, no chips.
    """
    if silent:
        return unavailability_reason("silence")
    if result is not None and signal_result is None:
        return unavailability_reason("failed")
    return None


def _chip_if_absent(value_text: str, reason: Optional[str]) -> Optional[ChipNote]:
    """R-M2-10: a chip renders ONLY when the value is ``—`` AND a reason
    exists. −∞ is a measurement and never carries a chip."""
    if value_text == EM_DASH and reason is not None:
        return ChipNote(text=reason)
    return None


def _gauge_frac(pct: Optional[float]) -> float:
    """Gauge fill fraction for a percentage; absent values keep the bar at 0
    (the demo's "— (bar 0)"), defensive clamp to 0..1 for the rest."""
    if pct is None:
        return 0.0
    pct = float(pct)
    if not math.isfinite(pct):
        return 0.0
    return min(1.0, max(0.0, pct / 100.0))


# ---------------------------------------------------------------------------
# Signal section
# ---------------------------------------------------------------------------


def _normalized_spectrum(
    signal_result, silent: bool
) -> tuple["Optional[np.ndarray]", "Optional[np.ndarray]"]:
    """Display-normalize the engine spectrum per R-M2-7.

    Max sits at the 0 dB top; −∞ (zero-power) bins clip to the −90 dB floor.
    A silent file has no finite bins — no curve, the well shows the R-M2-8
    copy instead. Degenerate input (empty arrays from a <2-sample clip) also
    yields no curve.
    """
    if signal_result is None or silent:
        return None, None
    freqs = np.asarray(signal_result.spectrum.freqs, dtype=np.float64)
    db = np.asarray(signal_result.spectrum.psd_db, dtype=np.float64)
    if freqs.size == 0 or db.size == 0:
        return None, None
    finite = np.isfinite(db)
    if not finite.any():
        return None, None  # nothing measurable — mirrors the silent path
    top = float(db[finite].max())
    norm = np.clip(db - top, SPECTRUM_FLOOR_DB, SPECTRUM_TOP_DB)
    return freqs, norm


def _width_card(signal_result, reason: Optional[str]) -> GaugeCardView:
    width = signal_result.stereo.width_pct if signal_result is not None else None
    value_text = fmt_pct(width)
    return GaugeCardView(
        label=_WIDTH_LABEL,
        value_text=value_text,
        gauge_frac=_gauge_frac(width),
        caption=_WIDTH_CAPTION,
        chip=_chip_if_absent(value_text, reason),
    )


def _sub_card(signal_result, reason: Optional[str]) -> GaugeCardView:
    sub = signal_result.bands.sub_pct if signal_result is not None else None
    value_text = fmt_pct(sub)
    return GaugeCardView(
        label=_SUB_LABEL,
        value_text=value_text,
        gauge_frac=_gauge_frac(sub),
        caption=_SUB_CAPTION,
        chip=_chip_if_absent(value_text, reason),
    )


def _dr_caption(signal_result) -> str:
    """``crest-based, whole file · RMS −16.4 dB`` — the demo appends the dB
    unit only to a finite RMS (silence prints a bare ``−∞``, absence ``—``)."""
    rms = signal_result.dynamics.rms_dbfs if signal_result is not None else None
    rms_text = fmt_dr(rms)
    if rms is not None and math.isfinite(float(rms)):
        rms_text += " dB"
    return _DR_CAPTION_PREFIX + rms_text


def _dr_card(signal_result, reason: Optional[str]) -> GaugeCardView:
    crest = signal_result.dynamics.crest_db if signal_result is not None else None
    value_text = fmt_dr(crest)  # NaN on silence → "—" (crest is undefined)
    return GaugeCardView(
        label=_DR_LABEL,
        value_text=value_text,
        gauge_frac=None,  # the DR card has no gauge bar (04:436–440)
        caption=_dr_caption(signal_result),
        chip=_chip_if_absent(value_text, reason),
    )


def build_signal_view(result, signal_result, verdict_state: Optional[VerdictState]) -> SignalViewModel:
    """Build the Signal section's complete view-model.

    ``result`` is the ``AnalysisResult`` (used only to distinguish
    "metrics degraded to None on a real analysis" from "no analysis at all"
    for the unavailability chip), ``signal_result`` the worker-composed
    ``SignalResult`` (or ``None``), ``verdict_state`` the session's reduced
    state (``None`` falls back to INITIAL).
    """
    if verdict_state is None:
        verdict_state = INITIAL

    # Same instrument doctrine as build_tempo_view: WORKING and ERROR blank
    # every surface — including the chips, which would otherwise explain an
    # absence that is really just "not measured yet".
    if verdict_state.kind in BLANK_VERDICT_KINDS:
        result = None
        signal_result = None

    has_signal = signal_result is not None
    silent = has_signal and _is_silent(signal_result)
    reason = _absence_reason(result, signal_result, silent)
    freqs, db = _normalized_spectrum(signal_result, silent)

    return SignalViewModel(
        has_signal=has_signal,
        silent=silent,
        silent_text=SILENT_SPECTRUM_TEXT if silent else None,
        spectrum_freqs=freqs,
        spectrum_db=db,
        width_card=_width_card(signal_result, reason),
        sub_card=_sub_card(signal_result, reason),
        dr_card=_dr_card(signal_result, reason),
    )


# ---------------------------------------------------------------------------
# Overview section
# ---------------------------------------------------------------------------


def _tempo_card(result, verdict_state: VerdictState) -> TempoCardView:
    tempo = getattr(result, "tempo", None)
    # The resolver's no-tempo shape: empty candidates and primary_bpm == 0.0
    # (same probe as build_tempo_view — a 0.0 BPM must never render).
    has_tempo = bool(tempo is not None and tempo.candidates and tempo.primary_bpm > 0)
    primary = tempo.primary_bpm if has_tempo else None
    felt = tempo.felt_bpm if has_tempo else None
    word, tint = _OVERVIEW_VERDICT.get(verdict_state.kind, (EM_DASH, COLOR_TEXT_MUTED))
    return TempoCardView(
        primary_text=fmt_bpm(primary),
        felt_text=fmt_bpm(felt),
        verdict_word=word,
        verdict_tint=tint,
    )


def _loudness_card(result) -> RowsCardView:
    loudness = getattr(result, "loudness", None)
    lufs = loudness.lufs_i if loudness is not None else None
    rows = (
        MetricRowView(label="Integrated", value_text=fmt_lufs(lufs), unit="LUFS"),
        MetricRowView(
            label="True peak",
            value_text=fmt_dbtp(loudness.true_peak_dbtp if loudness is not None else None),
            unit="dBTP",
        ),
        MetricRowView(
            label="Sample peak",
            value_text=fmt_dbfs(loudness.sample_peak_dbfs if loudness is not None else None),
            unit="dBFS",
        ),
    )
    # The M1 loudness chip idiom, unchanged: a chip only where LUFS is "—".
    # −∞ (silence) is a measurement and carries no chip (R-M2-10); NaN is the
    # meter's honest "could not gate" — short clip below the 0.4 s block, or
    # an unexpected meter failure on longer material.
    chip = None
    if result is not None:
        if loudness is None:
            chip = ChipNote(text=unavailability_reason("failed"))
        elif lufs is not None and math.isnan(float(lufs)):
            kind = (
                "short"
                if float(getattr(result, "duration", 0.0)) <= _LUFS_GATE_SECONDS
                else "failed"
            )
            chip = ChipNote(text=unavailability_reason(kind))
    return RowsCardView(label="Loudness", rows=rows, chip=chip)


def _dynamics_card(result, signal_result, silent: bool) -> RowsCardView:
    if signal_result is not None:
        crest = signal_result.dynamics.crest_db
        sub = signal_result.bands.sub_pct
        width = signal_result.stereo.width_pct
    else:
        crest = sub = width = None
    dr_text = fmt_dr(crest)
    rows = (
        MetricRowView(label="Dyn range", value_text=dr_text, unit="dB"),
        MetricRowView(label="Sub/bass", value_text=fmt_pct(sub), unit=None),
        MetricRowView(label="Stereo width", value_text=fmt_pct(width), unit=None),
    )
    # One chip slot per card: keyed off the DR row (the card's headline
    # absence — silence dashes all three, metrics-failure dashes all three).
    reason = _absence_reason(result, signal_result, silent)
    return RowsCardView(
        label="Dynamics", rows=rows, chip=_chip_if_absent(dr_text, reason)
    )


def _group_thousands(value: int) -> str:
    """``44100`` -> ``"44 100"`` — the File card's space-grouped sample rate
    (04:384 shows ``44 100 Hz``; a plain space, matching the approved HTML)."""
    return f"{int(value):,}".replace(",", " ")


def _channels_text(channels: int) -> str:
    if channels == 1:
        return "1 (mono)"
    if channels == 2:
        return "2 (stereo)"
    return f"{channels} (multichannel)"


def _file_card(result) -> RowsCardView:
    if result is None:
        name = length = rate = channels = EM_DASH
    else:
        name = os.path.basename(str(result.path))
        length = f"{float(result.duration):.1f} s"  # demo: "194.9 s"
        rate = f"{_group_thousands(result.sr)} Hz"  # demo: "44 100 Hz"
        channels = _channels_text(int(result.channels))
    rows = (
        MetricRowView(label="Name", value_text=name, unit=None),
        MetricRowView(label="Length", value_text=length, unit=None),
        MetricRowView(label="Rate", value_text=rate, unit=None),
        MetricRowView(label="Channels", value_text=channels, unit=None),
    )
    return RowsCardView(label="File", rows=rows, chip=None)


def _wave_envelope(signal_obj) -> tuple["Optional[np.ndarray]", "Optional[np.ndarray]"]:
    """Min/max envelope of a DISPLAY-ONLY channel mean of ``y_native``
    (R-M2-9). The downmix is fine for a context waveform (and is exactly what
    the well can draw); measurements never come from it — the metrics layer
    measured per-channel long before this runs."""
    y = getattr(signal_obj, "y_native", None) if signal_obj is not None else None
    if y is None:
        return None, None
    y = np.asarray(y, dtype=np.float64)
    if y.size == 0:
        return None, None
    if y.ndim > 1:
        y = y.mean(axis=1)
    mins, maxs = minmax_decimate(y, WAVEFORM_BINS)
    return mins, maxs


def build_overview_view(
    result, signal_obj, signal_result, verdict_state: Optional[VerdictState]
) -> OverviewViewModel:
    """Build the Overview section's complete view-model.

    ``result`` is the ``AnalysisResult`` (or ``None``), ``signal_obj`` the
    worker-delivered ``AudioSignal`` whose ``y_native`` feeds the waveform
    envelope (or ``None`` — e.g. shell tests drive the session with bare
    results), ``signal_result`` the composed metrics record (or ``None``),
    ``verdict_state`` the session's reduced state (``None`` → INITIAL).
    """
    if verdict_state is None:
        verdict_state = INITIAL

    # WORKING/ERROR blank rule — identical to build_tempo_view (one truth).
    if verdict_state.kind in BLANK_VERDICT_KINDS:
        result = None
        signal_obj = None
        signal_result = None

    has_result = result is not None
    silent = signal_result is not None and _is_silent(signal_result)
    wave_mins, wave_maxs = _wave_envelope(signal_obj)

    return OverviewViewModel(
        has_result=has_result,
        tempo_card=_tempo_card(result, verdict_state),
        loudness_card=_loudness_card(result),
        dynamics_card=_dynamics_card(result, signal_result, silent),
        file_card=_file_card(result),
        wave_mins=wave_mins,
        wave_maxs=wave_maxs,
        wave_len_text=fmt_mmss(float(result.duration)) if has_result else EM_DASH,
    )


# The no-file states every Overview/Signal widget starts from.
EMPTY_SIGNAL_VIEW: SignalViewModel = build_signal_view(None, None, INITIAL)
EMPTY_OVERVIEW_VIEW: OverviewViewModel = build_overview_view(None, None, None, INITIAL)
