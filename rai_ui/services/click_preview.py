"""Click-grid preview — the M3 audio service (rulings R-M3-8/9/10).

ONE shared playback engine for the candidate table's "▶ hear" cells AND the
tiebreak overlay's preview buttons (R-M3-8): MainWindow owns a single
:class:`ClickPreview`, both surfaces call into it, and starting any preview
takes over from whatever was playing.

What plays (D4, concretized):

* The analyzed file's native-rate PCM (``AudioSignal.y_native``) with the
  music ducked **−3 dB** so the click cuts through a dense drill mix, plus
* **2 kHz sine-burst ticks, ~30 ms each**, placed drift-free at
  ``phase + k * period`` from the engine's ``estimate_beat_phase(features,
  bpm)`` — each tick's sample index is computed from the multiplication, so
  no float accumulation drift over long files.

Envelope choice (documented per R-M3-8 — "the click must not itself click"):
each burst gets a **2 ms raised-cosine fade-in** and a **10 ms raised-cosine
fade-out**, exactly zero at both endpoints. The short attack keeps the tick
percussive enough to judge grid lock against transients; the longer release
avoids the audible spectral splatter of a hard cut. A full-length Hann was
rejected: its ~15 ms attack smears the very transient the ear is trying to
line up.

Premix, cache, memory honesty:

* Premixes are rendered **offline per candidate** (pure numpy — tested
  exactly) and kept in an **LRU cache of 2** (``PREMIX_CACHE_MAX``), the A/B
  pair. ``set_source``/``clear`` (new analysis / drop) empty the cache: a
  premix built from the previous file's PCM must never survive into the next.
* Files longer than **180 s premix in MONO** (``MONO_FOLD_SECONDS``): a 273 s
  48 kHz stereo file costs ~105 MB per cached premix; folding halves it. The
  fold is a memory-honesty measure, documented here, judged by ear at
  acceptance.
* If the mix would exceed ``PEAK_CEILING`` (music near full scale + tick),
  the whole premix is scaled down to the ceiling — a one-shot normalization,
  never a hard clip.

A/B semantics (D3): calling :meth:`preview` while something is already
playing **pointer-swaps the buffer at the same frame index** — the playhead
is preserved, the stream keeps running, and the previous preview is thereby
stopped (R-M3-8's "starting any preview stops the previous" and the pointer
swap are the same mechanism). A cold :meth:`preview` starts from frame 0.

NO CONFIDENCE GATE — R-M3-9, binding: measured beatgrid confidence on real
ground-truth material is 0.099–0.427 at the TRUE tempo, so any threshold
would kill the feature on every real track. This module never reads
``BeatGrid.confidence`` (test-pinned); the click always renders at the
requested bpm with the best-estimated phase, and phase-lock quality is judged
by ears.

Fakeability (plan §3's "faked player" doctrine — CI has no audio device):

* ``sounddevice`` is imported ONLY inside the default stream factory; the
  module imports clean without it (the Qt-less engine venv collects this
  file and its tests).
* The constructor takes ``stream_factory(samplerate, channels, fill)`` — the
  default wraps ``sounddevice.OutputStream`` (callback-based, float32; NOT
  ``sd.play``); tests inject a fake and drive :meth:`ClickPreview._fill`
  directly. ``fill(outdata, frames) -> bool`` returns True when playback is
  finished (the real adapter then raises ``sd.CallbackStop``).
* ``phase_estimator(features, bpm) -> BeatGrid`` is injectable the same way;
  the default lazily imports ``rai_analyzer.beatgrid.estimate_beat_phase``.

``estimate_beat_phase`` raises ``ValueError`` on non-finite/≤0 bpm by
contract; :meth:`preview` guards exactly that precondition and no-ops with a
log instead of ever making the illegal call (R-M3-8; same no-op-with-a-log
discipline as ``session.confirm``/``undo``). A missing/failed audio device
degrades the same way — a preview must never crash the shell.

Threading: the PortAudio callback thread only touches playback state through
:meth:`_fill`, under the same lock the UI-thread methods use. No Qt anywhere
in this module.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from typing import Callable, Optional

import numpy as np

log = logging.getLogger(__name__)

#: Tick oscillator frequency — cuts through a dense drill mix (D4).
TICK_FREQ_HZ = 2000.0
#: Tick duration, seconds (~30 ms per R-M3-8).
TICK_SECONDS = 0.030
#: Raised-cosine attack, seconds (short = percussive; see module docstring).
TICK_FADE_IN_SECONDS = 0.002
#: Raised-cosine release, seconds (longer = no cut-off splatter).
TICK_FADE_OUT_SECONDS = 0.010
#: Peak amplitude of one tick, linear full-scale.
TICK_AMPLITUDE = 0.85
#: Music bed attenuation under the active click, dB (D4).
MUSIC_DUCK_DB = -3.0
#: The same, as a linear gain.
MUSIC_DUCK_GAIN = float(10.0 ** (MUSIC_DUCK_DB / 20.0))
#: Files longer than this premix in mono (memory honesty; module docstring).
MONO_FOLD_SECONDS = 180.0
#: LRU premix cache size — the A/B pair (R-M3-8).
PREMIX_CACHE_MAX = 2
#: Premix normalization ceiling (one-shot scale-down, never a hard clip).
PEAK_CEILING = 0.99


# ---------------------------------------------------------------------------
# Pure premix math (numpy only — tested exactly)
# ---------------------------------------------------------------------------


def render_tick(sr: int) -> np.ndarray:
    """One click: a ~30 ms 2 kHz sine burst with raised-cosine fades.

    Returns a float32 ``(n,)`` array, exactly zero at both endpoints (the
    click must not itself click — envelope rationale in the module
    docstring), peaking at ``TICK_AMPLITUDE``.
    """
    sr = int(sr)
    if sr <= 0:
        raise ValueError(f"sample rate must be positive, got {sr!r}")
    n = max(1, int(round(TICK_SECONDS * sr)))
    t = np.arange(n, dtype=np.float64) / sr
    burst = np.sin(2.0 * np.pi * TICK_FREQ_HZ * t)

    env = np.ones(n, dtype=np.float64)
    n_in = min(int(round(TICK_FADE_IN_SECONDS * sr)), n // 2)
    if n_in > 0:
        # 0 at sample 0, rising toward 1: 0.5 * (1 - cos(pi * k / n_in)).
        env[:n_in] = 0.5 * (1.0 - np.cos(np.pi * np.arange(n_in) / n_in))
    n_out = min(int(round(TICK_FADE_OUT_SECONDS * sr)), n - n_in)
    if n_out > 0:
        # Falling to exactly 0 at the last sample:
        # 0.5 * (1 + cos(pi * (k+1) / n_out)) for k = 0..n_out-1.
        env[n - n_out :] = 0.5 * (
            1.0 + np.cos(np.pi * (np.arange(n_out) + 1.0) / n_out)
        )

    return (TICK_AMPLITUDE * burst * env).astype(np.float32)


def render_premix(
    y: np.ndarray,
    sr: int,
    phase_seconds: float,
    period_seconds: float,
    *,
    fold_mono: bool = False,
) -> np.ndarray:
    """Music −3 dB + click ticks at ``phase + k·period`` (D4), offline.

    Parameters
    ----------
    y:
        Native-rate PCM, ``(n,)`` mono or ``(n, ch)`` (the ``AudioSignal
        .y_native`` orientation).
    sr:
        The PCM's sample rate.
    phase_seconds / period_seconds:
        The ``BeatGrid`` fields from ``estimate_beat_phase``. ``period`` must
        be finite and positive; a non-finite/negative phase degrades to 0.0
        (defensive only — the engine contract already guarantees
        ``phase in [0, period)``).
    fold_mono:
        Fold multichannel PCM to mono before mixing (the >180 s memory rule —
        the CALLER decides from ``AudioSignal.duration``; this function just
        does the math).

    Returns float32, same shape family as the (possibly folded) input. Each
    tick's start index is ``round((phase + k*period) * sr)`` — computed by
    multiplication per k, so placement never drifts. Ticks landing on every
    channel of a multichannel premix. If the mix would exceed
    ``PEAK_CEILING`` the whole buffer is scaled down once.
    """
    sr = int(sr)
    if sr <= 0:
        raise ValueError(f"sample rate must be positive, got {sr!r}")
    period = float(period_seconds)
    if not math.isfinite(period) or period <= 0.0:
        raise ValueError(f"period_seconds must be finite and positive, got {period!r}")
    phase = float(phase_seconds)
    if not math.isfinite(phase) or phase < 0.0:
        phase = 0.0

    arr = np.asarray(y, dtype=np.float32)
    if fold_mono and arr.ndim == 2:
        arr = arr.mean(axis=1, dtype=np.float32)

    out = arr * np.float32(MUSIC_DUCK_GAIN)  # fresh buffer; never mutates y
    n = out.shape[0]
    if n == 0:
        return out.astype(np.float32, copy=False)

    tick = render_tick(sr)
    k = 0
    while True:
        idx = int(round((phase + k * period) * sr))
        if idx >= n:
            break
        m = min(tick.shape[0], n - idx)
        if out.ndim == 1:
            out[idx : idx + m] += tick[:m]
        else:
            out[idx : idx + m, :] += tick[:m, None]
        k += 1

    peak = float(np.max(np.abs(out)))
    if peak > PEAK_CEILING:
        out *= np.float32(PEAK_CEILING / peak)
    return out.astype(np.float32, copy=False)


# ---------------------------------------------------------------------------
# Stream + phase-estimator defaults (both injectable — fakeability doctrine)
# ---------------------------------------------------------------------------


def _sounddevice_stream_factory(samplerate: int, channels: int, fill: Callable):
    """Default factory: a callback-mode ``sounddevice.OutputStream``.

    ``sounddevice`` is imported HERE, not at module level (R-M3-8: import-
    guarded — the engine venv and CI have no sounddevice/audio device; only
    a real playback attempt touches it). ``fill(outdata, frames) -> bool``
    returning True ends the stream via ``sd.CallbackStop``.
    """
    import sounddevice as sd

    def _callback(outdata, frames, _time_info, _status):
        if fill(outdata, frames):
            raise sd.CallbackStop

    return sd.OutputStream(
        samplerate=samplerate,
        channels=channels,
        dtype="float32",
        callback=_callback,
    )


def _default_phase_estimator(features, bpm: float):
    """Lazy import keeps this module cheap to import (worker.py precedent)."""
    from rai_analyzer.beatgrid import estimate_beat_phase

    return estimate_beat_phase(features, bpm)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class ClickPreview:
    """The one shared click-grid playback engine (R-M3-8).

    API (the Stage-3 wiring contract): :meth:`preview`, :meth:`toggle`,
    :meth:`stop`, :attr:`playing_bpm`, :meth:`set_source`, :meth:`clear`.
    """

    def __init__(
        self,
        stream_factory: Optional[Callable] = None,
        phase_estimator: Optional[Callable] = None,
    ) -> None:
        self._stream_factory = stream_factory or _sounddevice_stream_factory
        self._phase_estimator = phase_estimator or _default_phase_estimator

        self._lock = threading.Lock()
        self._features = None  # engine Features | None
        self._signal = None  # AudioSignal | None
        self._generation = 0  # bumped by set_source/clear; guards stale premixes
        self._cache: "OrderedDict[float, np.ndarray]" = OrderedDict()
        self._stream = None
        self._buffer: Optional[np.ndarray] = None  # always (n, ch) float32
        self._frame = 0
        self._playing_bpm: Optional[float] = None

    # -- source lifecycle ---------------------------------------------------

    def set_source(self, features, signal_obj) -> None:
        """A new analysis landed: adopt its payload, drop everything stale.

        Stops playback and clears the premix cache (R-M3-8 — a pointer-swap
        buffer built from the previous file's PCM must never keep playing
        under the new one).
        """
        self.stop()
        with self._lock:
            self._features = features
            self._signal = signal_obj
            self._generation += 1
            self._cache.clear()

    def clear(self) -> None:
        """No current analysis (begin/fail/drop): stop and forget the source."""
        self.stop()
        with self._lock:
            self._features = None
            self._signal = None
            self._generation += 1
            self._cache.clear()

    # -- playback -----------------------------------------------------------

    @property
    def playing_bpm(self) -> Optional[float]:
        """The bpm currently audible, or None (stopped / finished / never
        started). This is what the tiebreak cards' ▶/⏸ state reads."""
        with self._lock:
            return self._playing_bpm

    def preview(self, bpm) -> None:
        """Play the click-grid premix for ``bpm`` (table ▶ hear semantics —
        R-M3-10: always the clicked row's bpm).

        Already playing → pointer-swap at the preserved frame index (D3);
        the same bpm swap is a seamless continue, never a restart. Stopped →
        start from frame 0. Unusable bpm / no source / no audio device →
        no-op with a log, never a crash and never an illegal
        ``estimate_beat_phase`` call.
        """
        try:
            bpm = float(bpm)
        except (TypeError, ValueError):
            log.warning("click preview ignored — non-numeric bpm %r", bpm)
            return
        if not math.isfinite(bpm) or bpm <= 0.0:
            # estimate_beat_phase's ValueError contract, guarded up front
            # (R-M3-8): the illegal call is never made.
            log.warning("click preview ignored — unusable bpm %r", bpm)
            return

        with self._lock:
            features = self._features
            signal = self._signal
            generation = self._generation
        if features is None or signal is None:
            log.warning("click preview ignored — no analysis loaded")
            return

        try:
            buf = self._premix_for(bpm, features, signal, generation)
        except Exception:
            # A preview must never take the shell down; the log is the trail.
            log.exception("click premix failed — preview skipped")
            return
        if buf is None:  # source changed underneath us (stale generation)
            log.warning("click preview dropped — analysis changed during premix")
            return

        # Hot path: pointer-swap into the running stream (D3).
        with self._lock:
            if self._stream is not None and self._playing_bpm is not None:
                self._buffer = buf
                self._frame = min(self._frame, buf.shape[0])
                self._playing_bpm = bpm
                return

        # Cold path: (re)start a stream from frame 0.
        self._teardown_stream()
        try:
            stream = self._stream_factory(
                samplerate=int(signal.sr_native),
                channels=int(buf.shape[1]),
                fill=self._fill,
            )
        except Exception:
            log.exception("audio output unavailable — click preview skipped")
            return
        with self._lock:
            self._stream = stream
            self._buffer = buf
            self._frame = 0
            self._playing_bpm = bpm
        try:
            stream.start()
        except Exception:
            log.exception("audio stream failed to start — click preview skipped")
            self._teardown_stream()

    def toggle(self, bpm) -> None:
        """Tiebreak-card semantics: playing this bpm → stop; else preview it."""
        current = self.playing_bpm
        try:
            same = current is not None and float(bpm) == current
        except (TypeError, ValueError):
            same = False
        if same:
            self.stop()
        else:
            self.preview(bpm)

    def stop(self) -> None:
        """Stop playback (idempotent). The premix cache survives — only a new
        analysis clears it."""
        self._teardown_stream()

    # -- internals ----------------------------------------------------------

    def _fill(self, outdata, frames: int) -> bool:
        """Copy the next ``frames`` frames into ``outdata`` ``(frames, ch)``.

        Returns True when playback is finished (buffer exhausted or gone);
        the tail is zero-padded either way. Runs on the audio callback
        thread — everything under the shared lock, nothing else touched.
        """
        with self._lock:
            buf = self._buffer
            start = self._frame
            if buf is None:
                outdata[:] = 0.0
                self._playing_bpm = None
                return True
            n = min(int(frames), max(0, buf.shape[0] - start))
            if n > 0:
                outdata[:n, :] = buf[start : start + n, :]
            if n < frames:
                outdata[n:, :] = 0.0
            self._frame = start + n
            done = self._frame >= buf.shape[0]
            if done:
                # Natural end: the stream stops itself (CallbackStop); state
                # reads stopped immediately, the object is reaped lazily on
                # the next preview()/stop().
                self._playing_bpm = None
            return done

    def _teardown_stream(self) -> None:
        # Swap state out under the lock, but stop the stream OUTSIDE it:
        # PortAudio's stop() waits for the callback, and the callback wants
        # this same lock.
        with self._lock:
            stream = self._stream
            self._stream = None
            self._buffer = None
            self._frame = 0
            self._playing_bpm = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                log.warning("audio stream teardown failed", exc_info=True)

    def _premix_for(
        self, bpm: float, features, signal, generation: int
    ) -> Optional[np.ndarray]:
        """The cached ``(n, ch)`` float32 premix for ``bpm`` (LRU-2).

        Cache miss = one ``estimate_beat_phase`` call + one offline render
        (~tens of ms — recon-measured, cheap enough on demand). Returns None
        if the source generation changed while rendering (the stale premix is
        discarded, never cached, never played).
        """
        key = float(bpm)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and generation == self._generation:
                self._cache.move_to_end(key)
                return cached

        grid = self._phase_estimator(features, bpm)
        fold = float(signal.duration) > MONO_FOLD_SECONDS
        premix = render_premix(
            signal.y_native,
            int(signal.sr_native),
            float(grid.phase_seconds),
            float(grid.period_seconds),
            fold_mono=fold,
        )
        buf = premix[:, None] if premix.ndim == 1 else premix
        buf = np.ascontiguousarray(buf, dtype=np.float32)

        with self._lock:
            if generation != self._generation:
                return None
            self._cache[key] = buf
            self._cache.move_to_end(key)
            while len(self._cache) > PREMIX_CACHE_MAX:
                self._cache.popitem(last=False)
        return buf
