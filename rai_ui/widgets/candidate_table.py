"""Candidate table (component C-13): the ranked-candidates card.

The table is the tempogram's legend — "ranked · the table is the legend"
(there is no plot legend widget, ever). Rows arrive on the view-model already
ranked by the engine (descending score, primary first) and render as-is:
selection is single-row, editing is off, and sorting is off *permanently*
because rank order is the engine's statement, not a user preference.

Architecture: QTableView + QAbstractTableModel + one row delegate (the
design's own Qt guidance, fixed by M0). Chips are **delegate-painted**, not
``setIndexWidget`` widgets — rationale:

* One rendering truth already exists: the delegate calls the same
  ``chips.paint_chip`` helper the standalone ``RelationshipChip`` widget
  wraps, so there is no paint-code fork to keep in sync.
* Row count is variable (~10-20) and every analysis resets the whole model;
  index widgets would churn 2 child QWidgets per row per analysis and then
  need ``deleteLater`` choreography (Landmine 1 territory) for zero gain —
  a repaint is free.
* Index widgets float above the delegate's row background, so the primary
  row's raised surface and the hover wash would need per-widget background
  coordination; painting inline keeps the row a single composition.

The ``▶ hear`` cell is likewise delegate-painted (the ▶/⏸ are drawn
``glyph_icon``s, never font glyphs — P3 rule) and clicks are routed through
the view's ``clicked`` signal; as of M3 the action is live: MainWindow
answers ``hear_requested`` with the shared click-preview engine plus the
verbatim design toast (R-M3-10).

R-M3-21 — the hear cell is a truthful toggle pair. The model carries ONE
``playing bpm`` (``set_playing_bpm``, exact-float keyed — the same
view-model float flows to the click service's cache keys, so ``==`` is the
documented equality); the row whose bpm matches renders ``⏸ stop`` in the
cell's accent treatment (the hover palette, calm — no pulsing dot at 24px;
that pulse belongs to the tiebreak card's 28px previewing button), every
other row keeps ``▶ hear``. The state follows the SERVICE, not click
bookkeeping: MainWindow sets it from ``ClickPreview.playing_bpm`` after each
toggle, clears it on the engine's ``stopped`` signal (natural EOF, device
death, external stop) and when a tiebreak-card preview takes the engine
over. ``set_rows`` deliberately PRESERVES the playing bpm — a same-analysis
re-render (e.g. an undo while a hear preview keeps playing) must not blank a
truthful stop cell; rows that no longer carry the bpm simply render ▶ hear.

Sizes are pinned widget-level per Landmine 6; the theme QSS
(``QFrame#candidatePane`` / ``QTableView#candidateTable``) owns surfaces and
the header rule only.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rai_ui.state.tempo_view import CandidateRowView, TempoViewModel
from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_ACCENT_BG,
    COLOR_BORDER_HAIRLINE,
    COLOR_BORDER_STRONG,
    COLOR_SEMANTIC_AMBIGUOUS_BASE,
    COLOR_SEMANTIC_AMBIGUOUS_HOVER,
    COLOR_SEMANTIC_AMBIGUOUS_ON,
    COLOR_SURFACE_HOVER,
    COLOR_SURFACE_RAISED,
    COLOR_SURFACE_ACTIVE,
    COLOR_PLOT_DATA_A,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    MOTION_WORKING_SWEEP_MS,
)
from rai_ui.theme.icons import glyph_icon
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.chips import CHIP_HEIGHT, paint_chip, paint_human_pill
from rai_ui.widgets.tiebreak import TiebreakOverlay

# Column order per the design grid `88px 168px 1fr 64px 56px 88px` with a
# 12px column gap (CO:273). Qt sections are contiguous (no grid gap), so each
# interior fixed column folds its trailing 12px gap into its section width
# (88→100, 168→180, 64→76, 56→68); the stretch column absorbs its own gap and
# the last column has no trailing gap (88 stays 88). ``content_rect`` below
# carves the design's cell content back out of these widened sections.
COL_BPM, COL_RELATION, COL_SALIENCE_BAR, COL_SALIENCE, COL_SCORE, COL_HEAR = range(6)
COLUMN_WIDTHS: tuple[int, ...] = (100, 180, -1, 76, 68, 88)  # -1 = stretch (1fr)
# Header labels pre-uppercased here — Qt QSS has no text-transform (see the
# theme template's header comment). Blank sections per the design.
HEADERS: tuple[str, ...] = ("BPM", "RELATION", "SALIENCE", "", "SCORE", "")

ROW_HEIGHT = 40  # design: row 40
ROW_GAP = 2  # design: 2px gap between rows (painted as a 1px inset each side)
_CELL_PAD_X = 10  # design: cell padding 0 10px
_COL_GAP = 12  # design: grid column-gap 12 — folded into section widths above
_ROW_RADIUS = 7


def content_rect(rect: QRect, column: int) -> QRect:
    """The design's cell content rect inside a (gap-widened) section rect.

    Every column gets the design's 10px cell padding on both sides; interior
    columns (all but the last) additionally reserve the 12px grid gap folded
    into their section's right edge, so content-to-content spacing between
    adjacent columns is 10 + 12 + 10 = 32px and right content edges (salience
    bar track, salience value, score) sit at the design's track positions.
    The header stays aligned for free: QSS pads ``QHeaderView::section`` 10px
    left, matching this rect's left edge for the left-aligned labels.
    """
    trailing = _CELL_PAD_X if column == len(COLUMN_WIDTHS) - 1 else _CELL_PAD_X + _COL_GAP
    return rect.adjusted(_CELL_PAD_X, 0, -trailing, 0)

HEAR_TEXT = "▶ hear"  # verbatim copy (model/accessibility); ▶ is drawn in paint
STOP_TEXT = "⏸ stop"  # playing-row copy (R-M3-21); ⏸ is drawn in paint
_HEAR_BUTTON_HEIGHT = 24  # size.hit-min
_HEAR_ICON_PX = 10
_HEAR_GAP = 5

TITLE_TEXT = "Candidates"
CAPTION_TEXT = "ranked · the table is the legend"
OPEN_TIEBREAK_TEXT = "Open tiebreak"
UNDO_TIEBREAK_TEXT = "Undo tiebreak"
EMPTY_TEXT_PREFIX = "no candidates"

# The whole CandidateRowView, for the delegate and for tests.
ROW_ROLE = Qt.ItemDataRole.UserRole + 1
# True on the row whose grid is audibly playing (R-M3-21) — the delegate's
# stop-state test, derived in the model from the one playing bpm.
PLAYING_ROLE = Qt.ItemDataRole.UserRole + 2

_PAGE_TABLE, _PAGE_EMPTY, _PAGE_SKELETON = range(3)


class CandidateModel(QAbstractTableModel):
    """Read-only model over the view-model's ``CandidateRowView`` tuple.

    Deliberately dumb: every string was already formatted by
    ``build_tempo_view`` (one truth), so ``data`` only routes fields.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: tuple[CandidateRowView, ...] = ()
        self._playing_bpm: float | None = None

    def set_rows(self, rows: tuple[CandidateRowView, ...]) -> None:
        # The playing bpm deliberately SURVIVES the reset (R-M3-21, module
        # docstring): a re-render of the same analysis while the hear preview
        # keeps playing must keep the stop cell truthful.
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    @property
    def playing_bpm(self) -> float | None:
        """The bpm whose row renders ⏸ stop, or None (test/introspection)."""
        return self._playing_bpm

    def set_playing_bpm(self, bpm: float | None) -> None:
        """Mark the row whose click grid is audibly playing (R-M3-21).

        ``None`` reverts every cell to ▶ hear. Equality is EXACT float
        equality — the same view-model float flows to the click service (its
        cache keys are ``float(bpm)``) and back here, so ``==`` is the one
        documented comparison; no tolerance, ever. Repaints ONLY the hear
        cells that actually changed (the old and new playing rows).
        """
        new = None if bpm is None else float(bpm)
        if new == self._playing_bpm:
            return
        old = self._playing_bpm
        self._playing_bpm = new
        roles = [Qt.ItemDataRole.DisplayRole, PLAYING_ROLE]
        for value in (old, new):
            if value is None:
                continue
            for row_index, row in enumerate(self._rows):
                if row.bpm == value:
                    index = self.index(row_index, COL_HEAR)
                    self.dataChanged.emit(index, index, roles)

    # -- QAbstractTableModel ------------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 — Qt naming
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802 — Qt naming
        return 0 if parent.isValid() else len(COLUMN_WIDTHS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        row = self._rows[index.row()]
        if role == ROW_ROLE:
            return row
        if role == PLAYING_ROLE:
            # Exact float equality — the documented comparison (R-M3-21).
            return self._playing_bpm is not None and row.bpm == self._playing_bpm
        if role == Qt.ItemDataRole.DisplayRole:
            playing = self._playing_bpm is not None and row.bpm == self._playing_bpm
            return {
                COL_BPM: row.bpm_text,
                COL_RELATION: row.chip.text,
                COL_SALIENCE_BAR: None,  # pure paint, no text
                COL_SALIENCE: row.salience_text,
                COL_SCORE: row.score_text,
                COL_HEAR: STOP_TEXT if playing else HEAR_TEXT,
            }[index.column()]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return HEADERS[section]
        return None

    def flags(self, index):
        # Selectable, never editable; sorting is disabled at the view.
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable


class CandidateRowDelegate(QStyledItemDelegate):
    """Paints complete candidate rows: background, numerals, chip, bar, hear.

    All fonts are set explicitly on the painter, so the app-wide QSS font
    rule (Landmine 6) cannot reach into cells.
    """

    def __init__(self, view: QTableView) -> None:
        super().__init__(view)
        self._view = view
        self._hover_row = -1
        # Cached drawn ▶/⏸ icons (P3: never a font glyph) for every button
        # state. token: color.text.secondary / color.accent.base
        self._play_icon = glyph_icon("play", COLOR_TEXT_SECONDARY)
        self._play_icon_accent = glyph_icon("play", COLOR_ACCENT_BASE)
        # The playing row's ⏸ (R-M3-21) — accent, like the tiebreak card's
        # previewing button (the only other drawn pause in the app).
        self._pause_icon_accent = glyph_icon("pause", COLOR_ACCENT_BASE)
        self._bpm_font = mono_font(15, QFont.Weight.DemiBold)
        self._salience_font = mono_font(11)
        self._score_font = mono_font(12)
        self._hear_font = ui_font(11, QFont.Weight.Medium)

    def set_hover_row(self, row: int) -> None:
        if row != self._hover_row:
            self._hover_row = row
            self._view.viewport().update()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 — Qt naming
        return QSize(option.rect.width(), ROW_HEIGHT + ROW_GAP)

    # -- painting -------------------------------------------------------------

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        row = index.data(ROW_ROLE)
        if row is None:
            return
        painter.save()
        painter.setClipRect(option.rect)
        self._paint_row_background(painter, option, index, row)

        column = index.column()
        inner = content_rect(option.rect, column)
        if column == COL_BPM:
            # token: color.text.primary — BPM mono 15/600
            painter.setFont(self._bpm_font)
            painter.setPen(QColor(COLOR_TEXT_PRIMARY))
            painter.drawText(
                inner,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                row.bpm_text,
            )
        elif column == COL_RELATION:
            y = option.rect.center().y() - CHIP_HEIGHT // 2
            width = paint_chip(painter, inner.left(), y, row.chip)
            if row.confirmed_human:
                # ✓ HUMAN tag next to the chip (M3 surface, built now).
                paint_human_pill(painter, inner.left() + width + 6, y)
        elif column == COL_SALIENCE_BAR:
            self._paint_salience_bar(painter, inner, row)
        elif column == COL_SALIENCE:
            # token: color.text.muted — salience value mono 11, 3dp
            painter.setFont(self._salience_font)
            painter.setPen(QColor(COLOR_TEXT_MUTED))
            painter.drawText(
                inner,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                row.salience_text,
            )
        elif column == COL_SCORE:
            # token: color.text.secondary — score mono 12, 2dp
            painter.setFont(self._score_font)
            painter.setPen(QColor(COLOR_TEXT_SECONDARY))
            painter.drawText(
                inner,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                row.score_text,
            )
        elif column == COL_HEAR:
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            playing = bool(index.data(PLAYING_ROLE))
            self._paint_hear_button(painter, inner, hovered, playing)
        painter.restore()

    def _paint_row_background(
        self, painter: QPainter, option, index, row: CandidateRowView
    ) -> None:
        """Row surface, drawn per-cell but clipped from the full-row rect so
        the 7px-radius corners land only on the row's real ends."""
        model = index.model()
        last = model.columnCount() - 1
        row_rect = self._view.visualRect(model.index(index.row(), 0)).united(
            self._view.visualRect(model.index(index.row(), last))
        )
        # 1px inset top+bottom = the design's 2px gap between 40px rows.
        bg = row_rect.adjusted(0, ROW_GAP // 2, 0, -ROW_GAP // 2)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if row.is_primary:
            # token: color.surface.raised / color.border.hairline
            painter.setBrush(QColor(COLOR_SURFACE_RAISED))
            pen = QPen(QColor(COLOR_BORDER_HAIRLINE))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.drawRoundedRect(bg.adjusted(0, 0, -1, -1), _ROW_RADIUS, _ROW_RADIUS)
        elif (
            option.state & QStyle.StateFlag.State_Selected
            or index.row() == self._hover_row
        ):
            # token: color.surface.hover — also the keyboard-selection wash
            # (the design defines no separate selected style; hover reads as
            # "this row is under the pointer/cursor" either way)
            painter.setBrush(QColor(COLOR_SURFACE_HOVER))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(bg, _ROW_RADIUS, _ROW_RADIUS)

    def _paint_salience_bar(
        self, painter: QPainter, inner: QRect, row: CandidateRowView
    ) -> None:
        track = QRect(inner.left(), inner.center().y() - 3, inner.width(), 6)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        # token: color.surface.active — the h6 track
        painter.setBrush(QColor(COLOR_SURFACE_ACTIVE))
        painter.drawRoundedRect(track, 3, 3)
        # fill width = round(salience × 100)% of the track (CO:736)
        percent = round(row.salience * 100)
        fill_width = round(track.width() * percent / 100)
        if fill_width > 0:
            fill = QRect(track.left(), track.top(), fill_width, track.height())
            # token: color.plot.data-a — same cyan as the tempogram curve
            painter.setBrush(QColor(COLOR_PLOT_DATA_A))
            painter.drawRoundedRect(fill, 3, 3)

    def _paint_hear_button(
        self, painter: QPainter, inner: QRect, hovered: bool, playing: bool
    ) -> None:
        button = QRect(
            inner.left(),
            inner.center().y() - _HEAR_BUTTON_HEIGHT // 2,
            inner.width(),
            _HEAR_BUTTON_HEIGHT,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if playing:
            # R-M3-21: the playing row's ⏸ stop — the cell's own hover-accent
            # palette, mirroring the tiebreak card's previewing button but
            # CALM (no pulsing dot; the cell is 24px). Hover adds nothing:
            # the state already wears the accent.
            # token: color.accent.bg / color.accent.base
            painter.setBrush(QColor(COLOR_ACCENT_BG))
            pen = QPen(QColor(COLOR_ACCENT_BASE))
            text_color = COLOR_ACCENT_BASE
            icon = self._pause_icon_accent
            label = "stop"
        elif hovered:
            # hover turns it accent (CL:288)
            # token: color.accent.bg / color.accent.base
            painter.setBrush(QColor(COLOR_ACCENT_BG))
            pen = QPen(QColor(COLOR_ACCENT_BASE))
            text_color = COLOR_ACCENT_BASE
            icon = self._play_icon_accent
            label = "hear"
        else:
            # token: color.border.strong / color.text.secondary
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(COLOR_BORDER_STRONG))
            text_color = COLOR_TEXT_SECONDARY
            icon = self._play_icon
            label = "hear"
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawRoundedRect(button.adjusted(0, 0, -1, -1), 5, 5)

        text_width = QFontMetrics(self._hear_font).horizontalAdvance(label)
        group_width = _HEAR_ICON_PX + _HEAR_GAP + text_width
        x = button.center().x() - group_width // 2
        icon_rect = QRect(
            x, button.center().y() - _HEAR_ICON_PX // 2, _HEAR_ICON_PX, _HEAR_ICON_PX
        )
        icon.paint(painter, icon_rect)
        painter.setFont(self._hear_font)
        painter.setPen(QColor(text_color))
        painter.drawText(
            QRect(x + _HEAR_ICON_PX + _HEAR_GAP, button.top(), text_width + 2, button.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            label,
        )


class _CandidateView(QTableView):
    """QTableView that feeds row-hover to the delegate (full-row hover wash)."""

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt naming
        delegate = self.itemDelegate()
        if isinstance(delegate, CandidateRowDelegate):
            delegate.set_hover_row(-1)
        super().leaveEvent(event)


class _SkeletonRows(QWidget):
    """Working-state placeholder: three h22 bars at 100/80/64% width.

    The 1200ms opacity pulse (1 → 0.3 → 1) is decorative — with the animation
    stopped the bars simply render solid, satisfying the motion policy that
    everything must work with animation disabled. The animation runs only
    while the widget is both active AND visible so a hidden pane never burns
    timer wakeups.
    """

    _WIDTH_FRACTIONS = (1.0, 0.8, 0.64)
    _BAR_HEIGHT = 22
    _BAR_RADIUS = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active = False
        self._opacity = 1.0
        self._pulse = QVariantAnimation(self)
        self._pulse.setDuration(MOTION_WORKING_SWEEP_MS)
        self._pulse.setStartValue(1.0)
        self._pulse.setKeyValueAt(0.5, 0.3)
        self._pulse.setEndValue(1.0)
        self._pulse.setLoopCount(-1)
        self._pulse.valueChanged.connect(self._on_pulse)

    @property
    def pulse_running(self) -> bool:
        return self._pulse.state() == QVariantAnimation.State.Running

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._sync_animation()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().showEvent(event)
        self._sync_animation()

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().hideEvent(event)
        self._sync_animation()

    def _sync_animation(self) -> None:
        should_run = self._active and self.isVisible()
        if should_run and not self.pulse_running:
            self._pulse.start()
        elif not should_run and self.pulse_running:
            self._pulse.stop()
            self._opacity = 1.0
            self.update()

    def _on_pulse(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 — Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        # token: color.surface.raised — skeleton bar surface
        painter.setBrush(QColor(COLOR_SURFACE_RAISED))
        for i, fraction in enumerate(self._WIDTH_FRACTIONS):
            y = i * (ROW_HEIGHT + ROW_GAP) + (ROW_HEIGHT - self._BAR_HEIGHT) // 2
            painter.drawRoundedRect(
                QRect(0, y, round(self.width() * fraction), self._BAR_HEIGHT),
                self._BAR_RADIUS,
                self._BAR_RADIUS,
            )
        painter.end()


class CandidatePane(QFrame):
    """The candidates card: header row + (table | empty copy | skeleton).

    ``set_rows`` consumes the whole ``TempoViewModel`` (rows AND the verdict
    that decides which header action shows); ``set_working`` overlays the
    skeleton state without disturbing the last rows.

    M3: the tiebreak overlay (C-14) mounts here as a raised child covering
    the WHOLE pane — the design's ``position:absolute; inset:0`` over the
    candidates card (04:308), the same raise idiom as the plots' working
    overlay. Its signals bubble through this pane; MainWindow opens it via
    ``open_tiebreak`` (ambiguous verdicts only, R-M3-6).
    """

    hear_requested = Signal(float)  # bpm of the clicked row
    tiebreak_requested = Signal()
    undo_requested = Signal()  # header "Undo tiebreak" ghost (R-M3-17)
    # Bubbled from the tiebreak overlay (audio service wired by MainWindow):
    preview_requested = Signal(float)
    preview_stop_requested = Signal()
    confirm_requested = Signal(float)
    # ✕/Esc/auto-dismiss (NOT confirm) — MainWindow stops ALL playback on it
    # (R-M3-8: overlay close stops playback, table-originated included).
    tiebreak_closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # QFrame#candidatePane in the theme QSS: panel surface, hairline, r12.
        self.setObjectName("candidatePane")
        self.setMinimumHeight(264)  # design: min-height 264

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)  # design: padding 14px 16px
        outer.setSpacing(8)  # design: internal gap 8

        outer.addLayout(self._build_header())

        self.model = CandidateModel(self)
        self.view = self._build_view()
        self.empty_label = self._build_empty_label()
        self.skeleton = _SkeletonRows(self)

        self._body = QStackedWidget(self)
        self._body.addWidget(self.view)  # _PAGE_TABLE
        self._body.addWidget(self.empty_label)  # _PAGE_EMPTY
        self._body.addWidget(self.skeleton)  # _PAGE_SKELETON
        outer.addWidget(self._body, 1)

        # The C-14 tiebreak overlay: raised child, NOT a stacked-body page —
        # it covers header and body alike (inset:0 over the pane).
        self.tiebreak = TiebreakOverlay(self)
        self.tiebreak.preview_requested.connect(self.preview_requested)
        self.tiebreak.preview_stop_requested.connect(self.preview_stop_requested)
        self.tiebreak.confirm_requested.connect(self.confirm_requested)
        self.tiebreak.closed.connect(self.tiebreak_closed)

        self._working = False
        self._refresh_body()

    # -- construction ---------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel(TITLE_TEXT, self)
        title.setFont(ui_font(15, QFont.Weight.DemiBold))
        # Pin type widget-level: the app-wide QSS font rule outranks QFont.
        # token: color.text.primary
        title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY};"
            ' font-family: "IBM Plex Sans"; font-size: 15px; font-weight: 600;'
        )
        header.addWidget(title)

        caption = QLabel(CAPTION_TEXT, self)
        caption.setFont(ui_font(11))
        # token: color.text.muted
        caption.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED};"
            ' font-family: "IBM Plex Sans"; font-size: 11px;'
        )
        header.addWidget(caption)
        header.addStretch(1)

        # Right-docked contextual actions: "Open tiebreak" (ambiguous) routes
        # to tiebreak_requested (MainWindow opens the overlay); the confirmed
        # state's "Undo tiebreak" ghost emits its own undo_requested
        # (R-M3-17 — in M1 both wrongly routed to tiebreak).
        self.tiebreak_button = QPushButton(OPEN_TIEBREAK_TEXT, self)
        self.tiebreak_button.setObjectName("tiebreakButton")
        self.tiebreak_button.setFixedHeight(30)
        self.tiebreak_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Candidates-header variant of the red action (CO:266-268): radius 7,
        # 13px/600, padding 0 14 — pinned widget-level over the shared
        # #tiebreakButton QSS block (whose radius-5 skin fits rail/bridge).
        self.tiebreak_button.setStyleSheet(
            "QPushButton#tiebreakButton {"
            # token: color.semantic.ambiguous.base / .on
            f" background-color: {COLOR_SEMANTIC_AMBIGUOUS_BASE};"
            f" color: {COLOR_SEMANTIC_AMBIGUOUS_ON};"
            " border: none; border-radius: 7px; padding: 0 14px;"
            " font-size: 13px; font-weight: 600; }"
            "QPushButton#tiebreakButton:hover {"
            # token: color.semantic.ambiguous.hover
            f" background-color: {COLOR_SEMANTIC_AMBIGUOUS_HOVER}; }}"
        )
        self.tiebreak_button.clicked.connect(self.tiebreak_requested.emit)
        self.tiebreak_button.hide()
        header.addWidget(self.tiebreak_button)

        self.undo_button = QPushButton(UNDO_TIEBREAK_TEXT, self)
        self.undo_button.setObjectName("undoTiebreakButton")
        self.undo_button.setFixedHeight(26)
        self.undo_button.setCursor(Qt.CursorShape.PointingHandCursor)
        # Ghost per CO:269-271: h26, padding 0 12, border strong, radius 7.
        self.undo_button.setStyleSheet(
            "QPushButton#undoTiebreakButton {"
            " background-color: transparent;"
            # token: color.text.secondary / color.border.strong
            f" color: {COLOR_TEXT_SECONDARY};"
            f" border: 1px solid {COLOR_BORDER_STRONG};"
            " border-radius: 7px; padding: 0 12px;"
            " font-size: 12px; font-weight: 500; }"
            "QPushButton#undoTiebreakButton:hover {"
            # token: color.surface.hover
            f" background-color: {COLOR_SURFACE_HOVER}; }}"
        )
        self.undo_button.clicked.connect(self.undo_requested.emit)
        self.undo_button.hide()
        header.addWidget(self.undo_button)
        return header

    def _build_view(self) -> QTableView:
        view = _CandidateView(self)
        view.setObjectName("candidateTable")
        view.setModel(self.model)
        self.delegate = CandidateRowDelegate(view)
        view.setItemDelegate(self.delegate)

        view.setShowGrid(False)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        view.setSortingEnabled(False)  # rank order is the engine's — never sorted
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setCornerButtonEnabled(False)
        view.setMouseTracking(True)  # per-cell hover for the ▶ hear accent
        view.entered.connect(self._on_cell_entered)
        view.clicked.connect(self._on_cell_clicked)

        view.verticalHeader().hide()
        view.verticalHeader().setDefaultSectionSize(ROW_HEIGHT + ROW_GAP)

        # With an application stylesheet active, QStyleSheetStyle paints
        # unmatched widgets from the PALETTE: the QHeaderView strip and the
        # scrollbar turned up #EFEFEF Base in the M1 preview shots. The theme
        # QSS only styles QHeaderView::section (per its comment), so pin the
        # header widget + a quiet dark scrollbar here, widget-level.
        view.setStyleSheet(
            "QHeaderView { background-color: transparent; }"
            # token: color.surface.active — the scrollbar handle
            "QScrollBar:vertical { background: transparent; width: 8px; }"
            "QScrollBar::handle:vertical { background: "
            f"{COLOR_SURFACE_ACTIVE}; border-radius: 4px; min-height: 24px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical "
            "{ background: transparent; }"
        )

        header = view.horizontalHeader()
        header.setSectionsClickable(False)
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        # Label style: 11px/500, tracking 0.07em, pre-uppercased in the model.
        label_font = ui_font(11, QFont.Weight.Medium)
        label_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107.0)
        header.setFont(label_font)
        for column, width in enumerate(COLUMN_WIDTHS):
            if width < 0:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
                view.setColumnWidth(column, width)
        return view

    def _build_empty_label(self) -> QLabel:
        label = QLabel(EMPTY_TEXT_PREFIX, self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(ui_font(13))
        # Empty is invitation, never error styling. token: color.text.muted
        label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED};"
            ' font-family: "IBM Plex Sans"; font-size: 13px;'
        )
        return label

    # -- public API (widget contract) ------------------------------------------

    def set_rows(self, vm: TempoViewModel) -> None:
        """Render the view-model: rows, header action, empty copy, overlay."""
        self.model.set_rows(vm.candidates)
        self.delegate.set_hover_row(-1)  # stale hover index after a reset

        verdict = vm.readout.verdict
        self.tiebreak_button.setVisible(verdict.show_tiebreak)
        self.undo_button.setVisible(verdict.show_undo)

        # The overlay always tracks the current view-model (a fresh analysis
        # resets its selection; the same analysis re-rendering preserves it).
        # Only an ambiguous verdict has a tiebreak entry point (R-M3-6:
        # show_tiebreak IS the ambiguous test) — any other verdict landing
        # while the overlay is up (new analysis, confirm, failure) dismisses
        # it, preview stopped, so an impossible state can't be reached.
        self.tiebreak.set_view(vm)
        if self.tiebreak.isVisible() and not verdict.show_tiebreak:
            self.tiebreak.dismiss()

        # `no candidates — {sub}` reuses the verdict's neutral sub-line (the
        # same {sub} the design threads through plot and table empty copy).
        sub = verdict.sub
        self.empty_label.setText(
            f"{EMPTY_TEXT_PREFIX} — {sub}" if sub else EMPTY_TEXT_PREFIX
        )
        self._refresh_body()

    def set_working(self, active: bool) -> None:
        """Skeleton bars while an analysis runs; back to rows/empty after."""
        self._working = bool(active)
        self._refresh_body()

    def set_playing_bpm(self, bpm: float | None) -> None:
        """R-M3-21: mark the row whose click grid is audibly playing (its
        hear cell renders ⏸ stop), or ``None`` to revert every cell to
        ▶ hear. Forwards to the model, which repaints just the changed hear
        cells. MainWindow drives this from the SERVICE's truth (post-toggle
        ``playing_bpm``, the ``stopped`` signal, tiebreak-preview takeover)."""
        self.model.set_playing_bpm(bpm)

    def open_tiebreak(self) -> None:
        """Raise the C-14 overlay over the whole pane (MainWindow calls this
        for ambiguous verdicts only — confirmed state has no entry point)."""
        self.tiebreak.set_target_geometry(self._tiebreak_rect())
        self.tiebreak.show_overlay()

    def close_tiebreak(self) -> None:
        """Dismiss the overlay if open (✕ semantics: preview stops, the
        selection survives). Safe to call when closed."""
        if self.tiebreak.isVisible():
            self.tiebreak.dismiss()

    # -- internals --------------------------------------------------------------

    def _tiebreak_rect(self) -> QRect:
        # inset:0 of the pane's padding box — inside the 1px QSS border, so
        # the overlay's radius-11 surface nests in the pane's radius-12 frame.
        return self.rect().adjusted(1, 1, -1, -1)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt naming
        super().resizeEvent(event)
        self._sync_tiebreak_geometry()

    def showEvent(self, event) -> None:  # noqa: N802 — Qt naming
        # Returning to this stack page with the overlay still open (R-M3-8
        # keeps nav from closing it) must re-cover the pane at its CURRENT
        # size — geometry may have changed while we were the hidden page.
        super().showEvent(event)
        self._sync_tiebreak_geometry()

    def _sync_tiebreak_geometry(self) -> None:
        """Keep an explicitly-shown overlay covering the whole pane.

        The test is ``not isHidden()`` — deliberately NOT ``isVisible()``:
        while this pane sits on a background stack page the overlay's
        effective visibility is False even though it is explicitly shown,
        yet QStackedLayout keeps resizing background pages. The old
        ``isVisible()`` guard skipped exactly those resizes, so the overlay
        came back at stale geometry after open → nav away → resize → return
        (adversarial-review live repro: back at 798×398 in an 1100×600
        window, live ▶ hear cells exposed around a nominally modal overlay).
        """
        if not self.tiebreak.isHidden():
            self.tiebreak.set_target_geometry(self._tiebreak_rect())
            self.tiebreak.raise_()

    def _refresh_body(self) -> None:
        if self._working:
            page = _PAGE_SKELETON
        elif self.model.rowCount() > 0:
            page = _PAGE_TABLE
        else:
            page = _PAGE_EMPTY
        self._body.setCurrentIndex(page)
        self.skeleton.set_active(self._working)

    def _on_cell_entered(self, index) -> None:
        self.delegate.set_hover_row(index.row() if index.isValid() else -1)

    def _on_cell_clicked(self, index) -> None:
        if not index.isValid() or index.column() != COL_HEAR:
            return
        row = index.data(ROW_ROLE)
        if row is not None:
            self.hear_requested.emit(row.bpm)
