"""Background analysis worker for the RAI v3 shell.

Runs the exact analysis composition the proven v2 pipeline uses (see
``rai_analyzer/gui.py:_run_analysis`` and ``rai_analyzer/analyzer.py``) but
Qt-native: an ``AnalysisWorker`` is moved to a ``QThread`` by the caller and
reports back over signals, so the UI thread never blocks on librosa.

Nothing is imported from ``rai_analyzer.gui`` — that module is the legacy
tkinter shell; only its call *semantics* are replicated here. Engine imports
happen inside ``run`` so importing this module stays cheap and so a broken
optional dependency (e.g. loudness) surfaces per-analysis, not at import.

The worker itself is stateless and reusable, but the shell treats analyses as
one-at-a-time: MainWindow owns a generation counter and drops stale
completions, so a worker never needs cancellation support in M0.
"""

from __future__ import annotations

import time
import traceback

from PySide6.QtCore import QObject, Signal, Slot

# R-M3-12 fallback copy — surfaced (once per affected analysis) by the shell
# when a user fingerprint exists on disk but fails shape validation.
PROFILE_FALLBACK_MESSAGE = "user profile unreadable — using packaged fingerprint"


class AnalysisWorker(QObject):
    """Analyze one file off the UI thread and emit the outcome.

    Signals:

    * ``finished(result, features, signal_obj, seconds, signal_result, md5)``
      — the ``AnalysisResult``, the ``Features`` (so plot panes never re-load
      the file), the ``AudioSignal``, the wall-clock analysis time in seconds
      (pure pipeline time, measured inside the worker), the M2
      ``SignalResult`` metrics record (or ``None`` — metrics are best-effort,
      appended fifth per R-M2-15 so the four existing positions never move),
      and the M3 whole-file md5 hex digest (or ``None`` — best-effort,
      appended sixth by the same additive rule; the session uses it for the
      ground-truth lookup, R-M3-3).
    * ``failed(message)`` — the last line of the traceback, suitable for a
      toast; never raises across the thread boundary.
    * ``profile_fallback(message)`` — emitted when a user fingerprint exists
      on disk but fails validation (R-M3-12): the analysis proceeds on the
      packaged fingerprint and the shell should surface ``message`` once.
    """

    finished = Signal(object, object, object, float, object, object)
    failed = Signal(str)
    profile_fallback = Signal(str)

    @Slot(str)
    def run(self, path: str) -> None:
        t0 = time.perf_counter()
        try:
            from rai_analyzer.contracts import AnalysisResult
            from rai_analyzer.io_audio import load_audio
            from rai_analyzer.resolver import resolve_tempo
            from rai_analyzer.tempogram import build_features

            cfg = self._analysis_config()
            signal = load_audio(path)
            features = build_features(signal, cfg)
            tempo = resolve_tempo(features, cfg)

            # Loudness is a nicety; never let it sink the tempo verdict
            # (same best-effort contract as analyzer.py).
            loudness = None
            try:
                from rai_analyzer.loudness import measure_loudness

                loudness = measure_loudness(signal)
            except Exception:
                loudness = None

            result = AnalysisResult(
                path=path,
                duration=signal.duration,
                sr=signal.sr_native,
                channels=signal.channels,
                tempo=tempo,
                loudness=loudness,
            )

            # M2 signal metrics ride the same best-effort contract as
            # loudness (R-M2-15): a metrics exception must never kill the
            # analysis. Log-and-None — the traceback goes to stderr so a
            # degraded run is diagnosable, and the UI honestly renders the
            # affected cards as absence with an "unavailable" chip.
            signal_result = None
            try:
                from rai_analyzer.metrics.compute import compute_signal_result

                signal_result = compute_signal_result(signal)
            except Exception:
                traceback.print_exc()
                signal_result = None

            # M3 identity: whole-file md5 for the ground-truth store lookup
            # (R-M3-3). Best-effort like the metrics record — a hashing
            # hiccup degrades to "no stored-truth lookup", never a failed
            # analysis. Computed off the UI thread on purpose (~1 ms/MB).
            md5 = None
            try:
                from rai_ui.services import ground_truth_store

                md5 = ground_truth_store.file_md5(path)
            except Exception:
                traceback.print_exc()
                md5 = None
        except Exception as exc:
            last_line = traceback.format_exception_only(type(exc), exc)[-1].strip()
            self.failed.emit(last_line)
            return
        self.finished.emit(
            result, features, signal, time.perf_counter() - t0, signal_result, md5
        )

    def _analysis_config(self):
        """The engine config for this run (R-M3-12 profile injection).

        When a VALIDATED user fingerprint exists under the App Support dir, a
        FRESH ``TempoConfig`` is built around it — ``DEFAULT_CONFIG`` is a
        module-level singleton shared with ``tempo_view`` and ``beatgrid``
        and is NEVER mutated. An invalid-but-present profile falls back to
        the packaged fingerprint and announces it over ``profile_fallback``;
        a simply-absent profile is the silent normal case.
        """
        import os

        from rai_analyzer.config import DEFAULT_CONFIG, FingerprintParams, TempoConfig

        from rai_ui.services import ground_truth_store

        profile_path = ground_truth_store.user_profile_path()
        if os.path.exists(profile_path):
            if ground_truth_store.validate_profile_file(profile_path):
                return TempoConfig(
                    fingerprint=FingerprintParams(fingerprint_path=profile_path)
                )
            self.profile_fallback.emit(PROFILE_FALLBACK_MESSAGE)
        return DEFAULT_CONFIG
