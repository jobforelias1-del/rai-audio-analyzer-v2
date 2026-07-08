"""Report section tests: verbatim rendering, Copy CLI, Export .txt.

``rai_ui.state.formatters`` is another agent's file; the copy test stubs it
into ``sys.modules`` (overriding the real one if it has landed) so the
clipboard assertion is exact either way.
"""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

import sys
import types

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog


def make_fake_result(path="/tmp/beat.wav", bpm=150.0):
    from rai_analyzer.contracts import (
        AnalysisResult,
        Candidate,
        LoudnessResult,
        Relationship,
        TempoResult,
    )

    tempo = TempoResult(
        primary_bpm=bpm,
        felt_bpm=bpm / 2,
        candidates=[
            Candidate(bpm=bpm, score=0.91, salience=1.0),
            Candidate(
                bpm=bpm / 2, score=0.62, salience=0.8, relationship=Relationship.OCTAVE_DOWN
            ),
        ],
        ambiguous=True,
        ambiguity_reason="half-time partner scores within margin",
    )
    loudness = LoudnessResult(lufs_i=-9.8, true_peak_dbtp=-0.4, sample_peak_dbfs=-0.9)
    return AnalysisResult(
        path=path, duration=194.9, sr=44100, channels=2, tempo=tempo, loudness=loudness
    )


@pytest.fixture
def section(qtbot):
    from rai_ui.sections.report import ReportSection

    widget = ReportSection()
    qtbot.addWidget(widget)
    return widget


def test_empty_state_before_first_result(section):
    assert section.text_edit.toPlainText() == ""
    assert "Drop a WAV to analyze" in section.text_edit.placeholderText()
    assert not section.copy_button.isEnabled()
    assert not section.export_button.isEnabled()


def test_report_text_is_verbatim(section):
    result = make_fake_result()
    section.set_result(result)
    # Byte-identical to the CLI / harness report — presentation only on top.
    assert section.text_edit.toPlainText() == result.to_report()
    assert section.text_edit.isReadOnly()
    assert section.copy_button.isEnabled()
    assert section.export_button.isEnabled()


def test_copy_sets_clipboard_to_cli_command(section, qtbot, monkeypatch):
    fake_formatters = types.ModuleType("rai_ui.state.formatters")
    fake_formatters.cli_command = lambda path: f"rai-analyze {path}"
    monkeypatch.setitem(sys.modules, "rai_ui.state.formatters", fake_formatters)

    result = make_fake_result("/tmp/beat.wav")
    section.set_result(result)
    section.copy_button.click()

    assert QGuiApplication.clipboard().text() == "rai-analyze /tmp/beat.wav"
    assert section.copy_button.text() == "Copied ✓"
    # Reverts to the action label after the 1500ms feedback window.
    qtbot.wait(1700)
    assert section.copy_button.text() == "Copy CLI command"


def test_copy_frozen_puts_bundle_binary_on_clipboard(section, qtbot, monkeypatch):
    """M5 wiring proof: with the REAL formatter under a posed sys.frozen, the
    Copy button lands the turnkey frozen-binary command on the clipboard."""
    import sys as real_sys

    monkeypatch.setattr(real_sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        real_sys,
        "executable",
        "/Applications/RAI Audio Analyzer.app/Contents/MacOS/RAIAudioAnalyzer",
    )

    result = make_fake_result("/tmp/beat.wav")
    section.set_result(result)
    section.copy_button.click()

    assert QGuiApplication.clipboard().text() == (
        '"/Applications/RAI Audio Analyzer.app/Contents/MacOS/RAIAudioAnalyzer"'
        ' "/tmp/beat.wav" --json --profile drill'
    )
    # Drain the 1500 ms copy-feedback singleShot before the widget dies, or
    # it fires into a LATER test's event loop against a deleted C++ button.
    qtbot.wait(1700)


def test_export_writes_report_txt(section, tmp_path, monkeypatch):
    result = make_fake_result("/tmp/beat.wav")
    section.set_result(result)

    destination = tmp_path / "out.txt"
    seen_args = []

    def fake_get_save_file_name(*args, **kwargs):
        seen_args.append(args)
        return str(destination), "Text files (*.txt)"

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(fake_get_save_file_name)
    )
    section.export_button.click()

    assert destination.read_text(encoding="utf-8") == result.to_report()
    # Default filename offered is <stem>_report.txt.
    assert any("beat_report.txt" in str(a) for a in seen_args[0])


def test_export_cancelled_writes_nothing(section, tmp_path, monkeypatch):
    result = make_fake_result("/tmp/beat.wav")
    section.set_result(result)
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    section.export_button.click()
    assert list(tmp_path.iterdir()) == []
