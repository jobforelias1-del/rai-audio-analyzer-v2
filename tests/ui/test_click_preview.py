"""Click-preview service tests (rulings R-M3-8/9/10).

The premix math is pure numpy and tested EXACTLY (tick placement from
phase + k*period, the shared per-FILE level plan — identical music bed for
every candidate of one file, bed+tick ≤ 0.95 by construction — the EOF
skip-not-truncate rule, sample alignment, the >180 s mono fold, the LRU-2
cache). Playback runs against a FAKE stream driven by hand — CI has no
audio device, and ``sounddevice`` is never imported here (the module
imports it only inside its default factory; AST-pinned below).

Qt: the service is a QObject with the ``stopped`` signal (playback-state
honesty — cards must stop pulsing when the buffer runs out), so PySide6 is
importorskip'd like every other Qt-dependent UI module and the Qt-less
engine venv skips this file cleanly. The ~250 ms poll behind ``stopped`` is
driven by calling ``_poll_playback()`` directly — no real timers, no waits.

R-M3-9 is enforced structurally: every fake BeatGrid in this file RAISES if
``confidence`` is ever read — a confidence gate cannot creep in without
turning this file red — and one test drives the REAL engine at the wrong
octave (the low-confidence case a naive gate would kill) and hears ticks.
"""

from __future__ import annotations

import ast
import logging
import math
import os
import types
from dataclasses import dataclass

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from rai_ui.services import click_preview as cp


@pytest.fixture(autouse=True)
def _qt_app(qapp):
    """Every test gets a QApplication: the service owns a QTimer (the
    playback-state poll), and QObject/QTimer want an app instance."""
    return qapp


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _GridNoConfidenceRead:
    """A BeatGrid stand-in whose ``confidence`` is a tripwire (R-M3-9)."""

    def __init__(self, phase_seconds: float, period_seconds: float) -> None:
        self.phase_seconds = phase_seconds
        self.period_seconds = period_seconds

    @property
    def confidence(self):
        raise AssertionError(
            "R-M3-9: the click preview must NEVER read beatgrid confidence"
        )


class _FakeEstimator:
    """Counts calls; enforces the estimate_beat_phase ValueError contract."""

    def __init__(self, phase: float = 0.25, period: float = 0.5) -> None:
        self.calls: list[float] = []
        self.phase = phase
        self.period = period

    def grid_for(self, bpm: float) -> _GridNoConfidenceRead:
        return _GridNoConfidenceRead(self.phase, self.period)

    def __call__(self, features, bpm):
        bpm = float(bpm)
        if not math.isfinite(bpm) or bpm <= 0.0:
            raise ValueError(f"bpm must be finite and positive, got {bpm!r}")
        self.calls.append(bpm)
        return self.grid_for(bpm)


class _PerBpmPhaseEstimator(_FakeEstimator):
    """Distinct phase per bpm so A/B premixes are distinguishable."""

    def __init__(self, phase_by_bpm: dict, period: float = 0.5) -> None:
        super().__init__(period=period)
        self.phase_by_bpm = dict(phase_by_bpm)

    def grid_for(self, bpm: float) -> _GridNoConfidenceRead:
        return _GridNoConfidenceRead(self.phase_by_bpm[bpm], self.period)


class _FakeStream:
    def __init__(self, samplerate: int, channels: int, fill) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.fill = fill
        self.started = 0
        self.stopped = 0
        self.closed = 0
        self.active = False  # mirrors sounddevice's OutputStream.active

    def start(self) -> None:
        self.started += 1
        self.active = True

    def stop(self) -> None:
        self.stopped += 1
        self.active = False

    def close(self) -> None:
        self.closed += 1
        self.active = False

    def pump(self, frames: int):
        """Drive the callback by hand: returns (block, done)."""
        out = np.zeros((frames, self.channels), dtype=np.float32)
        done = self.fill(out, frames)
        if done:
            self.active = False  # the real adapter raises sd.CallbackStop
        return out, done


class _FakeFactory:
    def __init__(self) -> None:
        self.streams: list[_FakeStream] = []

    def __call__(self, samplerate, channels, fill):
        stream = _FakeStream(samplerate, channels, fill)
        self.streams.append(stream)
        return stream

    @property
    def last(self) -> _FakeStream:
        return self.streams[-1]


@dataclass
class _FakeSignal:
    """Just the AudioSignal fields the service reads."""

    y_native: np.ndarray
    sr_native: int
    duration: float


def _service(signal=None, estimator=None, factory=None):
    estimator = estimator or _FakeEstimator()
    factory = factory or _FakeFactory()
    svc = cp.ClickPreview(stream_factory=factory, phase_estimator=estimator)
    if signal is not None:
        svc.set_source(object(), signal)
    return svc, estimator, factory


def _mono_signal(seconds=2.0, sr=8000, value=0.0):
    n = int(seconds * sr)
    y = np.full(n, value, dtype=np.float32)
    return _FakeSignal(y_native=y, sr_native=sr, duration=seconds)


def _stopped_log(svc) -> list:
    """Collect ``stopped`` emissions (direct connection — synchronous)."""
    hits: list = []
    svc.stopped.connect(lambda: hits.append(True))
    return hits


def _expected_bed(y: np.ndarray) -> np.ndarray:
    """Replicate the shared per-file level plan exactly (float32 op order
    mirrors render_premix): duck −3 dB, then one scale to BED_CEILING only
    if the ducked bed peaks above it."""
    bed = np.asarray(y, dtype=np.float32) * np.float32(cp.MUSIC_DUCK_GAIN)
    peak = float(np.max(np.abs(bed))) if bed.size else 0.0
    if peak > cp.BED_CEILING:
        bed = bed * np.float32(cp.BED_CEILING / peak)
    return bed


# ---------------------------------------------------------------------------
# Pure premix math — exact
# ---------------------------------------------------------------------------


class TestRenderTick:
    def test_length_is_30ms(self):
        for sr in (8000, 44100, 48000):
            assert cp.render_tick(sr).shape == (int(round(cp.TICK_SECONDS * sr)),)

    def test_endpoints_exactly_zero(self):
        # The click must not itself click: raised-cosine fades land on 0.0
        # at both ends by construction.
        tick = cp.render_tick(44100)
        assert tick[0] == 0.0
        assert tick[-1] == 0.0

    def test_peak_is_tick_amplitude(self):
        tick = cp.render_tick(48000)
        peak = float(np.max(np.abs(tick)))
        assert peak <= cp.TICK_AMPLITUDE + 1e-6
        assert peak >= 0.95 * cp.TICK_AMPLITUDE  # the sustain region reaches it

    def test_float32_and_finite(self):
        tick = cp.render_tick(22050)
        assert tick.dtype == np.float32
        assert np.all(np.isfinite(tick))

    def test_bad_sr_raises(self):
        with pytest.raises(ValueError):
            cp.render_tick(0)
        with pytest.raises(ValueError):
            cp.render_tick(-44100)


class TestRenderPremix:
    def test_tick_placement_exact_on_silence(self):
        # Silent music: the premix IS the tick track — sample-exact per tick.
        sr, phase, period = 8000, 0.25, 0.5
        y = np.zeros(2 * sr, dtype=np.float32)
        out = cp.render_premix(y, sr, phase, period)
        tick = cp.render_tick(sr)
        expected_starts = [2000, 6000, 10000, 14000]  # round((0.25+k*0.5)*8000)
        mask = np.zeros_like(out, dtype=bool)
        for idx in expected_starts:
            seg = out[idx : idx + tick.shape[0]]
            assert np.array_equal(seg, tick[: seg.shape[0]])
            mask[idx : idx + tick.shape[0]] = True
        assert np.all(out[~mask] == 0.0)

    def test_placement_is_drift_free(self):
        # Index comes from round((phase + k*period)*sr) per k — verify far
        # ks land exactly where the multiplication says (D4 drift-free).
        sr = 44100
        period = 60.0 / 166.01
        phase = 0.1234
        y = np.zeros(int(40.0 * sr), dtype=np.float32)
        out = cp.render_premix(y, sr, phase, period)
        tick = cp.render_tick(sr)
        for k in (0, 37, 100):
            idx = int(round((phase + k * period) * sr))
            assert np.array_equal(out[idx : idx + tick.shape[0]], tick)

    def test_music_ducked_exactly_3db(self):
        # Quiet bed (0.1): peak stays under the ceiling, so the duck is the
        # ONLY thing that touches the music — exact float32 equality.
        sr, phase, period = 8000, 0.25, 0.5
        y = np.full(2 * sr, 0.1, dtype=np.float32)
        out = cp.render_premix(y, sr, phase, period)
        expected_bed = np.float32(0.1) * np.float32(cp.MUSIC_DUCK_GAIN)
        tick_len = cp.render_tick(sr).shape[0]
        quiet = out[2000 + tick_len : 6000]  # between two ticks
        assert np.all(quiet == expected_bed)

    def test_premix_is_superposition(self):
        # premix == leveled bed + tick track, everywhere, exactly. Quiet bed:
        # the bed gain is 1.0, so the duck is the only music op.
        sr, phase, period = 8000, 0.1, 0.4
        rng = np.random.default_rng(7)
        y = (0.02 * rng.standard_normal(int(1.5 * sr))).astype(np.float32)
        out = cp.render_premix(y, sr, phase, period)
        expected = y * np.float32(cp.MUSIC_DUCK_GAIN)
        tick = cp.render_tick(sr)
        k = 0
        while True:
            idx = int(round((phase + k * period) * sr))
            if idx + tick.shape[0] > expected.shape[0]:
                break  # the EOF rule: a burst that cannot complete is skipped
            expected[idx : idx + tick.shape[0]] += tick
            k += 1
        assert np.array_equal(out, expected)

    def test_final_tick_that_cannot_complete_is_skipped(self):
        # A burst starting <30 ms before EOF is dropped whole, never sliced
        # mid-envelope (the no-hard-step EOF rule).
        sr = 8000
        y = np.zeros(sr, dtype=np.float32)  # 1 s
        phase = 0.99  # tick would run 10 ms past the end
        out = cp.render_premix(y, sr, phase, 10.0)
        assert out.shape == y.shape
        assert np.all(out == 0.0)  # silent bed stays silent — no partial tick

    def test_final_tick_that_exactly_fits_is_rendered(self):
        sr = 8000
        tick = cp.render_tick(sr)
        y = np.zeros(sr, dtype=np.float32)
        idx = sr - tick.shape[0]  # burst ends exactly at EOF
        phase = idx / sr
        out = cp.render_premix(y, sr, phase, 10.0)
        assert np.array_equal(out[idx:], tick)
        assert np.all(out[:idx] == 0.0)

    def test_no_hard_step_at_eof(self):
        # The bounded-step property: for phases that would land a burst
        # across EOF, the premix's junction into the stream's zero-padding
        # never steps harder than the tick's own largest intra-burst step
        # (the raised-cosine envelope's smoothness budget). On a silent bed
        # the tail is exactly zero — the old truncation ended at ~0.6 FS.
        sr = 8000
        tick = cp.render_tick(sr)
        tick_step = float(np.max(np.abs(np.diff(tick))))
        y = np.zeros(sr, dtype=np.float32)
        for offset in (1, 10, tick.shape[0] // 2, tick.shape[0] - 1):
            phase = (sr - tick.shape[0] + offset) / sr  # burst overruns EOF
            out = cp.render_premix(y, sr, phase, 10.0)
            padded = np.concatenate([out, np.zeros(1, dtype=np.float32)])
            eof_step = float(np.max(np.abs(np.diff(padded[-2:]))))
            assert eof_step <= tick_step  # bounded by the envelope budget
            assert out[-1] == 0.0  # silent bed: skipped burst leaves silence

    def test_stereo_tick_on_both_channels(self):
        sr = 8000
        y = np.zeros((sr, 2), dtype=np.float32)
        out = cp.render_premix(y, sr, 0.0, 0.5)
        assert out.shape == (sr, 2)
        assert np.array_equal(out[:, 0], out[:, 1])
        # Ticks landed at the fixed level-plan amplitude.
        assert float(np.max(np.abs(out))) >= 0.9 * cp.TICK_AMPLITUDE

    def test_mono_fold_folds_stereo(self):
        sr = 1000  # small rate keeps the ">180 s" array tiny
        n = 181 * sr
        y = np.stack(
            [np.full(n, 0.05, dtype=np.float32), np.full(n, 0.15, dtype=np.float32)],
            axis=1,
        )
        out = cp.render_premix(y, sr, 0.0, 1.0, fold_mono=True)
        assert out.ndim == 1
        assert out.shape == (n,)
        tick_len = cp.render_tick(sr).shape[0]
        bed = out[tick_len : sr - 1]  # between the first two ticks
        expected = np.float32(0.1) * np.float32(cp.MUSIC_DUCK_GAIN)
        assert np.allclose(bed, expected, atol=1e-6)

    def test_fold_mono_is_noop_on_mono(self):
        sr = 8000
        y = np.zeros(sr, dtype=np.float32)
        out = cp.render_premix(y, sr, 0.0, 0.5, fold_mono=True)
        assert out.ndim == 1

    def test_level_plan_headroom_by_construction(self):
        # The whole point of the shared plan: bed ≤ BED_CEILING and a fixed
        # tick mean NO premix can clip, with no normalization step to vary.
        assert cp.BED_CEILING + cp.TICK_AMPLITUDE <= 0.95 + 1e-9

    def test_hot_bed_scaled_once_to_bed_ceiling(self):
        # Full-scale-mastered material: the ducked bed (0.98·0.708 ≈ 0.694)
        # still exceeds BED_CEILING, so it is scaled ONCE to exactly 0.55 —
        # and the premix peak stays ≤ bed + tick = 0.95 even with ticks on
        # top of the hottest samples.
        sr = 8000
        y = np.full(sr, 0.98, dtype=np.float32)
        out = cp.render_premix(y, sr, 0.0, 0.25)
        expected_bed = _expected_bed(y)
        tick_len = cp.render_tick(sr).shape[0]
        quiet = out[tick_len : int(0.25 * sr)]  # between the first two ticks
        assert np.array_equal(quiet, expected_bed[tick_len : int(0.25 * sr)])
        assert abs(float(expected_bed[0]) - cp.BED_CEILING) < 1e-6
        peak = float(np.max(np.abs(out)))
        assert peak <= cp.BED_CEILING + cp.TICK_AMPLITUDE + 1e-6

    def test_hot_bed_premix_is_exact_superposition(self):
        # No post-tick normalization exists: even at worst case (ticks on a
        # ceiling-level bed) the output is exactly bed + tick track.
        sr = 8000
        y = np.full(sr, 1.0, dtype=np.float32)
        phase, period = 0.0, 0.25
        out = cp.render_premix(y, sr, phase, period)
        expected = _expected_bed(y)
        tick = cp.render_tick(sr)
        k = 0
        while True:
            idx = int(round((phase + k * period) * sr))
            if idx + tick.shape[0] > expected.shape[0]:
                break
            expected[idx : idx + tick.shape[0]] += tick
            k += 1
        assert np.array_equal(out, expected)

    def test_bed_level_identical_across_candidates(self):
        # THE A/B honesty rule (the ~3.9 dB swap-jump regression): two
        # candidates of the SAME hot file — one with ticks on the loud
        # samples, one offset — must carry a bit-identical music bed. Under
        # the old per-premix normalization the on-peak candidate's whole
        # buffer was scaled by ~0.64 while the offset one kept gain 1.0.
        sr = 8000
        y = np.full(2 * sr, 1.0, dtype=np.float32)  # full-scale bed
        out_a = cp.render_premix(y, sr, 0.0, 0.5)  # ticks at 0.0, 0.5, ...
        out_b = cp.render_premix(y, sr, 0.25, 0.5)  # ticks at 0.25, 0.75, ...
        tick_len = cp.render_tick(sr).shape[0]

        def bed_mask(phase):
            mask = np.ones(y.shape[0], dtype=bool)
            k = 0
            while True:
                idx = int(round((phase + k * 0.5) * sr))
                if idx >= y.shape[0]:
                    break
                mask[idx : idx + tick_len] = False
                k += 1
            return mask

        both_bed = bed_mask(0.0) & bed_mask(0.25)
        assert both_bed.any()
        # Identical bed samples across candidates — exact float equality.
        assert np.array_equal(out_a[both_bed], out_b[both_bed])
        # And both sit at the shared per-file level, not a per-premix one.
        expected_bed = _expected_bed(y)
        assert np.array_equal(out_a[both_bed], expected_bed[both_bed])

    def test_source_array_never_mutated(self):
        sr = 8000
        y = np.full(sr, 0.5, dtype=np.float32)
        snapshot = y.copy()
        cp.render_premix(y, sr, 0.0, 0.5)
        assert np.array_equal(y, snapshot)

    def test_float32_output(self):
        out = cp.render_premix(np.zeros(100, dtype=np.float64), 8000, 0.0, 0.5)
        assert out.dtype == np.float32

    def test_empty_audio_is_empty_premix(self):
        out = cp.render_premix(np.zeros(0, dtype=np.float32), 8000, 0.0, 0.5)
        assert out.shape == (0,)

    def test_bad_period_raises(self):
        y = np.zeros(100, dtype=np.float32)
        for period in (0.0, -1.0, float("nan"), float("inf")):
            with pytest.raises(ValueError):
                cp.render_premix(y, 8000, 0.0, period)

    def test_negative_phase_degrades_to_zero(self):
        sr = 8000
        y = np.zeros(sr, dtype=np.float32)
        out = cp.render_premix(y, sr, -0.5, 0.5)
        tick = cp.render_tick(sr)
        assert np.array_equal(out[: tick.shape[0]], tick)  # first tick at 0


# ---------------------------------------------------------------------------
# Service — playback lifecycle against the fake stream
# ---------------------------------------------------------------------------


class TestPreviewLifecycle:
    def test_no_source_is_a_logged_noop(self, caplog):
        svc, estimator, factory = _service()
        with caplog.at_level(logging.WARNING, logger=cp.__name__):
            svc.preview(150.0)
        assert svc.playing_bpm is None
        assert factory.streams == []
        assert estimator.calls == []
        assert "no analysis loaded" in caplog.text

    def test_preview_starts_stream_with_source_geometry(self):
        svc, _, factory = _service(_mono_signal(sr=8000))
        svc.preview(150.0)
        assert svc.playing_bpm == 150.0
        assert len(factory.streams) == 1
        assert factory.last.samplerate == 8000
        assert factory.last.channels == 1
        assert factory.last.started == 1

    def test_stereo_source_streams_two_channels(self):
        sr = 8000
        y = np.zeros((sr, 2), dtype=np.float32)
        svc, _, factory = _service(_FakeSignal(y, sr, 1.0))
        svc.preview(120.0)
        assert factory.last.channels == 2

    def test_long_file_streams_mono_folded(self):
        sr = 1000
        y = np.zeros((181 * sr, 2), dtype=np.float32)
        svc, _, factory = _service(_FakeSignal(y, sr, 181.0))
        svc.preview(120.0)
        assert factory.last.channels == 1  # >180 s stereo folds to mono

    def test_short_file_keeps_channels(self):
        sr = 1000
        y = np.zeros((100 * sr, 2), dtype=np.float32)
        svc, _, factory = _service(_FakeSignal(y, sr, 100.0))
        svc.preview(120.0)
        assert factory.last.channels == 2

    def test_pumped_audio_is_the_premix(self):
        signal = _mono_signal(seconds=1.0, sr=8000, value=0.1)
        svc, estimator, factory = _service(signal)
        svc.preview(150.0)
        expected = cp.render_premix(
            signal.y_native, 8000, estimator.phase, estimator.period
        )
        block, done = factory.last.pump(512)
        assert not done
        assert np.array_equal(block[:, 0], expected[:512])
        block, _ = factory.last.pump(512)
        assert np.array_equal(block[:, 0], expected[512:1024])

    def test_stop_stops_and_closes(self):
        svc, _, factory = _service(_mono_signal())
        svc.preview(150.0)
        svc.stop()
        assert svc.playing_bpm is None
        assert factory.last.stopped == 1
        assert factory.last.closed == 1

    def test_stop_is_idempotent(self):
        svc, _, factory = _service(_mono_signal())
        svc.stop()  # nothing playing: safe
        svc.preview(150.0)
        svc.stop()
        svc.stop()
        assert factory.last.stopped == 1

    def test_playback_end_reads_stopped(self):
        signal = _mono_signal(seconds=0.1, sr=8000)  # 800 frames
        svc, _, factory = _service(signal)
        svc.preview(150.0)
        block, done = factory.last.pump(1024)  # more than the whole buffer
        assert done
        assert svc.playing_bpm is None
        assert np.all(block[800:] == 0.0)  # tail zero-padded

    def test_preview_after_natural_end_restarts_fresh(self):
        signal = _mono_signal(seconds=0.1, sr=8000)
        svc, estimator, factory = _service(signal)
        svc.preview(150.0)
        factory.last.pump(1024)  # play to the end
        svc.preview(150.0)
        assert len(factory.streams) == 2  # a NEW stream, from frame 0
        assert svc.playing_bpm == 150.0
        assert len(estimator.calls) == 1  # premix came from the cache
        expected = cp.render_premix(
            signal.y_native, 8000, estimator.phase, estimator.period
        )
        block, _ = factory.last.pump(4)
        assert np.array_equal(block[:, 0], expected[:4])

    def test_stream_factory_failure_is_nonfatal(self, caplog):
        def broken_factory(samplerate, channels, fill):
            raise RuntimeError("no audio device")

        svc = cp.ClickPreview(
            stream_factory=broken_factory, phase_estimator=_FakeEstimator()
        )
        svc.set_source(object(), _mono_signal())
        with caplog.at_level(logging.ERROR, logger=cp.__name__):
            svc.preview(150.0)
        assert svc.playing_bpm is None
        assert "audio output unavailable" in caplog.text

    def test_stream_start_failure_tears_down(self):
        class _NoStartStream(_FakeStream):
            def start(self):
                raise RuntimeError("device busy")

        class _Factory(_FakeFactory):
            def __call__(self, samplerate, channels, fill):
                stream = _NoStartStream(samplerate, channels, fill)
                self.streams.append(stream)
                return stream

        factory = _Factory()
        svc = cp.ClickPreview(stream_factory=factory, phase_estimator=_FakeEstimator())
        svc.set_source(object(), _mono_signal())
        svc.preview(150.0)
        assert svc.playing_bpm is None
        assert factory.last.stopped == 1  # cleaned up, not leaked


class TestBpmGuard:
    """R-M3-8: estimate_beat_phase's ValueError contract is guarded — the
    illegal call is never made."""

    @pytest.mark.parametrize(
        "bad", [0.0, -1.0, float("nan"), float("inf"), float("-inf"), None, "fast"]
    )
    def test_unusable_bpm_never_reaches_estimator(self, bad, caplog):
        svc, estimator, factory = _service(_mono_signal())
        with caplog.at_level(logging.WARNING, logger=cp.__name__):
            svc.preview(bad)
        assert estimator.calls == []
        assert factory.streams == []
        assert svc.playing_bpm is None
        assert "click preview ignored" in caplog.text

    def test_toggle_with_unusable_bpm_is_safe(self):
        svc, estimator, _ = _service(_mono_signal())
        svc.toggle(float("nan"))
        assert estimator.calls == []
        assert svc.playing_bpm is None


class TestToggle:
    def test_toggle_starts_then_stops(self):
        svc, _, factory = _service(_mono_signal())
        svc.toggle(150.0)
        assert svc.playing_bpm == 150.0
        svc.toggle(150.0)
        assert svc.playing_bpm is None
        assert factory.last.stopped == 1

    def test_toggle_other_bpm_switches_not_stops(self):
        svc, _, _ = _service(_mono_signal())
        svc.toggle(150.0)
        svc.toggle(75.0)
        assert svc.playing_bpm == 75.0


class TestPointerSwapAB:
    def test_swap_preserves_frame_index(self):
        # Distinct per-bpm phases on a silent bed: premix A ticks at 0/4000,
        # premix B at 2000/6000 — the post-swap window proves BOTH the frame
        # preservation and that the audible buffer really changed.
        sr = 8000
        signal = _mono_signal(seconds=2.0, sr=sr)
        est = _PerBpmPhaseEstimator({120.0: 0.0, 160.0: 0.25}, period=0.5)
        svc, _, factory = _service(signal, estimator=est)
        svc.preview(120.0)
        factory.last.pump(896)
        factory.last.pump(896)  # playhead at frame 1792
        svc.preview(160.0)  # A/B: same stream, same playhead (D3)
        assert len(factory.streams) == 1  # NOT restarted
        assert factory.last.started == 1
        assert svc.playing_bpm == 160.0
        expected_b = cp.render_premix(signal.y_native, sr, 0.25, 0.5)
        block, _ = factory.last.pump(512)  # frames 1792..2304 span B's tick @2000
        assert np.array_equal(block[:, 0], expected_b[1792:2304])
        assert float(np.max(np.abs(block))) > 0.0  # B's tick; A is silent here

    def test_swap_to_same_bpm_continues_seamlessly(self):
        signal = _mono_signal(seconds=1.0, sr=8000, value=0.1)
        svc, estimator, factory = _service(signal)
        svc.preview(150.0)
        factory.last.pump(512)
        svc.preview(150.0)  # table ▶ hear re-click: continue, don't restart
        assert len(factory.streams) == 1
        expected = cp.render_premix(signal.y_native, 8000, 0.25, 0.5)
        block, _ = factory.last.pump(16)
        assert np.array_equal(block[:, 0], expected[512:528])
        assert len(estimator.calls) == 1  # cached premix reused


class TestPremixCache:
    def test_lru_two_entries(self):
        svc, estimator, _ = _service(_mono_signal())
        svc.preview(100.0)
        svc.preview(120.0)
        assert len(estimator.calls) == 2
        svc.preview(100.0)  # hit
        svc.preview(120.0)  # hit
        assert len(estimator.calls) == 2
        svc.preview(140.0)  # evicts the least-recently-used entry (100)
        assert len(estimator.calls) == 3
        svc.preview(120.0)  # still cached
        assert len(estimator.calls) == 3
        svc.preview(100.0)  # evicted — re-rendered
        assert len(estimator.calls) == 4

    def test_cache_cleared_on_new_analysis(self):
        signal = _mono_signal()
        svc, estimator, _ = _service(signal)
        svc.preview(150.0)
        assert len(estimator.calls) == 1
        svc.set_source(object(), signal)  # new analysis (even the same file)
        svc.preview(150.0)
        assert len(estimator.calls) == 2  # the old premix was NOT reused

    def test_set_source_stops_playback(self):
        svc, _, factory = _service(_mono_signal())
        svc.preview(150.0)
        svc.set_source(object(), _mono_signal())
        assert svc.playing_bpm is None
        assert factory.streams[0].stopped == 1

    def test_clear_stops_and_forgets_source(self, caplog):
        svc, _, factory = _service(_mono_signal())
        svc.preview(150.0)
        svc.clear()
        assert svc.playing_bpm is None
        with caplog.at_level(logging.WARNING, logger=cp.__name__):
            svc.preview(150.0)
        assert "no analysis loaded" in caplog.text
        assert len(factory.streams) == 1  # nothing new started

    def test_stop_keeps_cache(self):
        # Only a new analysis clears the premixes; stop is just transport.
        svc, estimator, _ = _service(_mono_signal())
        svc.preview(150.0)
        svc.stop()
        svc.preview(150.0)
        assert len(estimator.calls) == 1


# ---------------------------------------------------------------------------
# Playback-state honesty — the ``stopped`` signal (Wire-stage contract)
# ---------------------------------------------------------------------------


class TestStoppedSignal:
    """``stopped`` fires on every transition to not-playing that is NOT
    immediately followed by a start — natural EOF, device death, explicit
    stop — and never from the audio callback. Tests drive the timer's slot
    (``_poll_playback``) directly instead of waiting out ~250 ms."""

    def test_natural_eof_emits_stopped_once_then_toggle_restarts(self):
        signal = _mono_signal(seconds=0.1, sr=8000)  # 800 frames
        svc, _, factory = _service(signal)
        hits = _stopped_log(svc)
        svc.preview(150.0)
        assert svc._poll.isActive()
        _, done = factory.last.pump(1024)
        assert done
        assert svc.playing_bpm is None  # truthful immediately
        assert hits == []  # the callback NEVER emits; the main-thread poll does
        svc._poll_playback()
        assert len(hits) == 1
        assert not svc._poll.isActive()  # poll stops once delivered
        svc._poll_playback()  # straggler tick: no double emit
        assert len(hits) == 1
        # Truthful state means the next toggle starts FRESH — no dead-click.
        svc.toggle(150.0)
        assert svc.playing_bpm == 150.0
        assert len(factory.streams) == 2
        assert len(hits) == 1  # starting emits nothing

    def test_explicit_stop_emits_once(self):
        svc, _, _ = _service(_mono_signal())
        hits = _stopped_log(svc)
        svc.preview(150.0)
        svc.stop()
        assert hits == [True]
        svc.stop()  # idempotent: nothing playing, nothing pending
        assert hits == [True]

    def test_stop_without_playback_never_emits(self):
        svc, _, _ = _service(_mono_signal())
        hits = _stopped_log(svc)
        svc.stop()
        assert hits == []

    def test_stop_after_unnotified_eof_emits_once(self):
        # EOF lands, the poll hasn't ticked yet, the user hits stop: the
        # pending transition is still delivered — exactly once.
        signal = _mono_signal(seconds=0.1, sr=8000)
        svc, _, factory = _service(signal)
        hits = _stopped_log(svc)
        svc.preview(150.0)
        factory.last.pump(1024)  # EOF; notification pending
        svc.stop()
        assert len(hits) == 1
        svc._poll_playback()  # delivers nothing more
        assert len(hits) == 1

    def test_eof_then_immediate_preview_suppresses_pending_emit(self):
        # The transition WAS followed by a start, so nothing is emitted —
        # a rapid re-preview after the end never flashes card state.
        signal = _mono_signal(seconds=0.1, sr=8000)
        svc, _, factory = _service(signal)
        hits = _stopped_log(svc)
        svc.preview(150.0)
        factory.last.pump(1024)  # EOF; poll hasn't run yet
        svc.preview(150.0)  # cold restart supersedes the notification
        assert svc.playing_bpm == 150.0
        svc._poll_playback()  # playing again: nothing to deliver
        assert hits == []

    def test_rapid_ab_swap_never_emits(self):
        sr = 8000
        signal = _mono_signal(seconds=2.0, sr=sr)
        est = _PerBpmPhaseEstimator({120.0: 0.0, 160.0: 0.25}, period=0.5)
        svc, _, factory = _service(signal, estimator=est)
        hits = _stopped_log(svc)
        svc.preview(120.0)
        for bpm in (160.0, 120.0, 160.0, 120.0):
            factory.last.pump(64)
            svc.preview(bpm)  # pointer swap: playback never stops
            svc._poll_playback()  # a poll tick between swaps sees "playing"
        assert hits == []
        assert svc.playing_bpm == 120.0
        assert len(factory.streams) == 1

    def test_device_failure_mid_play_emits_and_resets(self, caplog):
        svc, _, factory = _service(_mono_signal())
        hits = _stopped_log(svc)
        svc.preview(150.0)
        factory.last.pump(64)
        factory.last.active = False  # the stream died under us
        with caplog.at_level(logging.WARNING, logger=cp.__name__):
            svc._poll_playback()
        assert hits == [True]
        assert svc.playing_bpm is None
        assert "went inactive" in caplog.text
        assert factory.last.closed == 1  # reaped
        svc.preview(150.0)  # and the next preview starts fresh
        assert svc.playing_bpm == 150.0
        assert len(factory.streams) == 2

    def test_set_source_and_clear_emit_when_playing(self):
        svc, _, _ = _service(_mono_signal())
        hits = _stopped_log(svc)
        svc.preview(150.0)
        svc.set_source(object(), _mono_signal())  # stops playback → emits
        assert len(hits) == 1
        svc.preview(150.0)
        svc.clear()
        assert len(hits) == 2
        svc.clear()  # nothing playing: silent
        assert len(hits) == 2

    def test_start_failure_emits_stopped(self):
        # stream.start() raising AFTER state install is a transition with
        # no following start: emit, so a dead device can't stick a card.
        class _NoStartStream(_FakeStream):
            def start(self):
                raise RuntimeError("device busy")

        class _Factory(_FakeFactory):
            def __call__(self, samplerate, channels, fill):
                stream = _NoStartStream(samplerate, channels, fill)
                self.streams.append(stream)
                return stream

        svc = cp.ClickPreview(
            stream_factory=_Factory(), phase_estimator=_FakeEstimator()
        )
        svc.set_source(object(), _mono_signal())
        hits = _stopped_log(svc)
        svc.preview(150.0)
        assert svc.playing_bpm is None
        assert hits == [True]

    def test_factory_failure_does_not_emit(self):
        # The factory raising means no state was ever installed — playback
        # never transitioned, so nothing is emitted.
        def broken_factory(samplerate, channels, fill):
            raise RuntimeError("no audio device")

        svc = cp.ClickPreview(
            stream_factory=broken_factory, phase_estimator=_FakeEstimator()
        )
        svc.set_source(object(), _mono_signal())
        hits = _stopped_log(svc)
        svc.preview(150.0)
        assert hits == []

    def test_poll_timer_wiring(self):
        # ~250 ms main-thread poll, active exactly while playing.
        svc, _, _ = _service(_mono_signal())
        assert svc._poll.interval() == cp.STOP_POLL_INTERVAL_MS
        assert not svc._poll.isActive()
        svc.preview(150.0)
        assert svc._poll.isActive()
        svc._poll_playback()  # mid-play tick: keeps running, changes nothing
        assert svc._poll.isActive()
        assert svc.playing_bpm == 150.0
        svc.stop()
        assert not svc._poll.isActive()


# ---------------------------------------------------------------------------
# R-M3-9 — no confidence gate, structurally and with the real engine
# ---------------------------------------------------------------------------


class TestNoConfidenceGate:
    def test_confidence_is_never_read(self):
        # Every fake grid raises on .confidence; a full round-trip (preview,
        # A/B swap, pump, toggle off/on) never trips it.
        svc, _, factory = _service(_mono_signal())
        svc.preview(150.0)
        svc.preview(75.0)
        factory.last.pump(64)
        svc.toggle(75.0)
        svc.toggle(75.0)
        assert svc.playing_bpm == 75.0

    def test_real_engine_wrong_octave_still_plays(self):
        # Real machinery end-to-end: a synthetic drill beat previewed at the
        # WRONG octave (half-time) — exactly the low-confidence case a naive
        # >=0.5 gate would kill (real material measures 0.099-0.427 even at
        # the TRUE tempo, R-M3-9). It must render ticks and play.
        from rai_analyzer.beatgrid import estimate_beat_phase
        from rai_analyzer.config import ANALYSIS_SR, DEFAULT_CONFIG
        from rai_analyzer.io_audio import AudioSignal
        from rai_analyzer.synthetic import drill_pattern
        from rai_analyzer.tempogram import build_features

        y = drill_pattern(150.0, duration=4.0)
        signal = AudioSignal(
            path="synthetic-drill150",
            y=y,
            sr=ANALYSIS_SR,
            y_native=y,
            sr_native=ANALYSIS_SR,
            channels=1,
            duration=float(y.shape[0]) / ANALYSIS_SR,
        )
        features = build_features(signal, DEFAULT_CONFIG)

        factory = _FakeFactory()
        svc = cp.ClickPreview(stream_factory=factory)  # the REAL estimator
        svc.set_source(features, signal)

        svc.preview(75.0)  # wrong octave, low confidence: plays anyway
        assert svc.playing_bpm == 75.0
        grid = estimate_beat_phase(features, 75.0)  # deterministic re-derive
        expected = cp.render_premix(
            y, ANALYSIS_SR, grid.phase_seconds, grid.period_seconds
        )
        block, _ = factory.last.pump(4096)
        assert np.array_equal(block[:, 0], expected[:4096])
        # The premix genuinely differs from plain ducked music (ticks exist).
        ducked = y * np.float32(cp.MUSIC_DUCK_GAIN)
        assert float(np.max(np.abs(expected - ducked))) > 0.1

        svc.preview(150.0)  # A/B to the true tempo — pointer swap, no restart
        assert svc.playing_bpm == 150.0
        assert len(factory.streams) == 1


# ---------------------------------------------------------------------------
# Import hygiene — sounddevice stays inside the default factory (R-M3-8)
# ---------------------------------------------------------------------------


def test_sounddevice_import_is_guarded():
    """No module-level ``sounddevice`` import: the engine venv (and any CI
    box without an audio stack) must import this module clean. AST-pinned,
    same technique as the gate-boundary fence."""
    src_path = os.path.abspath(cp.__file__)
    with open(src_path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src_path)
    for node in tree.body:  # module level only — nested imports are the point
        assert not (
            isinstance(node, ast.Import)
            and any(a.name.split(".")[0] == "sounddevice" for a in node.names)
        ), "module-level 'import sounddevice' breaks the import guard"
        assert not (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] == "sounddevice"
        ), "module-level 'from sounddevice import ...' breaks the import guard"


def test_module_binds_no_sounddevice_and_qtcore_only():
    # The service's own globals never bind sounddevice (the import lives
    # inside the default factory). Qt is now a DECLARED dependency — the
    # ``stopped`` signal + poll timer — but QtCore only: QtWidgets must
    # never creep into a service, and the Qt-less engine venv skips this
    # file via importorskip instead of the old module-level Qt-less pin.
    bound_modules = [
        v for v in vars(cp).values() if isinstance(v, types.ModuleType)
    ]
    for mod in bound_modules:
        assert mod.__name__ != "sounddevice"
        assert not mod.__name__.startswith("PySide6.QtWidgets")
    for name in ("QObject", "QTimer", "Signal"):
        assert getattr(cp, name).__module__.startswith("PySide6.QtCore")
