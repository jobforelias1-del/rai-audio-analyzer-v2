"""Report section (component C-20): the classic text report, verbatim.

The QTextEdit shows ``AnalysisResult.to_report()`` byte-for-byte — the same
text the CLI and the validation harness print. That verbatim guarantee is the
whole point of M0: the new shell must prove it renders the trusted output
before any richer views are built on top. Only presentation (mono 13,
175% line height) is added; the text itself is never touched.

``cli_command`` is imported lazily from ``rai_ui.state.formatters`` (built by
a parallel agent) so this module stays importable while that file lands;
tests stub the module via ``sys.modules``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QTextEdit, QVBoxLayout, QWidget

from rai_ui.widgets import mono_font, token

REPORT_FONT_PX = 13
REPORT_LINE_HEIGHT_PCT = 175.0
COPY_FEEDBACK_MS = 1500
COPY_LABEL = "Copy CLI command"
COPIED_LABEL = "Copied ✓"
EXPORT_LABEL = "Export .txt"
EMPTY_HINT = "Drop a WAV to analyze — the classic report renders here"


class ReportSection(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("reportSection")
        self._result = None  # AnalysisResult | None

        layout = QVBoxLayout(self)
        inset = int(token("space.pane-inset"))
        layout.setContentsMargins(inset, inset, inset, inset)
        layout.setSpacing(int(token("space.scale.3")))

        toolbar = QHBoxLayout()
        toolbar.setSpacing(int(token("space.scale.2")))
        self.copy_button = QPushButton(COPY_LABEL, self)
        self.export_button = QPushButton(EXPORT_LABEL, self)
        for button in (self.copy_button, self.export_button):
            button.setProperty("variant", "ghost")
            button.setProperty("size", "s")
            button.setEnabled(False)  # nothing to copy/export before a result
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.text_edit = QTextEdit(self)
        self.text_edit.setProperty("role", "report")
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(mono_font(REPORT_FONT_PX))
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_edit.setPlaceholderText(EMPTY_HINT)
        layout.addWidget(self.text_edit, 1)

        self.copy_button.clicked.connect(self._copy_cli_command)
        self.export_button.clicked.connect(self._export_txt)

    # -- data ---------------------------------------------------------------

    def set_result(self, result) -> None:
        """Render ``result.to_report()`` verbatim (presentation-only styling)."""
        self._result = result
        self.text_edit.setPlainText(result.to_report())
        self._apply_line_height()
        self.copy_button.setEnabled(True)
        self.export_button.setEnabled(True)

    def _apply_line_height(self) -> None:
        # Block format only — merging it never alters the text content.
        cursor = QTextCursor(self.text_edit.document())
        cursor.select(QTextCursor.SelectionType.Document)
        block_format = QTextBlockFormat()
        block_format.setLineHeight(
            REPORT_LINE_HEIGHT_PCT,
            QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
        )
        cursor.mergeBlockFormat(block_format)
        # Leave the view at the top of the report.
        top = QTextCursor(self.text_edit.document())
        top.movePosition(QTextCursor.MoveOperation.Start)
        self.text_edit.setTextCursor(top)

    # -- toolbar actions ------------------------------------------------------

    def _copy_cli_command(self) -> None:
        if self._result is None:
            return
        try:
            from rai_ui.state.formatters import cli_command
        except ImportError:
            # Parallel-build window only: formatters is another agent's file.
            self.copy_button.setToolTip("cli_command formatter not available yet")
            return
        QGuiApplication.clipboard().setText(cli_command(self._result.path))
        self.copy_button.setText(COPIED_LABEL)
        QTimer.singleShot(COPY_FEEDBACK_MS, lambda: self.copy_button.setText(COPY_LABEL))

    def _export_txt(self) -> None:
        if self._result is None:
            return
        default_name = Path(self._result.path).stem + "_report.txt"
        filename, _selected = QFileDialog.getSaveFileName(
            self, "Export report", default_name, "Text files (*.txt)"
        )
        if not filename:
            return
        Path(filename).write_text(self._result.to_report(), encoding="utf-8")
