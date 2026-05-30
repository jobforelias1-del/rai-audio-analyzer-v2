"""``python3 -m validation`` — run the acceptance gate and set the exit code.

Exit 0 iff the gate passes (or, when no real fixtures are present, iff the
synthetic self-test passes); exit 1 otherwise. This is what a CI job or a
pre-release check shells out to: the process exit code *is* the gate verdict.
"""

from __future__ import annotations

import sys

from .harness import run_gate


def main() -> int:
    passed = run_gate()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
