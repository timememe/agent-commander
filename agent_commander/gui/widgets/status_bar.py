"""Status bar widget."""

from __future__ import annotations

import customtkinter as ctk

from agent_commander.gui import theme


class StatusBar(ctk.CTkFrame):
    """Bottom status line."""

    def __init__(self, master: ctk.CTkBaseClass) -> None:
        super().__init__(master, fg_color=theme.COLOR_STATUS_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)

        self._label = ctk.CTkLabel(
            self,
            text="Disconnected",
            anchor="w",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 12),
        )
        self._label.grid(row=0, column=0, sticky="ew", padx=10, pady=4)

    def set_status(self, text: str) -> None:
        self._label.configure(text=text)
