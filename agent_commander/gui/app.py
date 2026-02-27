"""Main customtkinter desktop application."""

from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from agent_commander.usage.models import AgentUsageSnapshot

import customtkinter as ctk
from loguru import logger

from agent_commander.gui import theme
from agent_commander.session.extension_store import ExtensionStore
from agent_commander.session.gui_store import GUIStore
from agent_commander.session.project_store import ProjectStore
from agent_commander.gui.chat_panel import ChatMessage, ChatPanel
from agent_commander.gui.file_tray import FileTrayPanel
from agent_commander.gui.input_bar import InputBar
from agent_commander.gui.notifications import send_notification
from agent_commander.gui.plan_panel import PlanPanel
from agent_commander.gui.project_dialog import ProjectDialog
from agent_commander.gui.extensions_panel import ExtensionsPanel
from agent_commander.gui.project_panel import ProjectPanel
from agent_commander.gui.schedule_dialog import ScheduleDef
from agent_commander.gui.new_session_panel import NewSessionPanel
from agent_commander.gui.search_handler import SearchHandler
from agent_commander.gui.session_list import ProjectListItem, SessionListItem
from agent_commander.gui.session_manager import SessionManager, SessionState
from agent_commander.gui.settings_dialog import SettingsPanel
from agent_commander.gui.extension_bar import ExtensionBar
from agent_commander.gui.skill_bar import SkillBar
from agent_commander.gui.team_dialog import TeamPanel
from agent_commander.providers.capabilities import PLATFORM_CONTEXT
from agent_commander.session.skill_store import SkillStore
from agent_commander.gui.state_store import WindowState, load_window_state, save_window_state
from agent_commander.gui.sidebar import Sidebar
from agent_commander.gui.terminal_panel import TerminalPanel
from agent_commander.gui.widgets.status_bar import StatusBar
from agent_commander.utils.helpers import safe_filename

OnUserInput = Callable[[str, str, str, str | None, "dict | None"], None]
OnSessionStart = Callable[[str, str, str | None], None]
OnScheduleCreate = Callable[[str, str, str], None]  # session_id, prompt, cron_expr
OnDeleteSession = Callable[[str], None]              # session_id
OnClose = Callable[[], None]


def _find_icon() -> Path | None:
    """Resolve logo_w.ico from project root (works both frozen and dev)."""
    app_dir = os.environ.get("AGENT_COMMANDER_APP_DIR", "")
    root = Path(app_dir) if app_dir else Path(__file__).resolve().parents[2]
    ico = root / "logo_w.ico"
    return ico if ico.exists() else None


def _parse_checklist(text: str) -> list[dict]:
    """Parse markdown checklist items from agent response."""
    items = re.findall(r"- \[( |x|X)\] (.+)", text)
    return [{"text": t.strip(), "done": s.lower() == "x"} for s, t in items]


class TriptychApp:
    """Desktop GUI in Telegram-like triptych layout."""

    def __init__(
        self,
        on_user_input: OnUserInput | None = None,
        on_session_start: OnSessionStart | None = None,
        on_schedule_create: OnScheduleCreate | None = None,
        on_delete_session: OnDeleteSession | None = None,
        on_close: OnClose | None = None,
        default_agent: str = "codex",
        window_width: int = theme.WINDOW_WIDTH,
        window_height: int = theme.WINDOW_HEIGHT,
        window_state_path: Path | None = None,
        notify_on_long_tasks: bool = True,
        long_task_notify_s: float = 12.0,
        server_manager: object | None = None,
        session_store: GUIStore | None = None,
        skill_store: SkillStore | None = None,
        project_store: ProjectStore | None = None,
        extension_store: ExtensionStore | None = None,
    ) -> None:
        self._on_user_input = on_user_input
        self._on_session_start = on_session_start
        self._on_schedule_create = on_schedule_create
        self._on_delete_session = on_delete_session
        self._on_close = on_close
        self._default_agent = default_agent
        self._window_width = window_width
        self._window_height = window_height
        self._window_state_path = window_state_path
        self._notify_on_long_tasks = notify_on_long_tasks
        self._server_manager = server_manager
        self._session_store = session_store
        self._skill_store = skill_store
        self._project_store = project_store or (ProjectStore() if session_store is not None else None)
        self._extension_store = extension_store

        self._root: ctk.CTk | None = None
        self._chat_panel: ChatPanel | None = None
        self._terminal_panel: TerminalPanel | None = None
        self._sidebar: Sidebar | None = None
        self._input_bar: InputBar | None = None
        self._status_bar: StatusBar | None = None
        self._file_tray: FileTrayPanel | None = None
        self._file_tray_visible: bool = True
        self._skill_bar: SkillBar | None = None
        self._extension_bar: ExtensionBar | None = None
        self._plan_panel: PlanPanel | None = None
        self._project_panel: ProjectPanel | None = None
        self._extensions_panel: ExtensionsPanel | None = None
        self._team_panel: TeamPanel | None = None
        self._settings_panel: SettingsPanel | None = None
        self._new_session_panel: NewSessionPanel | None = None
        self._mode_switch: ctk.CTkSegmentedButton | None = None
        self._search_entry: ctk.CTkEntry | None = None
        self._long_task_notify_s = long_task_notify_s
        self._active_project_id: str | None = None
        self._showing_project_panel = False
        self._showing_extensions_panel = False
        self._showing_team_panel = False
        self._showing_settings_panel = False
        self._showing_new_session_panel = False
        self._new_session_mode: str = "manual"

        self._ui_thread_id: int | None = None
        self._pending_calls: list[Callable[[], None]] = []

        self._sm = SessionManager(session_store, default_agent)
        self._search = SearchHandler()

        # Default in-memory session when no persistent store is configured.
        if session_store is None:
            self._sm.create()

    def run(self) -> None:
        """Build and run tkinter mainloop."""
        theme.setup_theme()
        root = ctk.CTk()
        self._root = root
        self._ui_thread_id = threading.get_ident()

        root.title("Agent Commander")
        _icon = _find_icon()
        if _icon is not None:
            try:
                root.iconbitmap(str(_icon))
            except Exception as exc:
                logger.warning("Failed to set window icon: {}", exc)
        root.minsize(1024, 640)
        saved_state = load_window_state(path=self._window_state_path)
        if saved_state:
            root.geometry(f"{saved_state.width}x{saved_state.height}+{saved_state.x}+{saved_state.y}")
        else:
            root.geometry(f"{self._window_width}x{self._window_height}")
        root.configure(fg_color=theme.COLOR_BG_APP)

        if self._session_store is not None:
            if self._sm.load_persisted() is None:
                self._sm.create()

        root.protocol("WM_DELETE_WINDOW", self._handle_close)
        root.bind("<Control-f>", self._focus_search_shortcut)
        root.bind("<F3>", self._search_next_shortcut)

        root.grid_columnconfigure(0, weight=1)  # sidebar (1/4 of flexible space)
        root.grid_columnconfigure(1, weight=3)  # main content (3/4 of flexible space)
        root.grid_columnconfigure(2, weight=0)  # file tray (fixed)
        root.grid_rowconfigure(0, weight=1)

        self._sidebar = Sidebar(
            root,
            on_select_session=self._switch_session,
            on_new_chat=self._new_chat,
            on_select_agent=self._set_active_agent,
            on_delete_session=self._delete_session,
            on_new_agent=self._on_new_agent,
            on_select_project=self._on_select_project,
            on_new_project=self._on_new_project,
            on_delete_project=self._on_delete_project,
        )
        self._sidebar.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)

        main = ctk.CTkFrame(root, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=10)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(main, fg_color="transparent")
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top_bar.grid_columnconfigure(0, weight=0)
        top_bar.grid_columnconfigure(1, weight=1)
        top_bar.grid_columnconfigure(2, weight=0)
        top_bar.grid_columnconfigure(3, weight=0)
        top_bar.grid_columnconfigure(4, weight=0)
        top_bar.grid_columnconfigure(5, weight=0)

        self._mode_switch = ctk.CTkSegmentedButton(
            top_bar,
            values=["Chat", "Terminal"],
            command=self._on_mode_switch,
            width=220,
        )
        self._mode_switch.grid(row=0, column=0, sticky="w")
        self._mode_switch.set("Chat")

        self._search_entry = ctk.CTkEntry(
            top_bar,
            placeholder_text="Search in this chat (Ctrl+F)",
            height=32,
        )
        self._search_entry.grid(row=0, column=1, sticky="ew", padx=(10, 8))
        self._search_entry.bind("<Return>", self._on_search_next_event)

        team_btn = ctk.CTkButton(
            top_bar,
            text="Team",
            width=90,
            command=self._toggle_team_panel,
        )
        team_btn.grid(row=0, column=2, sticky="e", padx=(0, 8))

        self._ext_btn = ctk.CTkButton(
            top_bar,
            text="Extensions",
            width=110,
            command=self._toggle_extensions_panel,
        )
        self._ext_btn.grid(row=0, column=3, sticky="e", padx=(0, 8))

        settings_btn = ctk.CTkButton(
            top_bar,
            text="Settings",
            width=100,
            command=self._toggle_settings_panel,
        )
        settings_btn.grid(row=0, column=4, sticky="e", padx=(0, 8))

        self._files_btn = ctk.CTkButton(
            top_bar,
            text="Files ▸",
            width=86,
            command=self._toggle_file_tray,
        )
        self._files_btn.grid(row=0, column=5, sticky="e")

        # --- Content panel ---
        content = ctk.CTkFrame(
            main,
            fg_color=theme.COLOR_BG_PANEL,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=10,
        )
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)

        self._chat_panel = ChatPanel(content)
        self._chat_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self._terminal_panel = TerminalPanel(content)
        self._terminal_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self._terminal_panel.grid_remove()

        # Project panel (hidden initially, shown when project is selected)
        if self._project_store is not None:
            self._project_panel = ProjectPanel(
                content,
                project_store=self._project_store,
                on_edit=self._on_edit_project,
                on_delete=self._on_delete_project,
                on_add_agent=lambda pid: self._on_new_agent("manual"),
                on_select_agent=self._switch_session,
            )
            self._project_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
            self._project_panel.grid_remove()

        # --- Plan panel (row=2, hidden until loop mode active) ---
        self._plan_panel = PlanPanel(
            main,
            on_pause=self._on_loop_pause,
            on_stop=self._on_loop_stop,
        )
        self._plan_panel.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._plan_panel.grid_remove()

        # --- Skill bar (row=3) — only when skill_store is available ---
        if self._skill_store is not None:
            self._skill_bar = SkillBar(
                main,
                skill_store=self._skill_store,
                on_open_team=self._toggle_team_panel,
            )
            self._skill_bar.grid(row=3, column=0, sticky="ew", pady=(4, 2))

        # --- Extension bar (row=4) — only when extension_store is available ---
        if self._extension_store is not None:
            self._extension_bar = ExtensionBar(
                main,
                extension_store=self._extension_store,
                on_open_extensions=self._toggle_extensions_panel,
            )
            self._extension_bar.grid(row=4, column=0, sticky="ew", pady=(0, 2))

        self._input_bar = InputBar(
            main,
            agents=["claude", "gemini", "codex"],
            on_submit=self._handle_submit,
            on_workdir_change=self._update_file_tray,
            on_stop_schedule=self._on_stop_schedule_from_bar,
            on_edit_schedule=self._on_edit_schedule_from_bar,
        )
        self._input_bar.grid(row=5, column=0, sticky="ew", pady=(6, 6))

        self._status_bar = StatusBar(main)
        self._status_bar.grid(row=6, column=0, sticky="ew")

        # --- File tray (right column) ---
        self._file_tray = FileTrayPanel(root, on_status=self.set_status)
        self._file_tray.grid(row=0, column=2, sticky="nsew", padx=(6, 10), pady=10)
        self._file_tray.enable_dnd()

        self._refresh_sidebar()
        self._render_active_session()
        self._apply_pending_calls()
        self.set_status("GUI ready")
        self._start_session_runtime(self._sm.sessions[self._sm.active_session_id])

        root.mainloop()

    def stop(self) -> None:
        """Close GUI safely from any thread."""
        self._run_on_ui(self._handle_close)

    def set_status(self, text: str) -> None:
        self._run_on_ui(lambda: self._set_status_ui(text))

    def set_usage_placeholder(self, text: str) -> None:
        """Show a placeholder text in the usage area (e.g. 'Codex: checking limits…')."""
        self._run_on_ui(
            lambda: self._status_bar.set_usage(text) if self._status_bar else None
        )

    def update_usage(self, agent: str, snapshot: "AgentUsageSnapshot") -> None:
        """Thread-safe update of the right-side usage display in the status bar.

        Each agent reports its own snapshot; all are combined into one line.
        """
        self._run_on_ui(lambda: self._store_and_render_usage(agent, snapshot))

    def _store_and_render_usage(self, agent: str, snapshot: "AgentUsageSnapshot") -> None:
        if not hasattr(self, "_usage_snapshots"):
            self._usage_snapshots: dict[str, "AgentUsageSnapshot"] = {}
        self._usage_snapshots[agent] = snapshot
        self._update_usage_ui()

    def _update_usage_ui(self) -> None:
        if self._status_bar is None:
            return
        snapshots: dict[str, "AgentUsageSnapshot"] = getattr(
            self, "_usage_snapshots", {}
        )
        if not snapshots:
            return

        agent_parts: list[str] = []
        # Track the worst remaining % across quota windows to pick status colour.
        min_remaining: float | None = None

        for agent, snap in snapshots.items():
            if snap.error or not snap.windows:
                continue
            quota_windows = [w for w in snap.windows if w.has_quota]
            # For agents with many model windows (e.g. Gemini), show only the
            # most-constrained window to keep the status bar concise.
            display_windows = snap.windows if len(quota_windows) <= 2 else [snap.primary]
            window_parts: list[str] = []
            for w in (display_windows or snap.windows[:1]):
                if w is None:
                    continue
                window_parts.append(w.format_status())
                if w.has_quota:
                    r = w.remaining_percent
                    if min_remaining is None or r < min_remaining:
                        min_remaining = r
            if window_parts:
                label = "  ·  ".join(window_parts)
                agent_parts.append(f"{agent.capitalize()}: {label}")

        if not agent_parts:
            return

        text = "    ·    ".join(agent_parts)
        self._status_bar.set_usage(text, remaining_percent=min_remaining)

    def receive_tool_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Called from asyncio thread — routes tool call log to UI thread."""
        self._run_on_ui(lambda: self._receive_tool_chunk_ui(session_id, chunk, final))

    def receive_assistant_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Receive assistant response chunk and render/update session."""
        self._run_on_ui(lambda: self._receive_assistant_chunk_ui(session_id, chunk, final))

    def receive_terminal_chunk(self, chunk: str, session_id: str | None = None) -> None:
        """Append raw terminal output for a specific session."""
        sid = session_id or self._sm.active_session_id
        self._run_on_ui(lambda: self._append_terminal_ui(chunk, sid))

    def receive_system_message(self, session_id: str, text: str) -> None:
        """Render system message in target session."""
        self._run_on_ui(lambda: self._receive_system_message_ui(session_id, text))

    def _handle_submit(self, text: str, agent: str, cwd: str | None) -> None:
        session = self._sm.sessions[self._sm.active_session_id]
        session.agent = agent
        session.workdir = (cwd or "").strip()
        is_first_user_msg = not any(m.role == "user" for m in session.messages)

        full_text = text
        if is_first_user_msg:
            ctx_parts: list[str] = []
            ctx_parts.append(PLATFORM_CONTEXT)

            if self._skill_bar is not None and self._skill_store is not None:
                active_ids = self._skill_bar.get_active_ids()
                session.active_skill_ids = active_ids
                self._skill_bar.set_locked(True)
                if active_ids:
                    skill_ctx = self._skill_store.build_context(active_ids)
                    if skill_ctx:
                        ctx_parts.append(f"## Active Skills\n\n{skill_ctx}")
                        if self._session_store is not None:
                            try:
                                self._session_store.get_context_path(
                                    session.session_id
                                ).write_text(skill_ctx, encoding="utf-8")
                            except Exception as exc:
                                logger.warning("Failed to write context.md for session {}: {}", session.session_id, exc)

            if self._extension_bar is not None and self._extension_store is not None:
                ext_ids = self._extension_bar.get_active_ids()
                session.active_extension_ids = ext_ids
                self._extension_bar.set_locked(True)
                if ext_ids:
                    ext_ctx = self._extension_store.build_context(ext_ids)
                    if ext_ctx:
                        ctx_parts.append(f"## Connected Extensions\n\n{ext_ctx}")

            # Inject loop instructions for loop-mode first message
            if session.mode == "loop":
                ctx_parts.append(
                    "## Loop Mode\n\nYou are running in loop mode. "
                    "Create a markdown checklist of steps using `- [ ] step` syntax. "
                    "When all steps are done, output `[TASK_COMPLETE]` on its own line."
                )

            combined_ctx = "\n\n---\n\n".join(ctx_parts)
            if combined_ctx:
                full_text = f"<context>\n{combined_ctx}\n</context>\n\n{text}"

        session.messages.append(ChatMessage(role="user", text=text))
        session.messages.append(ChatMessage(role="assistant", text=""))
        session.streaming = True
        session.request_started_at = time.monotonic()

        if is_first_user_msg:
            self._sm.maybe_auto_title(session, text)

        # Update loop state
        if session.mode == "loop" and session.loop_state is not None:
            session.loop_state.status = "running"
            self._update_plan_panel(session)

        self._sm.persist_message(session.session_id, "user", text)
        self._update_file_tray(session.workdir)

        if self._chat_panel:
            self._chat_panel.add_message("user", text)
            self._chat_panel.begin_assistant_stream()
        if self._input_bar:
            self._input_bar.set_typing(True)

        self.set_status(f"Sending to {agent}...")
        self._refresh_sidebar()

        # Pass loop_mode in extra_meta if session is in loop mode
        extra_meta: dict | None = None
        if session.mode == "loop":
            extra_meta = {"loop_mode": True}

        if self._on_user_input:
            self._on_user_input(session.session_id, full_text, agent, session.workdir or None, extra_meta)

    def _receive_assistant_chunk_ui(self, session_id: str, chunk: str, final: bool) -> None:
        session = self._sm.sessions.get(session_id)
        if session is None:
            logger.debug(f"Dropping assistant chunk for unknown/deleted session {session_id!r}")
            return

        if not session.messages or session.messages[-1].role != "assistant":
            session.messages.append(ChatMessage(role="assistant", text=""))
            session.streaming = True

        session.messages[-1].text += chunk
        if final:
            session.streaming = False

        if final:
            full_text = session.messages[-1].text
            self._sm.persist_message(session_id, "assistant", full_text)

            # Update loop state if in loop mode
            if session.mode == "loop" and session.loop_state is not None:
                session.loop_state.iteration += 1
                checklist = _parse_checklist(full_text)
                if checklist:
                    session.loop_state.checklist = checklist
                if session.loop_state.status == "running":
                    session.loop_state.status = "running"
                self._update_plan_panel(session)

        if session_id == self._sm.active_session_id and self._chat_panel:
            self._chat_panel.append_assistant_chunk(chunk, final=final)
            if final and self._input_bar:
                self._input_bar.set_typing(False)
                self.set_status(f"Ready | Session: {session.title} | Agent: {session.agent}")
            if final:
                self._notify_if_long_turn(session)

        self._refresh_sidebar()

    def _receive_tool_chunk_ui(self, session_id: str, chunk: str, final: bool) -> None:
        """Append a tool call log chunk to a separate tool_log bubble."""
        session = self._sm.sessions.get(session_id)
        if session is None:
            return

        # Guard: empty final signal with no open tool_log → nothing to do
        if final and not chunk:
            last_role = session.messages[-1].role if session.messages else None
            if last_role != "tool_log":
                return

        # If assistant bubble is currently streaming, finalize it before the tool log
        if session.streaming and session.messages and session.messages[-1].role == "assistant":
            session.streaming = False
            full_text = session.messages[-1].text
            self._sm.persist_message(session_id, "assistant", full_text)
            if session_id == self._sm.active_session_id and self._chat_panel:
                self._chat_panel.append_assistant_chunk("", final=True)

        # Ensure last message is tool_log
        if not session.messages or session.messages[-1].role != "tool_log":
            session.messages.append(ChatMessage(role="tool_log", text=""))
            if session_id == self._sm.active_session_id and self._chat_panel:
                self._chat_panel.begin_tool_stream()

        session.messages[-1].text += chunk

        if final:
            self._sm.persist_message(session_id, "tool_log", session.messages[-1].text)

        if session_id == self._sm.active_session_id and self._chat_panel:
            self._chat_panel.append_tool_chunk(chunk, final=final)

        self._refresh_sidebar()

    def _receive_system_message_ui(self, session_id: str, text: str) -> None:
        session = self._sm.sessions.get(session_id)
        if session is None:
            logger.debug(f"Dropping system message for unknown/deleted session {session_id!r}")
            return
        session.messages.append(ChatMessage(role="system", text=text))
        self._sm.persist_message(session_id, "system", text)
        if session_id == self._sm.active_session_id and self._chat_panel:
            self._chat_panel.add_message("system", text)
        self._refresh_sidebar()

    def _append_terminal_ui(self, chunk: str, session_id: str | None = None) -> None:
        if self._terminal_panel:
            self._terminal_panel.append_text(chunk, session_id=session_id)

    def _on_mode_switch(self, value: str) -> None:
        if not self._chat_panel or not self._terminal_panel:
            return
        if value == "Terminal":
            self._chat_panel.grid_remove()
            self._terminal_panel.grid()
        else:
            self._terminal_panel.grid_remove()
            self._chat_panel.grid()

    def _new_chat(self) -> None:
        self._on_new_agent("manual")

    def _on_new_agent(self, mode: str) -> None:
        """Show inline new-session panel for the given mode."""
        self._new_session_mode = mode
        self._show_new_session_panel(mode=mode)

    def _show_new_session_panel(
        self,
        mode: str = "manual",
        existing_session_id: str | None = None,
    ) -> None:
        """Show the inline new/edit session panel."""
        content = self._get_content_widget()
        if self._chat_panel:
            self._chat_panel.grid_remove()
        if self._terminal_panel:
            self._terminal_panel.grid_remove()
        if self._project_panel:
            self._project_panel.grid_remove()
        self._hide_overlay_panels()

        # Determine defaults
        current_agent = self._sm.sessions[self._sm.active_session_id].agent
        existing_sched: ScheduleDef | None = None
        existing_prompt: str = ""
        if existing_session_id:
            sess = self._sm.sessions.get(existing_session_id)
            if sess:
                current_agent = sess.agent
                existing_sched = sess.schedule_def
                existing_prompt = sess.schedule_prompt

        if content is not None:
            # Always recreate to get fresh state
            if self._new_session_panel is not None:
                self._new_session_panel.destroy()
                self._new_session_panel = None

            self._new_session_panel = NewSessionPanel(
                content,
                mode=mode,
                default_agent=current_agent,
                agents=["claude", "gemini", "codex"],
                on_create=lambda agent, sched, prompt: self._on_new_session_created(
                    agent, sched, prompt, mode, existing_session_id,
                ),
                on_cancel=self._show_chat_panel,
                existing_schedule=existing_sched,
                existing_prompt=existing_prompt,
            )
            self._new_session_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self._showing_new_session_panel = True
        self._showing_project_panel = False
        self._active_project_id = None if existing_session_id is None else self._active_project_id
        if self._mode_switch:
            self._mode_switch.configure(state="disabled")
        self._refresh_sidebar()

    def _on_new_session_created(
        self,
        agent: str,
        sched: ScheduleDef | None,
        prompt: str,
        mode: str,
        edit_session_id: str | None,
    ) -> None:
        """Called when user clicks Create/Save in NewSessionPanel."""
        if edit_session_id:
            # Edit existing schedule session
            session = self._sm.sessions.get(edit_session_id)
            if session and sched:
                # Cancel old cron job
                if self._on_delete_session:
                    self._on_delete_session(edit_session_id)
                session.schedule_def = sched
                session.schedule_def.enabled = True
                session.schedule_prompt = prompt
                # Re-register new cron job
                self._start_session_runtime(session)
            self._show_chat_panel()
            self._render_active_session()
            self._refresh_sidebar()
            return

        # Create new session
        session = self._sm.create(
            agent=agent,
            mode=mode,
            project_id=self._active_project_id,
        )
        if sched:
            session.schedule_def = sched
            session.schedule_prompt = prompt
        if self._active_project_id and self._project_store:
            self._project_store.add_agent(self._active_project_id, session.session_id)

        self._show_chat_panel()
        self._render_active_session()
        self._refresh_sidebar()
        self._start_session_runtime(session)

    def _on_select_project(self, project_id: str) -> None:
        """Show project panel when a project header is clicked."""
        self._active_project_id = project_id
        self._show_project_panel(project_id)
        self._refresh_sidebar()

    def _on_new_project(self) -> None:
        """Open project creation dialog."""
        root = self._root
        if root is None:
            return

        def _on_save(name: str, desc: str, workdir: str) -> None:
            if self._project_store is None:
                return
            self._project_store.create_project(name, desc, workdir)
            self._refresh_sidebar()

        dlg = ProjectDialog(root, on_save=_on_save)
        self._center_child_window(dlg)

    def _on_edit_project(self, project_id: str) -> None:
        """Open project edit dialog."""
        root = self._root
        if root is None or self._project_store is None:
            return
        meta = self._project_store.get_project(project_id)
        if meta is None:
            return

        def _on_save(name: str, desc: str, workdir: str) -> None:
            if self._project_store is None:
                return
            meta.name = name
            meta.description = desc
            meta.workdir = workdir
            self._project_store.update_project(meta)
            self._refresh_sidebar()
            # Reload project panel
            if self._showing_project_panel and self._project_panel:
                self._project_panel.load_project(project_id, self._get_project_agents(project_id))

        dlg = ProjectDialog(root, meta=meta, on_save=_on_save)
        self._center_child_window(dlg)

    def _on_delete_project(self, project_id: str) -> None:
        """Confirm and delete project, reassigning its agents."""
        if self._project_store is None:
            return
        meta = self._project_store.get_project(project_id)
        if meta is None:
            return
        if not self._confirm_delete_dialog(meta.name, item_type="project"):
            return

        # Orphan all agent sessions from the project
        for session in self._sm.sessions.values():
            if session.project_id == project_id:
                session.project_id = None

        self._project_store.delete_project(project_id)
        if self._active_project_id == project_id:
            self._active_project_id = None
            self._show_chat_panel()
        self._refresh_sidebar()

    def _hide_overlay_panels(self) -> None:
        """Hide all overlay panels (extensions, team, settings, new session)."""
        if self._extensions_panel:
            self._extensions_panel.grid_remove()
        if self._team_panel:
            self._team_panel.grid_remove()
        if self._settings_panel:
            self._settings_panel.grid_remove()
        if self._new_session_panel:
            self._new_session_panel.grid_remove()
        self._showing_extensions_panel = False
        self._showing_team_panel = False
        self._showing_settings_panel = False
        self._showing_new_session_panel = False

    def _show_project_panel(self, project_id: str) -> None:
        """Switch center panel to project view."""
        if self._project_panel is None:
            return
        if self._chat_panel:
            self._chat_panel.grid_remove()
        if self._terminal_panel:
            self._terminal_panel.grid_remove()
        self._hide_overlay_panels()
        self._project_panel.grid()
        self._project_panel.load_project(project_id, self._get_project_agents(project_id))
        self._showing_project_panel = True
        if self._mode_switch:
            self._mode_switch.configure(state="disabled")

    def _toggle_extensions_panel(self) -> None:
        """Toggle the extensions panel on/off."""
        if self._showing_extensions_panel:
            self._show_chat_panel()
        else:
            self._show_extensions_panel()

    def _show_extensions_panel(self) -> None:
        """Switch center panel to extensions view."""
        content = self._get_content_widget()
        if self._chat_panel:
            self._chat_panel.grid_remove()
        if self._terminal_panel:
            self._terminal_panel.grid_remove()
        if self._project_panel:
            self._project_panel.grid_remove()
        self._hide_overlay_panels()

        if self._extensions_panel is None and content is not None:
            store = self._extension_store
            if store is None:
                from agent_commander.session.extension_store import ExtensionStore
                store = ExtensionStore()
                self._extension_store = store
            self._extensions_panel = ExtensionsPanel(content, extension_store=store)
            self._extensions_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        elif self._extensions_panel is not None:
            self._extensions_panel.grid()
            self._extensions_panel.refresh()

        self._showing_extensions_panel = True
        self._showing_project_panel = False
        self._active_project_id = None
        if self._mode_switch:
            self._mode_switch.configure(state="disabled")
        self._refresh_sidebar()

    def _toggle_team_panel(self) -> None:
        """Toggle the team/skill-library panel on/off."""
        if self._showing_team_panel:
            self._show_chat_panel()
        else:
            self._show_team_panel()

    def _show_team_panel(self) -> None:
        """Switch center panel to team/skill-library view."""
        content = self._get_content_widget()
        if self._chat_panel:
            self._chat_panel.grid_remove()
        if self._terminal_panel:
            self._terminal_panel.grid_remove()
        if self._project_panel:
            self._project_panel.grid_remove()
        self._hide_overlay_panels()

        if self._team_panel is None and content is not None:
            self._team_panel = TeamPanel(
                content,
                skill_store=self._skill_store,
                on_skill_changed=self._on_skill_changed,
            )
            self._team_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        elif self._team_panel is not None:
            self._team_panel.grid()
            self._team_panel.refresh()

        self._showing_team_panel = True
        self._showing_project_panel = False
        self._active_project_id = None
        if self._mode_switch:
            self._mode_switch.configure(state="disabled")
        self._refresh_sidebar()

    def _toggle_settings_panel(self) -> None:
        """Toggle the settings panel on/off."""
        if self._showing_settings_panel:
            self._show_chat_panel()
        else:
            self._show_settings_panel()

    def _show_settings_panel(self) -> None:
        """Switch center panel to settings view."""
        content = self._get_content_widget()
        if self._chat_panel:
            self._chat_panel.grid_remove()
        if self._terminal_panel:
            self._terminal_panel.grid_remove()
        if self._project_panel:
            self._project_panel.grid_remove()
        self._hide_overlay_panels()

        if self._settings_panel is None and content is not None:
            self._settings_panel = SettingsPanel(content, server_manager=self._server_manager)
            self._settings_panel.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        elif self._settings_panel is not None:
            self._settings_panel.grid()
            self._settings_panel.refresh()

        self._showing_settings_panel = True
        self._showing_project_panel = False
        self._active_project_id = None
        if self._mode_switch:
            self._mode_switch.configure(state="disabled")
        self._refresh_sidebar()

    def _get_content_widget(self) -> ctk.CTkBaseClass | None:
        """Return the content container widget (parent of chat_panel)."""
        if self._chat_panel is not None:
            return self._chat_panel.master  # type: ignore[return-value]
        return None

    def _show_chat_panel(self) -> None:
        """Switch center panel back to chat/terminal view."""
        was_showing_extensions = self._showing_extensions_panel
        if self._project_panel:
            self._project_panel.grid_remove()
        self._hide_overlay_panels()
        if self._chat_panel:
            self._chat_panel.grid()
        self._showing_project_panel = False
        if self._mode_switch:
            self._mode_switch.configure(state="normal")
        self._active_project_id = None
        # Refresh extension chips if user may have connected/disconnected accounts
        if was_showing_extensions and self._extension_bar is not None:
            self._extension_bar.refresh()
        self._refresh_sidebar()

    def _get_project_agents(self, project_id: str) -> list[tuple[str, str]]:
        """Return [(session_id, title)] for agents in the project."""
        result: list[tuple[str, str]] = []
        for session in self._sm.sessions.values():
            if session.project_id == project_id:
                result.append((session.session_id, session.title))
        return result

    def _update_plan_panel(self, session: SessionState) -> None:
        """Show or hide PlanPanel based on session loop state."""
        if session.mode == "loop" and session.loop_state is not None:
            if self._plan_panel:
                self._plan_panel.grid()
                self._plan_panel.update_loop_state(session.loop_state)
        else:
            if self._plan_panel:
                self._plan_panel.grid_remove()

    def _on_loop_pause(self) -> None:
        """Toggle loop pause state."""
        session = self._sm.sessions.get(self._sm.active_session_id)
        if session and session.loop_state:
            if session.loop_state.status == "running":
                session.loop_state.status = "paused"
            else:
                session.loop_state.status = "running"
            self._update_plan_panel(session)

    def _on_loop_stop(self) -> None:
        """Stop the loop for current session."""
        session = self._sm.sessions.get(self._sm.active_session_id)
        if session and session.loop_state:
            session.loop_state.status = "done"
            session.loop_state.stop_detected = True
            self._update_plan_panel(session)
        self.set_status("Loop stopped.")

    def _switch_session(self, session_id: str) -> None:
        if session_id not in self._sm.sessions:
            return
        self._show_chat_panel()
        self._active_project_id = None
        self._sm.active_session_id = session_id
        self._render_active_session()
        self._refresh_sidebar()
        self._start_session_runtime(self._sm.sessions[session_id])

    def _confirm_delete_dialog(self, title: str, item_type: str = "chat") -> bool:
        """Custom styled delete confirmation dialog. Returns True if confirmed."""
        root = self._root
        if root is None:
            return False
        result: dict[str, bool] = {"confirmed": False}
        dialog = ctk.CTkToplevel(root)
        dialog.title(f"Delete {item_type.capitalize()}")
        dialog.geometry("360x190")
        dialog.resizable(False, False)
        dialog.transient(root)
        theme.apply_window_icon(dialog)
        dialog.grab_set()
        dialog.configure(fg_color=theme.COLOR_BG_APP)
        dialog.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            dialog,
            text=f"Delete {item_type.capitalize()}",
            font=(theme.FONT_FAMILY, 15, "bold"),
            text_color=theme.COLOR_TEXT,
        ).grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 6))

        ctk.CTkLabel(
            dialog,
            text=f'Delete "{title}"?\n\nThis cannot be undone.',
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.COLOR_TEXT_MUTED,
            justify="center",
        ).grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 14))

        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 18))
        actions.grid_columnconfigure(0, weight=1)

        def _cancel() -> None:
            dialog.destroy()

        def _delete() -> None:
            result["confirmed"] = True
            dialog.destroy()

        ctk.CTkButton(actions, text="Cancel", width=90, command=_cancel).grid(
            row=0, column=1, sticky="e", padx=(0, 8)
        )
        ctk.CTkButton(
            actions,
            text="Delete",
            width=100,
            fg_color=theme.COLOR_DANGER,
            hover_color="#C04040",
            command=_delete,
        ).grid(row=0, column=2, sticky="e")

        dialog.bind("<Escape>", lambda _e: _cancel())
        dialog.bind("<Return>", lambda _e: _delete())
        self._center_child_window(dialog)
        dialog.lift(root)
        try:
            dialog.focus_force()
        except Exception:
            dialog.focus_set()
        dialog.wait_window()
        return result["confirmed"]

    def _delete_session(self, session_id: str) -> None:
        """Delete a session after confirmation, then switch to another or create new."""
        session = self._sm.sessions.get(session_id)
        if session is None:
            return
        title = session.title or session_id
        if not self._confirm_delete_dialog(title):
            return

        # Cancel any associated cron job before removing the session
        if session.mode == "schedule" and self._on_delete_session:
            logger.debug(f"Cancelling cron jobs for deleted schedule session {session_id!r}")
            self._on_delete_session(session_id)

        # Remove from project
        if session.project_id and self._project_store:
            self._project_store.remove_agent(session.project_id, session_id)

        was_active = session_id == self._sm.active_session_id
        self._sm.delete_session(session_id)

        if was_active:
            if self._sm.sessions:
                next_id = next(iter(self._sm.sessions))
                self._sm.active_session_id = next_id
                self._render_active_session()
                self._start_session_runtime(self._sm.sessions[next_id])
            else:
                new_session = self._sm.create(agent=self._default_agent)
                self._render_active_session()
                self._start_session_runtime(new_session)

        self._refresh_sidebar()
        self.set_status(f"Deleted chat: {title}")

    def _set_active_agent(self, agent: str) -> None:
        session = self._sm.sessions[self._sm.active_session_id]
        session.agent = agent
        if self._input_bar:
            self._input_bar.set_agent(agent)
        self.set_status(f"Active agent changed to {agent}")
        self._refresh_sidebar()

    def _toggle_file_tray(self) -> None:
        tray = self._file_tray
        if tray is None:
            return
        self._file_tray_visible = not self._file_tray_visible
        if self._file_tray_visible:
            tray.grid()
            self._files_btn.configure(text="Files ▸")
        else:
            tray.grid_remove()
            self._files_btn.configure(text="◂ Files")

    def _update_file_tray(self, workdir: str) -> None:
        tray = self._file_tray
        if tray is not None:
            tray.set_workdir(workdir or "")

    def _on_skill_changed(self) -> None:
        if self._skill_bar is not None:
            self._skill_bar.refresh()

    def _export_active_session_markdown(self) -> None:
        session = self._sm.sessions.get(self._sm.active_session_id)
        if not session:
            self.set_status("Export failed: no active session")
            return

        exports_dir = Path.home() / ".agent-commander" / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = safe_filename(session.title or session.session_id) or session.session_id
        output = exports_dir / f"{base_name}_{timestamp}.md"

        lines = [
            f"# {session.title}",
            "",
            f"- session_id: `{session.session_id}`",
            f"- exported_at: `{datetime.now().isoformat(timespec='seconds')}`",
            "",
        ]
        for message in session.messages:
            role = message.role.capitalize()
            lines.append(f"## {role}")
            lines.append("")
            lines.append(message.text or "")
            lines.append("")

        try:
            output.write_text("\n".join(lines), encoding="utf-8")
            self.set_status(f"Session exported: {output}")
        except Exception as exc:
            self.set_status(f"Export failed: {exc}")

    def _render_active_session(self) -> None:
        session = self._sm.sessions[self._sm.active_session_id]
        if self._terminal_panel:
            self._terminal_panel.set_active_session(session.session_id)
        search_status_applied = False
        if self._chat_panel:
            self._chat_panel.set_messages(session.messages)
            if session.streaming:
                self._chat_panel.append_assistant_chunk("", final=False)
            query = ""
            if self._search_entry is not None:
                query = self._search_entry.get().strip()
            self._search.clear(self._chat_panel)
            if query:
                index, total = self._chat_panel.search(query, forward=True)
                if total > 0:
                    self.set_status(f"Search: {index}/{total}")
                    search_status_applied = True
        if self._input_bar:
            self._input_bar.set_agent(session.agent)
            self._input_bar.set_workdir(session.workdir or None)
            self._input_bar.set_typing(session.streaming)
            self._input_bar.set_mode(session.mode)
            if session.mode == "schedule" and session.schedule_def:
                stopped = not session.schedule_def.enabled
                self._input_bar.set_schedule_info(
                    session.schedule_prompt,
                    session.schedule_def.display,
                    stopped=stopped,
                )
            else:
                self._input_bar.clear_schedule_info()
        self._update_file_tray(session.workdir)
        if self._skill_bar is not None:
            locked = any(m.role == "user" for m in session.messages)
            self._skill_bar.set_session(session.active_skill_ids, locked)
        if self._extension_bar is not None:
            locked = any(m.role == "user" for m in session.messages)
            self._extension_bar.set_session(session.active_extension_ids, locked)
        # Show/hide plan panel
        self._update_plan_panel(session)
        if not search_status_applied:
            self.set_status(f"Ready | Session: {session.title} | Agent: {session.agent}")

    def _refresh_sidebar(self) -> None:
        if not self._sidebar:
            return

        items: list[SessionListItem] = []
        for session in self._sm.sessions.values():
            preview = ""
            if session.messages:
                preview = session.messages[-1].text.strip().replace("\n", " ")
            stamp = datetime.now().strftime("%H:%M")
            items.append(
                SessionListItem(
                    session_id=session.session_id,
                    title=session.title,
                    preview=preview,
                    timestamp=stamp,
                    agent=session.agent,
                    streaming=session.streaming,
                    mode=session.mode,
                    project_id=session.project_id,
                )
            )

        # Build project list
        projects: list[ProjectListItem] = []
        if self._project_store is not None:
            for pmeta in self._project_store.list_projects():
                agent_count = sum(1 for s in self._sm.sessions.values() if s.project_id == pmeta.project_id)
                projects.append(ProjectListItem(
                    project_id=pmeta.project_id,
                    name=pmeta.name,
                    expanded=True,
                    agent_count=agent_count,
                ))

        panel_override = (
            self._showing_project_panel
            or self._showing_extensions_panel
            or self._showing_team_panel
            or self._showing_settings_panel
            or self._showing_new_session_panel
        )
        active_sid = "" if panel_override else self._sm.active_session_id
        self._sidebar.set_sessions(
            items,
            active_sid,
            projects=projects,
            active_project_id=self._active_project_id if self._showing_project_panel else None,
        )
        active_agent = self._sm.sessions[self._sm.active_session_id].agent
        self._sidebar.set_active_agent(active_agent)
        self._sidebar.set_agent_connected("claude", True)
        self._sidebar.set_agent_connected("gemini", True)
        self._sidebar.set_agent_connected("codex", True)

    def _start_session_runtime(self, session: SessionState) -> None:
        if self._on_session_start is None:
            return
        self._on_session_start(session.session_id, session.agent, session.workdir or None)
        # Register cron job for schedule sessions
        if (
            session.mode == "schedule"
            and session.schedule_def
            and session.schedule_def.cron_expr
            and self._on_schedule_create is not None
        ):
            self._on_schedule_create(
                session.session_id,
                session.schedule_prompt,
                session.schedule_def.cron_expr,
            )

    def _on_stop_schedule_from_bar(self) -> None:
        """Called from InputBar Stop/Restart button."""
        self._stop_schedule_session(self._sm.active_session_id)

    def _on_edit_schedule_from_bar(self) -> None:
        """Called from InputBar Edit button."""
        self._edit_schedule_session(self._sm.active_session_id)

    def _stop_schedule_session(self, session_id: str) -> None:
        """Stop (pause) the schedule — cancel cron job but keep the session."""
        session = self._sm.sessions.get(session_id)
        if session is None:
            return
        if session.schedule_def and session.schedule_def.enabled:
            # Cancel cron job
            if self._on_delete_session:
                self._on_delete_session(session_id)
            session.schedule_def.enabled = False
        else:
            # Restart — re-register cron job
            if session.schedule_def:
                session.schedule_def.enabled = True
            self._start_session_runtime(session)
        self._render_active_session()

    def _edit_schedule_session(self, session_id: str) -> None:
        """Open inline edit panel for the session's schedule settings."""
        session = self._sm.sessions.get(session_id)
        if session is None:
            return
        self._show_new_session_panel(mode="schedule", existing_session_id=session_id)

    def _center_child_window(self, child: ctk.CTkToplevel) -> None:
        root = self._root
        if root is None:
            return
        try:
            root.update_idletasks()
            child.update_idletasks()

            parent_x = int(root.winfo_rootx())
            parent_y = int(root.winfo_rooty())
            parent_w = int(root.winfo_width())
            parent_h = int(root.winfo_height())

            child_w = int(child.winfo_width()) or int(child.winfo_reqwidth())
            child_h = int(child.winfo_height()) or int(child.winfo_reqheight())
            if child_w <= 1:
                child_w = int(child.winfo_reqwidth())
            if child_h <= 1:
                child_h = int(child.winfo_reqheight())

            x = parent_x + max(0, (parent_w - child_w) // 2)
            y = parent_y + max(0, (parent_h - child_h) // 2)
            child.geometry(f"{child_w}x{child_h}+{x}+{y}")
        except Exception:
            return

    def _run_on_ui(self, fn: Callable[[], None]) -> None:
        if self._root is None:
            self._pending_calls.append(fn)
            return
        if threading.get_ident() == self._ui_thread_id:
            fn()
            return
        self._root.after(0, fn)

    def _apply_pending_calls(self) -> None:
        queued = list(self._pending_calls)
        self._pending_calls.clear()
        for fn in queued:
            fn()

    def _set_status_ui(self, text: str) -> None:
        if self._status_bar:
            self._status_bar.set_status(text)

    def _focus_search_shortcut(self, _event: object) -> str:
        if self._search_entry is None:
            return "break"
        self._search_entry.focus_set()
        self._search_entry.select_range(0, "end")
        return "break"

    def _search_next_shortcut(self, _event: object) -> str:
        self._search_next()
        return "break"

    def _on_search_next_event(self, _event: object) -> str:
        self._search_next()
        return "break"

    def _search_next(self) -> None:
        self._run_search(forward=True)

    def _search_prev(self) -> None:
        self._run_search(forward=False)

    def _run_search(self, forward: bool) -> None:
        if self._chat_panel is None or self._search_entry is None:
            return
        query = self._search_entry.get().strip()
        if not query:
            self._search.clear(self._chat_panel)
            session = self._sm.sessions[self._sm.active_session_id]
            self.set_status(f"Ready | Session: {session.title} | Agent: {session.agent}")
            return

        index, total = self._search.run(forward=forward, chat_panel=self._chat_panel, query=query)
        if total == 0:
            self.set_status(f"Search: no matches for '{query}'")
            return
        self.set_status(f"Search: {index}/{total} for '{query}'")

    def _notify_if_long_turn(self, session: SessionState) -> None:
        started = session.request_started_at
        session.request_started_at = None
        if started is None:
            return
        elapsed = time.monotonic() - started
        if elapsed < self._long_task_notify_s:
            return
        if not self._notify_on_long_tasks:
            return
        if self._window_is_active():
            return
        seconds = int(elapsed)
        send_notification(
            title="Agent Commander: response ready",
            message=f"{session.title} ({session.agent}) finished in {seconds}s.",
        )

    def _window_is_active(self) -> bool:
        root = self._root
        if root is None:
            return False
        try:
            if str(root.state()) == "iconic":
                return False
            return root.focus_displayof() is not None
        except Exception:
            return False

    def _handle_close(self) -> None:
        root = self._root
        if root:
            self._persist_window_state(root)
        if self._on_close:
            self._on_close()
        if root:
            try:
                root.quit()
                root.destroy()
            except Exception as exc:
                logger.warning("Error during GUI shutdown: {}", exc)
            self._root = None

    def _persist_window_state(self, root: ctk.CTk) -> None:
        try:
            root.update_idletasks()
            state = WindowState(
                width=int(root.winfo_width()),
                height=int(root.winfo_height()),
                x=int(root.winfo_x()),
                y=int(root.winfo_y()),
            )
            save_window_state(state=state, path=self._window_state_path)
        except Exception as exc:
            logger.warning("Failed to persist window state: {}", exc)
