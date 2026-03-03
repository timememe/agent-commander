"""Input bar widget - message input + Send button."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme


class _MessageInput(QTextEdit):
    """QTextEdit that submits on Ctrl+Return."""

    def __init__(self, on_submit: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self._on_submit = on_submit

    def keyPressEvent(self, event) -> None:
        if (
            event.key() == Qt.Key.Key_Return
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._on_submit()
        else:
            super().keyPressEvent(event)


class InputBar(QWidget):
    """Bottom input area with multiline text field + Send button."""

    def __init__(
        self,
        on_submit: Callable[[str], None] | None = None,
        on_cwd_change: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._on_cwd_change = on_cwd_change
        self._cwd: str = ""
        self.setFixedHeight(96)
        self.setStyleSheet(
            f"background-color: {theme.BG_INPUT};"
            f"border-top: 1px solid {theme.BORDER};"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(0)

        msg_row = QWidget()
        msg_row.setStyleSheet("background: transparent;")
        mr = QHBoxLayout(msg_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(10)

        self._input = _MessageInput(on_submit=self._submit)
        self._input.setPlaceholderText("Type a message... (Ctrl+Return to send)")
        self._input.setMinimumHeight(74)
        mr.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedWidth(102)
        self._send_btn.setFixedHeight(74)
        self._send_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white; border: none;"
            " border-radius: 9px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #52B1FF; }"
            "QPushButton:pressed { background-color: #2D96E8; }"
        )
        self._send_btn.clicked.connect(self._submit)
        mr.addWidget(self._send_btn)

        root.addWidget(msg_row, stretch=1)

    # ------------------------------------------------------------------
    # CWD state (source of truth is now the Files panel)
    # ------------------------------------------------------------------

    def set_cwd(self, path: str) -> None:
        new_cwd = (path or "").strip()
        changed = new_cwd != self._cwd
        self._cwd = new_cwd
        if changed and self._on_cwd_change:
            self._on_cwd_change(self._cwd)

    def current_cwd(self) -> str:
        return self._cwd

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    def _submit(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        if self._on_submit:
            self._on_submit(text)

    def set_on_submit(self, callback: Callable[[str], None]) -> None:
        self._on_submit = callback

    def set_on_cwd_change(self, callback: Callable[[str], None] | None) -> None:
        self._on_cwd_change = callback
