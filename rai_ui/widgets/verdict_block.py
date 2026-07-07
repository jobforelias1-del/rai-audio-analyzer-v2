"""Verdict block (component C-05): the word, its reason, and the one action.

"A reason ALWAYS accompanies the word" (C-05): this card never shows a bare
verdict. It renders every ``VerdictView`` kind the reducer can produce —
Confident / Ambiguous / Confirmed · human / Working / — No file / — No tempo /
Error — on the rail geometry (radius 7, padding 11px 12px). State skins come
from the theme QSS via the ``verdict`` dynamic property; this module only
colors text and swaps content.

Doctrine enforced here:

* Ambiguous is a crafted state, not error styling — same geometry as
  Confident, red family, reason in full. Error, conversely, sits on the
  NEUTRAL surface (it has no design card of its own; red panels are reserved
  for the ambiguous verdict).
* The ◆ ambiguous mark is a drawn icon from ``rai_ui.theme.icons`` — never a
  font glyph (P3 drawn-icons rule). ✓ IS covered by the vendored Plex cmap,
  so it rides inside the word text.
* Reason lines render in full here (the rail has room); the meter bridge owns
  the one-line-ellipsized treatment.
* The red "Open tiebreak" action exists ONLY inside the ambiguous state
  (C-10); "undo" is an inline accent link on the confirmed card. Both are
  live-looking in M1 — wiring them to toasts is the shell's job (R6).
* The Working card's 2px sweep is decorative motion: it stops whenever the
  widget is hidden and the card is fully readable with the animation off.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rai_ui.state.tempo_view import EMPTY_VIEW, VerdictView
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_AMBIGUOUS_TEXT,
    COLOR_SEMANTIC_CONFIDENT_BASE,
    COLOR_SEMANTIC_CONFIDENT_TEXT,
    COLOR_SURFACE_ACTIVE,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
    MOTION_WORKING_SWEEP_MS,
)
from rai_ui.theme.icons import glyph_icon
from rai_ui.widgets import mono_font, ui_font

# ✓ is in the vendored Plex Mono cmap (P3:65) — safe as text, unlike ◆.
_CHECK = "✓"
_EM_DASH = "—"

# VerdictView.kind (VerdictKind value strings) → the QSS `verdict` dynamic
# property vocabulary (app.qss.tmpl: confident|ambiguous|confirmed|neutral|
# working|error).
_QSS_PROPERTY: dict[str, str] = {
    "confident": "confident",
    "confirmed_human": "confirmed",
    "ambiguous": "ambiguous",
    "working": "working",
    "error": "error",
    "no_file": "neutral",
    "no_tempo": "neutral",
}

# Word tint per kind (C-05 table). Semantic color tints the WORD only —
# never a numeral (design global rule).
_WORD_COLOR: dict[str, str] = {
    "confident": COLOR_SEMANTIC_CONFIDENT_BASE,
    "confirmed_human": COLOR_SEMANTIC_CONFIDENT_BASE,
    "ambiguous": COLOR_SEMANTIC_AMBIGUOUS_BASE,
}

# Body/reason tint per kind (falls back to muted for the neutral family).
_BODY_COLOR: dict[str, str] = {
    "confident": COLOR_SEMANTIC_CONFIDENT_TEXT,
    "confirmed_human": COLOR_SEMANTIC_CONFIDENT_TEXT,
    "ambiguous": COLOR_SEMANTIC_AMBIGUOUS_TEXT,
}


def verdict_qss_property(kind: str) -> str:
    """Map a ``VerdictView.kind`` to the theme QSS ``verdict`` property."""
    return _QSS_PROPERTY.get(kind, "neutral")


def word_color(kind: str) -> str:
    """Hex tint for the verdict word (neutral family → text.secondary)."""
    return _WORD_COLOR.get(kind, COLOR_TEXT_SECONDARY)


def body_color(kind: str) -> str:
    """Hex tint for reason/sub lines (neutral family → text.muted)."""
    return _BODY_COLOR.get(kind, COLOR_TEXT_MUTED)


def display_word(view: VerdictView, bridge: bool = False) -> str:
    """The rendered verdict word, glyph prefixes included.

    ``VerdictView.word`` carries the bare vocabulary; the design's leading
    glyphs are presentation (Console verbatim): ``✓ CONFIDENT`` /
    ``✓ CONFIRMED · HUMAN`` / ``— NO FILE`` / ``— NO TEMPO`` / ``WORKING…``.
    The ◆ before AMBIGUOUS is deliberately ABSENT here — it must be a drawn
    icon, so the widgets place it as a pixmap next to this text. The bridge's
    ambiguous word reads ``AMBIGUOUS — HUMAN TIEBREAK`` (CO:105). Error has
    no design card; it borrows the neutral "— " unavailability prefix.
    """
    kind = view.kind
    if kind in ("confident", "confirmed_human"):
        return f"{_CHECK} {view.word}"
    if kind == "ambiguous":
        return f"{view.word} {_EM_DASH} HUMAN TIEBREAK" if bridge else view.word
    if kind == "no_file":
        return f"{_EM_DASH} NO FILE"
    if kind in ("no_tempo", "error"):
        return f"{_EM_DASH} {view.word}"
    return view.word  # working: "WORKING…"


def diamond_pixmap(px: int, color: str):
    """The drawn ◆ mark at ``px`` logical pixels (never a font glyph)."""
    return glyph_icon("diamond", color).pixmap(QSize(px, px))


def type_pin(font: QFont) -> str:
    """Widget-level QSS type pin for a label whose font matters.

    The app-wide stylesheet's ``QWidget { font-family; font-size }`` rule
    outranks any ``QLabel.setFont`` (M0 landmine 6 — the nav/header pins are
    the established convention), so every designed type size restates
    family / pixel size / weight at widget-stylesheet level. The paired
    ``setFont`` call STAYS: it carries letter-spacing and fallback behavior
    QSS does not manage. Deriving the pin FROM the same ``QFont`` guarantees
    the two can never disagree.
    """
    return (
        f' font-family: "{font.family()}"; font-size: {font.pixelSize()}px;'
        f" font-weight: {int(font.weight())};"
    )


class SweepTrack(QWidget):
    """The Working card's 2px progress track with a 30%-wide accent sweep.

    Mirrors the Console's raiSweep keyframes: the sweep segment travels from
    x = −4% to x = 102% of the track every 1200 ms on the design easing,
    looping while visible. Purely decorative (TK motion policy): the
    animation stops whenever the widget hides so a stacked-away page never
    burns a timer, and the track still reads as a track when static.
    """

    _SWEEP_FRACTION = 0.30  # sweep segment width, fraction of the track
    _FROM = -0.04  # keyframes: from left:-4% …
    _TO = 1.02  # … to left:102%

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)  # 2px track (Console CO:559)
        self._active = False
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(self._FROM)
        self._anim.setEndValue(self._TO)
        self._anim.setDuration(MOTION_WORKING_SWEEP_MS)
        self._anim.setLoopCount(-1)
        easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
        # token: motion.easing = cubic-bezier(0.2, 0, 0, 1)
        easing.addCubicBezierSegment(QPointF(0.2, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
        self._anim.setEasingCurve(easing)
        self._anim.valueChanged.connect(lambda _v: self.update())
        self.hide()

    def set_active(self, active: bool) -> None:
        """Show + animate, or hide + stop. Idempotent."""
        self._active = active
        self.setVisible(active)  # show/hide events keep the animation honest
        self._sync()

    def is_running(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._sync()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._anim.stop()

    def _sync(self) -> None:
        if self._active and self.isVisible():
            if not self.is_running():
                self._anim.start()
        else:
            self._anim.stop()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        # token: color.surface.active (track) / radius 1 (Console CO:559)
        painter.setBrush(QColor(COLOR_SURFACE_ACTIVE))
        painter.drawRoundedRect(self.rect(), 1.0, 1.0)
        value = self._anim.currentValue()
        frac = float(value) if value is not None else self._FROM
        painter.setClipRect(self.rect())
        painter.setBrush(QColor(COLOR_ACCENT_BASE))  # token: color.accent.base
        painter.drawRect(
            QRectF(frac * self.width(), 0.0, self._SWEEP_FRACTION * self.width(), self.height())
        )
        painter.end()


class VerdictBlock(QFrame):
    """The rail's verdict card. Feed it any ``VerdictView`` via ``set_verdict``."""

    tiebreak_requested = Signal()
    undo_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # objectName + the `verdict` dynamic property drive the theme QSS skin.
        self.setObjectName("verdictBlock")
        self.setProperty("verdict", "neutral")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 11, 12, 11)  # C-05 padding 11px 12px
        layout.setSpacing(5)  # column gap 5 (ambiguous swaps to 7)
        self._layout = layout

        word_row = QHBoxLayout()
        word_row.setSpacing(6)
        self._icon_label = QLabel(self)  # the drawn ◆, ambiguous only
        self._icon_label.setFixedSize(13, 13)
        self._icon_label.hide()
        self._word_label = QLabel(self)
        word_font = mono_font(13, QFont.Weight.DemiBold)  # word 13/600
        self._word_label.setFont(word_font)
        self._word_pin = type_pin(word_font)  # re-applied on every set_verdict restyle
        word_row.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        word_row.addWidget(self._word_label, 0, Qt.AlignmentFlag.AlignVCenter)
        word_row.addStretch(1)
        layout.addLayout(word_row)

        # Ambiguous caps subline: "HUMAN TIEBREAK NEEDED" 11/600/0.05em.
        self._tiebreak_sub = QLabel(self)
        sub_font = ui_font(11, QFont.Weight.DemiBold)
        sub_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 105.0)  # 0.05em
        self._tiebreak_sub.setFont(sub_font)
        # token: color.semantic.ambiguous.text (letter-spacing rides the QFont)
        self._tiebreak_sub.setStyleSheet(
            f"color: {COLOR_SEMANTIC_AMBIGUOUS_TEXT};{type_pin(sub_font)}"
        )
        self._tiebreak_sub.hide()
        layout.addWidget(self._tiebreak_sub)

        # Neutral sub (working / no-file / no-tempo): 12px muted body line.
        self._neutral_sub = QLabel(self)
        neutral_sub_font = ui_font(12)
        self._neutral_sub.setFont(neutral_sub_font)
        self._neutral_sub.setWordWrap(True)
        self._neutral_sub.setStyleSheet(  # token: color.text.muted
            f"color: {COLOR_TEXT_MUTED};{type_pin(neutral_sub_font)}"
        )
        self._neutral_sub.hide()
        layout.addWidget(self._neutral_sub)

        # Reason lines — rendered IN FULL on the rail (bridge ellipsizes).
        self._reasons_container = QWidget(self)
        reasons_layout = QVBoxLayout(self._reasons_container)
        reasons_layout.setContentsMargins(0, 0, 0, 0)
        reasons_layout.setSpacing(5)
        self._reasons_layout = reasons_layout
        self._reason_labels: list[QLabel] = []
        self._reasons_container.hide()
        layout.addWidget(self._reasons_container)

        self._working_track = SweepTrack(self)
        layout.addWidget(self._working_track)

        # Confirmed card's closing line: "saved as ground truth · undo".
        self._undo_line = QLabel(self)
        undo_font = ui_font(12)
        self._undo_line.setFont(undo_font)
        self._undo_line.setStyleSheet(type_pin(undo_font))  # colors are inline rich text
        self._undo_line.setTextFormat(Qt.TextFormat.RichText)
        self._undo_line.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._undo_line.setText(
            # token: color.semantic.confident.text (line) / color.accent.base (link)
            f'<span style="color:{COLOR_SEMANTIC_CONFIDENT_TEXT}">saved as ground truth · '
            f'</span><a href="undo" style="color:{COLOR_ACCENT_BASE};'
            f'text-decoration:none">undo</a>'
        )
        self._undo_line.linkActivated.connect(lambda _href: self.undo_requested.emit())
        self._undo_line.hide()
        layout.addWidget(self._undo_line)

        # C-10: the red action exists ONLY inside ambiguous contexts.
        self._tiebreak_button = QPushButton("Open tiebreak", self)
        self._tiebreak_button.setObjectName("tiebreakButton")
        self._tiebreak_button.setFixedHeight(30)  # h30 (Console CO:545)
        self._tiebreak_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tiebreak_button.clicked.connect(self.tiebreak_requested.emit)
        self._tiebreak_button.hide()
        layout.addWidget(self._tiebreak_button)

        self._view: VerdictView = EMPTY_VIEW.readout.verdict
        self.set_verdict(self._view)

    # -- API ------------------------------------------------------------------

    def set_verdict(self, view: VerdictView) -> None:
        """Render ``view``. Idempotent — safe to call with the same view twice."""
        self._view = view
        kind = view.kind

        self.setProperty("verdict", verdict_qss_property(kind))
        # Dynamic-property QSS swaps need a re-polish to repaint (see app.qss.tmpl).
        self.style().unpolish(self)
        self.style().polish(self)
        self._layout.setSpacing(7 if kind == "ambiguous" else 5)

        self._word_label.setText(display_word(view))
        self._word_label.setStyleSheet(f"color: {word_color(kind)};{self._word_pin}")
        if kind == "ambiguous":
            self._icon_label.setPixmap(diamond_pixmap(13, COLOR_SEMANTIC_AMBIGUOUS_BASE))
            self._icon_label.show()
        else:
            self._icon_label.hide()

        # sub: ambiguous gets the caps subline; the neutral family gets the
        # 12px muted line; confident/confirmed carry no sub by design.
        if kind == "ambiguous" and view.sub:
            self._tiebreak_sub.setText(view.sub)
            self._tiebreak_sub.show()
            self._neutral_sub.hide()
        elif view.sub:
            self._neutral_sub.setText(view.sub)
            self._neutral_sub.show()
            self._tiebreak_sub.hide()
        else:
            self._tiebreak_sub.hide()
            self._neutral_sub.hide()

        for label in self._reason_labels:
            self._reasons_layout.removeWidget(label)
            label.deleteLater()
        self._reason_labels = []
        for reason in view.reasons:
            label = QLabel(reason, self._reasons_container)
            reason_font = ui_font(12)
            label.setFont(reason_font)
            label.setWordWrap(True)  # full reason, never truncated on the rail
            label.setStyleSheet(f"color: {body_color(kind)};{type_pin(reason_font)}")
            self._reasons_layout.addWidget(label)
            self._reason_labels.append(label)
        self._reasons_container.setVisible(bool(view.reasons))

        self._working_track.set_active(kind == "working")
        self._undo_line.setVisible(view.show_undo)
        self._tiebreak_button.setVisible(view.show_tiebreak)

    def view(self) -> VerdictView:
        """The last-rendered view (test/introspection hook)."""
        return self._view
