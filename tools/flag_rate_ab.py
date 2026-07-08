"""Flag-rate A/B: packaged fingerprint vs a user profile, over a fixed corpus.

The Phase 3 risk register's outstanding item ("Relearn shifts flag rates" →
*before/after flag-rate log on a fixed corpus*, docs/PHASE3_PLAN.md §5). Every
WAV in the corpus is analyzed twice by the same engine:

* **packaged** — a fresh ``TempoConfig()``: the packaged drill fingerprint,
  exactly what the CLI and the validation gate run;
* **profiled** — a fresh ``TempoConfig`` whose ``FingerprintParams.
  fingerprint_path`` points at a **temp copy** of the given profile JSON —
  the same injection recipe as the GUI worker
  (``rai_ui/services/worker.py::_analysis_config``).

HARD RULES honored:

* The given profile file is opened READ-ONLY, once, to copy its bytes to a
  private temp path (``shutil.copyfile``); the engine only ever reads the
  copy. Nothing under the real App Support store is written or opened for
  write by this tool.
* ``clear_fingerprint_cache()`` brackets the run: the engine's fingerprint
  load cache is path-keyed and content-blind, so the bracket guarantees no
  in-process cache state leaks into or out of the A/B.

Loudness is skipped (``with_loudness=False``): the ambiguity flag is a tempo
property, and skipping the BS.1770 chain roughly halves the wall time.

Usage (from the repo root, either venv)::

    python tools/flag_rate_ab.py CORPUS [CORPUS ...]
        [--profile-json PATH]   # default: the app's live user profile
        [--json]                # machine-readable instead of markdown

``CORPUS`` entries are WAV files and/or directories (directories are scanned
non-recursively for ``*.wav``). Output is a markdown table (file · packaged
verdict+bpm · profiled verdict+bpm · flipped?) plus summary flag rates, or
the same report as JSON with ``--json``. Exit code: 0 on success, 2 on a
usable-input problem (no WAVs, missing profile).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from typing import Optional

# Repo root on sys.path so `python tools/flag_rate_ab.py` works from anywhere.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

AMBIGUOUS = "AMBIGUOUS"
CONFIDENT = "confident"


def default_profile_path() -> str:
    """The app's live user profile (read-only use; copied before injection).

    Resolved through the store's injectable ``_store_dir`` factory so tests
    can redirect it exactly like every other store consumer (R-M3-2).
    """
    from rai_ui.services import ground_truth_store  # stdlib-only module

    return ground_truth_store.user_profile_path()


def collect_wavs(entries: list[str]) -> list[str]:
    """Expand files/dirs into a sorted, de-duplicated list of .wav paths."""
    out: list[str] = []
    for entry in entries:
        if os.path.isdir(entry):
            for name in sorted(os.listdir(entry)):
                if name.lower().endswith(".wav"):
                    out.append(os.path.join(entry, name))
        elif entry.lower().endswith(".wav"):
            out.append(entry)
        else:
            print(f"flag_rate_ab: skipping non-WAV argument {entry!r}", file=sys.stderr)
    seen: set[str] = set()
    unique = []
    for path in out:
        key = os.path.abspath(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _verdict(ambiguous: bool) -> str:
    return AMBIGUOUS if ambiguous else CONFIDENT


def run_ab(paths: list[str], profile_json: str) -> dict:
    """Analyze every path twice (packaged vs temp-copied profile) and report.

    Returns a plain-dict report (JSON-serializable): per-file rows plus
    summary flag rates. Per-file analysis failures are recorded on the row
    (``error``) and excluded from the rates — one unreadable file must not
    sink a corpus run.
    """
    from rai_analyzer.analyzer import analyze_file
    from rai_analyzer.config import FingerprintParams, TempoConfig
    from rai_analyzer.evidence.fingerprint import clear_fingerprint_cache

    if not os.path.isfile(profile_json):
        raise FileNotFoundError(f"profile JSON not found: {profile_json}")

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="rai-flagrate-") as tmp_dir:
        # THE hard rule: the engine only ever sees this private copy; the
        # original profile is opened read-only exactly once, right here.
        profile_copy = os.path.join(tmp_dir, "profile-under-test.json")
        shutil.copyfile(profile_json, profile_copy)

        clear_fingerprint_cache()
        try:
            for path in paths:
                row: dict = {"name": os.path.basename(path), "path": os.path.abspath(path)}
                try:
                    packaged = analyze_file(path, cfg=TempoConfig(), with_loudness=False)
                    profiled = analyze_file(
                        path,
                        cfg=TempoConfig(
                            fingerprint=FingerprintParams(fingerprint_path=profile_copy)
                        ),
                        with_loudness=False,
                    )
                except Exception as exc:  # per-file casualty: report, move on
                    row["error"] = f"{type(exc).__name__}: {exc}"
                else:
                    row.update(
                        packaged_ambiguous=bool(packaged.tempo.ambiguous),
                        packaged_bpm=float(packaged.tempo.primary_bpm),
                        profiled_ambiguous=bool(profiled.tempo.ambiguous),
                        profiled_bpm=float(profiled.tempo.primary_bpm),
                        flipped=bool(packaged.tempo.ambiguous)
                        != bool(profiled.tempo.ambiguous),
                    )
                rows.append(row)
        finally:
            # The other bracket end: never leave the temp-copy (a dead path
            # once the TemporaryDirectory exits) in the engine's cache.
            clear_fingerprint_cache()

    analyzed = [r for r in rows if "error" not in r]
    packaged_flags = sum(1 for r in analyzed if r["packaged_ambiguous"])
    profiled_flags = sum(1 for r in analyzed if r["profiled_ambiguous"])
    flips = sum(1 for r in analyzed if r["flipped"])
    return {
        "profile_json": os.path.abspath(profile_json),
        "rows": rows,
        "summary": {
            "files": len(rows),
            "analyzed": len(analyzed),
            "errors": len(rows) - len(analyzed),
            "packaged_flagged": packaged_flags,
            "profiled_flagged": profiled_flags,
            "flips": flips,
        },
    }


def _rate(count: int, total: int) -> str:
    return f"{count}/{total}" + (f" ({100.0 * count / total:.1f} %)" if total else "")


def render_markdown(report: dict) -> str:
    lines = [
        "# Flag-rate A/B — packaged fingerprint vs user profile",
        "",
        f"- profile: `{report['profile_json']}` (injected via temp copy)",
        f"- corpus: {report['summary']['files']} file(s)",
        "",
        "| File | Packaged | Profiled | Flipped |",
        "|---|---|---|---|",
    ]
    for row in report["rows"]:
        if "error" in row:
            lines.append(f"| {row['name']} | ERROR: {row['error']} | — | — |")
            continue
        packaged = f"{_verdict(row['packaged_ambiguous'])} · {row['packaged_bpm']:.2f}"
        profiled = f"{_verdict(row['profiled_ambiguous'])} · {row['profiled_bpm']:.2f}"
        flipped = "YES" if row["flipped"] else "no"
        lines.append(f"| {row['name']} | {packaged} | {profiled} | {flipped} |")
    s = report["summary"]
    lines += [
        "",
        "**Flag rate:** packaged "
        f"{_rate(s['packaged_flagged'], s['analyzed'])} → profiled "
        f"{_rate(s['profiled_flagged'], s['analyzed'])} · {s['flips']} flip(s)"
        + (f" · {s['errors']} error(s)" if s["errors"] else ""),
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="flag_rate_ab",
        description="Flag-rate A/B: packaged fingerprint vs a user profile "
        "over a fixed corpus (see module docstring).",
    )
    parser.add_argument(
        "corpus",
        nargs="+",
        help="WAV files and/or directories (scanned non-recursively for *.wav)",
    )
    parser.add_argument(
        "--profile-json",
        default=None,
        metavar="PATH",
        help="profile JSON to A/B against (default: the app's live user "
        "profile under App Support; ALWAYS copied to a temp path before "
        "the engine reads it)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit the report as JSON instead of markdown",
    )
    args = parser.parse_args(argv)

    profile_json = args.profile_json or default_profile_path()
    paths = collect_wavs(args.corpus)
    if not paths:
        print("flag_rate_ab: no .wav files found in the given corpus", file=sys.stderr)
        return 2
    try:
        report = run_ab(paths, profile_json)
    except FileNotFoundError as exc:
        print(f"flag_rate_ab: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
