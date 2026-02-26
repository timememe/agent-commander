"""Horizontal skill-toggle chip bar shown between content and input."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.skill_store import SkillDef, SkillStore


class SkillBar(ctk.CTkFrame):
    """A one-row strip of toggleable skill chips.

    - Active skill  → filled accent-coloured chip
    - Inactive skill → border-only chip
    - Locked (session has messages) → chips are not interactive

    The bar is always visible. When no skills exist it shows a prompt
    to open the Team / Skill Library dialog.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        skill_store: SkillStore,
        on_open_team: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_APP,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=6,
        )
        self._skill_store = skill_store
        self._on_open_team = on_open_team
        self._active_ids: set[str] = set()
        self._locked = False
        self._chip_buttons: dict[str, ctk.CTkButton] = {}

        self.grid_columnconfigure(1, weight=1)

        # "Skills:" label
        ctk.CTkLabel(
            self,
            text="Skills:",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.COLOR_TEXT_MUTED,
            width=52,
            anchor="w",
        ).grid(row=0, column=0, padx=(10, 0), pady=5, sticky="w")

        # Chips area (left-aligned, clips on overflow)
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

        self._rebuild_chips()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def set_session(self, active_ids: list[str], locked: bool) -> None:
        """Sync bar state when switching to a session."""
        self._active_ids = set(active_ids)
        self._locked = locked
        self._rebuild_chips()

    def set_locked(self, locked: bool) -> None:
        """Lock or unlock chip interaction (called when first message is sent)."""
        if self._locked == locked:
            return
        self._locked = locked
        self._rebuild_chips()

    def get_active_ids(self) -> list[str]:
        """Return the list of currently toggled skill IDs."""
        return list(self._active_ids)

    def refresh(self) -> None:
        """Re-read skills from disk and rebuild chips (call after Team dialog saves)."""
        self._rebuild_chips()

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    def _rebuild_chips(self) -> None:
        for w in self._chips_frame.winfo_children():
            w.destroy()
        self._chip_buttons.clear()

        skills = sorted(self._skill_store.list_skills(), key=lambda s: s.name.lower())

        if not skills:
            ctk.CTkLabel(
                self._chips_frame,
                text="No skills yet – click Manage to create one",
                font=(theme.FONT_FAMILY, 11),
                text_color=theme.COLOR_TEXT_MUTED,
                anchor="w",
            ).pack(side="left", padx=4)
            return

        for skill in skills:
            self._add_chip(skill)

    def _add_chip(self, skill: SkillDef) -> None:
        is_active = skill.id in self._active_ids
        if is_active:
            fg_color = theme.COLOR_ACCENT
            text_color = "#ffffff"
            border_color = theme.COLOR_ACCENT
            hover = theme.COLOR_ACCENT
        else:
            fg_color = "transparent"
            text_color = theme.COLOR_TEXT_MUTED
            border_color = theme.COLOR_BORDER
            hover = theme.COLOR_BG_PANEL

        btn = ctk.CTkButton(
            self._chips_frame,
            text=skill.name,
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
            command=lambda sid=skill.id: self._toggle(sid),
        )
        btn.pack(side="left", padx=(0, 4))
        self._chip_buttons[skill.id] = btn

    def _toggle(self, skill_id: str) -> None:
        if self._locked:
            return
        if skill_id in self._active_ids:
            self._active_ids.discard(skill_id)
        else:
            self._active_ids.add(skill_id)
        self._rebuild_chips()

    def _on_manage_click(self) -> None:
        if self._on_open_team:
            self._on_open_team()
