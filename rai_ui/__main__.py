"""Entry point: ``python -m rai_ui`` runs the shell; smoke flags route to CI.

The smoke harness (``rai_ui.smoke``, built in parallel) is imported only when
a smoke flag is present, so a normal app launch never depends on it and the
module stays importable while the harness lands.
"""

from __future__ import annotations

import argparse
from typing import Optional


def main(argv: Optional[list] = None) -> int:
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
    args = parser.parse_args(argv)

    if args.smoke or args.smoke_json or args.smoke_audio:
        from rai_ui.smoke import run_smoke

        return run_smoke(args)

    from rai_ui.app import create_app
    from rai_ui.main_window import MainWindow

    app = create_app()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
