"""End-to-end M2 Overview/Signal-section tests: session in, every surface out.

The binding contracts under test (offscreen, fake engine payloads through the
REAL session/reducer — the same drive path tests/ui/test_tempo_section.py
uses):

* A finished analysis with a SignalResult populates the Overview cards
  (Tempo/Loudness/Dynamics/File) + waveform AND the Signal spectrum + three
  metric cards from ONE session snapshot — and lights up the rail's
  Dynamics·stereo rows and the bridge's DR/Width cells with REAL values
  (R-M1-6's em-dashes retire in M2). The bridge has NO Sub/bass cell by
  design (CO:127–146) — asserted absent, not just untested.
* WORKING blanks all three sections (R-M1-3/R-M2-16) — dashes everywhere,
  no chips, no curves — while the C-17 sweeps run on both new wells.
* analyze(A) ok → analyze(B) fails: the M1 resurrect regression extended to
  the M2 signal data — B's ERROR must not wear A's DR/Sub/Width, spectrum,
  or waveform on ANY surface.
* Silence: −∞ loudness renders as a measurement with NO chip, while
  crest/sub/width render as absence WITH the `silent file` chip; the
  spectrum well shows the R-M2-8 copy, the waveform draws its honest flat
  line with no copy.

Qt-dependent throughout — PySide6/pytest-qt are importorskip'd before any Qt
import so the Qt-less engine venv skips this module cleanly.
"""

import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QSettings

from rai_analyzer.contracts import LoudnessResult
from rai_ui.state.formatters import EM_DASH, NEG_INFINITY
from rai_ui.state.signal_view import SILENT_SPECTRUM_TEXT
from tests.ui.test_signal_view import (
    make_signal_result,
    silent_signal_result,
)
from tests.ui.test_tempo_view import make_features, make_result, no_tempo_result

OVERVIEW_PAGE = 1  # hero=0, Overview=1
SIGNAL_PAGE = 3  # hero=0, Overview=1, Tempo=2, Signal=3

NEG_INF = float("-inf")


class FakeSignalObj:
    """The minimal AudioSignal shape the waveform envelope reads (y_native)."""

    def __init__(self, y_native: np.ndarray) -> None:
        self.y_native = y_native


def make_signal_obj(n: int = 4096) -> FakeSignalObj:
    t = np.linspace(0.0, 1.0, n)
    return FakeSignalObj(np.sin(2 * np.pi * 6.0 * t).astype(np.float64) * 0.5)


def silent_signal_obj(n: int = 4096) -> FakeSignalObj:
    return FakeSignalObj(np.zeros(n, dtype=np.float64))


def make_loudness(
    lufs: float = -9.8, dbtp: float = -0.6, dbfs: float = -1.1
) -> LoudnessResult:
    return LoudnessResult(lufs_i=lufs, true_peak_dbtp=dbtp, sample_peak_dbfs=dbfs)


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    """MainWindow with recent-files AND ui-pref settings isolated to tmp INIs."""
    import rai_ui.main_window as mw
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
    qtbot.addWidget(win)
    return win


# Sentinel: ``signal_result=None`` is a MEANINGFUL payload (metrics degraded,
# R-M2-15), so the helper default must be distinguishable from an explicit None.
_DEFAULT = object()


def finish_analysis(
    qtbot,
    window,
    result=None,
    features=None,
    signal_obj=None,
    signal_result=_DEFAULT,
    path="/tmp/beat.wav",
):
    """begin() then finish() — completions only reduce from WORKING (the
    reducer's stale-completion guard), so verdict-dependent assertions must
    drive the full lifecycle. The M2 payload rides the keyword-additive
    finish parameters exactly as MainWindow forwards them from the worker."""
    if result is None:
        result = make_result(loudness=make_loudness())
    if features is None:
        features = make_features()
    if signal_obj is None:
        signal_obj = make_signal_obj()
    if signal_result is _DEFAULT:
        signal_result = make_signal_result()
    window.session.begin(path)
    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(
            result, features, signal_obj, 1.23, signal_result=signal_result
        )
    return result


def row_texts(card) -> list[str]:
    return [label.text() for label in card.row_value_labels]


# ---------------------------------------------------------------------------
# Result → Overview cards + waveform
# ---------------------------------------------------------------------------


def test_result_populates_overview_cards_and_waveform(window, qtbot):
    finish_analysis(qtbot, window)
    overview = window.overview_section
    vm = overview.view()
    assert vm.has_result is True

    # Tempo card: primary/felt numerals + the short tinted verdict word.
    assert overview.tempo_card.primary_value.text() == "205.15"
    assert overview.tempo_card.felt_value.text() == "102.57"
    assert overview.tempo_card.word_label.text() == "✓ confident"

    # Loudness card: the trio, 2 dp, U+2212 minus, no chip on real values.
    assert row_texts(overview.loudness_card) == ["−9.80", "−0.60", "−1.10"]
    assert not overview.loudness_card.chip_label.isVisibleTo(overview)

    # Dynamics card: the three M2 metrics, REAL values, no chip.
    assert row_texts(overview.dynamics_card) == ["8.2", "21 %", "62 %"]
    assert not overview.dynamics_card.chip_label.isVisibleTo(overview)

    # File card: metadata verbatim (space-grouped rate, channel wording).
    assert row_texts(overview.file_card) == [
        "beat.wav",
        "6.0 s",
        "44 100 Hz",
        "2 (stereo)",
    ]

    # Waveform: envelope drawn, mm:ss endpoint on the axis.
    assert overview.waveform._envelope.isVisible()
    assert overview.waveform._spine.isVisible()
    assert overview.waveform._axis.length_text() == "0:06"


# ---------------------------------------------------------------------------
# Result → Signal spectrum + cards
# ---------------------------------------------------------------------------


def test_result_populates_signal_spectrum_and_cards(window, qtbot):
    finish_analysis(qtbot, window)
    signal = window.signal_section
    vm = signal.view()
    assert vm.has_signal is True
    assert vm.silent is False

    # Spectrum: curve visible, display-normalized to the 0 dB top.
    assert signal.spectrum._curve.isVisible()
    assert not signal.spectrum._silent_label.isVisibleTo(signal)
    assert float(np.max(vm.spectrum_db)) == pytest.approx(0.0)

    # Width card: value + proportional gauge fill.
    assert signal.width_card.value_label.text() == "62 %"
    assert signal.width_card.gauge.isVisibleTo(signal)
    assert signal.width_card.gauge.fraction() == pytest.approx(0.62)

    # Sub card.
    assert signal.sub_card.value_label.text() == "21 %"
    assert signal.sub_card.gauge.fraction() == pytest.approx(0.21)

    # DR card: crest value, unconditional dB unit, RMS-bearing caption,
    # NO gauge bar (04:436–440).
    assert signal.dr_card.value_label.text() == "8.2"
    assert signal.dr_card.unit_label is not None
    assert signal.dr_card.unit_label.text() == "dB"
    assert signal.dr_card.caption_label.text() == (
        "crest-based, whole file · RMS −16.4 dB"
    )
    assert not signal.dr_card.gauge.isVisibleTo(signal)

    # No chips anywhere — every value is a measurement.
    for card in (signal.width_card, signal.sub_card, signal.dr_card):
        assert not card.chip_label.isVisibleTo(signal)


# ---------------------------------------------------------------------------
# Rail + bridge: the M1 em-dashes retire — real values on the chrome readouts
# ---------------------------------------------------------------------------


def test_rail_and_bridge_show_real_m2_values(window, qtbot):
    finish_analysis(qtbot, window)

    # Rail: all three Dynamics·stereo rows, real numbers.
    assert window.rail.dr_value.text() == "8.2"
    assert window.rail.sub_value.text() == "21 %"
    assert window.rail.width_value.text() == "62 %"

    # Bridge: DR + Width cells real; Sub/bass is rail-only by design
    # (CO:127–146) — the bridge must not have grown a sub cell.
    assert window.bridge.dr_value.text() == "8.2"
    assert window.bridge.width_value.text() == "62 %"
    assert not hasattr(window.bridge, "sub_value")


def test_mono_width_renders_zero_percent_as_measurement(window, qtbot):
    finish_analysis(qtbot, window, signal_result=make_signal_result(width=0.0))
    # 0 % is a MEASUREMENT (R-M2-4) — never an em-dash, never a chip.
    assert window.signal_section.width_card.value_label.text() == "0 %"
    assert window.signal_section.width_card.chip_label.isHidden()
    assert window.rail.width_value.text() == "0 %"


# ---------------------------------------------------------------------------
# WORKING blanks all three sections (R-M1-3 / R-M2-16)
# ---------------------------------------------------------------------------


def test_working_blanks_all_three_sections_and_sweeps_run(window, qtbot):
    window.show()
    finish_analysis(qtbot, window)  # a real result first — the blank must win

    window.session.begin("/tmp/next.wav")

    # Tempo surfaces blank (M1 behavior, still true).
    assert window.rail.primary_value.text() == EM_DASH
    assert window.rail.dr_value.text() == EM_DASH

    # Overview blanks: every card dashes, no chips, waveform empties.
    overview = window.overview_section
    assert overview.view().has_result is False
    assert overview.tempo_card.primary_value.text() == EM_DASH
    assert row_texts(overview.dynamics_card) == [EM_DASH, EM_DASH, EM_DASH]
    assert row_texts(overview.file_card) == [EM_DASH] * 4
    assert not overview.dynamics_card.chip_label.isVisibleTo(overview)
    assert not overview.waveform._envelope.isVisible()
    assert overview.waveform._axis.length_text() == EM_DASH

    # Signal blanks: no curve, dashed cards, no chips.
    signal = window.signal_section
    assert signal.view().has_signal is False
    assert not signal.spectrum._curve.isVisible()
    for card in (signal.width_card, signal.sub_card, signal.dr_card):
        assert card.value_label.text() == EM_DASH
        assert not card.chip_label.isVisibleTo(signal)

    # Both new wells run the C-17 sweep while working.
    window.nav.set_current("Overview")
    assert overview.waveform._overlay.isVisible()
    window.nav.set_current("Signal")
    assert signal.spectrum._overlay.isVisible()

    # Finishing turns the sweeps back off.
    with qtbot.waitSignal(window.session.result_ready):
        window.session.finish(
            make_result(loudness=make_loudness()),
            make_features(),
            make_signal_obj(),
            1.0,
            signal_result=make_signal_result(),
        )
    assert not overview.waveform._overlay.isVisible()
    assert not signal.spectrum._overlay.isVisible()


# ---------------------------------------------------------------------------
# ERROR after success — the M1 resurrect regression, extended to signal data
# ---------------------------------------------------------------------------


def test_failed_reanalysis_never_resurrects_signal_data(window, qtbot):
    """analyze(A) ok → analyze(B) fails: B's ERROR must not wear A's
    DR/Sub/Width, spectrum, or waveform on ANY surface (the M1 finding's
    exact shape — fail() keeps the session payload, so only the ERROR blank
    in the view-model builders stands between file B's failure and file A's
    numbers)."""
    window.show()
    finish_analysis(qtbot, window)  # file A lands with full signal data
    assert window.rail.dr_value.text() == "8.2"
    assert window.signal_section.spectrum._curve.isVisible()

    window.session.begin("/tmp/fileB.wav")
    with qtbot.waitSignal(window.session.analysis_failed):
        window.session.fail("could not decode")

    # Rail + bridge: M2 rows dash again.
    assert window.rail.dr_value.text() == EM_DASH
    assert window.rail.sub_value.text() == EM_DASH
    assert window.rail.width_value.text() == EM_DASH
    assert window.bridge.dr_value.text() == EM_DASH
    assert window.bridge.width_value.text() == EM_DASH

    # Overview: nothing of A's survives — and no chip dresses the blank
    # (an ERROR is not a measured absence).
    overview = window.overview_section
    assert overview.view().has_result is False
    assert row_texts(overview.dynamics_card) == [EM_DASH, EM_DASH, EM_DASH]
    assert row_texts(overview.loudness_card) == [EM_DASH, EM_DASH, EM_DASH]
    assert not overview.dynamics_card.chip_label.isVisibleTo(overview)
    assert not overview.waveform._envelope.isVisible()

    # Signal: no curve, no values, no chips.
    signal = window.signal_section
    assert signal.view().has_signal is False
    assert not signal.spectrum._curve.isVisible()
    for card in (signal.width_card, signal.sub_card, signal.dr_card):
        assert card.value_label.text() == EM_DASH
        assert not card.chip_label.isVisibleTo(signal)


# ---------------------------------------------------------------------------
# Silence: −∞ is a measurement, — is absence (chip-explained)
# ---------------------------------------------------------------------------


def test_silence_renders_neg_inf_loudness_and_chipped_absence(window, qtbot):
    silent_result = make_result(
        tempo=no_tempo_result().tempo,
        loudness=make_loudness(lufs=NEG_INF, dbtp=NEG_INF, dbfs=NEG_INF),
    )
    finish_analysis(
        qtbot,
        window,
        result=silent_result,
        signal_obj=silent_signal_obj(),
        signal_result=silent_signal_result(),
        path="/tmp/silent.wav",
    )

    # Overview Loudness: −∞ across the trio — measurements, NO chip.
    overview = window.overview_section
    assert row_texts(overview.loudness_card) == [NEG_INFINITY] * 3
    assert not overview.loudness_card.chip_label.isVisibleTo(overview)

    # Overview Dynamics: absence with the `silent file` chip.
    assert row_texts(overview.dynamics_card) == [EM_DASH, EM_DASH, EM_DASH]
    assert overview.dynamics_card.chip_label.isVisibleTo(overview)
    assert overview.dynamics_card.chip_label.text() == "silent file"

    # Overview Tempo card: no-tempo falls back to the muted em-dash word.
    assert overview.tempo_card.word_label.text() == EM_DASH

    # Waveform: the honest flat line — envelope items visible, NO copy
    # (the silent-file prose belongs to the spectrum well only, R-M2-8).
    assert overview.waveform._envelope.isVisible()
    assert overview.waveform._spine.isVisible()

    # Signal spectrum: no curve, the authored silent copy on the well.
    signal = window.signal_section
    assert signal.view().silent is True
    assert not signal.spectrum._curve.isVisible()
    assert signal.spectrum._silent_label.isVisibleTo(signal)
    assert signal.spectrum._silent_label.text() == SILENT_SPECTRUM_TEXT

    # Signal cards: crest/sub/width are undefined on silence → absence with
    # the chip; the DR caption still carries the measured RMS −∞ (bare, no
    # dB unit — matches the demo's silence row).
    for card in (signal.width_card, signal.sub_card, signal.dr_card):
        assert card.value_label.text() == EM_DASH
        assert card.chip_label.isVisibleTo(signal)
        assert card.chip_label.text() == "silent file"
    assert signal.dr_card.caption_label.text() == (
        "crest-based, whole file · RMS " + NEG_INFINITY
    )
    # Absent gauges stay at 0 (the demo's "— (bar 0)").
    assert signal.width_card.gauge.fraction() == 0.0
    assert signal.sub_card.gauge.fraction() == 0.0

    # Rail mirrors the same doctrine.
    assert window.rail.dr_value.text() == EM_DASH
    assert window.rail.lufs_value.text() == NEG_INFINITY


# ---------------------------------------------------------------------------
# Metrics degradation (R-M2-15): analysis lands, SignalResult is None
# ---------------------------------------------------------------------------


def test_degraded_metrics_render_unavailable_chips_not_a_crash(window, qtbot):
    finish_analysis(qtbot, window, signal_result=None)

    # Tempo/loudness still real — only the M2 metrics degrade.
    overview = window.overview_section
    assert overview.tempo_card.primary_value.text() == "205.15"
    assert row_texts(overview.loudness_card) == ["−9.80", "−0.60", "−1.10"]

    # The M2 surfaces read absence, chip-explained as `unavailable for this
    # file` (a real analysis happened; the metrics did not).
    assert row_texts(overview.dynamics_card) == [EM_DASH, EM_DASH, EM_DASH]
    assert overview.dynamics_card.chip_label.text() == "unavailable for this file"

    signal = window.signal_section
    assert signal.view().has_signal is False
    assert not signal.spectrum._curve.isVisible()
    for card in (signal.width_card, signal.sub_card, signal.dr_card):
        assert card.value_label.text() == EM_DASH
        assert card.chip_label.text() == "unavailable for this file"

    assert window.rail.dr_value.text() == EM_DASH


# ---------------------------------------------------------------------------
# Wiring sanity: nav pages host the real sections and math stays honest
# ---------------------------------------------------------------------------


def test_nav_lands_on_real_overview_and_signal_pages(window, qtbot):
    from rai_ui.main_window import OVERVIEW_PAGE as MW_OVERVIEW_PAGE
    from rai_ui.main_window import SIGNAL_PAGE as MW_SIGNAL_PAGE

    assert MW_OVERVIEW_PAGE == OVERVIEW_PAGE
    assert MW_SIGNAL_PAGE == SIGNAL_PAGE
    window.nav.button("Overview").click()
    assert window.stack.currentWidget() is window.overview_section
    window.nav.button("Signal").click()
    assert window.stack.currentWidget() is window.signal_section


def test_sections_render_idempotently(window, qtbot):
    """set_view twice with the same session snapshot changes nothing — the
    pane/card doctrine, asserted at section level through the fan-out."""
    finish_analysis(qtbot, window)
    overview_vm = window.overview_section.view()
    signal_vm = window.signal_section.view()
    window.overview_section.set_view(overview_vm)
    window.signal_section.set_view(signal_vm)
    assert window.overview_section.view() is overview_vm
    assert window.signal_section.view() is signal_vm
    assert window.overview_section.tempo_card.primary_value.text() == "205.15"
    assert window.signal_section.width_card.value_label.text() == "62 %"
    assert math.isclose(window.signal_section.width_card.gauge.fraction(), 0.62)
