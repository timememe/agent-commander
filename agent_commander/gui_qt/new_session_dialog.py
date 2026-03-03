"""New session dialog for the Qt GUI backend."""

from __future__ import annotations

import uuid

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from agent_commander.gui_qt import theme


class NewSessionDialog(QDialog):
    """Simple dialog to pick an agent and create a new chat session."""

    def __init__(self, parent=None, default_agent: str = "codex") -> None:
        super().__init__(parent)
        self.setWindowTitle("New Chat")
        self.setMinimumWidth(280)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        layout.addWidget(QLabel("Select agent:"))

        self._combo = QComboBox()
        self._combo.addItems(["codex", "claude", "gemini"])
        idx = self._combo.findText(default_agent)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        layout.addWidget(self._combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_data(self) -> tuple[str, str]:
        """Return (session_id, agent_name)."""
        return str(uuid.uuid4()), self._combo.currentText()
