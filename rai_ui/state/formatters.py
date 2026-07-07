"""Pure string formatters for the v3 UI — numbers, chips, and copy targets.

Everything user-visible that is *derived text* (not layout) is built here, in
plain Python with no Qt, so the exact strings are unit-testable headless and
byte-stable across widgets. Design doctrine this module enforces:

* Vocabulary is law: relationship chips use the design's fixed labels
  (primary / half-time / double-time / dotted / cross / triplet), never
  free-form prose.
* "−∞ is a measurement, — is absence" (design decision C-06): silence has a
  defined loudness of −∞; a value we could not measure is an em-dash. The two
  must never share a glyph.
* Semantic colors never decorate — so these functions return *text only*;
  coloring is the widgets' job, keyed off state, not off string contents.
"""

from __future__ import annotations

import math
from typing import Optional

# Fractional tolerance on a ratio before a candidate is "unrelated" to the
# primary. The design spec drafted ±2%, but the engine's
# ``classify_relationship`` (rai_analyzer/contracts.py) ships 4% — the engine
# wins, because the chip a user reads must never disagree with the
# relationship the engine already logged in the JSON report for the same
# candidate. Mirrors contracts.classify_relationship's default exactly.
DEFAULT_RATIO_TOL = 0.04

# Chip shown when no tabled ratio is within tolerance.
UNRELATED_CHIP = "unrelated"

# Typography constants (design tokens mandate tabular numerals; these glyphs
# are chosen to sit correctly next to them).
EM_DASH = "—"  # absence: value could not be measured
MINUS_SIGN = "−"  # U+2212, not the ASCII hyphen — matches −∞'s minus
NEG_INFINITY = MINUS_SIGN + "∞"  # the loudness of digital silence

# Ratio table: (ratio vs primary, chip label, ASCII-fraction fallback label).
# The ratio set mirrors contracts._RATIO_TABLE exactly (drift is caught by
# tests/ui/test_formatters.py, which imports the engine table and checks both
# directions). The fallback keeps "×" and "·" — they are covered by
# essentially every font — and replaces only the vulgar-fraction glyphs,
# which are the characters that actually go missing in numeric fonts.
_CHIP_TABLE: tuple[tuple[float, str, str], ...] = (
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
)


def _best_index(candidate_bpm: float, primary_bpm: float, tol: float) -> Optional[int]:
    """Index of the tabled ratio with the smallest relative error under tol.

    Semantics mirror ``contracts.classify_relationship`` exactly: relative
    error ``|ratio - target| / target``, strict ``< tol`` (an error of
    exactly ``tol`` is out), minimum error wins. Non-positive or non-finite
    BPMs classify as unrelated, same as the engine's guard.
    """
    if not (math.isfinite(candidate_bpm) and math.isfinite(primary_bpm)):
        return None
    if candidate_bpm <= 0 or primary_bpm <= 0:
        return None
    ratio = candidate_bpm / primary_bpm
    best: Optional[int] = None
    best_err = tol
    for i, (target, _, _) in enumerate(_CHIP_TABLE):
        err = abs(ratio - target) / target
        if err < best_err:
            best_err = err
            best = i
    return best


def relationship_chip(
    candidate_bpm: float, primary_bpm: float, tol: float = DEFAULT_RATIO_TOL
) -> str:
    """Chip text describing how a candidate relates to the primary tempo.

    E.g. ``relationship_chip(155.25, 205.15)`` -> ``"¾× · cross"``.
    """
    i = _best_index(candidate_bpm, primary_bpm, tol)
    return UNRELATED_CHIP if i is None else _CHIP_TABLE[i][1]


def ascii_chip(
    candidate_bpm: float, primary_bpm: float, tol: float = DEFAULT_RATIO_TOL
) -> str:
    """``relationship_chip`` with ASCII fractions (e.g. ``"5/8× · cross"``).

    Fallback for surfaces where the vulgar-fraction glyphs are not reliably
    rendered (clipboard exports, logs, fonts without U+215x coverage).
    """
    i = _best_index(candidate_bpm, primary_bpm, tol)
    return UNRELATED_CHIP if i is None else _CHIP_TABLE[i][2]


# ---------------------------------------------------------------------------
# Measurement formatting
# ---------------------------------------------------------------------------


def _fmt_measurement(x: Optional[float]) -> str:
    """Two-decimal, unit-less number string with the C-06 absence policy.

    * ``None`` / NaN -> ``"—"`` — the measurement does not exist.
    * infinities -> ``"−∞"`` — the meter's silence sentinel. The BS.1770
      chain can only ever produce *negative* infinity (digital silence), so
      any infinite input is treated as that sentinel rather than inventing a
      "+∞" rendering for an impossible measurement.
    * finite values render with U+2212 MINUS SIGN (not the hyphen) so the
      sign glyph matches −∞ and aligns in tabular figures.

    Units (LUFS / dBTP / dBFS / BPM) are deliberately absent: the design puts
    units in the surrounding label, never inside the numeral.
    """
    if x is None:
        return EM_DASH
    x = float(x)
    if math.isnan(x):
        return EM_DASH
    if math.isinf(x):
        return NEG_INFINITY
    return f"{x:.2f}".replace("-", MINUS_SIGN)


def fmt_bpm(x: Optional[float]) -> str:
    """``205.153`` -> ``"205.15"`` (2 dp, unit-less)."""
    return _fmt_measurement(x)


def fmt_lufs(x: Optional[float]) -> str:
    """Integrated loudness number (2 dp; −∞ for silence, — for absence)."""
    return _fmt_measurement(x)


def fmt_db(x: Optional[float]) -> str:
    """Generic dB number (2 dp; −∞ for silence, — for absence)."""
    return _fmt_measurement(x)


def fmt_dbtp(x: Optional[float]) -> str:
    """True-peak number (2 dp; −∞ for silence, — for absence)."""
    return _fmt_measurement(x)


def fmt_dbfs(x: Optional[float]) -> str:
    """Sample-peak number (2 dp; −∞ for silence, — for absence)."""
    return _fmt_measurement(x)


# ---------------------------------------------------------------------------
# Unavailability chips
# ---------------------------------------------------------------------------

# Fixed vocabulary for the "— Unavailable (+reason)" verdict chip. "0.4 s" is
# the pyloudnorm gating block (see rai_analyzer/loudness.py): the shortest
# clip for which integrated loudness is defined at all.
_UNAVAILABILITY_REASONS: dict[str, str] = {
    "silence": "silent file",
    "short": "undefined below 0.4 s",
    "failed": "unavailable for this file",
}


def unavailability_reason(kind: str) -> str:
    """Chip text for an unavailable measurement (kinds: silence/short/failed).

    Unknown kinds raise ``ValueError`` — a typo here would silently ship a
    blank chip, and the vocabulary is fixed by design.
    """
    try:
        return _UNAVAILABILITY_REASONS[kind]
    except KeyError:
        raise ValueError(
            f"unknown unavailability kind {kind!r}; "
            f"expected one of {sorted(_UNAVAILABILITY_REASONS)}"
        ) from None


# ---------------------------------------------------------------------------
# CLI copy target
# ---------------------------------------------------------------------------


def cli_command(path: str) -> str:
    """The copy-pasteable CLI equivalent of the current analysis.

    Emits exactly ``rai-analyze "<path>" --json``. No ``--profile`` flag until
    M4: the M0 CLI does not accept one (rai_analyzer/cli.py), and a copied
    command must never error when pasted — the flag is added here the moment
    the CLI grows it, not before.

    Quoting: the path is double-quoted with embedded double quotes
    backslash-escaped. ``shlex.quote`` is deliberately not used — its
    single-quote style breaks on Windows ``cmd``, and double quotes are the
    one form every target shell accepts.
    """
    escaped = path.replace('"', '\\"')
    return f'rai-analyze "{escaped}" --json'
