"""Command-line entry point: analyze a file and print the report or JSON.

    python -m rai_analyzer.cli path/to/track.wav
    python -m rai_analyzer.cli path/to/track.wav --json
"""

from __future__ import annotations

import argparse
import json
import sys

from .analyzer import analyze_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rai-analyze", description="RAI Audio Analyzer v2")
    parser.add_argument("path", help="audio file to analyze (WAV recommended)")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of the text report")
    parser.add_argument("--no-loudness", action="store_true", help="skip loudness measurement")
    args = parser.parse_args(argv)

    try:
        result = analyze_file(args.path, with_loudness=not args.no_loudness)
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.to_report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
