"""Status bar widget."""

from __future__ import annotations

import customtkinter as ctk

from agent_commander.gui import theme

# Remaining-% thresholds for colour coding.
_WARN_THRESHOLD = 25.0
_DANGER_THRESHOLD = 10.0
_COLOR_WARN = "#FFA940"   # amber


class StatusBar(ctk.CTkFrame):
    """Bottom status line: connection info (left) + agent usage (right)."""

    def __init__(self, master: ctk.CTkBaseClass) -> None:
        super().__init__(master, fg_color=theme.COLOR_STATUS_BG, corner_radius=0)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)

        self._label = ctk.CTkLabel(
            self,
            text="Disconnected",
            anchor="w",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 12),
        )
        self._label.grid(row=0, column=0, sticky="ew", padx=10, pady=4)

        self._usage_label = ctk.CTkLabel(
            self,
            text="",
            anchor="e",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 12),
        )
        self._usage_label.grid(row=0, column=1, sticky="e", padx=10, pady=4)

    def set_status(self, text: str) -> None:
        self._label.configure(text=text)

    def set_usage(self, text: str, remaining_percent: float | None = None) -> None:
        """Update the right-side usage display with automatic colour coding."""
        if remaining_percent is not None:
            if remaining_percent < _DANGER_THRESHOLD:
                color = theme.COLOR_DANGER
            elif remaining_percent < _WARN_THRESHOLD:
                color = _COLOR_WARN
            else:
                color = theme.COLOR_TEXT_MUTED
        else:
            color = theme.COLOR_TEXT_MUTED

        self._usage_label.configure(text=text, text_color=color)
