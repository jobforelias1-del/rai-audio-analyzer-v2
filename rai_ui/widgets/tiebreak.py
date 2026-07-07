"""Tiebreak overlay (component C-14): the flagship human-tiebreak flow.

"The flagship — overlays the candidate pane, 220ms entrance" (C-14). This
widget renders the approved Console's tiebreak overlay VERBATIM (04:306-345,
JS 04:742-751/857-861, per ruling R-M3-6): the top-3 ranked candidates as
cards, each with the 30px mono BPM numeral (R-M3-18: 04 + C-14 win over
C-07's 44px ladder), a relation chip computed against the ORIGINAL engine
primary, an in-band tag, the salience bar, and a click-grid preview button.

Doctrine enforced here (so the shell cannot get it wrong):

* **Selection is separate from preview** (C-14 verbatim). Two independent
  state fields — ``chosenIdx`` and ``previewIdx`` (04:625) — so a card can be
  selected, previewing, both, or neither. Clicking a card chooses it;
  clicking its preview button toggles preview WITHOUT selecting (the demo's
  ``stopPropagation``, 04:750). Selecting another card never stops a running
  preview; starting preview on another card moves the single preview slot.
* **✕ closes, preview stops, selection SURVIVES** (04:857): dismiss nulls
  ``previewIdx`` only — reopening shows the same chosen card. Confirm
  (04:861) also keeps ``chosenIdx``; only new candidates reset it.
* **Confirm is enabled only with a selection**: computed label
  ``Set {bpm} — save as ground truth`` vs the static "Pick a candidate"
  ghost (04:340-344). The click is guarded like the demo's ``if(chosen)``.
* **Keyboard (ruling R-M3-7**, wireframe 1d + RC's Esc gap-fill): ←/→ move
  the selection, Space toggles preview on the selected card, Enter chooses
  (select ONLY — confirming ground truth stays a deliberate, visible button
  click per D6), Esc closes. All child buttons are ``NoFocus`` so Space/Enter
  can never activate a focused button behind the overlay's back.
* **No audio here**: the preview button emits ``preview_requested(bpm)`` /
  ``preview_stop_requested()`` and the click-preview SERVICE (another
  module) is wired by MainWindow — this widget never imports it.
* ▶ / ⏸ / ✕ are drawn, never font glyphs (P3 rule — the vendored Plex cmap
  lacks all three; the copy constants keep them verbatim for tests and
  accessibility, the paint path draws them).

The overlay is mounted by ``CandidatePane`` as a raised child covering the
whole pane (design: ``position:absolute; inset:0`` over the pane, 04:308) —
geometry is the pane's job via ``set_target_geometry``; the 220ms raiIn
entrance (fade + 8px rise, motion token easing) is decorative and the overlay
is fully readable with the animation stopped.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rai_ui.state.tempo_view import CandidateRowView, ChipView, TempoViewModel
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_ACCENT_BG,
    COLOR_ACCENT_HOVER,
    COLOR_ACCENT_ON,
    COLOR_ACCENT_PRESSED,
    COLOR_BORDER_HAIRLINE,
    COLOR_BORDER_STRONG,
    COLOR_SEMANTIC_CONFIDENT_TEXT,
    COLOR_SURFACE_ACTIVE,
    COLOR_SURFACE_HOVER,
    COLOR_SURFACE_PANEL,
    COLOR_SURFACE_RAISED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    MOTION_GENTLE_MS,
)
from rai_ui.theme.icons import glyph_icon
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.chips import RelationshipChip
from rai_ui.widgets.verdict_block import type_pin

# --- verbatim design copy (04 Console; ▶/⏸/✕ drawn at paint time) -----------

TITLE_TEXT = "Human tiebreak — which grid locks?"
CLOSE_TEXT = "✕"  # accessibility name; the glyph itself is two drawn strokes
PREVIEW_IDLE_TEXT = "▶ preview click grid"
PREVIEW_ACTIVE_TEXT = "previewing click grid — ⏸"
BAND_IN_TEXT = "✓ in drill band"
BAND_OUT_TEXT = "outside band"
SALIENCE_LABEL_PREFIX = "salience "
FOOTER_HINT_TEXT = "▶ overlays a click track on the audio · pick the grid that locks"
FOOTER_SAVE_TEXT = "saved locally · feeds the engine's relearning"
CONFIRM_DISABLED_TEXT = "Pick a candidate"


def confirm_label(bpm_text: str) -> str:
    """The enabled confirm button's computed label (04:860)."""
    return f"Set {bpm_text} — save as ground truth"


# --- geometry literals (04:306-345) ------------------------------------------

MAX_CARDS = 3  # tb = d.cands.slice(0, 3) — exactly the top-3 ranked (04:742)
OVERLAY_RADIUS = 11
OVERLAY_MARGIN_H = 18  # overlay padding 16px 18px
OVERLAY_MARGIN_V = 16
OVERLAY_GAP = 10
CARD_RADIUS = 12
CARD_MIN_HEIGHT = 186  # card row min-height (04:315)
CARD_GAP = 12
BPM_PX = 30  # R-M3-18: 04/C-14's mono 30px wins over C-07's "l 44" ladder
CLOSE_SIZE = 26
PREVIEW_HEIGHT = 28
CONFIRM_HEIGHT = 38
_BAR_HEIGHT = 6
_BADGE_SIZE = 16  # selected-card check badge, top:12 right:12
_BADGE_INSET = 12
_ICON_PX = 10  # drawn ▶/⏸ size beside 11-12px text (candidate-table precedent)
_ICON_GAP = 5
_DOT_SIZE = 6  # the previewing button's pulsing dot
_DOT_GAP = 8
_PULSE_MS = 900  # raiPulse 900ms on the preview button (04:324 literal)
_ENTRANCE_RISE_PX = 8  # raiIn: fade + translateY(8px)→0 (04:19)


def _design_easing() -> QEasingCurve:
    """The motion token cubic-bezier(0.2, 0, 0, 1)."""
    easing = QEasingCurve(QEasingCurve.Type.BezierSpline)
    easing.addCubicBezierSegment(QPointF(0.2, 0.0), QPointF(0.0, 1.0), QPointF(1.0, 1.0))
    return easing


class _SalienceBar(QWidget):
    """The card's 6px salience track + accent fill (04:320)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._salience = 0.0
        self.setFixedHeight(_BAR_HEIGHT)

    def set_salience(self, salience: float) -> None:
        self._salience = min(1.0, max(0.0, float(salience)))
        self.update()

    @property
    def salience(self) -> float:
        return self._salience

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QRect(0, 0, self.width(), _BAR_HEIGHT)
        # token: color.surface.active — the h6 track (#232B34)
        painter.setBrush(QColor(COLOR_SURFACE_ACTIVE))
        painter.drawRoundedRect(track, 3, 3)
        # fill width = round(sal × 100)% of the track (04:748)
        percent = round(self._salience * 100)
        fill_width = round(track.width() * percent / 100)
        if fill_width > 0:
            # token: color.accent.base
            painter.setBrush(QColor(COLOR_ACCENT_BASE))
            painter.drawRoundedRect(QRect(0, 0, fill_width, _BAR_HEIGHT), 3, 3)
        painter.end()


class _PreviewButton(QPushButton):
    """The card's ▶ preview / previewing-⏸ toggle — the ONLY designed
    play/pause pair in the whole app (recon §3.2).

    Fully custom-painted: the ▶/⏸ glyphs must be drawn (P3), the previewing
    state carries a 6px dot pulsing at 900ms (opacity 1→0.3→1), and the
    hover accent swaps border/text/icon together. The pulse is decorative:
    it runs only while previewing AND visible, and the button reads
    identically with the animation stopped (dot solid).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._previewing = False
        # The verbatim copy rides QPushButton.text() for accessibility and
        # tests; paintEvent (fully custom) derives its drawn substrings from
        # the same constants, so the copy has exactly one truth.
        self.setText(PREVIEW_IDLE_TEXT)
        self.setFixedHeight(PREVIEW_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Keyboard is the overlay's job (R-M3-7); a focused button stealing
        # Space would fork the "Space = preview" semantics.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._idle_font = ui_font(12, QFont.Weight.Medium)  # 12/500 (04:327)
        self._active_font = ui_font(12, QFont.Weight.DemiBold)  # 12/600 (04:324)
        # token: color.text.secondary / color.accent.base
        self._play_icon = glyph_icon("play", COLOR_TEXT_SECONDARY)
        self._play_icon_accent = glyph_icon("play", COLOR_ACCENT_BASE)
        self._pause_icon = glyph_icon("pause", COLOR_ACCENT_BASE)

        self._dot_opacity = 1.0
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(_PULSE_MS)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, 0.3)
        self._pulse.setEndValue(1.0)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)

    # -- state ------------------------------------------------------------------

    @property
    def previewing(self) -> bool:
        return self._previewing

    def set_previewing(self, previewing: bool) -> None:
        previewing = bool(previewing)
        if previewing == self._previewing:
            return
        self._previewing = previewing
        self.setText(PREVIEW_ACTIVE_TEXT if previewing else PREVIEW_IDLE_TEXT)
        self._sync_pulse()
        self.update()

    @property
    def pulse_running(self) -> bool:
        return self._pulse.state() == QVariantAnimation.State.Running

    # -- animation plumbing -------------------------------------------------------

    def _on_pulse(self, value) -> None:
        self._dot_opacity = float(value)
        self.update()

    def _sync_pulse(self) -> None:
        should_run = self._previewing and self.isVisible()
        if should_run and not self.pulse_running:
            self._pulse.start()
        elif not should_run and self.pulse_running:
            self._pulse.stop()
            self._dot_opacity = 1.0

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().showEvent(event)
        self._sync_pulse()

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().hideEvent(event)
        self._sync_pulse()

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().enterEvent(event)
        self.update()  # hover accent needs a repaint under full-custom paint

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().leaveEvent(event)
        self.update()

    # -- painting -----------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        if self._previewing:
            self._paint_previewing(painter, rect)
        else:
            self._paint_idle(painter, rect)
        painter.end()

    def _paint_idle(self, painter: QPainter, rect: QRect) -> None:
        hovered = self.underMouse()
        if hovered:
            # hover: background #11333B, accent text/border (04:327)
            # token: color.accent.bg / color.accent.base
            painter.setBrush(QColor(COLOR_ACCENT_BG))
            pen = QPen(QColor(COLOR_ACCENT_BASE))
            text_color = COLOR_ACCENT_BASE
            icon = self._play_icon_accent
        else:
            # token: color.border.strong / color.text.secondary
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(COLOR_BORDER_STRONG))
            text_color = COLOR_TEXT_SECONDARY
            icon = self._play_icon
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)

        text = PREVIEW_IDLE_TEXT.removeprefix("▶ ")  # the leading ▶ is drawn
        text_width = QFontMetrics(self._idle_font).horizontalAdvance(text)
        group = _ICON_PX + _ICON_GAP + text_width
        x = rect.center().x() - group // 2
        icon.paint(
            painter,
            QRect(x, rect.center().y() - _ICON_PX // 2, _ICON_PX, _ICON_PX),
        )
        painter.setFont(self._idle_font)
        painter.setPen(QColor(text_color))
        painter.drawText(
            QRect(x + _ICON_PX + _ICON_GAP, rect.top(), text_width + 2, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )

    def _paint_previewing(self, painter: QPainter, rect: QRect) -> None:
        # filled accent state: bg #11333B, 1px #57C2D6, 12/600 accent (04:324)
        # token: color.accent.bg / color.accent.base
        painter.setBrush(QColor(COLOR_ACCENT_BG))
        pen = QPen(QColor(COLOR_ACCENT_BASE))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)

        text = PREVIEW_ACTIVE_TEXT.removesuffix(" ⏸")  # the trailing ⏸ is drawn
        text_width = QFontMetrics(self._active_font).horizontalAdvance(text)
        group = _DOT_SIZE + _DOT_GAP + text_width + _ICON_GAP + _ICON_PX
        x = rect.center().x() - group // 2

        # the 6px pulsing dot (raiPulse 900ms — opacity only, layout static)
        painter.save()
        painter.setOpacity(self._dot_opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_ACCENT_BASE))
        painter.drawEllipse(
            QRectF(x, rect.center().y() - _DOT_SIZE / 2, _DOT_SIZE, _DOT_SIZE)
        )
        painter.restore()

        painter.setFont(self._active_font)
        painter.setPen(QColor(COLOR_ACCENT_BASE))
        text_x = x + _DOT_SIZE + _DOT_GAP
        painter.drawText(
            QRect(text_x, rect.top(), text_width + 2, rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        self._pause_icon.paint(
            painter,
            QRect(
                text_x + text_width + _ICON_GAP,
                rect.center().y() - _ICON_PX // 2,
                _ICON_PX,
                _ICON_PX,
            ),
        )


class _CloseButton(QPushButton):
    """The 26×26 ✕ dismiss button (04:313). The ✕ is two drawn strokes —
    U+2715 is not in the vendored Plex cmap (P3 rule)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tiebreakClose")
        self.setFixedSize(CLOSE_SIZE, CLOSE_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAccessibleName(CLOSE_TEXT)
        # token: color.border.strong / color.surface.hover
        self.setStyleSheet(
            "QPushButton#tiebreakClose {"
            " background-color: transparent;"
            f" border: 1px solid {COLOR_BORDER_STRONG};"
            " border-radius: 5px; }"
            "QPushButton#tiebreakClose:hover {"
            f" background-color: {COLOR_SURFACE_HOVER}; }}"
        )

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().paintEvent(event)  # QSS border + hover wash
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # token: color.text.secondary — the design's 12px ✕ ≈ an 8px cross
        pen = QPen(QColor(COLOR_TEXT_SECONDARY))
        pen.setWidthF(1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cx, cy, r = self.width() / 2, self.height() / 2, 4.0
        painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
        painter.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))
        painter.end()


class _TiebreakCard(QWidget):
    """One candidate card (04:317-331): numeral, chip+band, salience, preview.

    Selection chrome (accent bg + 1.5px accent border + ✓ badge) and the
    default surface are painted here; content is child widgets so the type
    pins hold under the app stylesheet (landmine 8).
    """

    clicked = Signal()  # card body = choose (04:749)
    preview_toggled = Signal()  # the button; never selects (stopPropagation)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._selected = False
        self._row: Optional[CandidateRowView] = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(0)  # flex min-width:0 — cards may shrink evenly
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)  # card padding 14px 16px
        layout.setSpacing(7)  # card column gap 7

        # BPM numeral: IBM Plex Mono 30/600 (R-M3-18 — 30, not C-07's 44).
        self.bpm_label = QLabel(self)
        bpm_font = mono_font(BPM_PX, QFont.Weight.DemiBold)
        self.bpm_label.setFont(bpm_font)
        # token: color.text.primary
        self.bpm_label.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY};{type_pin(bpm_font)}")
        layout.addWidget(self.bpm_label)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.chip = RelationshipChip(self)
        chip_row.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.band_label = QLabel(self)
        band_font = ui_font(11, QFont.Weight.Medium)
        self.band_label.setFont(band_font)
        self._band_pin = type_pin(band_font)  # color swaps with band membership
        chip_row.addWidget(self.band_label, 0, Qt.AlignmentFlag.AlignVCenter)
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        self.bar = _SalienceBar(self)
        layout.addWidget(self.bar)

        self.salience_label = QLabel(self)
        salience_font = mono_font(11)
        self.salience_label.setFont(salience_font)
        # token: color.text.muted
        self.salience_label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED};{type_pin(salience_font)}"
        )
        layout.addWidget(self.salience_label)

        layout.addStretch(1)

        self.preview_button = _PreviewButton(self)
        self.preview_button.clicked.connect(self.preview_toggled.emit)
        layout.addWidget(self.preview_button)

    # -- data / state -------------------------------------------------------------

    def set_row(self, row: CandidateRowView, band: tuple[float, float]) -> None:
        self._row = row
        self.bpm_label.setText(row.bpm_text)
        # Tiebreak chips are computed against the ORIGINAL engine primary
        # (04:745) — `row.chip` IS that computation while the verdict is
        # ambiguous (the only state with a tiebreak entry point, R-M3-6) —
        # and render in the card's single neutral chip style (04:319 fixes
        # border #333D49 for every card; the table's amber-primary styling
        # deliberately does not apply here).
        self.chip.set_chip(ChipView(text=row.chip.text, kind="related"))
        lo, hi = band
        in_band = lo <= row.bpm <= hi  # band from the engine config, never hardcoded
        self.band_label.setText(BAND_IN_TEXT if in_band else BAND_OUT_TEXT)
        # token: color.semantic.confident.text / color.text.muted (04:746)
        band_color = COLOR_SEMANTIC_CONFIDENT_TEXT if in_band else COLOR_TEXT_MUTED
        self.band_label.setStyleSheet(f"color: {band_color};{self._band_pin}")
        self.bar.set_salience(row.salience)
        self.salience_label.setText(f"{SALIENCE_LABEL_PREFIX}{row.salience_text}")

    @property
    def row(self) -> Optional[CandidateRowView]:
        return self._row

    @property
    def selected(self) -> bool:
        return self._selected

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if selected != self._selected:
            self._selected = selected
            self.update()

    @property
    def previewing(self) -> bool:
        return self.preview_button.previewing

    def set_previewing(self, previewing: bool) -> None:
        self.preview_button.set_previewing(previewing)

    # -- interaction ----------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt naming
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    # -- painting ---------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        if self._selected:
            # selected: accent bg + 1.5px accent border (04:747)
            # token: color.accent.bg / color.accent.base
            painter.setBrush(QColor(COLOR_ACCENT_BG))
            pen = QPen(QColor(COLOR_ACCENT_BASE))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), CARD_RADIUS, CARD_RADIUS)
        else:
            # default: panel surface + 1px strong border (04:748)
            # token: color.surface.panel / color.border.strong
            painter.setBrush(QColor(COLOR_SURFACE_PANEL))
            pen = QPen(QColor(COLOR_BORDER_STRONG))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), CARD_RADIUS, CARD_RADIUS)

        if self._selected:
            # ✓ check badge, 16px accent circle at top:12 right:12 (04:329-331).
            # ✓ IS in the vendored Plex cmap, so it rides as painter text.
            badge = QRectF(
                self.width() - _BADGE_INSET - _BADGE_SIZE,
                _BADGE_INSET,
                _BADGE_SIZE,
                _BADGE_SIZE,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLOR_ACCENT_BASE))  # token: color.accent.base
            painter.drawEllipse(badge)
            painter.setFont(mono_font(10, QFont.Weight.Bold))  # 10/700
            painter.setPen(QColor(COLOR_ACCENT_ON))  # token: color.accent.on
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "✓")
        painter.end()


class TiebreakOverlay(QWidget):
    """The overlay itself: header, top-3 cards, confirm footer.

    State machine per the 04 demo JS (executable truth): ``_chosen_idx`` and
    ``_preview_idx`` are independent; every transition that stops a preview
    emits ``preview_stop_requested``; starting one emits
    ``preview_requested(bpm)`` (starting implicitly stops the previous —
    single preview slot, and the audio service swaps pointer-atomically).
    """

    preview_requested = Signal(float)  # bpm of the card whose preview starts
    preview_stop_requested = Signal()
    confirm_requested = Signal(float)  # the chosen bpm — Stage-3 wires session.confirm
    closed = Signal()  # ✕/Esc dismiss only (confirm speaks via confirm_requested)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("tiebreakOverlay")
        self._rows: tuple[CandidateRowView, ...] = ()
        self._chosen_idx: Optional[int] = None
        self._preview_idx: Optional[int] = None
        self._target_pos = QPoint(0, 0)
        # Keyboard lands here (R-M3-7); children are NoFocus by design.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # overflow-y:auto (04:308): the whole overlay column scrolls when the
        # pane is shorter than the content's minimum.
        scroll = QScrollArea(self)
        scroll.setObjectName("tiebreakScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Landmine 9: with any app stylesheet active, unmatched scroll chrome
        # paints palette-white — skin it widget-level, quiet dark handle.
        scroll.setStyleSheet(
            "QScrollArea#tiebreakScroll { background: transparent; border: none; }"
            # token: color.surface.active — the scrollbar handle
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            "QScrollBar::handle:vertical { background: "
            f"{COLOR_SURFACE_ACTIVE}; border-radius: 4px; min-height: 24px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical "
            "{ background: transparent; }"
        )
        content = QWidget(scroll)
        self._build_content(content)
        scroll.setWidget(content)
        # Landmine 9: setWidget re-enables autoFillBackground — re-clear AFTER.
        content.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        # raiIn entrance: fade (opacity effect — the toast's idiom) + 8px
        # rise over 220ms on the motion-token easing. Decorative only.
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._entrance = QVariantAnimation(self)
        self._entrance.setStartValue(0.0)
        self._entrance.setEndValue(1.0)
        self._entrance.setDuration(MOTION_GENTLE_MS)  # token: motion.gentle
        self._entrance.setEasingCurve(_design_easing())
        self._entrance.valueChanged.connect(self._on_entrance)

        self.hide()

    # -- construction ---------------------------------------------------------------

    def _build_content(self, content: QWidget) -> None:
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            OVERLAY_MARGIN_H, OVERLAY_MARGIN_V, OVERLAY_MARGIN_H, OVERLAY_MARGIN_V
        )
        layout.setSpacing(OVERLAY_GAP)

        # Header: title 15/600 · original ambiguity reason 12 secondary · ✕.
        header = QHBoxLayout()
        header.setSpacing(10)
        self.title_label = QLabel(TITLE_TEXT, content)
        title_font = ui_font(15, QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        # token: color.text.primary
        self.title_label.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY};{type_pin(title_font)}"
        )
        header.addWidget(self.title_label)
        self.reason_label = QLabel(content)
        reason_font = ui_font(12)
        self.reason_label.setFont(reason_font)
        # token: color.text.secondary — verdictReasonBase = d.reason (04:838)
        self.reason_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY};{type_pin(reason_font)}"
        )
        header.addWidget(self.reason_label)
        header.addStretch(1)
        self.close_button = _CloseButton(content)
        self.close_button.clicked.connect(self.dismiss)
        header.addWidget(self.close_button)
        layout.addLayout(header)

        # Cards row: flex 1, gap 12, min-height 186.
        cards_holder = QWidget(content)
        cards_holder.setMinimumHeight(CARD_MIN_HEIGHT)
        cards_row = QHBoxLayout(cards_holder)
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(CARD_GAP)
        self.cards: list[_TiebreakCard] = []
        for i in range(MAX_CARDS):
            card = _TiebreakCard(cards_holder)
            # Same-thread child wiring — the cross-thread functor landmine
            # (M0 #2) does not apply; default-arg binding pins the index.
            card.clicked.connect(lambda i=i: self._choose(i))
            card.preview_toggled.connect(lambda i=i: self._toggle_preview(i))
            card.hide()
            cards_row.addWidget(card, 1)
            self.cards.append(card)
        layout.addWidget(cards_holder, 1)

        # Confirm footer: hints 11 muted flanking, then the one action.
        footer = QHBoxLayout()
        footer.setSpacing(14)
        hint_font = ui_font(11)
        hint_row = QHBoxLayout()
        hint_row.setSpacing(_ICON_GAP)
        hint_icon = QLabel(content)
        # the copy's leading ▶ is drawn (P3) — token: color.text.muted
        hint_icon.setPixmap(glyph_icon("play", COLOR_TEXT_MUTED).pixmap(_ICON_PX, _ICON_PX))
        hint_row.addWidget(hint_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hint_label = QLabel(
            FOOTER_HINT_TEXT.removeprefix("▶ "), content
        )
        self.hint_label.setFont(hint_font)
        # token: color.text.muted
        self.hint_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED};{type_pin(hint_font)}")
        hint_row.addWidget(self.hint_label, 0, Qt.AlignmentFlag.AlignVCenter)
        footer.addLayout(hint_row)
        footer.addStretch(1)
        self.save_hint_label = QLabel(FOOTER_SAVE_TEXT, content)
        self.save_hint_label.setFont(hint_font)
        # token: color.text.muted
        self.save_hint_label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED};{type_pin(hint_font)}"
        )
        footer.addWidget(self.save_hint_label)

        self.confirm_button = QPushButton(CONFIRM_DISABLED_TEXT, content)
        self.confirm_button.setObjectName("tiebreakConfirm")
        self.confirm_button.setFixedHeight(CONFIRM_HEIGHT)
        self.confirm_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.confirm_button.clicked.connect(self._confirm)
        footer.addWidget(self.confirm_button)
        layout.addLayout(footer)

        self._style_confirm()

    def _style_confirm(self) -> None:
        """Enabled = solid accent action; no selection = quiet ghost with the
        static "Pick a candidate" copy (04:340-344). The click handler is
        guarded (demo's ``if(chosen)``), so the ghost is never a dead-feeling
        disabled Qt widget — it simply does nothing until a card is chosen."""
        if self._chosen_idx is not None:
            row = self._rows[self._chosen_idx]
            self.confirm_button.setText(confirm_label(row.bpm_text))
            self.confirm_button.setCursor(Qt.CursorShape.PointingHandCursor)
            # token: color.accent.base / .on / .hover / .pressed
            self.confirm_button.setStyleSheet(
                "QPushButton#tiebreakConfirm {"
                f" background-color: {COLOR_ACCENT_BASE}; color: {COLOR_ACCENT_ON};"
                " border: none; border-radius: 7px; padding: 0 18px;"
                " font-size: 13px; font-weight: 600; }"
                "QPushButton#tiebreakConfirm:hover {"
                f" background-color: {COLOR_ACCENT_HOVER}; }}"
                "QPushButton#tiebreakConfirm:pressed {"
                f" background-color: {COLOR_ACCENT_PRESSED}; }}"
            )
        else:
            self.confirm_button.setText(CONFIRM_DISABLED_TEXT)
            self.confirm_button.setCursor(Qt.CursorShape.ArrowCursor)
            # token: color.surface.raised / color.border.hairline / color.text.disabled
            self.confirm_button.setStyleSheet(
                "QPushButton#tiebreakConfirm {"
                f" background-color: {COLOR_SURFACE_RAISED};"
                f" border: 1px solid {COLOR_BORDER_HAIRLINE};"
                f" color: {COLOR_TEXT_DISABLED};"
                " border-radius: 7px; padding: 0 18px;"
                " font-size: 13px; font-weight: 600; }"
            )

    # -- public API (widget contract) --------------------------------------------------

    def set_view(self, vm: TempoViewModel) -> None:
        """Feed the current view-model: top-3 cards, reason line, band.

        A DIFFERENT candidate set (new analysis) resets selection and preview
        (the demo resets all tiebreak state on scenario change, 04:628-634);
        the SAME set re-rendering preserves both — closing and reopening the
        overlay must keep the chosen card (04:857).
        """
        rows = tuple(vm.candidates[:MAX_CARDS])
        if tuple(r.bpm for r in rows) != tuple(r.bpm for r in self._rows):
            self._set_preview(None)
            self._chosen_idx = None
        self._rows = rows
        # verdictReasonBase = the ORIGINAL ambiguity reason (04:838); the
        # view-model splits the engine's "; "-joined string — rejoin verbatim.
        self.reason_label.setText("; ".join(vm.readout.verdict.reasons))
        for i, card in enumerate(self.cards):
            if i < len(rows):
                card.set_row(rows[i], vm.band)
                card.show()
            else:
                card.hide()
        self._refresh_cards()
        self._style_confirm()

    def show_overlay(self) -> None:
        """Show + raise + focus + play the 220ms entrance."""
        self._entrance.stop()
        self._effect.setOpacity(1.0)
        self.move(self._target_pos)
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self._entrance.start()

    def set_target_geometry(self, rect: QRect) -> None:
        """The pane's geometry feed; safe to call during the entrance."""
        self._target_pos = rect.topLeft()
        self.resize(rect.size())
        if self._entrance.state() != QVariantAnimation.State.Running:
            self.move(self._target_pos)

    def dismiss(self) -> None:
        """✕ / Esc semantics (04:857): stop preview, KEEP selection, close."""
        self._set_preview(None)
        self.hide()
        self.closed.emit()

    @property
    def chosen_index(self) -> Optional[int]:
        return self._chosen_idx

    @property
    def preview_index(self) -> Optional[int]:
        return self._preview_idx

    @property
    def chosen_bpm(self) -> Optional[float]:
        return self._rows[self._chosen_idx].bpm if self._chosen_idx is not None else None

    # -- state transitions (04 demo JS verbatim) -----------------------------------------

    def _choose(self, index: int) -> None:
        if not (0 <= index < len(self._rows)) or index == self._chosen_idx:
            return
        self._chosen_idx = index
        self._refresh_cards()
        self._style_confirm()

    def _toggle_preview(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        # toggle: previewing card stops; any other card takes the single slot
        self._set_preview(None if self._preview_idx == index else index)

    def _set_preview(self, index: Optional[int]) -> None:
        if index == self._preview_idx:
            return
        self._preview_idx = index
        self._refresh_cards()
        if index is None:
            self.preview_stop_requested.emit()
        else:
            # Starting a preview implicitly stops the previous one — single
            # slot; the audio service swaps at the same frame (R-M3-8), so no
            # stop is emitted in between.
            self.preview_requested.emit(self._rows[index].bpm)

    def _confirm(self) -> None:
        if self._chosen_idx is None:
            return  # the demo's `if(chosen)` guard — ghost click is a no-op
        bpm = self._rows[self._chosen_idx].bpm
        self._set_preview(None)  # confirm nulls previewIdx (04:861)
        self.hide()  # overlay closes immediately; chosenIdx retained
        self.confirm_requested.emit(bpm)

    def _refresh_cards(self) -> None:
        for i, card in enumerate(self.cards):
            card.set_selected(i == self._chosen_idx)
            card.set_previewing(i == self._preview_idx)

    # -- keyboard (R-M3-7) -----------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 — Qt naming
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self._rows:
                if self._chosen_idx is None:
                    index = 0  # first press lands on the top-ranked card
                else:
                    step = 1 if key == Qt.Key.Key_Right else -1
                    index = min(len(self._rows) - 1, max(0, self._chosen_idx + step))
                self._choose(index)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter = choose, select ONLY — confirming ground truth stays an
            # explicit button click (D6: a deliberate, visible act).
            if self._rows and self._chosen_idx is None:
                self._choose(0)
            event.accept()
            return
        if key == Qt.Key.Key_Space:
            if self._chosen_idx is not None:
                self._toggle_preview(self._chosen_idx)
            event.accept()
            return
        super().keyPressEvent(event)

    # -- entrance plumbing --------------------------------------------------------------------

    def _on_entrance(self, value) -> None:
        fraction = float(value)
        self._effect.setOpacity(fraction)
        self.move(
            self._target_pos.x(),
            self._target_pos.y() + round(_ENTRANCE_RISE_PX * (1.0 - fraction)),
        )

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt naming
        self._entrance.stop()
        self._effect.setOpacity(1.0)  # a plain .show() must render solid
        super().hideEvent(event)

    # -- painting --------------------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # token: color.surface.raised — solid cover, radius 11 (04:308)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(COLOR_SURFACE_RAISED))
        painter.drawRoundedRect(QRectF(self.rect()), OVERLAY_RADIUS, OVERLAY_RADIUS)
        painter.end()
