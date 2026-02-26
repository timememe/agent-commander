"""Sidebar composition widget."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.gui.session_list import ProjectListItem, SessionList, SessionListItem


class Sidebar(ctk.CTkFrame):
    """Left panel containing agent sessions grouped by project."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_select_session: Callable[[str], None],
        on_new_chat: Callable[[], None],
        on_select_agent: Callable[[str], None] | None = None,
        on_delete_session: Callable[[str], None] | None = None,
        on_new_agent: Callable[[str], None] | None = None,
        on_select_project: Callable[[str], None] | None = None,
        on_new_project: Callable[[], None] | None = None,
        on_delete_project: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_SIDEBAR,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=10,
        )
        del on_select_agent

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._sessions = SessionList(
            self,
            on_select=on_select_session,
            on_new_chat=on_new_chat,
            on_delete=on_delete_session,
            on_new_agent=on_new_agent,
            on_select_project=on_select_project,
            on_new_project=on_new_project,
            on_delete_project=on_delete_project,
        )
        self._sessions.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def set_sessions(
        self,
        items: list[SessionListItem],
        active_session_id: str,
        projects: list[ProjectListItem] | None = None,
        active_project_id: str | None = None,
    ) -> None:
        self._sessions.set_items(items, active_session_id, projects=projects, active_project_id=active_project_id)

    def set_active_session(self, session_id: str) -> None:
        self._sessions.set_active(session_id)

    def set_active_project(self, project_id: str | None) -> None:
        pass  # handled via set_sessions active_project_id

    def set_active_agent(self, name: str) -> None:
        del name

    def set_agent_connected(self, name: str, connected: bool) -> None:
        del name, connected
