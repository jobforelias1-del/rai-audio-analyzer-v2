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

Expanded 2026-07-12 (M5 acceptance finding #2, thinness half — Elias chose
the expand direction over collapse-to-button; existing structures only):

* a **profile identity row** under the title — the header chip's own
  ``DRILL · 140–170`` (imported, so chip and popover can never drift) as
  the active profile entry, anticipating design C-11's "drill-first, grows
  into a selector" without faking a clickable selector today;
* **hairline separators** framing the state block — the Console panel's
  own structure idiom, so the surface reads as sections, not a stub;
* an **honest gate hint** under the relearn button, visible only below the
  ≥3 gate — the disabled state now *says* what unlocks it instead of only
  looking disabled.

The relearn skip-report row stays out: it needs a persisted last-report
store surface (product decision), and this expansion is existing-data-only.

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
    COLOR_SEMANTIC_MARKER_PRIMARY_BASE,
    COLOR_SURFACE_PANEL,
    COLOR_SURFACE_RAISED,
    COLOR_TEXT_DISABLED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from rai_ui.widgets import mono_font, ui_font
from rai_ui.widgets.header import GENRE_CHIP_TEXT
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

# The honest-gate hint (M5 finding #2 expansion): shown only below the ≥3
# gate, so the disabled relearn button states its own unlock condition.
GATE_HINT_TEXT = f"relearn unlocks at {RELEARN_MIN_CONFIRMS} confirmed truths"

# The design's profile-popover footer, verbatim (04:83, 05:229).
FOOTER_TEXT = (
    "Profiles are learned locally. Tiebreak choices feed the engine's relearning."
)

POPOVER_WIDTH = 300  # comfortably fits the footer at 11px over two lines

# Placement gaps (M5 backlog item 2 — the overlap fix). DROP is the vertical
# gap under whatever edge the popover clears (header hairline or bridge
# strip); GAP is the horizontal breathing room kept from the metric rail.
POPOVER_DROP = 6
POPOVER_GAP = 8


def anchor_position(
    *,
    chip_right_x: int,
    header_bottom_y: int,
    popover_width: int,
    rail_left_x: Optional[int],
    bridge_bottom_y: Optional[int],
    min_x: int,
    screen_bottom_y: Optional[int] = None,
    popover_height: int = 0,
) -> QPoint:
    """Global top-left for the popover — chip-aligned but occlusion-free.

    The original anchor pinned the popover's top-right to the chip's
    bottom-right + 6px with no awareness of what sat underneath: at every
    window size it covered the rail's left 112px (half the verdict card plus
    the Primary BPM label) and started 6px above the header's bottom
    hairline. The rules here keep the designed right-alignment to the genre
    chip while dodging every fixed surface:

    * y drops below the HEADER's bottom edge (never slicing the hairline);
      in bridge mode it drops below the 76px strip instead — pass the
      bridge's global bottom as ``bridge_bottom_y`` only when the bridge is
      the visible readout;
    * in rail mode (``rail_left_x`` set), x is clamped so the popover's
      right edge stays ``POPOVER_GAP`` left of the rail — the popover reads
      as a popup over the plot, never as a broken half-covered card;
    * x never goes past ``min_x`` (the window's left content edge), so a
      narrow window degrades by overlapping plot, not by escaping the
      window;
    * with ``screen_bottom_y`` + ``popover_height`` supplied, y is clamped
      so the popover's bottom stays on the screen — a plain ``Qt.Popup``
      gets NO automatic screen-fitting from Qt (only QMenu computes its
      own), so a window dragged low would otherwise leave the relearn
      button / revert link / footer rendered below the screen edge and
      unreachable (post-ship review finding, 2026-07-12). The upward clamp
      may cover header chrome on a very low window — a popup over chrome
      beats controls that cannot be clicked.

    Pure math — the shell feeds global coordinates; the widget stays a dumb
    ``open_at`` target.
    """
    x = chip_right_x - popover_width
    if rail_left_x is not None:
        x = min(x, rail_left_x - popover_width - POPOVER_GAP)
    y = header_bottom_y + POPOVER_DROP
    if bridge_bottom_y is not None:
        y = bridge_bottom_y + POPOVER_DROP
    if screen_bottom_y is not None:
        y = min(y, screen_bottom_y - popover_height - POPOVER_DROP)
    return QPoint(max(x, min_x), y)


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

        # Profile identity row — the header chip's own text (imported, so
        # chip and popover can never drift), rendered in C-11's active-entry
        # idiom: the 7px amber marker dot ("ties the chip to the band shading
        # on the tempogram", 05:232 — the dot identifies the profile, it
        # judges nothing) + mono 12/600, mirroring the chip's own RichText
        # treatment. Entry chrome only — deliberately NOT a raised/selected
        # row, which could read as a dead click while there is one profile.
        self._profile_row = QLabel(self)
        profile_font = mono_font(12, QFont.Weight.DemiBold)
        self._profile_row.setFont(profile_font)
        self._profile_row.setTextFormat(Qt.TextFormat.RichText)
        self._profile_row.setText(
            # token: color.semantic.marker-primary.base (dot)
            f'<span style="color: {COLOR_SEMANTIC_MARKER_PRIMARY_BASE};">●</span>'
            f"&nbsp;{GENRE_CHIP_TEXT}"
        )
        self._profile_row.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; background: transparent; border: none;"  # token: color.text.primary
            + type_pin(profile_font)
        )
        layout.addWidget(self._profile_row)

        layout.addWidget(self._hairline())

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

        # Honest-gate hint — visible only below the ≥3 gate, so the disabled
        # button states its unlock condition instead of only looking disabled.
        self._gate_hint = QLabel(GATE_HINT_TEXT, self)
        hint_font = ui_font(11)
        self._gate_hint.setFont(hint_font)
        self._gate_hint.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent; border: none;"  # token: color.text.muted
            + type_pin(hint_font)
        )
        layout.addWidget(self._gate_hint)

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

        layout.addWidget(self._hairline())

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

    def _hairline(self) -> QFrame:
        """A 1px separator in the Console hairline idiom (sections, not stub)."""
        line = QFrame(self)
        line.setFixedHeight(1)
        line.setStyleSheet(
            f"background: {COLOR_BORDER_HAIRLINE}; border: none;"  # token: color.border.hairline
        )
        return line

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
        self._gate_hint.setVisible(not armed)
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
