"""Agent selector widget."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme


class AgentSelector(ctk.CTkFrame):
    """Dropdown for active agent choice."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        values: list[str],
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_change = on_change
        self._values = values

        self._label = ctk.CTkLabel(
            self,
            text="Agent",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 11),
        )
        self._label.pack(side="left", padx=(0, 6))

        self._option = ctk.CTkOptionMenu(
            self,
            values=values,
            font=(theme.FONT_FAMILY, 12),
            command=self._handle_change,
            width=130,
        )
        self._option.pack(side="left")
        if values:
            self._option.set(values[0])

    def get(self) -> str:
        return self._option.get()

    def set(self, value: str) -> None:
        if value in self._values:
            self._option.set(value)

    def _handle_change(self, value: str) -> None:
        if self._on_change:
            self._on_change(value)
