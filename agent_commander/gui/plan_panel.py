"""Loop plan panel — shows loop mode progress above the input bar."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.gui_store import LoopState


class PlanPanel(ctk.CTkFrame):
    """Sticky panel showing loop iteration progress and checklist.

    Placed between the content area and skill bar when loop mode is active.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_pause: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        self._on_pause = on_pause
        self._on_stop = on_stop
        self._checklist_visible = True

        self.grid_columnconfigure(0, weight=1)

        # --- Header row ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 2))
        header.grid_columnconfigure(0, weight=1)

        self._status_label = ctk.CTkLabel(
            header,
            text="🔄 Loop · Iteration 0",
            anchor="w",
            text_color=theme.COLOR_TEXT,
            font=(theme.FONT_FAMILY, 12, "bold"),
        )
        self._status_label.grid(row=0, column=0, sticky="ew")

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        self._toggle_btn = ctk.CTkButton(
            btn_frame,
            text="▼",
            width=26,
            height=22,
            fg_color="transparent",
            text_color=theme.COLOR_TEXT_MUTED,
            hover_color=theme.COLOR_SESSION_HOVER_BG,
            font=(theme.FONT_FAMILY, 10),
            command=self._toggle_checklist,
        )
        self._toggle_btn.pack(side="left", padx=(0, 2))

        self._pause_btn = ctk.CTkButton(
            btn_frame,
            text="Pause",
            width=54,
            height=22,
            fg_color=theme.COLOR_BG_PANEL,
            text_color=theme.COLOR_TEXT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            font=(theme.FONT_FAMILY, 10),
            command=self._do_pause,
        )
        self._pause_btn.pack(side="left", padx=(0, 2))

        self._stop_btn = ctk.CTkButton(
            btn_frame,
            text="Stop",
            width=50,
            height=22,
            fg_color=theme.COLOR_DANGER,
            font=(theme.FONT_FAMILY, 10),
            command=self._do_stop,
        )
        self._stop_btn.pack(side="left")

        # --- Checklist frame (collapsible) ---
        self._checklist_frame = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            height=80,
        )
        self._checklist_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 6))
        self._checklist_frame.grid_columnconfigure(0, weight=1)

        self._checklist_labels: list[ctk.CTkLabel] = []

    def update_loop_state(self, state: LoopState) -> None:
        """Refresh the panel with the current loop state."""
        status_icons = {
            "idle": "⏸",
            "running": "🔄",
            "paused": "⏸",
            "done": "✅",
        }
        icon = status_icons.get(state.status, "🔄")
        self._status_label.configure(
            text=f"{icon} Loop · Iteration {state.iteration}"
        )

        # Update pause button text
        if state.status == "paused":
            self._pause_btn.configure(text="Resume")
        else:
            self._pause_btn.configure(text="Pause")

        # Rebuild checklist
        for lbl in self._checklist_labels:
            try:
                lbl.destroy()
            except Exception:
                pass
        self._checklist_labels.clear()

        for i, item in enumerate(state.checklist):
            done = item.get("done", False)
            icon_ch = "✅" if done else "⬜"
            text = item.get("text", "")
            lbl = ctk.CTkLabel(
                self._checklist_frame,
                text=f"{icon_ch} {text}",
                anchor="w",
                text_color=theme.COLOR_TEXT_MUTED if done else theme.COLOR_TEXT,
                font=(theme.FONT_FAMILY, 11),
            )
            lbl.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            self._checklist_labels.append(lbl)

    def _toggle_checklist(self) -> None:
        if self._checklist_visible:
            self._checklist_frame.grid_remove()
            self._toggle_btn.configure(text="▶")
            self._checklist_visible = False
        else:
            self._checklist_frame.grid()
            self._toggle_btn.configure(text="▼")
            self._checklist_visible = True

    def _do_pause(self) -> None:
        if self._on_pause:
            self._on_pause()

    def _do_stop(self) -> None:
        if self._on_stop:
            self._on_stop()
