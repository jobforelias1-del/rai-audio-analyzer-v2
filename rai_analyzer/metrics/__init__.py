"""Additive signal metrics (Phase 3 / M2) — spectrum, dynamics, bands, stereo.

This package is NEW in M2 and strictly additive: nothing in the frozen engine
imports it, and it never imports the tempo machinery (resolver / tempogram /
onsets / evidence) or the 22.05 kHz mono analysis view. Every measurement here
runs on ``AudioSignal.y_native`` at the native sample rate, in float64 — the
same doctrine as :mod:`rai_analyzer.loudness`.

Deliberately re-export-free (per the M2 architecture brief): import what you
need by full path, e.g.::

    from rai_analyzer.metrics.compute import compute_signal_result

Module map:

* ``params``    — every constant (band edges, Welch nperseg, mask limits)
* ``contracts`` — frozen result dataclasses + JSON-strict ``to_dict``
* ``spectrum``  — shared Welch PSD (computed once) + display spectrum
* ``dynamics``  — sample peak / whole-file RMS / crest factor
* ``bands``     — six-band energy shares integrated from the shared PSD
* ``stereo``    — mid/side width ratio + L/R Pearson correlation
* ``compute``   — ``compute_signal_result``, the one composition entry point
"""
