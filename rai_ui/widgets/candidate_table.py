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

The ``▶ hear`` cell is likewise delegate-painted (the ▶ is a drawn
``glyph_icon``, never a font glyph — P3 rule) and clicks are routed through
the view's ``clicked`` signal; in M1 the action is present-but-inert (R6):
MainWindow answers ``hear_requested`` with the "arrives in M3" toast.

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

# Column order per the design grid `88px 168px 1fr 64px 56px 88px` (CO:273).
COL_BPM, COL_RELATION, COL_SALIENCE_BAR, COL_SALIENCE, COL_SCORE, COL_HEAR = range(6)
COLUMN_WIDTHS: tuple[int, ...] = (88, 168, -1, 64, 56, 88)  # -1 = stretch (1fr)
# Header labels pre-uppercased here — Qt QSS has no text-transform (see the
# theme template's header comment). Blank sections per the design.
HEADERS: tuple[str, ...] = ("BPM", "RELATION", "SALIENCE", "", "SCORE", "")

ROW_HEIGHT = 40  # design: row 40
ROW_GAP = 2  # design: 2px gap between rows (painted as a 1px inset each side)
_CELL_PAD_X = 10  # design: cell padding 0 10px
_ROW_RADIUS = 7

HEAR_TEXT = "▶ hear"  # verbatim copy (model/accessibility); ▶ is drawn in paint
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

_PAGE_TABLE, _PAGE_EMPTY, _PAGE_SKELETON = range(3)


class CandidateModel(QAbstractTableModel):
    """Read-only model over the view-model's ``CandidateRowView`` tuple.

    Deliberately dumb: every string was already formatted by
    ``build_tempo_view`` (one truth), so ``data`` only routes fields.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: tuple[CandidateRowView, ...] = ()

    def set_rows(self, rows: tuple[CandidateRowView, ...]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

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
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                COL_BPM: row.bpm_text,
                COL_RELATION: row.chip.text,
                COL_SALIENCE_BAR: None,  # pure paint, no text
                COL_SALIENCE: row.salience_text,
                COL_SCORE: row.score_text,
                COL_HEAR: HEAR_TEXT,
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
        # Cached drawn ▶ icons (P3: never a font glyph) in both button states.
        # token: color.text.secondary / color.accent.base
        self._play_icon = glyph_icon("play", COLOR_TEXT_SECONDARY)
        self._play_icon_accent = glyph_icon("play", COLOR_ACCENT_BASE)
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

        inner = option.rect.adjusted(_CELL_PAD_X, 0, -_CELL_PAD_X, 0)
        column = index.column()
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
            self._paint_hear_button(painter, inner, hovered)
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

    def _paint_hear_button(self, painter: QPainter, inner: QRect, hovered: bool) -> None:
        button = QRect(
            inner.left(),
            inner.center().y() - _HEAR_BUTTON_HEIGHT // 2,
            inner.width(),
            _HEAR_BUTTON_HEIGHT,
        )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if hovered:
            # hover turns it accent (CL:288)
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
        painter.drawRoundedRect(button.adjusted(0, 0, -1, -1), 5, 5)

        text_width = QFontMetrics(self._hear_font).horizontalAdvance("hear")
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
            "hear",
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
    """

    hear_requested = Signal(float)  # bpm of the clicked row
    tiebreak_requested = Signal()

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

        # Right-docked contextual actions. Both are M3 seams rendered live per
        # R6 (never disabled-greyed, never a dead click): each routes to
        # tiebreak_requested, which MainWindow answers with the M3 toast.
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
        self.undo_button.clicked.connect(self.tiebreak_requested.emit)
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
        """Render the view-model: rows, header action, empty copy."""
        self.model.set_rows(vm.candidates)
        self.delegate.set_hover_row(-1)  # stale hover index after a reset

        verdict = vm.readout.verdict
        self.tiebreak_button.setVisible(verdict.show_tiebreak)
        self.undo_button.setVisible(verdict.show_undo)

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

    # -- internals --------------------------------------------------------------

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
