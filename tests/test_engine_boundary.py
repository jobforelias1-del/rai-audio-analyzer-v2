"""Engine-boundary AST test — ruling R-M2-17.

Walks EVERY module under ``rai_analyzer/`` (including ``metrics/`` and
``beatgrid``) and asserts, from the source alone (no imports executed, so the
Qt-less engine venv collects and runs this), that the engine never imports the
UI layer or any Qt binding. Also pins the M2 hard rule that the metrics
package stays decoupled from the tempo machinery (no resolver / tempogram /
onsets / evidence / candidates imports into ``rai_analyzer.metrics``).
"""

from __future__ import annotations

import ast
import os

import pytest

_ENGINE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "rai_analyzer")
)

#: No engine module may import any of these (top-level name match).
_FORBIDDEN_EVERYWHERE = {
    "rai_ui",
    "PySide6",
    "PyQt5",
    "PyQt6",
    "pyqtgraph",
    "shiboken6",
    "qtpy",
}

#: The metrics package must additionally never pull the tempo machinery or
#: the mono analysis view's producers (M2 hard rule).
_FORBIDDEN_IN_METRICS = {
    "rai_analyzer.resolver",
    "rai_analyzer.tempogram",
    "rai_analyzer.onsets",
    "rai_analyzer.evidence",
    "rai_analyzer.candidates",
    "rai_analyzer.analyzer",
    "rai_analyzer.cli",
    "rai_analyzer.config",
}


def _engine_py_files() -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(_ENGINE_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def _module_package(path: str) -> str:
    """Dotted package containing ``path`` (for resolving relative imports).

    For both ``pkg/module.py`` and ``pkg/__init__.py`` the package that
    relative imports resolve against is ``pkg`` — i.e. everything but the
    final path component.
    """
    rel = os.path.relpath(path, os.path.dirname(_ENGINE_ROOT))
    parts = rel.split(os.sep)
    return ".".join(parts[:-1])


def _imported_modules(path: str) -> set[str]:
    """Absolute dotted names imported by ``path`` (relative imports resolved)."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=path)
    package = _module_package(path)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.add(node.module)
            else:
                base = package.split(".")
                # level=1 -> current package, each extra level climbs one.
                base = base[: len(base) - (node.level - 1)]
                prefix = ".".join(base)
                found.add(f"{prefix}.{node.module}" if node.module else prefix)
    return found


def _violates(imported: str, forbidden: set[str]) -> bool:
    return any(imported == f or imported.startswith(f + ".") for f in forbidden)


_ALL_FILES = _engine_py_files()


def test_engine_tree_was_found():
    assert any(p.endswith("io_audio.py") for p in _ALL_FILES)
    assert any(os.sep + "metrics" + os.sep in p for p in _ALL_FILES)
    assert any(p.endswith("beatgrid.py") for p in _ALL_FILES)


@pytest.mark.parametrize(
    "path", _ALL_FILES, ids=[os.path.relpath(p, _ENGINE_ROOT) for p in _ALL_FILES]
)
def test_no_ui_or_qt_imports_anywhere_in_engine(path):
    bad = {m for m in _imported_modules(path) if _violates(m, _FORBIDDEN_EVERYWHERE)}
    assert not bad, f"{path} imports forbidden UI/Qt modules: {sorted(bad)}"


_METRICS_FILES = [p for p in _ALL_FILES if os.sep + "metrics" + os.sep in p]


@pytest.mark.parametrize(
    "path", _METRICS_FILES, ids=[os.path.basename(p) for p in _METRICS_FILES]
)
def test_metrics_never_imports_tempo_machinery(path):
    bad = {m for m in _imported_modules(path) if _violates(m, _FORBIDDEN_IN_METRICS)}
    assert not bad, f"{path} imports tempo-engine modules: {sorted(bad)}"
