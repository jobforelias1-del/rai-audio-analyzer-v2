"""Status bar (component C-04): 28px strip of quiet operational truth.

Left side is one mono line: engine version · analysis time · profile · the
privacy statement. It re-renders from stored state (working flag, seconds,
failure note) so signal ordering upstream can't leave it stale. Right side
reports drag-drop capability, decided once at startup.

M3 (R-M3-11): a relearn run reports its progress here — ``set_relearn_
progress`` slots a transient ``relearning {done}/{total}`` segment into the
line while the worker grinds through the confirmed files, and clears it on
completion/failure (the toast carries the outcome). Same stored-state
re-render discipline as everything else on the strip.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from rai_ui.widgets import mono_font, token

STATUSBAR_HEIGHT = int(token("size.statusbar"))  # 28

ENGINE_SEGMENT = "engine v3.0-m0"
PROFILE_SEGMENT = "profile drill"
PRIVACY_SEGMENT = "local — nothing leaves this machine"
WORKING_SEGMENT = "analyzing…"
FAILED_SEGMENT = "analysis failed"
NO_TIME_SEGMENT = "analysis —"

DND_READY = "drag-drop ready"
DND_UNAVAILABLE = "drag-drop unavailable — file picker active"


class StatusBar(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # "StatusBar" matches the theme QSS selector (QWidget#StatusBar).
        self.setObjectName("StatusBar")
        self.setFixedHeight(STATUSBAR_HEIGHT)

        self._working = False
        self._failed = False
        self._seconds: Optional[float] = None
        self._relearn_note: Optional[str] = None  # e.g. "relearning 2/3" (M3)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(int(token("space.scale.3")), 0, int(token("space.scale.3")), 0)

        # role="status": mono 11 muted comes from the theme QSS; the QFont is
        # only the unthemed fallback (tests run without the app stylesheet).
        self.left_label = QLabel(self)
        self.left_label.setProperty("role", "status")
        self.left_label.setFont(mono_font(11))
        layout.addWidget(self.left_label)
        layout.addStretch(1)
        self.right_label = QLabel(self)
        self.right_label.setProperty("role", "status")
        self.right_label.setFont(mono_font(11))
        layout.addWidget(self.right_label)

        self.set_dnd(True)
        self._render()

    # -- state setters (each re-renders; order-independent) ------------------

    def set_working(self, working: bool) -> None:
        self._working = working
        if working:
            self._failed = False
        self._render()

    def set_analysis_seconds(self, seconds: Optional[float]) -> None:
        self._seconds = seconds
        self._failed = False
        self._render()

    def set_failed(self) -> None:
        self._failed = True
        self._render()

    def set_dnd(self, available: bool) -> None:
        self.right_label.setText(DND_READY if available else DND_UNAVAILABLE)

    def set_relearn_progress(self, note: Optional[str]) -> None:
        """Show (or clear, with ``None``) the transient relearn segment."""
        self._relearn_note = note
        self._render()

    def _render(self) -> None:
        if self._working:
            middle = WORKING_SEGMENT
        elif self._failed:
            middle = FAILED_SEGMENT
        elif self._seconds is not None:
            middle = f"analysis {self._seconds:.1f} s"
        else:
            middle = NO_TIME_SEGMENT
        segments = [ENGINE_SEGMENT, middle]
        if self._relearn_note:
            segments.append(self._relearn_note)
        segments += [PROFILE_SEGMENT, PRIVACY_SEGMENT]
        self.left_label.setText(" · ".join(segments))
