"""Top-level analysis orchestration: a file path in, an AnalysisResult out.

This is the single entry point the GUI, CLI, and validation harness all call.
Loudness is optional and isolated behind a try/except so a tempo analysis never
fails just because the loudness measurement did.
"""

from __future__ import annotations

from .config import DEFAULT_CONFIG, TempoConfig
from .contracts import AnalysisResult
from .io_audio import load_audio
from .resolver import resolve_tempo
from .tempogram import build_features


def analyze_file(
    path: str, cfg: TempoConfig = DEFAULT_CONFIG, with_loudness: bool = True
) -> AnalysisResult:
    """Analyze one audio file: tempo (with ambiguity verdict) + loudness."""
    signal = load_audio(path)
    features = build_features(signal, cfg)
    tempo = resolve_tempo(features, cfg)

    loudness = None
    if with_loudness:
        try:
            from .loudness import measure_loudness

            loudness = measure_loudness(signal)
        except Exception:
            # Loudness is a Tier-1 nicety; never let it sink the tempo verdict.
            loudness = None

    return AnalysisResult(
        path=path,
        duration=signal.duration,
        sr=signal.sr_native,
        channels=signal.channels,
        tempo=tempo,
        loudness=loudness,
    )
