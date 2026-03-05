"""Extensions panel — manage external service integrations."""

from __future__ import annotations

import webbrowser
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
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

# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

_PROVIDERS: list[dict] = [
    {
        "id": "google",
        "name": "Google",
        "provider": "google",
        "badge_color": "#4285F4",
        "auth_type": "oauth2",
        "services": ["Gmail", "Google Drive", "Google Calendar"],
        "oauth_scopes": [
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/drive",
        ],
        "fields": [
            {
                "key": "client_id",
                "label": "Client ID",
                "placeholder": "xxxx.apps.googleusercontent.com",
                "show": True,
            },
            {
                "key": "client_secret",
                "label": "Client Secret",
                "placeholder": "GOCSPX-...",
                "show": False,
            },
        ],
        "get_token_url": "https://console.cloud.google.com/apis/credentials",
        "steps": [
            "1. Click 'Get Credentials' — Google Cloud Console will open",
            "2. Create a project, enable Gmail API, Calendar API, Drive API",
            "3. Go to Credentials → Create OAuth 2.0 Client ID → Desktop app",
            "4. Copy Client ID and Client Secret into the fields below",
            "5. Click 'Authorize with Google' — browser will open for sign-in",
        ],
    },
    {
        "id": "yandex",
        "name": "Яндекс",
        "provider": "yandex",
        "badge_color": "#FC3F1D",
        "auth_type": "app_password",
        "services": ["Яндекс Почта", "Яндекс Диск"],
        "fields": [
            {
                "key": "email",
                "label": "Яндекс email",
                "placeholder": "you@yandex.ru",
                "show": True,
            },
            {
                "key": "token",
                "label": "Пароль приложения",
                "placeholder": "xxxx xxxx xxxx xxxx",
                "show": False,
            },
        ],
        "get_token_url": "https://id.yandex.ru/security/app-passwords",
        "steps": [
            "1. Нажмите 'Get Token' — откроется раздел 'Пароли приложений' в Яндекс ID",
            "2. Нажмите 'Создать пароль приложения'",
            "3. Один пароль работает для Почты (IMAP) и Диска (WebDAV)",
            "4. Скопируйте пароль (показывается один раз) и вставьте ниже",
        ],
    },
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Google OAuth2 background thread
# ---------------------------------------------------------------------------

class _GoogleAuthThread(QThread):
    """Runs InstalledAppFlow.run_local_server() off the UI thread."""

    auth_success = Signal(dict)   # emits credentials dict
    auth_failed = Signal(str)     # emits error message

    def __init__(self, client_id: str, client_secret: str, scopes: list) -> None:
        super().__init__()
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes

    def run(self) -> None:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore

            client_config = {
                "installed": {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            }
            flow = InstalledAppFlow.from_client_config(client_config, self._scopes)
            creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

            email = ""
            try:
                from googleapiclient.discovery import build as _build  # type: ignore
                svc = _build("oauth2", "v2", credentials=creds)
                info = svc.userinfo().get().execute()
                email = info.get("email", "")
            except Exception:
                pass

            self.auth_success.emit({
                "email": email,
                "token": creds.token or "",
                "refresh_token": creds.refresh_token or "",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "token_expiry": creds.expiry.isoformat() if creds.expiry else "",
            })
        except Exception as exc:
            self.auth_failed.emit(str(exc))


# ---------------------------------------------------------------------------
# Google OAuth dialog (replaces manual token entry)
# ---------------------------------------------------------------------------

class _GoogleOAuthDialog(QDialog):
    """OAuth2 connection dialog for Google — no manual token copying needed."""

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
        self._auth_thread: _GoogleAuthThread | None = None
        self._entries: dict[str, QLineEdit] = {}

        self.setWindowTitle(f"Connect — {provider_info['name']}")
        self.setMinimumWidth(480)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(10)

        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 3px 12px; font-weight: bold; font-size: 14px;"
        )
        badge.setFixedHeight(28)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        services_row = QWidget()
        services_row.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(services_row)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        inc_lbl = QLabel("Включает:")
        inc_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        srl.addWidget(inc_lbl)
        for svc in provider_info.get("services", []):
            chip = QLabel(svc)
            chip.setStyleSheet(
                f"background-color: {theme.BG_APP}; color: {theme.TEXT};"
                " border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            srl.addWidget(chip)
        srl.addStretch()
        hl.addWidget(services_row)
        layout.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(12)

        steps_title = QLabel("Как подключить:")
        steps_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        bl.addWidget(steps_title)

        for step in provider_info.get("steps", []):
            lbl = QLabel(step)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            bl.addWidget(lbl)

        token_url = provider_info.get("get_token_url", "")
        if token_url:
            get_creds_btn = QPushButton("Get Credentials  ↗")
            get_creds_btn.setFixedWidth(160)
            get_creds_btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
                " border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
                "QPushButton:hover { background-color: #4AABFF; }"
            )
            get_creds_btn.clicked.connect(lambda: webbrowser.open(token_url))
            bl.addWidget(get_creds_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
        bl.addWidget(sep)

        # Fields: client_id + client_secret
        creds = existing.credentials if existing else {}
        for field in provider_info["fields"]:
            field_lbl = QLabel(field["label"])
            field_lbl.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
            )
            bl.addWidget(field_lbl)
            entry = QLineEdit()
            entry.setPlaceholderText(field.get("placeholder", field["label"]))
            entry.setFixedHeight(34)
            entry.setStyleSheet(
                f"QLineEdit {{ background: {theme.BG_INPUT}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px 10px; font-size: 12px; }}"
                f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
            )
            if not field["show"]:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            if field["key"] in creds:
                entry.setText(creds[field["key"]])
            bl.addWidget(entry)
            self._entries[field["key"]] = entry

        # Authorize button
        self._auth_btn = QPushButton("Authorize with Google →")
        self._auth_btn.setFixedHeight(36)
        self._auth_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
            " border: none; border-radius: 6px; padding: 5px 16px;"
            " font-size: 13px; font-weight: bold; }}"
            "QPushButton:hover { background-color: #4AABFF; }"
            "QPushButton:disabled { background-color: #374151; color: #9CA3AF; }"
        )
        self._auth_btn.clicked.connect(self._on_authorize_clicked)
        bl.addWidget(self._auth_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        bl.addWidget(self._status_lbl)

        layout.addWidget(body)

        # ── Button bar (Cancel only — Save is automatic after OAuth) ────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {theme.BG_INPUT};")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 12, 20, 12)
        bbl.addStretch()
        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bbl.addWidget(cancel_btn)
        layout.addWidget(btn_bar)

    def _on_authorize_clicked(self) -> None:
        client_id = self._entries.get("client_id", QLineEdit()).text().strip()
        client_secret = self._entries.get("client_secret", QLineEdit()).text().strip()
        if not client_id or not client_secret:
            self._status_lbl.setText("Please enter Client ID and Client Secret first.")
            return

        self._auth_btn.setEnabled(False)
        self._auth_btn.setText("Waiting for browser authorization…")
        self._status_lbl.setText(
            "A browser window will open — sign in with your Google account."
        )

        scopes = self._provider_info.get("oauth_scopes", [])
        self._auth_thread = _GoogleAuthThread(client_id, client_secret, scopes)
        self._auth_thread.auth_success.connect(self._on_auth_success)
        self._auth_thread.auth_failed.connect(self._on_auth_failed)
        self._auth_thread.start()

    def _on_auth_success(self, creds: dict) -> None:
        creds["services"] = self._provider_info.get("services", [])
        self._on_save(self._provider_info["id"], creds)
        self.accept()

    def _on_auth_failed(self, error: str) -> None:
        self._auth_btn.setEnabled(True)
        self._auth_btn.setText("Authorize with Google →")
        self._status_lbl.setText(f"Error: {error}")


# ---------------------------------------------------------------------------
# Simple connect dialog (Yandex / generic)
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
        self.setMinimumWidth(460)
        self.setStyleSheet(f"background-color: {theme.BG_PANEL};")

        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # ── Header ──────────────────────────────────────────────────────
        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(20, 16, 20, 16)
        hl.setSpacing(10)

        badge = QLabel(provider_info["name"])
        badge.setStyleSheet(
            f"background-color: {provider_info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 3px 12px;"
            " font-weight: bold; font-size: 14px;"
        )
        badge.setFixedHeight(28)
        hl.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        services_row = QWidget()
        services_row.setStyleSheet("background: transparent;")
        srl = QHBoxLayout(services_row)
        srl.setContentsMargins(0, 0, 0, 0)
        srl.setSpacing(6)
        inc_lbl = QLabel("Включает:")
        inc_lbl.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        srl.addWidget(inc_lbl)
        for svc in provider_info.get("services", []):
            chip = QLabel(svc)
            chip.setStyleSheet(
                f"background-color: {theme.BG_APP}; color: {theme.TEXT};"
                " border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            srl.addWidget(chip)
        srl.addStretch()
        hl.addWidget(services_row)
        layout.addWidget(header)

        # ── Body ────────────────────────────────────────────────────────
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        bl.setSpacing(12)

        steps_title = QLabel("Как подключить:")
        steps_title.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
        )
        bl.addWidget(steps_title)

        for step in provider_info.get("steps", []):
            lbl = QLabel(step)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
            )
            bl.addWidget(lbl)

        token_url = provider_info.get("get_token_url", "")
        if token_url:
            get_token_btn = QPushButton("Get Token  ↗")
            get_token_btn.setFixedWidth(140)
            get_token_btn.setStyleSheet(
                f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
                " border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
                "QPushButton:hover { background-color: #4AABFF; }"
            )
            get_token_btn.clicked.connect(lambda: webbrowser.open(token_url))
            bl.addWidget(get_token_btn)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {theme.BORDER}; background: {theme.BORDER}; max-height: 1px;")
        bl.addWidget(sep)

        creds = existing.credentials if existing else {}
        for field in provider_info["fields"]:
            field_lbl = QLabel(field["label"])
            field_lbl.setStyleSheet(
                f"color: {theme.TEXT}; font-size: 12px; font-weight: bold; background: transparent;"
            )
            bl.addWidget(field_lbl)
            entry = QLineEdit()
            entry.setPlaceholderText(field.get("placeholder", field["label"]))
            entry.setFixedHeight(34)
            entry.setStyleSheet(
                f"QLineEdit {{ background: {theme.BG_INPUT}; color: {theme.TEXT};"
                f" border: 1px solid {theme.BORDER}; border-radius: 6px; padding: 4px 10px;"
                f" font-size: 12px; }}"
                f"QLineEdit:focus {{ border-color: {theme.ACCENT}; }}"
            )
            if not field["show"]:
                entry.setEchoMode(QLineEdit.EchoMode.Password)
            if field["key"] in creds:
                entry.setText(creds[field["key"]])
            bl.addWidget(entry)
            self._entries[field["key"]] = entry

        layout.addWidget(body)

        # ── Buttons ─────────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet(f"background: {theme.BG_INPUT};")
        bbl = QHBoxLayout(btn_bar)
        bbl.setContentsMargins(20, 12, 20, 12)
        bbl.setSpacing(8)
        bbl.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.reject)
        bbl.addWidget(cancel_btn)

        save_btn = QPushButton("Сохранить")
        save_btn.setFixedWidth(110)
        save_btn.setDefault(True)
        save_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
            " border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: bold; }}"
            "QPushButton:hover { background-color: #4AABFF; }"
        )
        save_btn.clicked.connect(self._save)
        bbl.addWidget(save_btn)
        layout.addWidget(btn_bar)

    def _save(self) -> None:
        creds: dict = {key: entry.text().strip() for key, entry in self._entries.items()}
        creds["services"] = self._provider_info.get("services", [])
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
            "  border: none; border-radius: 8px; }}"
        )
        self._build()

    def _build(self) -> None:
        for child in self.findChildren(QWidget):
            child.deleteLater()

        is_connected = self._ext is not None and self._ext.status == "connected"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        badge = QLabel(self._info["name"])
        badge.setStyleSheet(
            f"background-color: {self._info['badge_color']}; color: white;"
            " border-radius: 4px; padding: 2px 10px; font-weight: bold; font-size: 13px;"
        )
        badge.setFixedHeight(26)
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignLeft)

        chips_row = QWidget()
        chips_row.setStyleSheet("background: transparent;")
        crl = QHBoxLayout(chips_row)
        crl.setContentsMargins(0, 0, 0, 0)
        crl.setSpacing(4)
        for svc in self._info.get("services", []):
            chip = QLabel(svc)
            chip.setStyleSheet(
                f"background-color: {theme.BG_APP}; color: {theme.TEXT_MUTED};"
                " border-radius: 3px; padding: 1px 6px; font-size: 10px;"
            )
            crl.addWidget(chip)
        crl.addStretch()
        layout.addWidget(chips_row)

        status_color = theme.SUCCESS if is_connected else "#6B7280"
        status_text = "● Connected" if is_connected else "● Not connected"
        if is_connected and self._ext:
            email = self._ext.credentials.get("email", "")
            if email:
                status_text = f"● {email}"
        status_lbl = QLabel(status_text)
        status_lbl.setWordWrap(True)
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

        header = QFrame()
        header.setStyleSheet(f"background-color: {theme.BG_INPUT};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(16, 12, 16, 12)

        title = QLabel("Extensions")
        title.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: 15px; background: transparent;"
        )
        hl.addWidget(title)

        sub = QLabel("Подключите внешние аккаунты — агент получит доступ к вашим сервисам")
        sub.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 12px; background: transparent;"
        )
        hl.addWidget(sub)
        root.addWidget(header)

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

        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()

        for pinfo in _PROVIDERS:
            ext = extensions_by_id.get(pinfo["id"]) or extensions_by_id.get(
                "yandex_mail" if pinfo["id"] == "yandex" else ""
            )
            card = _ProviderCard(
                provider_info=pinfo,
                extension=ext,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            self._cards_layout.addWidget(card, alignment=Qt.AlignmentFlag.AlignTop)
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

        if provider_info.get("auth_type") == "oauth2":
            dlg = _GoogleOAuthDialog(
                provider_info=provider_info,
                existing=existing,
                on_save=_save,
                parent=self,
            )
        else:
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
