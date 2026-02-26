"""Horizontal extension-toggle chip bar shown between SkillBar and InputBar."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.extension_store import ExtensionDef, ExtensionStore

_COLOR_ACTIVE = "#22C55E"   # green — distinct from blue Skills


class ExtensionBar(ctk.CTkFrame):
    """A one-row strip of toggleable extension chips (connected extensions only).

    - Active extension  → filled green chip
    - Inactive extension → border-only chip
    - Locked (session has messages) → chips are not interactive

    The bar hides itself (grid_remove) when no connected extensions exist
    and shows itself (grid) when at least one connected extension appears.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        extension_store: ExtensionStore,
        on_open_extensions: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_APP,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=6,
        )
        self._extension_store = extension_store
        self._on_open_extensions = on_open_extensions
        self._active_ids: set[str] = set()
        self._locked = False
        self._chip_buttons: dict[str, ctk.CTkButton] = {}

        self.grid_columnconfigure(1, weight=1)

        # "Ext:" label
        ctk.CTkLabel(
            self,
            text="Ext:",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.COLOR_TEXT_MUTED,
            width=52,
            anchor="w",
        ).grid(row=0, column=0, padx=(10, 0), pady=5, sticky="w")

        # Chips area
        self._chips_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._chips_frame.grid(row=0, column=1, sticky="w", padx=(4, 4), pady=5)

        # Manage button
        self._manage_btn = ctk.CTkButton(
            self,
            text="Manage",
            width=72,
            height=24,
            font=(theme.FONT_FAMILY, 11),
            fg_color="transparent",
            border_width=1,
            border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT_MUTED,
            hover_color=theme.COLOR_BG_PANEL,
            command=self._on_manage_click,
        )
        self._manage_btn.grid(row=0, column=2, padx=(0, 10), pady=5, sticky="e")

        self.refresh()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_session(self, active_ids: list[str], locked: bool) -> None:
        """Sync bar state when switching to a session."""
        self._active_ids = set(active_ids)
        self._locked = locked
        self._rebuild_chips()

    def set_locked(self, locked: bool) -> None:
        """Lock or unlock chip interaction."""
        if self._locked == locked:
            return
        self._locked = locked
        self._rebuild_chips()

    def get_active_ids(self) -> list[str]:
        """Return the list of currently toggled extension IDs."""
        return list(self._active_ids)

    def refresh(self) -> None:
        """Re-read extensions from disk and rebuild chips.

        Also shows/hides the entire bar depending on whether any connected
        extensions exist.
        """
        self._rebuild_chips()

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _connected_extensions(self) -> list[ExtensionDef]:
        return [
            e for e in self._extension_store.list_extensions()
            if e.status == "connected"
        ]

    def _rebuild_chips(self) -> None:
        for w in self._chips_frame.winfo_children():
            w.destroy()
        self._chip_buttons.clear()

        connected = sorted(self._connected_extensions(), key=lambda e: e.name.lower())

        if not connected:
            # Remove stale active_ids for disconnected extensions
            self._active_ids.clear()
            try:
                self.grid_remove()
            except Exception:
                pass
            return

        # Ensure bar is visible
        try:
            self.grid()
        except Exception:
            pass

        # Remove active_ids that are no longer connected
        connected_ids = {e.id for e in connected}
        self._active_ids &= connected_ids

        for ext in connected:
            self._add_chip(ext)

    def _add_chip(self, ext: ExtensionDef) -> None:
        is_active = ext.id in self._active_ids
        if is_active:
            fg_color = _COLOR_ACTIVE
            text_color = "#ffffff"
            border_color = _COLOR_ACTIVE
            hover = _COLOR_ACTIVE
        else:
            fg_color = "transparent"
            text_color = theme.COLOR_TEXT_MUTED
            border_color = theme.COLOR_BORDER
            hover = theme.COLOR_BG_PANEL

        btn = ctk.CTkButton(
            self._chips_frame,
            text=ext.name,
            width=0,
            height=24,
            font=(theme.FONT_FAMILY, 11),
            fg_color=fg_color,
            border_width=1,
            border_color=border_color,
            text_color=text_color,
            hover_color=hover,
            corner_radius=12,
            state="disabled" if self._locked else "normal",
            command=lambda eid=ext.id: self._toggle(eid),
        )
        btn.pack(side="left", padx=(0, 4))
        self._chip_buttons[ext.id] = btn

    def _toggle(self, ext_id: str) -> None:
        if self._locked:
            return
        if ext_id in self._active_ids:
            self._active_ids.discard(ext_id)
        else:
            self._active_ids.add(ext_id)
        self._rebuild_chips()

    def _on_manage_click(self) -> None:
        if self._on_open_extensions:
            self._on_open_extensions()
