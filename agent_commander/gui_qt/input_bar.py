"""Input bar widget - message input + Send / Run / Stop button."""

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
    """QTextEdit that fires on_submit on Ctrl+Return."""

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
    """Bottom input area with multiline text field + context-aware action button.

    Normal mode:  button = "Send"    → calls on_submit(text)
    Cycle mode:   button = "▶ Run"  → calls on_cycle_click()
                  button = "■ Stop" → calls on_cycle_click()  (same callback, app decides)
    """

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
        self._cycle_mode = False
        self._on_cycle_click: Callable[[], None] | None = None

        self.setFixedHeight(96)
        # BG_PANEL is set both on the widget and explicitly on QTextEdit children
        # because the global app stylesheet would otherwise override QTextEdit color.
        self.setStyleSheet(
            f"background-color: {theme.BG_PANEL};"
            f"QTextEdit {{ background-color: {theme.BG_PANEL}; border: none; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 10)
        root.setSpacing(0)

        msg_row = QWidget()
        msg_row.setStyleSheet("background: transparent;")
        mr = QHBoxLayout(msg_row)
        mr.setContentsMargins(0, 0, 0, 0)
        mr.setSpacing(10)

        self._input = _MessageInput(on_submit=self._handle_action)
        self._input.setPlaceholderText("Type a message... (Ctrl+Return to send)")
        self._input.setMinimumHeight(74)
        self._input.setStyleSheet(
            f"background-color: {theme.BG_PANEL};"
            f"color: {theme.TEXT};"
            "border: none;"
        )
        mr.addWidget(self._input, stretch=1)

        self._action_btn = QPushButton("Send")
        self._action_btn.setFixedWidth(102)
        self._action_btn.setFixedHeight(74)
        self._action_btn.setStyleSheet(self._send_style())
        self._action_btn.clicked.connect(self._handle_action)
        mr.addWidget(self._action_btn)

        root.addWidget(msg_row, stretch=1)

    # ------------------------------------------------------------------
    # CWD
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
    # Cycle mode
    # ------------------------------------------------------------------

    def set_cycle_mode(
        self,
        active: bool,
        on_cycle_click: Callable[[], None] | None = None,
    ) -> None:
        """Switch button between Send and Run/Stop modes."""
        self._cycle_mode = active
        self._on_cycle_click = on_cycle_click
        if active:
            self._action_btn.setText("▶ Run")
            self._action_btn.setStyleSheet(self._run_style())
            self._input.setPlaceholderText(
                "Enter cycle task… (Ctrl+Return to run / stop)"
            )
        else:
            self._action_btn.setText("Send")
            self._action_btn.setStyleSheet(self._send_style())
            self._input.setPlaceholderText("Type a message... (Ctrl+Return to send)")

    def set_cycle_running(self, running: bool) -> None:
        """Toggle between ▶ Run and ■ Stop visuals while cycle mode is active."""
        if not self._cycle_mode:
            return
        if running:
            self._action_btn.setText("■ Stop")
            self._action_btn.setStyleSheet(self._stop_style())
        else:
            self._action_btn.setText("▶ Run")
            self._action_btn.setStyleSheet(self._run_style())

    # ------------------------------------------------------------------
    # Text
    # ------------------------------------------------------------------

    def get_text(self) -> str:
        return self._input.toPlainText().strip()

    def set_placeholder(self, text: str) -> None:
        self._input.setPlaceholderText(text)

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _handle_action(self) -> None:
        if self._cycle_mode:
            if self._on_cycle_click:
                self._on_cycle_click()
        else:
            self._do_send()

    def _do_send(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        if self._on_submit:
            self._on_submit(text)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_on_submit(self, callback: Callable[[str], None]) -> None:
        self._on_submit = callback

    def set_on_cwd_change(self, callback: Callable[[str], None] | None) -> None:
        self._on_cwd_change = callback

    # ------------------------------------------------------------------
    # Button styles
    # ------------------------------------------------------------------

    @staticmethod
    def _send_style() -> str:
        return (
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white; border: none;"
            " border-radius: 6px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #52B1FF; }"
            "QPushButton:pressed { background-color: #2D96E8; }"
        )

    @staticmethod
    def _run_style() -> str:
        return (
            f"QPushButton {{ background-color: {theme.SUCCESS}; color: white; border: none;"
            " border-radius: 6px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4DD68A; }"
            "QPushButton:pressed { background-color: #2AAD60; }"
        )

    @staticmethod
    def _stop_style() -> str:
        return (
            f"QPushButton {{ background-color: {theme.DANGER}; color: white; border: none;"
            " border-radius: 6px; font-size: 13px; font-weight: bold; }"
            "QPushButton:hover { background-color: #F57A7A; }"
            "QPushButton:pressed { background-color: #D94F4F; }"
        )
