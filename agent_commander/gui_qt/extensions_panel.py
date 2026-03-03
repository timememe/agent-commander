"""Extensions panel — manage external service integrations."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme
from agent_commander.session.extension_store import ExtensionDef, ExtensionStore

_PROVIDERS: list[dict] = [
    {
        "id": "google",
        "name": "Google",
        "provider": "google",
        "description": "Gmail, Google Drive, Google Calendar",
        "badge_color": "#4285F4",
        "fields": [
            {"key": "email", "label": "Google Account Email", "show": True},
            {"key": "token", "label": "OAuth Access Token", "show": False},
        ],
        "hint": "Get token from Google Account → Security → App passwords",
    },
    {
        "id": "yandex_mail",
        "name": "Яндекс Почта",
        "provider": "yandex_mail",
        "description": "Яндекс Почта, Яндекс Диск",
        "badge_color": "#FF0000",
        "fields": [
            {"key": "email", "label": "Яндекс Email", "show": True},
            {"key": "token", "label": "App Password", "show": False},
        ],
        "hint": "Создайте пароль приложения: myaccount.yandex.ru → Безопасность",
    },
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Connect dialog
# ---------------------------------------------------------------------------

class _ConnectDialog(QDialog):
    def __init__(
        self,
        provider_info: dict,
        existing: ExtensionDef | None,
        on_save: Callable[[str, dict], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._provider_info = provider_info
        self._on_save = on_save
        self._entries: dict[str, QLineEdit] = {}

        self.setWindowTitle(f"Connect — {provider_info['name']}")
        self.setMinimumWidth(420)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header badge
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)

        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 0px; padding: 3px 10px; font-weight: bold; font-size: 13px;"
        )
        hl.addWidget(badge)

        desc = QLabel(provider_info["description"])
        desc.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
        hl.addWidget(desc, stretch=1)
        layout.addWidget(header)

        # Fields
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        form = QFormLayout(body)
        form.setContentsMargins(20, 8, 20, 0)
        form.setSpacing(10)

        creds = existing.credentials if existing else {}
        for field in provider_info["fields"]:
            lbl = QLabel(field["label"] + ":")
            lbl.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
            entry = QLineEdit()
            entry.setPlaceholderText(field["label"])
            if not field["show"]:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            if field["key"] in creds:
                entry.setText(creds[field["key"]])
            form.addRow(lbl, entry)
            self._entries[field["key"]] = entry

        layout.addWidget(body)

        # Hint
        hint_lbl = QLabel(provider_info["hint"])
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        hint_lbl.setContentsMargins(20, 0, 20, 0)
        layout.addWidget(hint_lbl)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        buttons.setContentsMargins(20, 4, 20, 16)
        layout.addWidget(buttons)

    def _save(self) -> None:
        creds = {key: entry.text().strip() for key, entry in self._entries.items()}
        self._on_save(self._provider_info["id"], creds)
        self.accept()


# ---------------------------------------------------------------------------
# Provider card
# ---------------------------------------------------------------------------

class _ProviderCard(QFrame):
    def __init__(
        self,
        provider_info: dict,
        extension: ExtensionDef | None,
        on_connect: Callable[[dict], None],
        on_disconnect: Callable[[str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._info = provider_info
        self._ext = extension
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self.setFixedWidth(240)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.BG_INPUT};"
            "  border: none; border-radius: 0px; }"
        )
        self._build()

    def _build(self) -> None:
        # Clear existing children
        for child in self.findChildren(QWidget):
            child.deleteLater()

        is_connected = self._ext is not None and self._ext.status == "connected"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        badge = QLabel(self._info["name"])
        badge.setStyleSheet(
            f"background-color: {self._info['badge_color']}; color: white;"
            " border-radius: 0px; padding: 2px 10px; font-weight: bold; font-size: 12px;"
        )
        badge.setFixedHeight(26)
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        desc = QLabel(self._info["description"])
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;")
        layout.addWidget(desc)

        status_color = theme.SUCCESS if is_connected else "#6B7280"
        status_text = "● Connected" if is_connected else "● Not connected"
        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(
            f"color: {status_color}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(status_lbl)

        if is_connected:
            btn = QPushButton("Disconnect")
            btn.setFixedWidth(110)
            btn.setStyleSheet(
                "QPushButton { background-color: #374151; color: white; border: none;"
                " border-radius: 5px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #4B5563; }"
            )
            btn.clicked.connect(lambda: self._on_disconnect(self._info["id"]))
        else:
            btn = QPushButton("Connect")
            btn.setFixedWidth(110)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white; border: none;"
                " border-radius: 5px; padding: 4px 10px; font-size: 12px; }"
                "QPushButton:hover { background-color: #4AABFF; }"
            )
            btn.clicked.connect(lambda: self._on_connect(self._info))
        layout.addWidget(btn)
        layout.addStretch()

    def refresh(self, extension: ExtensionDef | None) -> None:
        self._ext = extension
        self._build()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ExtensionsPanel(QWidget):
    """Full-screen panel for managing external service integrations."""

    def __init__(self, extension_store: ExtensionStore, parent=None) -> None:
        super().__init__(parent)
        self._store = extension_store
        self._cards: dict[str, _ProviderCard] = {}
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(
            f"background-color: {theme.BG_INPUT};"
        )
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Extensions")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 15px; background: transparent;"
        )
        hl.addWidget(title)

        sub = QLabel("Connect external accounts so agents can access your services")
        sub.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;")
        hl.addWidget(sub)
        root.addWidget(header)

        # Scroll area for cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ background: {theme.BG_APP}; border: none; }}")

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet(f"background: {theme.BG_APP};")
        self._cards_layout = QHBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(20, 20, 20, 20)
        self._cards_layout.setSpacing(16)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll.setWidget(self._cards_container)
        root.addWidget(scroll, stretch=1)

    def refresh(self) -> None:
        extensions_by_id = {e.id: e for e in self._store.list_extensions()}

        # Remove old cards
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        for pinfo in _PROVIDERS:
            ext = extensions_by_id.get(pinfo["id"])
            card = _ProviderCard(
                provider_info=pinfo,
                extension=ext,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            self._cards_layout.addWidget(card)
            self._cards[pinfo["id"]] = card

        self._cards_layout.addStretch()

    def _on_connect(self, provider_info: dict) -> None:
        ext_id = provider_info["id"]
        existing = self._store.get_extension(ext_id)

        def _save(pid: str, creds: dict) -> None:
            now = _now()
            ext = ExtensionDef(
                id=pid,
                name=provider_info["name"],
                provider=provider_info["provider"],
                status="connected",
                credentials=creds,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            self._store.upsert_extension(ext)
            if pid in self._cards:
                self._cards[pid].refresh(ext)

        dlg = _ConnectDialog(
            provider_info=provider_info,
            existing=existing,
            on_save=_save,
            parent=self,
        )
        dlg.exec()

    def _on_disconnect(self, ext_id: str) -> None:
        ext = self._store.get_extension(ext_id)
        if ext is None:
            return
        ext.status = "disconnected"
        self._store.upsert_extension(ext)
        if ext_id in self._cards:
            self._cards[ext_id].refresh(ext)
