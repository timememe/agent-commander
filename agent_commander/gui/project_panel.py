"""Project overview panel — architecture editor + agent mini-list."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.session.project_store import ProjectMeta, ProjectStore


class ProjectPanel(ctk.CTkFrame):
    """Central panel shown when a project is selected in the sidebar.

    Layout::

        row=0: header (name + Edit / Delete buttons)
        row=1: content (weight=1)
            col=0 (220px): mini agent list + [+ Add Agent] button
            col=1 (weight=1): tab bar + MD editor pane + [Save]
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        project_store: ProjectStore,
        on_edit: Callable[[str], None] | None = None,
        on_delete: Callable[[str], None] | None = None,
        on_add_agent: Callable[[str], None] | None = None,
        on_select_agent: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._store = project_store
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._on_add_agent = on_add_agent
        self._on_select_agent = on_select_agent
        self._project_id: str | None = None
        self._active_tab = "Architecture"
        self._agent_labels: list[ctk.CTkLabel] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # --- Header ---
        header = ctk.CTkFrame(
            self,
            fg_color=theme.COLOR_BG_INPUT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            header,
            text="Project",
            anchor="w",
            text_color=theme.COLOR_TEXT,
            font=(theme.FONT_FAMILY, 15, "bold"),
        )
        self._title_label.grid(row=0, column=0, sticky="ew", padx=12, pady=10)

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e", padx=8, pady=8)

        ctk.CTkButton(
            btn_frame, text="Edit", width=70, height=28,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, font=(theme.FONT_FAMILY, 11),
            command=self._edit,
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            btn_frame, text="Delete", width=70, height=28,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_DANGER,
            text_color=theme.COLOR_DANGER, font=(theme.FONT_FAMILY, 11),
            command=self._delete,
        ).pack(side="left")

        # --- Content area ---
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=0)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        # Left: agent mini-list
        left_panel = ctk.CTkFrame(
            content,
            width=220,
            fg_color=theme.COLOR_BG_SIDEBAR,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        left_panel.grid_propagate(False)
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            left_panel, text="Agents", anchor="w",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 11, "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))

        self._agent_scroll = ctk.CTkScrollableFrame(left_panel, fg_color="transparent")
        self._agent_scroll.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self._agent_scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkButton(
            left_panel, text="+ Add Agent", height=28,
            fg_color=theme.COLOR_ACCENT, font=(theme.FONT_FAMILY, 11),
            command=self._add_agent,
        ).grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))

        # Right: MD editor pane
        right_panel = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=8,
        )
        right_panel.grid(row=0, column=1, sticky="nsew")
        right_panel.grid_columnconfigure(0, weight=1)
        right_panel.grid_rowconfigure(1, weight=1)

        # Tab bar
        tab_bar = ctk.CTkFrame(right_panel, fg_color="transparent")
        tab_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self._arch_tab = ctk.CTkButton(
            tab_bar, text="Architecture", width=110, height=26,
            fg_color=theme.COLOR_ACCENT, font=(theme.FONT_FAMILY, 11),
            command=lambda: self._switch_tab("Architecture"),
        )
        self._arch_tab.pack(side="left", padx=(0, 4))
        self._hist_tab = ctk.CTkButton(
            tab_bar, text="History", width=80, height=26,
            fg_color="transparent", border_width=1, border_color=theme.COLOR_BORDER,
            text_color=theme.COLOR_TEXT, font=(theme.FONT_FAMILY, 11),
            command=lambda: self._switch_tab("History"),
        )
        self._hist_tab.pack(side="left")

        # Text editor
        self._textbox = ctk.CTkTextbox(
            right_panel,
            font=(theme.FONT_FAMILY, 12),
            fg_color=theme.COLOR_BG_APP,
            border_width=0,
            wrap="word",
            text_color=theme.COLOR_TEXT,
        )
        self._textbox.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)

        # Save button (Architecture tab only)
        self._save_btn = ctk.CTkButton(
            right_panel, text="Save Architecture", width=140, height=28,
            fg_color=theme.COLOR_ACCENT, font=(theme.FONT_FAMILY, 11),
            command=self._save_architecture,
        )
        self._save_btn.grid(row=2, column=0, sticky="e", padx=8, pady=(0, 8))

    def load_project(self, project_id: str, agent_sessions: list[tuple[str, str]] | None = None) -> None:
        """Load and display project data. agent_sessions: [(session_id, title)]."""
        self._project_id = project_id
        meta = self._store.get_project(project_id)
        if meta is None:
            return

        self._title_label.configure(text=f"📁 {meta.name}")

        # Populate agent list
        for lbl in self._agent_labels:
            try:
                lbl.destroy()
            except Exception:
                pass
        self._agent_labels.clear()

        sessions = agent_sessions or []
        for i, (sid, title) in enumerate(sessions):
            lbl = ctk.CTkLabel(
                self._agent_scroll,
                text=title or sid,
                anchor="w",
                text_color=theme.COLOR_TEXT,
                font=(theme.FONT_FAMILY, 11),
                cursor="hand2",
            )
            lbl.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
            session_id = sid
            lbl.bind("<Button-1>", lambda e, s=session_id: self._select_agent(s))
            self._agent_labels.append(lbl)

        self._switch_tab("Architecture")

    def _switch_tab(self, tab: str) -> None:
        self._active_tab = tab
        if tab == "Architecture":
            self._arch_tab.configure(fg_color=theme.COLOR_ACCENT, text_color="#FFFFFF")
            self._hist_tab.configure(fg_color="transparent", text_color=theme.COLOR_TEXT)
            self._save_btn.grid()
            if self._project_id:
                content = self._store.read_architecture(self._project_id)
                self._textbox.configure(state="normal")
                self._textbox.delete("1.0", "end")
                self._textbox.insert("1.0", content)
        else:
            self._hist_tab.configure(fg_color=theme.COLOR_ACCENT, text_color="#FFFFFF")
            self._arch_tab.configure(fg_color="transparent", text_color=theme.COLOR_TEXT)
            self._save_btn.grid_remove()
            if self._project_id:
                content = self._store.read_context_history(self._project_id)
                self._textbox.configure(state="normal")
                self._textbox.delete("1.0", "end")
                self._textbox.insert("1.0", content)
                self._textbox.configure(state="disabled")

    def _save_architecture(self) -> None:
        if self._project_id is None:
            return
        content = self._textbox.get("1.0", "end-1c")
        self._store.write_architecture(self._project_id, content)

    def _edit(self) -> None:
        if self._project_id and self._on_edit:
            self._on_edit(self._project_id)

    def _delete(self) -> None:
        if self._project_id and self._on_delete:
            self._on_delete(self._project_id)

    def _add_agent(self) -> None:
        if self._project_id and self._on_add_agent:
            self._on_add_agent(self._project_id)

    def _select_agent(self, session_id: str) -> None:
        if self._on_select_agent:
            self._on_select_agent(session_id)
