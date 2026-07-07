"""Anti-drift gate for the generated theme artifacts.

_tokens_gen.py and app.qss are committed (the app never parses JSON at
startup), so nothing structurally stops them drifting from rai.tokens.json —
except this module: it regenerates both in memory and diffs byte-for-byte
against the committed files. It also pins the generator's hard-fail
behaviors (unresolved placeholders, stray braces, the pill-radius cap).

Pure python on purpose: the engine CI job has no Qt and must keep collecting
tests/ cleanly. The generator is loaded by file path so the test does not
depend on sys.path shape or packaging.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
THEME_DIR = REPO_ROOT / "rai_ui" / "theme"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_theme", REPO_ROOT / "tools" / "gen_theme.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


@pytest.fixture(scope="module")
def tokens():
    return gen.load_tokens()


class TestRoundTrip:
    def test_tokens_gen_py_matches_committed(self, tokens):
        committed = (THEME_DIR / "_tokens_gen.py").read_text(encoding="utf-8")
        assert gen.generate_tokens_py(tokens) == committed, (
            "rai_ui/theme/_tokens_gen.py drifted from rai.tokens.json — "
            "run tools/gen_theme.py and commit the result"
        )

    def test_app_qss_matches_committed(self, tokens):
        template = (THEME_DIR / "app.qss.tmpl").read_text(encoding="utf-8")
        committed = (THEME_DIR / "app.qss").read_text(encoding="utf-8")
        assert gen.render_qss(template, tokens) == committed, (
            "rai_ui/theme/app.qss drifted from its template/tokens — "
            "run tools/gen_theme.py and commit the result"
        )

    def test_generated_header_present(self):
        first_line = (THEME_DIR / "_tokens_gen.py").read_text(encoding="utf-8").splitlines()[0]
        assert first_line == gen.GENERATED_HEADER


class TestHardFailures:
    def test_unresolved_placeholder_raises(self, tokens):
        with pytest.raises(gen.ThemeGenError, match="unknown token path"):
            gen.render_qss("QLabel { color: {color.does.not.exist}; }", tokens)

    def test_group_path_raises(self, tokens):
        # A group (no scalar value) must never be substituted into QSS.
        with pytest.raises(gen.ThemeGenError, match="group"):
            gen.render_qss("QLabel { color: {color.surface}; }", tokens)

    def test_surviving_brace_raises(self, tokens):
        # Not placeholder-shaped (leading digit), so substitution skips it;
        # the output scan must still refuse the glued-brace artifact.
        with pytest.raises(gen.ThemeGenError, match="stray brace"):
            gen.render_qss("QLabel { color: #FFFFFF; }\nbad {2bad}\n", tokens)

    def test_radius_above_cap_raises(self, tokens):
        with pytest.raises(gen.ThemeGenError, match="border-radius"):
            gen.render_qss("QLabel { border-radius: 999px; }", tokens)

    def test_alpha_modifier_renders_rgba(self, tokens):
        out = gen.render_qss("QLabel { color: {color.text.secondary|alpha38}; }", tokens)
        # #A8B2BF = rgb(168, 178, 191)
        assert "rgba(168, 178, 191, 38%)" in out


class TestCommittedQss:
    def test_no_emitted_radius_exceeds_pill_cap(self):
        # Defense in depth: the generator enforces this at build time, but the
        # committed artifact is what ships, so pin it here too.
        qss = (THEME_DIR / "app.qss").read_text(encoding="utf-8")
        radii = [float(m.group(1)) for m in gen._RADIUS_RE.finditer(qss)]
        assert radii, "expected at least one border-radius in app.qss"
        assert max(radii) <= gen.MAX_EMITTED_RADIUS_PX

    def test_no_placeholder_braces_survive(self):
        qss = (THEME_DIR / "app.qss").read_text(encoding="utf-8")
        assert gen._PLACEHOLDER_RE.search(qss) is None
