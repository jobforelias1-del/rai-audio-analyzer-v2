"""Entry point: ``python -m rai_ui`` — GUI shell, smoke probe, or headless CLI.

Three routes, decided by :func:`classify_argv` (a pure function, unit-tested
in ``tests/ui/test_main_dispatch.py``) BEFORE anything Qt-flavoured is
imported:

* **smoke** — any smoke flag present. RESERVED vocabulary: the frozen probe 2
  launches the .app via ``open -n … --args --smoke --smoke-json …``
  (``build/smoke_frozen.sh``), so smoke flags win over everything else and
  can never be re-routed to the engine CLI.
* **cli** (M5, the turnkey Copy-CLI passthrough) — a positional argument
  (no leading ``-``) present and no smoke flag. The argv is handed verbatim
  to ``rai_analyzer.cli.main``; no QApplication is ever constructed, so the
  frozen bundle binary doubles as the headless engine CLI
  (``…/Contents/MacOS/RAIAudioAnalyzer track.wav --json --profile drill``).
* **gui** — everything else (the normal ``python -m rai_ui`` / double-click
  launch).

Finder's legacy process-serial-number token (``-psn_0_12345``) is stripped
before any decision or hand-off: it starts with ``-`` so it can never read as
a positional, and it must not reach either argparse. (``argv_emulation`` is
off in the spec — Finder file-opens arrive as Apple Events, never argv — so a
double-click can only ever produce flag-less or ``-psn_``-only argv, i.e. the
gui route.)

The smoke harness (``rai_ui.smoke``) is imported only on the smoke route, so
a normal app launch never depends on it; Qt is imported only on the gui
route; ``rai_analyzer.cli`` only on the cli route.
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional

#: The reserved smoke vocabulary (see module docstring). ``--smoke-json``
#: takes a value, so both the split (``--smoke-json PATH``) and the glued
#: (``--smoke-json=PATH``) argparse spellings must be recognised.
_SMOKE_FLAGS = ("--smoke", "--smoke-audio", "--smoke-json")

ROUTE_SMOKE = "smoke"
ROUTE_CLI = "cli"
ROUTE_GUI = "gui"


def _is_finder_token(arg: str) -> bool:
    """True for the legacy Finder/LaunchServices ``-psn_…`` argv token."""
    return arg.startswith("-psn_")


def classify_argv(argv: list) -> str:
    """The pure dispatch decision: ``"smoke"`` | ``"cli"`` | ``"gui"``.

    Order matters and is load-bearing: smoke flags are checked FIRST so the
    path value of ``--smoke-json report.json`` (a positional-looking token)
    can never flip a smoke run onto the cli route.
    """
    args = [a for a in argv if not _is_finder_token(a)]
    for arg in args:
        if arg in _SMOKE_FLAGS or arg.startswith("--smoke-json="):
            return ROUTE_SMOKE
    if any(not a.startswith("-") for a in args):
        return ROUTE_CLI
    return ROUTE_GUI


def _smoke_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rai_ui", description="RAI Audio Analyzer v3 — Qt shell"
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run the offscreen smoke check and exit",
    )
    parser.add_argument(
        "--smoke-json",
        metavar="PATH",
        default=None,
        help="write the smoke report as JSON to PATH (implies smoke mode)",
    )
    parser.add_argument(
        "--smoke-audio",
        action="store_true",
        help="during the smoke run, also play a 0.5 s test tone via the "
        "audio output stack (the frozen audio spike; implies smoke mode)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    route = classify_argv(argv)
    args = [a for a in argv if not _is_finder_token(a)]

    if route == ROUTE_CLI:
        # Headless passthrough: exact argv, no Qt, no QApplication — the
        # engine CLI owns parsing, output and the exit code from here.
        from rai_analyzer.cli import main as cli_main

        return cli_main(args)

    # smoke + gui share the shell's own (smoke-flags-only) parser, so an
    # unknown flag keeps failing loudly with the standard argparse usage
    # error (exit 2) exactly as it did pre-M5.
    parsed = _smoke_parser().parse_args(args)

    if route == ROUTE_SMOKE:
        from rai_ui.smoke import run_smoke

        return run_smoke(parsed)

    from rai_ui.app import create_app
    from rai_ui.main_window import MainWindow

    app = create_app()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
