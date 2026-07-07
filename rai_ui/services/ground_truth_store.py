"""Ground-truth journal — the M3 persistence layer (rulings R-M3-1/2/19).

An append-only JSONL journal of human tempo confirmations, keyed by whole-file
md5 (the exact recipe the acceptance gate pins use — any byte change re-keys).
The journal lives at::

    ~/Library/Application Support/RAI Audio Analyzer/ground_truth.jsonl

constructed explicitly (the plan's org-less path — NOT QStandardPaths, which
would org-qualify it to ``SiliconClick/...``). The relearned user fingerprint
shares the directory at ``fingerprints/drill.user.json``.

Record shapes (R-M3-1)::

    {"v": 1, "kind": "confirm", "id": <uuid4>, "md5": ..., "bpm": ...,
     "name": <basename>, "path": <abspath>, "at": <iso-utc>}
    {"v": 1, "kind": "retract", "id": <uuid4>, "retracts_md5": ..., "at": ...}

``path`` is additive over the R-M3-1 schema: relearn (R-M3-11) must re-open
the confirmed files from disk and re-verify their md5s, which is impossible
from a basename alone. Readers must tolerate records without it.

Effective truth = replay the journal in order, last record per md5 wins; a
retraction clears that md5. Corrupt or unrecognised lines are skipped with a
logged warning, never fatal (R-M3-1) — a half-written trailing line after a
crash must not take the whole journal down.

The store directory is injectable via the module-level ``_store_dir`` factory,
exactly like ``recent_files._settings`` (R-M3-2): tests, the smoke probe, and
the preview-shot harness monkeypatch it to a temp dir so they NEVER touch the
user's real journal. Everything else in this module resolves paths through
that factory at call time.

Pure stdlib (json/os/hashlib/uuid/datetime/logging) — importable Qt-less; the
engine is imported lazily and read-only (fingerprint geometry constants for
profile validation).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

RECORD_VERSION = 1
JOURNAL_FILENAME = "ground_truth.jsonl"
PROFILE_SUBDIR = "fingerprints"
PROFILE_FILENAME = "drill.user.json"
PROFILE_BACKUP_FILENAME = "drill.user.backup.json"


def _store_dir() -> str:
    """The per-user App Support directory (R-M3-1 path, org-less).

    Module-level factory ON PURPOSE (R-M3-2): tests/smoke/shots monkeypatch
    this single symbol to a temp dir. Never cache its result.
    """
    return os.path.expanduser(
        os.path.join("~", "Library", "Application Support", "RAI Audio Analyzer")
    )


def journal_path() -> str:
    return os.path.join(_store_dir(), JOURNAL_FILENAME)


def user_profile_path() -> str:
    """Where relearn writes (and the worker looks for) the user fingerprint."""
    return os.path.join(_store_dir(), PROFILE_SUBDIR, PROFILE_FILENAME)


def user_profile_backup_path() -> str:
    """One-step-revert backup written before relearn overwrites a profile."""
    return os.path.join(_store_dir(), PROFILE_SUBDIR, PROFILE_BACKUP_FILENAME)


# ---------------------------------------------------------------------------
# md5 identity
# ---------------------------------------------------------------------------


def file_md5(path: str) -> str:
    """Whole-file md5, streamed in 1 MiB chunks.

    Deliberately the same recipe as ``validation.ground_truth`` (which must
    NEVER be imported from ``rai_ui`` — R-M3-19): the hash is of the exact
    file bytes, so the store keys identically to the gate pins.
    """
    digest = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Journal records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfirmedTruth:
    """One effective (not-retracted) human confirmation."""

    md5: str
    bpm: float
    name: str  # basename at confirm time
    path: str  # absolute path at confirm time ("" in legacy records)
    at: str  # ISO-8601 UTC timestamp
    id: str  # uuid4 of the confirm record


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _append(record: dict) -> dict:
    """Append one JSON line to the journal, fsynced (ground truth is
    crash-safe by construction — the append either lands whole or is a
    corrupt trailing line the replay skips).

    Torn-line healing: a crash mid-append can leave the file WITHOUT a
    trailing newline. Gluing the next record onto that fragment would merge
    both into one unparseable line — replay would then skip the NEW record
    too (e.g. a retraction, silently resurrecting an undone confirmation).
    So if the file's last byte isn't ``b"\\n"``, a healing newline is written
    first: the fragment stays one skippable corrupt line and the new record
    lands whole on its own line. ``a+b`` mode reads the last byte while every
    write still lands at end-of-file regardless of seek position.
    """
    path = journal_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(path, "a+b") as fh:
        fh.seek(0, os.SEEK_END)
        if fh.tell() > 0:
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")  # heal the torn trailing line
        fh.write(line.encode("utf-8") + b"\n")
        fh.flush()
        os.fsync(fh.fileno())
    return record


def append_confirm(md5: str, bpm: float, name: str, path: str = "") -> dict:
    """Journal a human confirmation of ``bpm`` for the file hashed ``md5``."""
    return _append(
        {
            "v": RECORD_VERSION,
            "kind": "confirm",
            "id": str(uuid.uuid4()),
            "md5": str(md5),
            "bpm": float(bpm),
            "name": str(name),
            "path": str(path),
            "at": _now_iso(),
        }
    )


def append_retract(md5: str) -> dict:
    """Journal a retraction — undo that works across sessions (R-M3-1)."""
    return _append(
        {
            "v": RECORD_VERSION,
            "kind": "retract",
            "id": str(uuid.uuid4()),
            "retracts_md5": str(md5),
            "at": _now_iso(),
        }
    )


# ---------------------------------------------------------------------------
# Replay / effective truth
# ---------------------------------------------------------------------------


def _truth_from_record(rec: dict) -> ConfirmedTruth:
    bpm = float(rec["bpm"])
    if not (math.isfinite(bpm) and bpm > 0):
        raise ValueError(f"confirm record with unusable bpm: {bpm!r}")
    return ConfirmedTruth(
        md5=str(rec["md5"]),
        bpm=bpm,
        name=str(rec.get("name", "")),
        path=str(rec.get("path", "")),
        at=str(rec.get("at", "")),
        id=str(rec.get("id", "")),
    )


def effective_truths() -> dict[str, ConfirmedTruth]:
    """Replay the journal: last record per md5 wins, retractions clear.

    Corrupt/unrecognised lines are skipped with a warning, never fatal.
    The file is read in BINARY and each line is decoded INSIDE the per-line
    guard: a crash-torn append can shear a multibyte character (accented
    basenames are journaled ``ensure_ascii=False``), and the resulting
    ``UnicodeDecodeError`` must degrade to a skipped line exactly like torn
    JSON does — never propagate into ``session.finish``. The outer guard is
    ``Exception``-wide for the same reason: replay must NEVER raise.
    Returns an md5-keyed dict (first-confirmation journal order preserved for
    md5s that were never cleared, per plain-dict semantics).
    """
    path = journal_path()
    truths: dict[str, ConfirmedTruth] = {}
    if not os.path.exists(path):
        return truths
    try:
        with open(path, "rb") as fh:
            for lineno, raw in enumerate(fh, 1):
                try:
                    line = raw.decode("utf-8").strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    kind = rec["kind"]
                    if kind == "confirm":
                        truth = _truth_from_record(rec)
                        truths[truth.md5] = truth
                    elif kind == "retract":
                        truths.pop(str(rec["retracts_md5"]), None)
                    else:
                        raise ValueError(f"unknown record kind: {kind!r}")
                except Exception as exc:
                    log.warning(
                        "ground_truth.jsonl:%d skipped (%s: %s)",
                        lineno,
                        type(exc).__name__,
                        exc,
                    )
    except Exception as exc:
        # An unreadable journal degrades to "no stored truth", never a crash.
        log.warning("ground truth journal unreadable (%s) — treating as empty", exc)
        return {}
    return truths


def lookup(md5: str) -> Optional[ConfirmedTruth]:
    """The effective confirmation for ``md5``, or None (never confirmed, or
    retracted)."""
    if not md5:
        return None
    return effective_truths().get(str(md5))


def confirmed_count() -> int:
    """How many files currently carry an effective confirmation (the R-M3-11
    relearn gate reads this: button enabled at >= 3)."""
    return len(effective_truths())


# ---------------------------------------------------------------------------
# User-profile validation (R-M3-12)
# ---------------------------------------------------------------------------


def validate_profile_file(path: str) -> bool:
    """True iff ``path`` is a structurally sound fingerprint JSON.

    Shape (the ``save_fingerprint`` format): a JSON object whose non-``_``
    keys are band profiles — every band the engine scores against
    (``DEFAULT_CONFIG.fingerprint.bands``) must be present as a list of
    ``bins_per_bar`` finite, non-negative numbers, and at least one bin must
    be positive (an all-zero profile scores nothing and is treated as
    unreadable). ``_``-prefixed metadata keys are ignored.

    Never raises: any parse/shape problem returns False — the worker then
    falls back to the packaged fingerprint (with a toast, R-M3-12).
    """
    try:
        # Read-only engine constants (the tempo_view lazy-import precedent).
        from rai_analyzer.config import DEFAULT_CONFIG

        params = DEFAULT_CONFIG.fingerprint
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            return False
        any_energy = False
        for band in params.bands:
            profile = raw.get(band)
            if not isinstance(profile, list) or len(profile) != params.bins_per_bar:
                return False
            for x in profile:
                if isinstance(x, bool) or not isinstance(x, (int, float)):
                    return False
                if not math.isfinite(float(x)) or float(x) < 0.0:
                    return False
            if any(float(x) > 0.0 for x in profile):
                any_energy = True
        return any_energy
    except Exception as exc:
        log.warning("user profile %s failed validation (%s)", path, exc)
        return False
