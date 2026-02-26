"""Extensions panel — manage external service integrations."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.extension_store import ExtensionDef, ExtensionStore

# ── Provider catalogue ────────────────────────────────────────────────────────

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


# ── Connect dialog ─────────────────────────────────────────────────────────────

class _ExtensionConnectDialog(ctk.CTkToplevel):
    """Dialog for entering credentials for a specific provider."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        provider_info: dict,
        existing: ExtensionDef | None,
        on_save: "Callable[[str, dict], None]",
    ) -> None:
        super().__init__(master)
        self._provider_info = provider_info
        self._on_save = on_save

        self.title(f"Connect — {provider_info['name']}")
        self.configure(fg_color=theme.COLOR_BG_APP)
        self.transient(master)
        self.resizable(False, False)
        self.geometry("460x320")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.lift(master)
        try:
            self.focus_force()
        except Exception:
            self.focus_set()

        self._entries: dict[str, ctk.CTkEntry] = {}
        self._build_ui(existing)
        self.after(0, self._center_on_parent)

    def _center_on_parent(self) -> None:
        self.update_idletasks()
        pw = self.master.winfo_width()
        ph = self.master.winfo_height()
        px = self.master.winfo_rootx()
        py = self.master.winfo_rooty()
        dw = self.winfo_width()
        dh = self.winfo_height()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self.geometry(f"+{x}+{y}")

    def _build_ui(self, existing: ExtensionDef | None) -> None:
        pad = {"padx": 20, "pady": 8}

        # Header
        header = ctk.CTkFrame(self, fg_color=theme.COLOR_BG_PANEL, corner_radius=0)
        header.pack(fill="x")
        badge = ctk.CTkLabel(
            header,
            text=self._provider_info["name"],
            fg_color=self._provider_info["badge_color"],
            corner_radius=6,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=120,
            height=28,
        )
        badge.pack(side="left", padx=16, pady=12)
        ctk.CTkLabel(
            header,
            text=self._provider_info["description"],
            text_color=theme.COLOR_TEXT_MUTED,
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 16))

        # Fields
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(8, 0))
        body.grid_columnconfigure(1, weight=1)

        creds = existing.credentials if existing else {}
        for row_idx, field in enumerate(self._provider_info["fields"]):
            ctk.CTkLabel(
                body,
                text=field["label"] + ":",
                anchor="w",
                text_color=theme.COLOR_TEXT_MUTED,
                font=ctk.CTkFont(size=12),
            ).grid(row=row_idx, column=0, sticky="w", pady=4)
            show_char = "" if field["show"] else "•"
            entry = ctk.CTkEntry(
                body,
                height=32,
                show=show_char,
                placeholder_text=field["label"],
            )
            entry.grid(row=row_idx, column=1, sticky="ew", padx=(10, 0), pady=4)
            if field["key"] in creds:
                entry.insert(0, creds[field["key"]])
            self._entries[field["key"]] = entry

        # Hint
        hint_row = len(self._provider_info["fields"])
        ctk.CTkLabel(
            body,
            text=self._provider_info["hint"],
            text_color=theme.COLOR_TEXT_MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
            wraplength=380,
        ).grid(row=hint_row, column=0, columnspan=2, sticky="w", pady=(8, 0))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            width=90,
            fg_color=theme.COLOR_BG_INPUT,
            hover_color=theme.COLOR_BG_PANEL,
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_frame,
            text="Save",
            width=90,
            command=self._on_save_clicked,
        ).pack(side="right")

    def _on_save_clicked(self) -> None:
        creds = {key: entry.get().strip() for key, entry in self._entries.items()}
        self._on_save(self._provider_info["id"], creds)
        self.destroy()


# ── Provider card ──────────────────────────────────────────────────────────────

class _ProviderCard(ctk.CTkFrame):
    """Visual card for one integration provider."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        provider_info: dict,
        extension: ExtensionDef | None,
        on_connect: "Callable[[dict], None]",
        on_disconnect: "Callable[[str], None]",
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=10,
            width=240,
        )
        self._provider_info = provider_info
        self._extension = extension
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

        self.grid_propagate(False)
        self.configure(height=160)
        self._build()

    def _build(self) -> None:
        # Clear children
        for w in self.winfo_children():
            w.destroy()

        is_connected = self._extension is not None and self._extension.status == "connected"

        # Badge
        badge = ctk.CTkLabel(
            self,
            text=self._provider_info["name"],
            fg_color=self._provider_info["badge_color"],
            corner_radius=6,
            text_color="#FFFFFF",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=100,
            height=24,
        )
        badge.pack(anchor="w", padx=14, pady=(14, 4))

        # Description
        ctk.CTkLabel(
            self,
            text=self._provider_info["description"],
            text_color=theme.COLOR_TEXT_MUTED,
            font=ctk.CTkFont(size=11),
            anchor="w",
            wraplength=200,
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Status indicator
        status_color = "#22C55E" if is_connected else "#6B7280"
        status_text = "● Connected" if is_connected else "● Not connected"
        ctk.CTkLabel(
            self,
            text=status_text,
            text_color=status_color,
            font=ctk.CTkFont(size=11),
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # Action button
        if is_connected:
            ctk.CTkButton(
                self,
                text="Disconnect",
                width=110,
                height=28,
                fg_color="#374151",
                hover_color="#4B5563",
                command=lambda: self._on_disconnect(self._provider_info["id"]),
            ).pack(anchor="w", padx=14, pady=(0, 14))
        else:
            ctk.CTkButton(
                self,
                text="Connect",
                width=110,
                height=28,
                command=lambda: self._on_connect(self._provider_info),
            ).pack(anchor="w", padx=14, pady=(0, 14))

    def refresh(self, extension: ExtensionDef | None) -> None:
        self._extension = extension
        self._build()


# ── Main panel ─────────────────────────────────────────────────────────────────

class ExtensionsPanel(ctk.CTkFrame):
    """Full-screen panel for managing external service integrations."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        extension_store: ExtensionStore,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._store = extension_store
        self._cards: dict[str, _ProviderCard] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        # Header
        header = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Extensions",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="w", padx=16, pady=10)

        ctk.CTkLabel(
            header,
            text="Connect external accounts so agents can access your services",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=theme.COLOR_TEXT_MUTED,
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 10))

        # Cards container (scrollable)
        self._cards_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=theme.COLOR_BORDER,
        )
        self._cards_frame.grid(row=1, column=0, sticky="nsew")

    def refresh(self) -> None:
        """Reload extension statuses from store and update cards."""
        extensions_by_id: dict[str, ExtensionDef] = {
            e.id: e for e in self._store.list_extensions()
        }

        # Clear old cards
        for w in self._cards_frame.winfo_children():
            w.destroy()
        self._cards.clear()

        # Build cards row
        for col_idx, pinfo in enumerate(_PROVIDERS):
            ext = extensions_by_id.get(pinfo["id"])
            card = _ProviderCard(
                self._cards_frame,
                provider_info=pinfo,
                extension=ext,
                on_connect=self._on_connect,
                on_disconnect=self._on_disconnect,
            )
            card.grid(row=0, column=col_idx, padx=(0, 16), pady=8, sticky="n")
            self._cards[pinfo["id"]] = card

    def _on_connect(self, provider_info: dict) -> None:
        """Open connect dialog for the given provider."""
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

        dlg = _ExtensionConnectDialog(
            self.winfo_toplevel(),
            provider_info=provider_info,
            existing=existing,
            on_save=_save,
        )
        dlg.grab_set()

    def _on_disconnect(self, ext_id: str) -> None:
        """Mark extension as disconnected."""
        ext = self._store.get_extension(ext_id)
        if ext is None:
            return
        ext.status = "disconnected"
        self._store.upsert_extension(ext)
        if ext_id in self._cards:
            self._cards[ext_id].refresh(ext)
