"""Profile popover (R-M3-11): the header genre chip's click surface.

The approved design has NO relearn surface anywhere — the recon proved the
negative (the GUI's designed relearn responsibility is *writing ground
truth*; 'relearn' appears only as prose). R-M3-11 therefore rules a minimal,
RC-designed, Console-idiomatic popover on the header genre chip:

* a **profile source line** — what the engine actually reads on the next
  analysis: ``packaged fingerprint`` or ``user profile · relearned {date}``;
* the **confirmed-truth count**;
* a **"Relearn from N confirmed" button**, enabled only at
  N ≥ ``RELEARN_MIN_CONFIRMS`` (3) — relearn stays a deliberate, visible act
  (D6), and the disabled state borrows the tiebreak confirm-footer idiom
  (surface box, hairline border, disabled text — an honest gate, never a
  dead click that looks live);
* a **"revert to previous" link**, visible only while a one-step-revert
  backup exists — the verdict block's inline accent-link idiom;
* the design's own profile-popover footer copy, verbatim (04:83 / 05:229):
  *"Profiles are learned locally. Tiebreak choices feed the engine's
  relearning."* — the one piece of designed prose this surface has.

Chrome is the Console panel idiom: panel surface, hairline border, radius 7,
with every designed label ``setFont`` + ``type_pin``-pinned (M1 landmine 8).

The popover is presentation-only. It emits ``relearn_requested`` /
``revert_requested`` and renders whatever ``set_state`` pushes in; it imports
NO service module — the shell (Stage-3 wiring) reads the relearn service's
``profile_state()`` and connects the signals. That keeps this widget testable
in isolation and keeps the store/relearn machinery out of the widget layer.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from rai_ui.theme._tokens_gen import (
    COLOR_ACCENT_BASE,
    COLOR_ACCENT_HOVER,
    COLOR_ACCENT_ON,
    COLOR_BORDER_HAIRLINE,
    COLOR_SURFACE_PANEL,
    COLOR_SURFACE_RAISED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_SECONDARY,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.verdict_block import type_pin

# The relearn gate (R-M3-11 / plan D6): the button goes live at 3 effective
# confirmations. The count itself comes in through set_state — the popover
# never reads the store.
RELEARN_MIN_CONFIRMS = 3

POPOVER_TITLE = "TEMPO PROFILE"

# Source-line vocabulary (R-M3-11 verbatim).
SOURCE_PACKAGED_TEXT = "packaged fingerprint"
SOURCE_USER_TEXT = "user profile"

REVERT_LINK_TEXT = "revert to previous"

# The design's profile-popover footer, verbatim (04:83, 05:229).
FOOTER_TEXT = (
    "Profiles are learned locally. Tiebreak choices feed the engine's relearning."
)

POPOVER_WIDTH = 300  # comfortably fits the footer at 11px over two lines


def source_line(profile_kind: str, relearned_date: Optional[str]) -> str:
    """The profile source line (R-M3-11 copy).

    ``profile_kind`` is ``"user"`` when a validated user profile will be
    injected on the next analysis (the worker's own R-M3-12 test), anything
    else renders as the packaged fingerprint — including an invalid-but-
    present user file, because this line reports what the engine READS, not
    what exists on disk. The date rides only when known.
    """
    if profile_kind == "user":
        if relearned_date:
            return f"{SOURCE_USER_TEXT} · relearned {relearned_date}"
        return SOURCE_USER_TEXT
    return SOURCE_PACKAGED_TEXT


def relearn_label(confirmed_count: int) -> str:
    """The button label — always states the N it would learn from."""
    return f"Relearn from {confirmed_count} confirmed"


def confirmed_count_line(confirmed_count: int) -> str:
    """``3 confirmed truths`` — effective (not-retracted) confirmations."""
    noun = "truth" if confirmed_count == 1 else "truths"
    return f"{confirmed_count} confirmed {noun}"


class ProfilePopover(QFrame):
    """The small profile panel that pops from the header genre chip.

    Feed it state via ``set_state`` (idempotent); listen on
    ``relearn_requested`` / ``revert_requested``. ``open_at`` shows it as a
    Qt popup at a global position (outside-click dismisses it).
    """

    relearn_requested = Signal()
    revert_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("profilePopover")
        # A real popup: frameless top-level, dismissed by any outside click.
        # Translucent so the QSS rounded corners are actual transparency.
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Console panel chrome (R-M3-11): panel surface, hairline border,
        # radius 7. Widget-level — this RC-designed surface has no theme QSS
        # block, and widget styles keep it self-contained.
        self.setStyleSheet(
            f"QFrame#profilePopover {{ background: {COLOR_SURFACE_PANEL};"  # token: color.surface.panel
            f" border: 1px solid {COLOR_BORDER_HAIRLINE};"  # token: color.border.hairline
            " border-radius: 7px; }"
        )
        self.setFixedWidth(POPOVER_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        # Title — the pane-label style (11/500, 0.07em tracking, muted).
        self._title = QLabel(POPOVER_TITLE, self)
        title_font = ui_font(11, QFont.Weight.Medium)
        title_font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 107)
        self._title.setFont(title_font)
        self._title.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"  # token: color.text.muted
            + type_pin(title_font)
        )
        layout.addWidget(self._title)

        # Source line — a measurement-ish status, so mono 12 secondary (the
        # header file-chip's type treatment).
        self._source_label = QLabel(self)
        source_font = mono_font(12)
        self._source_label.setFont(source_font)
        self._source_label.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; background: transparent; border: none;"  # token: color.text.secondary
            + type_pin(source_font)
        )
        layout.addWidget(self._source_label)

        # Confirmed-truth count — mono 12 muted.
        self._count_label = QLabel(self)
        count_font = mono_font(12)
        self._count_label.setFont(count_font)
        self._count_label.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"  # token: color.text.muted
            + type_pin(count_font)
        )
        layout.addWidget(self._count_label)

        # The relearn action: accent when armed (the deliberate visible act),
        # the confirm-footer disabled idiom below the ≥3 gate (04:342 shape —
        # honest, designed-looking disablement, not a grey dead thing).
        self.relearn_button = QPushButton(self)
        self.relearn_button.setObjectName("relearnButton")
        self.relearn_button.setFixedHeight(30)
        button_font = ui_font(13, QFont.Weight.DemiBold)
        self.relearn_button.setFont(button_font)
        self.relearn_button.setStyleSheet(
            "QPushButton#relearnButton {"
            # token: color.accent.base / color.accent.on
            f" background-color: {COLOR_ACCENT_BASE}; color: {COLOR_ACCENT_ON};"
            " border: none; border-radius: 7px; padding: 0 14px;"
            " font-size: 13px; font-weight: 600; }"
            "QPushButton#relearnButton:hover {"
            # token: color.accent.hover
            f" background-color: {COLOR_ACCENT_HOVER}; }}"
            "QPushButton#relearnButton:disabled {"
            # token: color.surface.raised / color.border.hairline / color.text.disabled
            f" background-color: {COLOR_SURFACE_RAISED};"
            f" border: 1px solid {COLOR_BORDER_HAIRLINE};"
            f" color: {COLOR_TEXT_DISABLED}; }}"
        )
        self.relearn_button.clicked.connect(self.relearn_requested.emit)
        layout.addWidget(self.relearn_button)

        # Revert link — the verdict block's inline accent-link idiom; visible
        # only while a one-step backup exists.
        self._revert_link = QLabel(self)
        revert_font = ui_font(12)
        self._revert_link.setFont(revert_font)
        self._revert_link.setStyleSheet(
            f"background: transparent; border: none;{type_pin(revert_font)}"
        )
        self._revert_link.setTextFormat(Qt.TextFormat.RichText)
        self._revert_link.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._revert_link.setText(
            # token: color.accent.base (link)
            f'<a href="revert" style="color:{COLOR_ACCENT_BASE};'
            f'text-decoration:none">{REVERT_LINK_TEXT}</a>'
        )
        self._revert_link.linkActivated.connect(
            lambda _href: self.revert_requested.emit()
        )
        layout.addWidget(self._revert_link)

        # Designed footer copy (04:83), 11px muted, wrapped.
        self._footer = QLabel(FOOTER_TEXT, self)
        footer_font = ui_font(11)
        self._footer.setFont(footer_font)
        self._footer.setWordWrap(True)
        self._footer.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"  # token: color.text.muted
            + type_pin(footer_font)
        )
        layout.addWidget(self._footer)

        # Rendered defaults: the packaged, nothing-confirmed state.
        self._profile_kind = "packaged"
        self._relearned_date: Optional[str] = None
        self._confirmed_count = 0
        self._backup_exists = False
        self.set_state(
            profile_kind="packaged",
            relearned_date=None,
            confirmed_count=0,
            backup_exists=False,
        )

    # -- API ------------------------------------------------------------------

    def set_state(
        self,
        *,
        profile_kind: str,
        relearned_date: Optional[str],
        confirmed_count: int,
        backup_exists: bool,
    ) -> None:
        """Render a profile state. Idempotent — only mutates existing widgets.

        ``profile_kind`` is ``"user"`` or ``"packaged"`` (anything else is
        rendered as packaged — the honest fallback, matching the worker's
        actual injection behavior). The shell derives all four values from
        the relearn service's ``profile_state()``.
        """
        self._profile_kind = profile_kind
        self._relearned_date = relearned_date
        self._confirmed_count = int(confirmed_count)
        self._backup_exists = bool(backup_exists)

        self._source_label.setText(source_line(profile_kind, relearned_date))
        self._count_label.setText(confirmed_count_line(self._confirmed_count))
        self.relearn_button.setText(relearn_label(self._confirmed_count))
        armed = self._confirmed_count >= RELEARN_MIN_CONFIRMS
        self.relearn_button.setEnabled(armed)
        self.relearn_button.setCursor(
            Qt.CursorShape.PointingHandCursor if armed else Qt.CursorShape.ArrowCursor
        )
        self._revert_link.setVisible(self._backup_exists)

    def open_at(self, global_pos: QPoint) -> None:
        """Show the popup with its top-left at ``global_pos``."""
        self.move(global_pos)
        self.show()
        self.raise_()

    def state(self) -> dict:
        """The last-rendered state (test/introspection hook)."""
        return {
            "profile_kind": self._profile_kind,
            "relearned_date": self._relearned_date,
            "confirmed_count": self._confirmed_count,
            "backup_exists": self._backup_exists,
        }
