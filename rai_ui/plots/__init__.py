"""Plot widgets and plot math for the v3 UI.

Layering rule: ``helpers`` and ``decimate`` are pure numpy/Python — no Qt, no
pyqtgraph — so plot math is unit-testable headless and collectable by the
engine CI job (which has no Qt). Widget modules added later in this package
may import pyqtgraph, but this ``__init__`` must stay import-free so that
``import rai_ui.plots.decimate`` never drags Qt in.
"""
