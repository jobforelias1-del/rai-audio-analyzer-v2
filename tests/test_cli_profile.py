"""CLI ``--profile`` byte-identity + registry contract (M4, ruling R-M4-9).

The plan's requirement: adding ``--profile`` must leave the default CLI
output byte-identical — no flag, ``--profile drill``, and the pre-M4
behavior (``analyze_file`` with its default config) all produce the same
bytes, in both text and ``--json`` modes. Engine-venv collectable (no Qt).
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from rai_analyzer.config import DEFAULT_CONFIG, TempoConfig
from rai_analyzer.profiles import DEFAULT_PROFILE, PROFILES


@pytest.fixture(scope="module")
def wav(tmp_path_factory):
    from rai_analyzer.synthetic import click_track, write_wav

    path = tmp_path_factory.mktemp("cliwav") / "clicks.wav"
    return write_wav(str(path), click_track(150.0, duration=4.0))


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    code = "from rai_analyzer.cli import main; import sys; sys.exit(main(sys.argv[1:]))"
    return subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True,
        timeout=180,
    )


# ---------------------------------------------------------------------------
# Byte identity: no flag ≡ --profile drill, text and JSON
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [[], ["--json"]])
def test_no_flag_byte_equals_profile_drill(wav, mode):
    plain = _run_cli([wav, *mode])
    flagged = _run_cli([wav, *mode, "--profile", "drill"])
    assert plain.returncode == 0 and flagged.returncode == 0, (
        plain.stderr,
        flagged.stderr,
    )
    assert plain.stdout == flagged.stdout  # bytes, not str — the whole point
    assert plain.stderr == flagged.stderr == b""


# ---------------------------------------------------------------------------
# Pre-M4 identity: the drill factory IS the old default config
# ---------------------------------------------------------------------------


def test_drill_factory_result_equals_pre_m4_default(wav):
    """Old CLI: ``analyze_file(path)`` (DEFAULT_CONFIG). New: ``cfg=PROFILES
    ['drill']()``. Identical report and dict bytes ⇒ the M4 diff cannot have
    changed any user-visible output."""
    import json

    from rai_analyzer import analyze_file

    old = analyze_file(wav, cfg=DEFAULT_CONFIG)
    new = analyze_file(wav, cfg=PROFILES["drill"]())
    assert new.to_report() == old.to_report()
    assert json.dumps(new.to_dict(), sort_keys=True) == json.dumps(
        old.to_dict(), sort_keys=True
    )


# ---------------------------------------------------------------------------
# Flag surface + registry contract
# ---------------------------------------------------------------------------


def test_unknown_profile_is_an_argparse_error(wav):
    proc = _run_cli([wav, "--profile", "polka"])
    assert proc.returncode == 2  # argparse usage error, never a traceback
    assert b"invalid choice" in proc.stderr


def test_registry_is_packaged_only_and_fresh_per_call():
    assert set(PROFILES) == {"drill"}  # grows deliberately, never implicitly
    assert DEFAULT_PROFILE == "drill"
    a, b = PROFILES["drill"](), PROFILES["drill"]()
    assert isinstance(a, TempoConfig)
    assert a is not b  # factory, not shared instance (mutation safety)


def test_profile_help_names_the_default(wav):
    proc = _run_cli(["--help"])
    assert proc.returncode == 0
    assert b"--profile" in proc.stdout and b"drill" in proc.stdout
