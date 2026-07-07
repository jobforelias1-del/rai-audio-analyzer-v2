"""M4 Compare + report-banner end-to-end arcs — the Stage-2 integration proof.

Everything drives the REAL MainWindow offscreen with REAL analyses on
synthetic WAVs (worker threads, the session, the CompareSlot, the reducer,
the view-model fan-out — nothing mocked but audio playback). Coverage per
the Stage-2 manifest:

* drop routing (R-M4-1): a WAV dropped while Compare is the ACTIVE page
  loads B (with the verbatim design toast + the ``B · analyzing…`` chip);
  dropped anywhere else it is A, untouched behavior;
* B is a persistent reference (R-M4-2): an A re-analysis keeps B; the chip's
  ✕ is the ONE clearing act;
* mutual exclusion (R-M4-3): B refused while A is WORKING and while a
  relearn runs (stubbed controller probe) — and the vice-versa gates: an A
  drop and a relearn both refuse while B analyzes;
* the M3 blank doctrine holds through Compare: A-side WORKING/ERROR dashes
  A's table column while the B chip and B column persist;
* the R-M4-13 nav gate: with no file loaded the Compare page renders
  NOTHING, and a drop there falls through to A;
* the report banner (R-M4-11): appears on a real confirm, vanishes on undo,
  and the text edit's copyable bytes are UNCHANGED throughout.

Audio is faked (CI never opens a device); the ground-truth store is the
conftest's per-test temp dir (R-M3-2). Qt-dependent — importorskip'd so the
engine venv skips cleanly.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QMimeData, QPointF, QSettings, Qt, QUrl
from PySide6.QtGui import QDropEvent

import rai_ui.main_window as mw
from rai_ui.services.compare_slot import (
    TOAST_B_BLOCKED_BY_ANALYSIS,
    TOAST_B_BLOCKED_BY_RELEARN,
)
from rai_ui.state.compare_view import (
    B_EMPTY_CHIP_TEXT,
    B_EMPTY_PILL_TEXT,
    B_WORKING_CHIP_TEXT,
)
from rai_ui.state.compare_view import BStatus
from rai_ui.state.verdict import VerdictKind

ANALYSIS_TIMEOUT_MS = 60_000
EM_DASH = "—"


class FakeClickPreview:
    """The ClickPreview API surface — no device, no playback (plan §3)."""

    def __init__(self) -> None:
        self._playing = None

    def preview(self, bpm) -> None:
        self._playing = float(bpm)

    def toggle(self, bpm) -> None:
        self._playing = None if self._playing == float(bpm) else float(bpm)

    def stop(self) -> None:
        self._playing = None

    def set_source(self, features, signal_obj) -> None:
        pass

    def clear(self) -> None:
        self._playing = None

    @property
    def playing_bpm(self):
        return self._playing


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """Real MainWindow, QSettings isolated, audio faked (the flagship recipe).

    (The ground-truth store is already isolated by the tests/ui conftest.)
    """
    from rai_ui.services import recent_files

    monkeypatch.setattr(
        recent_files,
        "_settings",
        lambda: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    monkeypatch.setattr(
        mw,
        "_ui_settings",
        lambda: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    win = mw.MainWindow()
    win.click_preview = FakeClickPreview()
    qtbot.addWidget(win)
    return win


def _write_drill(tmp_path, bpm: float, name: str) -> str:
    """8 s synthetic drill — honestly AMBIGUOUS end-to-end (M3-verified)."""
    from rai_analyzer.synthetic import drill_pattern, write_wav

    return write_wav(str(tmp_path / name), drill_pattern(bpm, duration=8.0))


def _analyze(window, qtbot, path: str) -> None:
    """One REAL A analysis through open_path (worker thread, generation gate)."""
    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_path(path)


def _load_reference(window, qtbot, path: str) -> None:
    """One REAL B analysis through the public reference entry point."""
    with qtbot.waitSignal(window.compare_slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_reference(path)


def _drop(window, path: str) -> None:
    """Deliver a real QDropEvent to the window (the test_shell recipe)."""
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.dropEvent(event)


# ---------------------------------------------------------------------------
# R-M4-1: drop routing by ACTIVE page
# ---------------------------------------------------------------------------


def test_drop_on_compare_routes_to_b_with_toast_and_working_chip(window, qtbot, tmp_path):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    ref_wav = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)
    window.nav.set_current("Compare")
    assert window.stack.currentIndex() == mw.COMPARE_PAGE

    with qtbot.waitSignal(window.compare_slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        _drop(window, ref_wav)
        # Synchronous truth right after the drop: B WORKING, chip verbatim,
        # in-flight indication CONFINED to the chip (R-M4-3).
        assert window.compare_slot.is_working()
        assert (
            window.compare_section.chips.b_chip.text_label.text()
            == B_WORKING_CHIP_TEXT
        )

    # Routed to B: A untouched, B landed, design toast verbatim (04:875).
    assert window.session.last_result.path == a_wav
    assert window.compare_slot.result.path == ref_wav
    assert window.toast.label.text() == "ref.wav analyzed — reference loaded"
    assert window.compare_section.chips.b_chip.text_label.text() == "B · ref.wav"
    # The Δ table's B column is live.
    assert window.compare_section.table.b_value_labels[0].text() != EM_DASH


def test_drop_elsewhere_routes_to_a(window, qtbot, tmp_path):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    b_wav = _write_drill(tmp_path, 150.0, "b.wav")
    _analyze(window, qtbot, a_wav)
    window.nav.set_current("Tempo")

    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        _drop(window, b_wav)
    assert window.session.last_result.path == b_wav  # replaced A
    assert window.compare_slot.status is BStatus.EMPTY  # B untouched


def test_no_file_loaded_compare_renders_nothing_and_drop_falls_to_a(
    window, qtbot, tmp_path
):
    """R-M4-13 nav gate + the authored no-invisible-B guard."""
    window.nav.set_current("Compare")
    assert window.compare_section.view() is None
    assert window.compare_section.chips.isHidden()
    assert window.compare_section.table.isHidden()
    assert window.compare_section.overlay.isHidden()

    wav = _write_drill(tmp_path, 140.0, "first.wav")
    with qtbot.waitSignal(window.session.result_ready, timeout=ANALYSIS_TIMEOUT_MS):
        _drop(window, wav)
    assert window.session.last_result.path == wav  # A, not an invisible B
    assert window.compare_slot.status is BStatus.EMPTY
    # And the section now renders (a file is loaded).
    assert window.compare_section.view() is not None


# ---------------------------------------------------------------------------
# R-M4-2: B is a persistent reference; ✕ is the one clearing act
# ---------------------------------------------------------------------------


def test_a_reanalysis_keeps_b(window, qtbot, tmp_path):
    a1 = _write_drill(tmp_path, 140.0, "a1.wav")
    a2 = _write_drill(tmp_path, 165.0, "a2.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a1)
    _load_reference(window, qtbot, ref)

    _analyze(window, qtbot, a2)  # the TRUCK workflow: new candidate, same ref
    assert window.compare_slot.status is BStatus.LOADED
    assert window.compare_slot.result.path == ref
    vm = window.compare_section.view()
    assert vm.a_chip_text == "A · a2.wav"
    assert vm.b_chip_text == "B · ref.wav"
    assert window.compare_section.table.b_value_labels[0].text() != EM_DASH


def test_clear_via_chip_x(window, qtbot, tmp_path):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)
    _load_reference(window, qtbot, ref)
    window.nav.set_current("Compare")
    window.show()

    qtbot.mouseClick(
        window.compare_section.chips.b_chip.clear_glyph, Qt.MouseButton.LeftButton
    )
    assert window.compare_slot.status is BStatus.EMPTY
    assert window.compare_slot.result is None
    # The section re-rendered the B-empty state end to end.
    chips = window.compare_section.chips
    assert chips.b_chip.text_label.text() == B_EMPTY_CHIP_TEXT
    table = window.compare_section.table
    assert all(label.text() == EM_DASH for label in table.b_value_labels)
    assert all(label.text() == EM_DASH for label in table.delta_labels)
    pill = window.compare_section.overlay.pill_label
    assert pill.isVisibleTo(window.compare_section.overlay)
    assert pill.text() == B_EMPTY_PILL_TEXT


# ---------------------------------------------------------------------------
# R-M4-3: mutual exclusion, both directions
# ---------------------------------------------------------------------------


def test_b_refused_while_a_working(window, qtbot, tmp_path):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)

    # Posed WORKING (the preview_shots precedent): begin() alone flips the
    # verdict without racing a real worker.
    window.session.begin(a_wav)
    assert window.session.verdict_state.kind is VerdictKind.WORKING
    window.open_reference(ref)
    assert window.compare_slot.status is BStatus.EMPTY
    assert window.toast.label.text() == TOAST_B_BLOCKED_BY_ANALYSIS
    window.session.fail("posed")  # settle the posed lifecycle


def test_b_refused_during_relearn(window, qtbot, tmp_path, monkeypatch):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)

    monkeypatch.setattr(window.relearn, "is_running", lambda: True)
    window.open_reference(ref)
    assert window.compare_slot.status is BStatus.EMPTY
    assert window.toast.label.text() == TOAST_B_BLOCKED_BY_RELEARN


def test_a_and_relearn_refused_while_b_working(window, qtbot, tmp_path):
    """The vice-versa gates: while B analyzes, an A drop and a relearn both
    refuse with their toasts (same fingerprint-cache hazard, finding 18)."""
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    a2 = _write_drill(tmp_path, 165.0, "a2.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)

    with qtbot.waitSignal(window.compare_slot.loaded, timeout=ANALYSIS_TIMEOUT_MS):
        window.open_reference(ref)
        assert window.compare_slot.is_working()

        window.open_path(a2)  # synchronous refusal before the loop spins
        assert window.toast.label.text() == mw.TOAST_ANALYSIS_BLOCKED_BY_REFERENCE
        assert window.session.last_result.path == a_wav

        window._on_relearn_requested()
        assert window.toast.label.text() == mw.TOAST_RELEARN_BLOCKED_BY_REFERENCE

    assert window.session.last_result.path == a_wav  # A never restarted


# ---------------------------------------------------------------------------
# M3 blank doctrine through Compare
# ---------------------------------------------------------------------------


def test_a_working_and_error_blank_a_side_while_b_persists(window, qtbot, tmp_path):
    a_wav = _write_drill(tmp_path, 140.0, "a.wav")
    ref = _write_drill(tmp_path, 150.0, "ref.wav")
    _analyze(window, qtbot, a_wav)
    _load_reference(window, qtbot, ref)
    table = window.compare_section.table
    chips = window.compare_section.chips

    # WORKING blanks A's column; B chip and B column persist.
    window.session.begin(a_wav)
    vm = window.compare_section.view()
    assert vm is not None and not vm.has_a
    assert vm.a_chip_text == f"A · {EM_DASH}"
    assert all(label.text() == EM_DASH for label in table.a_value_labels)
    assert all(label.text() == EM_DASH for label in table.delta_labels)
    assert chips.b_chip.text_label.text() == "B · ref.wav"
    assert table.b_value_labels[0].text() != EM_DASH

    # ERROR keeps the same blank-A / persistent-B shape.
    window.session.fail("boom")
    assert window.session.verdict_state.kind is VerdictKind.ERROR
    vm = window.compare_section.view()
    assert vm is not None and not vm.has_a
    assert all(label.text() == EM_DASH for label in table.a_value_labels)
    assert chips.b_chip.text_label.text() == "B · ref.wav"

    # A fresh A result repopulates the A side, B still untouched.
    _analyze(window, qtbot, a_wav)
    vm = window.compare_section.view()
    assert vm.has_a and vm.a_chip_text == "A · a.wav"
    assert window.compare_slot.result.path == ref


# ---------------------------------------------------------------------------
# R-M4-11: the report banner, bytes-unchanged proof end to end
# ---------------------------------------------------------------------------


def test_report_banner_confirm_undo_bytes_unchanged(window, qtbot, tmp_path):
    wav = _write_drill(tmp_path, 140.0, "amb.wav")
    _analyze(window, qtbot, wav)
    assert window.session.verdict_state.kind is VerdictKind.AMBIGUOUS

    banner = window.report_section.banner
    text_before = window.report_section.text_edit.toPlainText()
    assert banner.isHidden()

    # A REAL confirm through the session (reducer + journal in the isolated
    # temp store) — the verdict fan-out drives the banner.
    bpm = window.session.last_result.tempo.candidates[0].bpm
    outcome = window.session.confirm(bpm)
    assert outcome.accepted and outcome.persisted
    assert not banner.isHidden()
    assert banner.label.text() == (
        f"✓ CONFIRMED · HUMAN — human tiebreak · {bpm:.2f} saved as ground truth"
    )
    assert window.report_section.text_edit.toPlainText() == text_before  # bytes frozen

    # Undo → the banner vanishes, the report bytes still untouched.
    outcome = window.session.undo()
    assert outcome.accepted
    assert banner.isHidden()
    assert window.session.verdict_state.kind is VerdictKind.AMBIGUOUS
    assert window.report_section.text_edit.toPlainText() == text_before
