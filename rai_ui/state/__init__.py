"""UI state for the v3 desktop app.

Layering rule: this package's *pure* modules (``verdict``, ``formatters``)
import nothing from Qt — they are plain-Python reducers and string builders so
they can be unit-tested headless and collected by the engine CI job, which has
no PySide6 installed. The Qt-facing session object (``rai_ui.state.session``)
is the only module here allowed to import Qt, and this ``__init__`` must stay
import-free so that ``import rai_ui.state.verdict`` never drags Qt in.
"""
