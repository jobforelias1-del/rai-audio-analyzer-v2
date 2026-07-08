"""Dispatch tests for ``rai_ui.__main__`` (M5 headless CLI passthrough).

Deliberately Qt-free: ``rai_ui.__main__`` imports only argparse/sys at module
level, and the whole point of the cli route is that a QApplication is NEVER
constructed. That property is enforced here by planting booby-trapped
``rai_ui.app`` / ``rai_ui.smoke`` modules in ``sys.modules`` — the lazy
route imports consult sys.modules first, so a wrong route detonates the trap
instead of silently importing PySide6. Runs in both venvs (no importorskip).

The three contracts under test:

* smoke flags are RESERVED — ``build/smoke_frozen.sh`` probe 2 launches the
  frozen .app with ``open -n … --args --smoke --smoke-json PATH`` and must
  keep reaching the smoke harness forever;
* a positional argument routes to ``rai_analyzer.cli.main`` with the exact
  argv (minus Finder ``-psn_…`` tokens) and no Qt;
* flag-less / Finder-token-only argv keeps launching the GUI.
"""

from __future__ import annotations

import sys
import types

import pytest

from rai_ui.__main__ import ROUTE_CLI, ROUTE_GUI, ROUTE_SMOKE, classify_argv, main

# ---------------------------------------------------------------------------
# classify_argv — the pure decision
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--smoke"],
        ["--smoke-audio"],
        ["--smoke-json", "/tmp/r.json"],
        ["--smoke-json=/tmp/r.json"],
        # Probe argv shapes verbatim (build/smoke_frozen.sh):
        ["--smoke", "--smoke-json", "/tmp/rai_smoke1.json", "--smoke-audio"],
        ["--smoke", "--smoke-json", "/tmp/rai_smoke2.json"],
        # Reserved even when a positional rides along — smoke wins.
        ["/t.wav", "--smoke"],
        ["--smoke", "/t.wav"],
        ["-psn_0_123", "--smoke"],
    ],
)
def test_smoke_flags_are_reserved(argv):
    assert classify_argv(argv) == ROUTE_SMOKE


@pytest.mark.parametrize(
    "argv",
    [
        ["/a/track.wav"],
        ["track.wav"],
        ["--json", "/a.wav"],
        ["/a.wav", "--json", "--profile", "drill"],
        ["/a.wav", "--no-loudness"],
        ["-psn_0_123", "/a.wav"],  # Finder token can't mask a real positional
    ],
)
def test_positional_routes_to_cli(argv):
    assert classify_argv(argv) == ROUTE_CLI


@pytest.mark.parametrize(
    "argv",
    [
        [],  # the normal launch
        ["-psn_0_12345"],  # legacy Finder token only — still a GUI launch
        ["--some-unknown-flag"],  # flags-only: gui route (argparse then errors)
    ],
)
def test_flags_only_routes_to_gui(argv):
    assert classify_argv(argv) == ROUTE_GUI


def test_smoke_json_value_is_not_mistaken_for_a_positional():
    # "--smoke-json report.json": the PATH value has no leading dash, but the
    # smoke check runs first — the ordering is load-bearing.
    assert classify_argv(["--smoke-json", "report.json"]) == ROUTE_SMOKE


# ---------------------------------------------------------------------------
# main() — route integration (traps instead of real imports)
# ---------------------------------------------------------------------------


def _trap_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)

    def _boom(*a, **k):  # pragma: no cover - only fires on a routing bug
        raise AssertionError(f"{name} entered on the wrong route")

    mod.__getattr__ = lambda attr: _boom  # any lookup detonates
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture
def qt_trap(monkeypatch):
    """Fail loudly if the cli/smoke route ever reaches the Qt shell."""
    monkeypatch.setitem(sys.modules, "rai_ui.app", _trap_module("rai_ui.app"))
    monkeypatch.setitem(
        sys.modules, "rai_ui.main_window", _trap_module("rai_ui.main_window")
    )


def test_cli_route_calls_cli_main_with_exact_argv(monkeypatch, qt_trap):
    import rai_analyzer.cli as cli_mod

    seen: list[list[str]] = []

    def fake_cli_main(argv):
        seen.append(list(argv))
        return 42

    monkeypatch.setattr(cli_mod, "main", fake_cli_main)
    assert main(["/tmp/x.wav", "--json"]) == 42
    assert seen == [["/tmp/x.wav", "--json"]]


def test_cli_route_filters_finder_token(monkeypatch, qt_trap):
    import rai_analyzer.cli as cli_mod

    seen: list[list[str]] = []
    monkeypatch.setattr(cli_mod, "main", lambda argv: seen.append(list(argv)) or 0)
    assert main(["-psn_0_1", "/tmp/x.wav"]) == 0
    assert seen == [["/tmp/x.wav"]]


def test_smoke_route_reaches_run_smoke(monkeypatch, qt_trap):
    seen: dict = {}

    def fake_run_smoke(args):
        seen["smoke"] = args.smoke
        seen["json"] = args.smoke_json
        seen["audio"] = args.smoke_audio
        return 0

    monkeypatch.setitem(
        sys.modules, "rai_ui.smoke", _trap_module("rai_ui.smoke", run_smoke=fake_run_smoke)
    )
    assert main(["--smoke", "--smoke-json", "/tmp/r.json"]) == 0
    assert seen == {"smoke": True, "json": "/tmp/r.json", "audio": False}


def test_smoke_with_stray_positional_fails_loudly_not_into_cli(monkeypatch, qt_trap):
    """Mixing a positional with a reserved smoke flag is a usage error (exit
    2), NEVER a silent hand-off to the engine CLI — probe 2's vocabulary
    stays unshadowable."""
    import rai_analyzer.cli as cli_mod

    def never(argv):  # pragma: no cover - only fires on a routing bug
        raise AssertionError("engine CLI entered with a smoke flag present")

    monkeypatch.setattr(cli_mod, "main", never)
    with pytest.raises(SystemExit) as exc:
        main(["/t.wav", "--smoke"])
    assert exc.value.code == 2


def test_gui_route_constructs_the_shell(monkeypatch):
    calls: list[str] = []

    class FakeApp:
        def exec(self):
            calls.append("exec")
            return 0

    class FakeWindow:
        def show(self):
            calls.append("show")

    app_mod = types.ModuleType("rai_ui.app")
    app_mod.create_app = lambda: (calls.append("create"), FakeApp())[1]
    mw_mod = types.ModuleType("rai_ui.main_window")
    mw_mod.MainWindow = FakeWindow
    monkeypatch.setitem(sys.modules, "rai_ui.app", app_mod)
    monkeypatch.setitem(sys.modules, "rai_ui.main_window", mw_mod)

    assert main([]) == 0
    assert calls == ["create", "show", "exec"]


def test_gui_route_swallows_finder_token(monkeypatch):
    # -psn_… must be stripped before the shell parser sees it, or every
    # legacy Finder launch dies with an argparse usage error.
    calls: list[str] = []

    class FakeApp:
        def exec(self):
            return 0

    app_mod = types.ModuleType("rai_ui.app")
    app_mod.create_app = lambda: (calls.append("create"), FakeApp())[1]
    mw_mod = types.ModuleType("rai_ui.main_window")
    mw_mod.MainWindow = lambda: types.SimpleNamespace(show=lambda: None)
    monkeypatch.setitem(sys.modules, "rai_ui.app", app_mod)
    monkeypatch.setitem(sys.modules, "rai_ui.main_window", mw_mod)

    assert main(["-psn_0_98765"]) == 0
    assert calls == ["create"]
