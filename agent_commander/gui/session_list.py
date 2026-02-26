"""Session list widget with project grouping and agent mode support."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable

import customtkinter as ctk

from agent_commander.gui import theme


def _unbind_configure_recursive(widget: object) -> None:
    """Remove <Configure> bindings from *widget* and all descendants.

    customtkinter widgets (CTkLabel, CTkFrame, …) with corner_radius bind
    _update_dimensions_event to <Configure> to repaint their canvas.  When a
    container is destroyed, tkinter fires a final Configure on each child just
    as the underlying Tk canvas object is being torn down.  That races with the
    repaint callback and produces:
        TclError: invalid command name "...!ctkcanvas"
    Unbinding before destroy() prevents the stale callback from firing.
    """
    try:
        widget.unbind("<Configure>")  # type: ignore[union-attr]
    except Exception:
        pass
    try:
        for child in widget.winfo_children():  # type: ignore[union-attr]
            _unbind_configure_recursive(child)
    except Exception:
        pass


def _mode_icon(mode: str, agent: str) -> str:
    """Return avatar character based on session mode."""
    if mode == "loop":
        return "↺"
    if mode == "schedule":
        return "◷"
    return (agent[:1] or "?").upper()


@dataclass(frozen=True)
class SessionListItem:
    """Session row metadata."""

    session_id: str
    title: str
    preview: str = ""
    timestamp: str = ""
    agent: str = ""
    streaming: bool = False
    mode: str = "manual"
    project_id: str | None = None


@dataclass(frozen=True)
class ProjectListItem:
    """Project group header metadata."""

    project_id: str
    name: str
    expanded: bool = True
    agent_count: int = 0


class _SessionCard(ctk.CTkFrame):
    """Single session card with Telegram-style layout."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        item: SessionListItem,
        active: bool,
        on_click: Callable[[str], None],
        on_delete: Callable[[str], None] | None = None,
        indent: bool = False,
    ) -> None:
        bg = theme.COLOR_SESSION_ACTIVE_BG if active else theme.COLOR_SESSION_NORMAL_BG
        super().__init__(
            master,
            fg_color=bg,
            corner_radius=8,
            border_width=0,
        )
        self._item = item
        self._active = active
        self._on_click = on_click
        self._on_delete = on_delete
        self._streaming = item.streaming
        self._spinner_after_id: str | None = None
        self._indent = indent

        # Column layout: accent | avatar | content | time+dot
        self.grid_columnconfigure(0, weight=0)  # accent bar
        self.grid_columnconfigure(1, weight=0)  # avatar circle
        self.grid_columnconfigure(2, weight=1)  # title + preview
        self.grid_columnconfigure(3, weight=0)  # time + streaming dot

        # --- Left accent border ---
        self._accent = ctk.CTkFrame(
            self,
            width=3,
            height=1,
            corner_radius=0,
            fg_color=theme.COLOR_ACCENT if active else "transparent",
        )
        self._accent.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(0, 4), pady=0)
        self._accent.grid_propagate(False)

        # --- Agent avatar circle (shows mode icon) ---
        avatar_char = _mode_icon(item.mode, item.agent)
        avatar_color = theme.agent_avatar_color(item.agent)
        self._avatar = ctk.CTkLabel(
            self,
            text=avatar_char,
            width=32,
            height=32,
            corner_radius=16,
            fg_color=avatar_color,
            text_color="#FFFFFF",
            font=(theme.FONT_FAMILY, 13, "bold"),
        )
        self._avatar.grid(row=0, column=1, rowspan=2, sticky="", padx=(0, 8), pady=0)

        # --- Title label ---
        self._title_label = ctk.CTkLabel(
            self,
            text=item.title or "New Chat",
            height=18,
            anchor="w",
            text_color=theme.COLOR_TEXT,
            font=(theme.FONT_FAMILY, 12, "bold"),
        )
        self._title_label.grid(row=0, column=2, sticky="sew", pady=(4, 0))

        # --- Preview label ---
        raw = item.preview.replace("\n", " ") if item.preview else ""
        preview_text = (raw[:42] + "…") if len(raw) > 42 else raw
        self._preview_label = ctk.CTkLabel(
            self,
            text=preview_text,
            height=16,
            anchor="w",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 11),
        )
        self._preview_label.grid(row=1, column=2, sticky="new", pady=(0, 4))

        # --- Right side: timestamp + streaming dot ---
        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=3, rowspan=2, sticky="ne", padx=(4, 8), pady=4)

        self._time_label = ctk.CTkLabel(
            right,
            text=item.timestamp,
            height=14,
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 10),
        )
        self._time_label.pack(side="top", anchor="e")

        self._stream_dot = ctk.CTkLabel(
            right,
            text="●",
            height=12,
            text_color=theme.COLOR_SUCCESS,
            font=(theme.FONT_FAMILY, 10),
        )
        if item.streaming:
            self._stream_dot.pack(side="top", anchor="e")
            self._start_dot_blink()
        else:
            self._stream_dot.pack_forget()

        # Right-click context menu
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="Delete chat", command=self._request_delete)

        # Bind hover, click, and right-click on card and all children
        self._bind_recursive(self)

        # --- × delete button (shown on hover) ---
        self._close_btn = ctk.CTkLabel(
            self,
            text="×",
            width=20,
            height=20,
            corner_radius=10,
            fg_color=theme.COLOR_DANGER,
            text_color="#FFFFFF",
            font=(theme.FONT_FAMILY, 13, "bold"),
            cursor="hand2",
        )
        self._close_btn.bind("<Enter>", self._on_enter, add=True)
        self._close_btn.bind("<Leave>", self._on_leave, add=True)
        self._close_btn.bind("<Button-1>", self._on_close_click)
        self._close_btn.bind("<Button-3>", lambda e: "break")
        self._close_btn_visible = False

    def _bind_recursive(self, widget: ctk.CTkBaseClass) -> None:
        if isinstance(widget, tk.Menu):
            return
        widget.bind("<Enter>", self._on_enter, add=True)
        widget.bind("<Leave>", self._on_leave, add=True)
        widget.bind("<Button-1>", self._on_click_event, add=True)
        widget.bind("<Button-3>", self._on_right_click, add=True)
        for child in widget.winfo_children():
            self._bind_recursive(child)

    def _on_enter(self, _event: object) -> None:
        if not self._active:
            self.configure(fg_color=theme.COLOR_SESSION_HOVER_BG)
        if not self._close_btn_visible:
            self._close_btn_visible = True
            self._close_btn.place(relx=1.0, rely=0.5, anchor="e", x=-8)

    def _on_leave(self, event: object) -> None:
        try:
            mx = int(getattr(event, "x_root", 0))
            my = int(getattr(event, "y_root", 0))
            cx = self.winfo_rootx()
            cy = self.winfo_rooty()
            cw = self.winfo_width()
            ch = self.winfo_height()
            if cx <= mx < cx + cw and cy <= my < cy + ch:
                return
        except Exception:
            pass
        if not self._active:
            self.configure(fg_color=theme.COLOR_SESSION_NORMAL_BG)
        if self._close_btn_visible:
            self._close_btn_visible = False
            self._close_btn.place_forget()

    def _on_click_event(self, _event: object) -> None:
        self._on_click(self._item.session_id)

    def _on_right_click(self, event: object) -> None:
        try:
            x = getattr(event, "x_root", 0)
            y = getattr(event, "y_root", 0)
            self._menu.tk_popup(x, y)
        finally:
            self._menu.grab_release()

    def _request_delete(self) -> None:
        if self._on_delete:
            self._on_delete(self._item.session_id)

    def _on_close_click(self, _event: object) -> str:
        self._request_delete()
        return "break"

    def _start_dot_blink(self) -> None:
        self._blink_visible = True
        self._blink()

    def _blink(self) -> None:
        if not self._streaming:
            return
        try:
            if self._blink_visible:
                self._stream_dot.configure(text_color=theme.COLOR_SUCCESS)
            else:
                self._stream_dot.configure(text_color="transparent")
            self._blink_visible = not self._blink_visible
            self._spinner_after_id = self.after(600, self._blink)
        except Exception:
            pass

    def destroy(self) -> None:
        self._streaming = False
        if self._spinner_after_id:
            try:
                self.after_cancel(self._spinner_after_id)
            except Exception:
                pass
        _unbind_configure_recursive(self)
        try:
            self._menu.destroy()
        except Exception:
            pass
        super().destroy()


class _ProjectHeader(ctk.CTkFrame):
    """Project group header with expand/collapse, icon, name, and agent count badge."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        item: ProjectListItem,
        on_click: Callable[[str], None],
        on_toggle: Callable[[str], None],
        active: bool = False,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_SESSION_ACTIVE_BG if active else "transparent",
            corner_radius=6,
        )
        self._item = item
        self._on_click = on_click
        self._on_toggle = on_toggle
        self._active = active

        self.grid_columnconfigure(1, weight=1)

        # Expand/collapse arrow
        arrow = "▼" if item.expanded else "▶"
        self._arrow = ctk.CTkLabel(
            self,
            text=arrow,
            width=16,
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 10),
        )
        self._arrow.grid(row=0, column=0, sticky="w", padx=(6, 2), pady=6)

        # Folder icon + name
        self._name_label = ctk.CTkLabel(
            self,
            text=f"📁 {item.name}",
            anchor="w",
            text_color=theme.COLOR_TEXT,
            font=(theme.FONT_FAMILY, 12, "bold"),
        )
        self._name_label.grid(row=0, column=1, sticky="ew", pady=6)

        # Agent count badge
        if item.agent_count > 0:
            self._badge = ctk.CTkLabel(
                self,
                text=str(item.agent_count),
                width=20,
                height=18,
                corner_radius=9,
                fg_color=theme.COLOR_ACCENT,
                text_color="#FFFFFF",
                font=(theme.FONT_FAMILY, 10, "bold"),
            )
            self._badge.grid(row=0, column=2, sticky="e", padx=(0, 8), pady=6)

        # Bindings
        for w in [self, self._arrow, self._name_label]:
            w.bind("<Enter>", self._on_enter, add=True)
            w.bind("<Leave>", self._on_leave, add=True)
            w.bind("<Button-1>", self._on_click_event, add=True)

    def _on_enter(self, _event: object) -> None:
        if not self._active:
            self.configure(fg_color=theme.COLOR_SESSION_HOVER_BG)

    def _on_leave(self, event: object) -> None:
        try:
            mx = int(getattr(event, "x_root", 0))
            my = int(getattr(event, "y_root", 0))
            cx = self.winfo_rootx()
            cy = self.winfo_rooty()
            cw = self.winfo_width()
            ch = self.winfo_height()
            if cx <= mx < cx + cw and cy <= my < cy + ch:
                return
        except Exception:
            pass
        if not self._active:
            self.configure(fg_color="transparent")

    def _on_click_event(self, _event: object) -> None:
        self._on_toggle(self._item.project_id)
        self._on_click(self._item.project_id)

    def destroy(self) -> None:
        _unbind_configure_recursive(self)
        super().destroy()


class SessionList(ctk.CTkFrame):
    """Sidebar list of agent sessions grouped by project."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_select: Callable[[str], None],
        on_new_chat: Callable[[], None],
        on_delete: Callable[[str], None] | None = None,
        on_new_agent: Callable[[str], None] | None = None,
        on_select_project: Callable[[str], None] | None = None,
        on_new_project: Callable[[], None] | None = None,
        on_delete_project: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self._on_select = on_select
        self._on_new_chat = on_new_chat
        self._on_delete = on_delete
        self._on_new_agent = on_new_agent or (lambda mode: on_new_chat())
        self._on_select_project = on_select_project or (lambda pid: None)
        self._on_new_project = on_new_project or (lambda: None)
        self._on_delete_project = on_delete_project
        self._active_session_id = ""
        self._active_project_id: str | None = None
        self._expanded: set[str] = set()
        self._cards: list[_SessionCard | _ProjectHeader] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Title "Agents"
        title = ctk.CTkLabel(
            self,
            text="Agents",
            anchor="w",
            text_color=theme.COLOR_TEXT_MUTED,
            font=(theme.FONT_FAMILY, 12, "bold"),
        )
        title.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 6))

        # Button row: [+ Project] and [+ ▾]
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 8))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=0)

        self._new_project_btn = ctk.CTkButton(
            btn_row,
            text="+ Project",
            height=28,
            fg_color=theme.COLOR_BG_INPUT,
            text_color=theme.COLOR_TEXT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            font=(theme.FONT_FAMILY, 11),
            command=self._on_new_project,
        )
        self._new_project_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self._new_agent_btn = ctk.CTkButton(
            btn_row,
            text="+ ▾",
            height=28,
            width=52,
            fg_color=theme.COLOR_ACCENT,
            font=(theme.FONT_FAMILY, 11, "bold"),
            command=self._show_mode_menu,
        )
        self._new_agent_btn.grid(row=0, column=1, sticky="e")

        self._list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._list.grid(row=2, column=0, sticky="nsew")
        self._list.grid_columnconfigure(0, weight=1)

    def _show_mode_menu(self) -> None:
        """Show popup menu for agent mode selection."""
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="💬  Chat", command=lambda: self._on_new_agent("manual"))
        menu.add_command(label="↺  Loop", command=lambda: self._on_new_agent("loop"))
        menu.add_command(label="◷  Schedule", command=lambda: self._on_new_agent("schedule"))
        try:
            btn = self._new_agent_btn
            x = btn.winfo_rootx()
            y = btn.winfo_rooty() + btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_items(
        self,
        items: list[SessionListItem],
        active_session_id: str,
        projects: list[ProjectListItem] | None = None,
        active_project_id: str | None = None,
    ) -> None:
        """Rebuild the list grouped by project."""
        self._active_session_id = active_session_id
        self._active_project_id = active_project_id

        # Destroy existing widgets
        for card in self._cards:
            card.destroy()
        self._cards.clear()

        # Auto-expand new projects
        if projects:
            for proj in projects:
                if proj.project_id not in self._expanded and not proj.expanded:
                    pass  # leave collapsed
                else:
                    self._expanded.add(proj.project_id)

        row = 0
        project_list = projects or []

        # Build lookup: project_id -> list of sessions
        project_sessions: dict[str, list[SessionListItem]] = {}
        no_project_items: list[SessionListItem] = []
        for item in items:
            if item.project_id:
                project_sessions.setdefault(item.project_id, []).append(item)
            else:
                no_project_items.append(item)

        # Render project groups
        for proj in project_list:
            expanded = proj.project_id in self._expanded
            proj_item = ProjectListItem(
                project_id=proj.project_id,
                name=proj.name,
                expanded=expanded,
                agent_count=len(project_sessions.get(proj.project_id, [])),
            )
            header = _ProjectHeader(
                self._list,
                item=proj_item,
                on_click=self._on_select_project,
                on_toggle=self._toggle_project,
                active=(proj.project_id == active_project_id and active_session_id == ""),
            )
            header.grid(row=row, column=0, sticky="ew", padx=4, pady=(4, 1))
            self._cards.append(header)
            row += 1

            if expanded:
                for session_item in project_sessions.get(proj.project_id, []):
                    active = session_item.session_id == active_session_id
                    card = _SessionCard(
                        self._list,
                        item=session_item,
                        active=active,
                        on_click=self._on_select,
                        on_delete=self._on_delete,
                        indent=True,
                    )
                    card.grid(row=row, column=0, sticky="ew", padx=(16, 4), pady=1)
                    self._cards.append(card)
                    row += 1

        # Orphan sessions (no project)
        if no_project_items:
            if project_list:
                sep = ctk.CTkLabel(
                    self._list,
                    text="── No Project ──",
                    text_color=theme.COLOR_TEXT_MUTED,
                    font=(theme.FONT_FAMILY, 10),
                )
                sep.grid(row=row, column=0, sticky="ew", padx=6, pady=(8, 2))
                row += 1

            for item in no_project_items:
                active = item.session_id == active_session_id
                card = _SessionCard(
                    self._list,
                    item=item,
                    active=active,
                    on_click=self._on_select,
                    on_delete=self._on_delete,
                )
                card.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
                self._cards.append(card)
                row += 1

        # If no projects at all, just show all sessions (backward compat)
        if not project_list and not no_project_items:
            for item in items:
                active = item.session_id == active_session_id
                card = _SessionCard(
                    self._list,
                    item=item,
                    active=active,
                    on_click=self._on_select,
                    on_delete=self._on_delete,
                )
                card.grid(row=row, column=0, sticky="ew", padx=6, pady=1)
                self._cards.append(card)
                row += 1

    def _toggle_project(self, project_id: str) -> None:
        if project_id in self._expanded:
            self._expanded.discard(project_id)
        else:
            self._expanded.add(project_id)

    def set_active(self, session_id: str) -> None:
        """Update active state without full rebuild."""
        self._active_session_id = session_id
