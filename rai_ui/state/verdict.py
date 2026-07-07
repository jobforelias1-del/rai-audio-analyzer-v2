"""Pure verdict reducer — the single source of truth for what the UI is saying.

The v3 UI vocabulary is fixed (design doctrine): *Confident* / *Ambiguous —
human tiebreak* / *Confirmed · human* / *Working* / *— Unavailable (+reason)*.
Every widget that shows a verdict must derive it from one place, or the app
can drift into showing "Confident" in the header while the candidate table
still says "Ambiguous". This module is that one place: a plain-Python
(state, event) -> state reducer with no Qt anywhere, so the entire verdict
lifecycle is unit-testable headless and collectable by the engine CI job.

The Qt session object (``rai_ui.state.session``) owns threads and signals; it
feeds events into ``reduce`` and broadcasts the resulting ``VerdictState``.
The reducer itself never does I/O and never mutates — it returns new frozen
instances, which is what makes Undo trivial and races impossible to encode.

Transition table (rows = current ``kind``; ``·`` = event ignored, state
returned unchanged)::

                     OpenFile   AnalysisOk*   AnalysisFailed   Confirm      Undo
    NO_FILE          WORKING    ·             ·                ·            ·
    WORKING          WORKING    see below     ERROR            ·            ·
    CONFIDENT        WORKING    ·             ·                CONFIRMED    ·
    AMBIGUOUS        WORKING    ·             ·                CONFIRMED    ·
    CONFIRMED_HUMAN  WORKING    ·             ·                CONFIRMED**  prev_kind
    NO_TEMPO         WORKING    ·             ·                ·            ·
    ERROR            WORKING    ·             ·                ·            ·

``*``  ``AnalysisOk`` resolves, in order: ``has_tempo=False`` -> NO_TEMPO
(nothing to be ambiguous about); ``confirmed_bpm`` set (a re-opened file that
already carries a human confirmation) -> CONFIRMED_HUMAN with ``prev_kind``
set from ``ambiguous``; ``ambiguous=True`` -> AMBIGUOUS; else CONFIDENT.

``**`` Re-confirming replaces ``confirmed_bpm`` but keeps the original
``prev_kind`` — Undo always returns to the engine's *pre-confirmation*
verdict, never to an intermediate human number.

Completion events (``AnalysisOk`` / ``AnalysisFailed``) are only honoured in
WORKING. That is the stale-completion guard: analysis runs on a worker thread,
so a result for file A can land after the user has already opened file B; the
reducer cannot tell requests apart, so any completion arriving outside WORKING
is dropped rather than allowed to overwrite a newer verdict.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Union


class VerdictKind(str, Enum):
    """The seven verdict states the UI can be in (see module docstring)."""

    NO_FILE = "no_file"
    WORKING = "working"
    CONFIDENT = "confident"
    AMBIGUOUS = "ambiguous"
    CONFIRMED_HUMAN = "confirmed_human"
    NO_TEMPO = "no_tempo"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenFile:
    """User opened (or dropped) a file; analysis is starting."""

    path: str


@dataclass(frozen=True)
class AnalysisOk:
    """Worker finished successfully.

    ``confirmed_bpm`` is set when the opened file already carries a human
    confirmation (e.g. a persisted session being restored), so the UI lands
    directly on *Confirmed · human* without replaying the click.
    """

    ambiguous: bool
    has_tempo: bool = True
    confirmed_bpm: Optional[float] = None


@dataclass(frozen=True)
class AnalysisFailed:
    """Worker raised; ``msg`` is the human-readable reason."""

    msg: str


@dataclass(frozen=True)
class Confirm:
    """Human picked a tempo — the tiebreak the engine asked for."""

    bpm: float


@dataclass(frozen=True)
class Undo:
    """Take back the last confirmation; restore the engine's verdict."""


Event = Union[OpenFile, AnalysisOk, AnalysisFailed, Confirm, Undo]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VerdictState:
    """Immutable verdict snapshot.

    ``prev_kind`` is only populated while ``kind`` is CONFIRMED_HUMAN: it
    remembers which engine verdict (CONFIDENT or AMBIGUOUS) the confirmation
    overrode, which is all Undo needs.
    """

    kind: VerdictKind
    path: Optional[str] = None
    confirmed_bpm: Optional[float] = None
    error_msg: Optional[str] = None
    prev_kind: Optional[VerdictKind] = None


INITIAL = VerdictState(kind=VerdictKind.NO_FILE)


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


def reduce(state: VerdictState, event: Event) -> VerdictState:
    """Apply ``event`` to ``state`` and return the next state.

    Pure: never mutates ``state``, never touches the outside world. Ignored
    (state, event) pairs return ``state`` itself unchanged. An object that is
    not one of the five event types raises ``TypeError`` — a typo'd event
    silently dropped would be a debugging tarpit.
    """
    if isinstance(event, OpenFile):
        # A new file always restarts the lifecycle, whatever was on screen.
        return VerdictState(kind=VerdictKind.WORKING, path=event.path)

    if isinstance(event, AnalysisOk):
        if state.kind is not VerdictKind.WORKING:
            return state  # stale-completion guard (see module docstring)
        if not event.has_tempo:
            return replace(state, kind=VerdictKind.NO_TEMPO)
        if event.confirmed_bpm is not None:
            return replace(
                state,
                kind=VerdictKind.CONFIRMED_HUMAN,
                confirmed_bpm=event.confirmed_bpm,
                prev_kind=(
                    VerdictKind.AMBIGUOUS if event.ambiguous else VerdictKind.CONFIDENT
                ),
            )
        if event.ambiguous:
            return replace(state, kind=VerdictKind.AMBIGUOUS)
        return replace(state, kind=VerdictKind.CONFIDENT)

    if isinstance(event, AnalysisFailed):
        if state.kind is not VerdictKind.WORKING:
            return state  # stale-completion guard
        return replace(state, kind=VerdictKind.ERROR, error_msg=event.msg)

    if isinstance(event, Confirm):
        if state.kind in (VerdictKind.CONFIDENT, VerdictKind.AMBIGUOUS):
            return replace(
                state,
                kind=VerdictKind.CONFIRMED_HUMAN,
                confirmed_bpm=event.bpm,
                prev_kind=state.kind,
            )
        if state.kind is VerdictKind.CONFIRMED_HUMAN:
            # Re-confirm: new number, same provenance (Undo still returns to
            # the engine's original verdict, not the earlier human pick).
            return replace(state, confirmed_bpm=event.bpm)
        return state  # nothing on screen to confirm

    if isinstance(event, Undo):
        if state.kind is not VerdictKind.CONFIRMED_HUMAN:
            return state
        # prev_kind is always set by the reducer's own paths into
        # CONFIRMED_HUMAN; if a hand-built state lacks it, fall back to
        # AMBIGUOUS — undoing a confirmation of unknown provenance must not
        # fabricate engine confidence.
        restored = state.prev_kind if state.prev_kind is not None else VerdictKind.AMBIGUOUS
        return replace(state, kind=restored, confirmed_bpm=None, prev_kind=None)

    raise TypeError(f"not a verdict event: {event!r}")
