"""Main Qt window — mirrors TriptychApp public interface."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from PySide6.QtCore import QTimer

from agent_commander.gui_qt import theme
from agent_commander.gui_qt.chat_panel import ChatPanel, ToolBubble
from agent_commander.gui_qt.cycle_bar import CycleControlBar
from agent_commander.gui_qt.extensions_panel import ExtensionsPanel
from agent_commander.gui_qt.file_tray import FileTrayPanel
from agent_commander.gui_qt.input_bar import InputBar
from agent_commander.gui_qt.new_session_dialog import NewSessionDialog
from agent_commander.gui_qt.session_list import SessionListWidget
from agent_commander.gui_qt.settings_panel import SettingsPanel
from agent_commander.gui_qt.projects_panel import ProjectsPanel
from agent_commander.gui_qt.team_panel import TeamPanel
from agent_commander.session.gui_store import GUIStore, SessionMeta, StoredMessage
from agent_commander.session.project_store import ProjectStore
from agent_commander.session.skill_store import SkillStore

if TYPE_CHECKING:
    from agent_commander.session.extension_store import ExtensionStore
    from agent_commander.usage.models import AgentUsageSnapshot

# Content panel indices (Agent Tab is a right-side tray, not a stack page)
_PANEL_CHAT = 0
_PANEL_EXTENSIONS = 1
_PANEL_SETTINGS = 2
_PANEL_TEAM = 3
_PANEL_PROJECTS = 4

_MODE_TOGGLES = [
    (_PANEL_EXTENSIONS, "Extensions"),
    (_PANEL_SETTINGS, "Settings"),
    (_PANEL_TEAM, "Team"),
    (_PANEL_PROJECTS, "Projects"),
]

_WARN_THRESHOLD = 25.0
_DANGER_THRESHOLD = 10.0
_COLOR_WARN = "#FFA940"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class QtApp(QMainWindow):
    """PySide6 main window for Agent Commander.

    Thread bridge: `_invoke = Signal(object)`.  Any thread can safely call
    `_run_on_ui(fn)` — emits the signal → Qt queues delivery on the GUI thread
    (auto QueuedConnection across threads).
    """

    _invoke = Signal(object)

    def __init__(
        self,
        on_user_input: Callable[[str, str, str, str | None, dict | None], None] | None = None,
        on_session_start: Callable[[str, str, str | None], None] | None = None,
        on_close: Callable[[], None] | None = None,
        on_restart_app: Callable[[], None] | None = None,
        on_model_change: Callable[[str, str], None] | None = None,
        model_defaults: dict[str, str] | None = None,
        default_agent: str = "codex",
        window_width: int = 1400,
        window_height: int = 800,
        session_store: GUIStore | None = None,
        agent_workdirs: dict[str, str] | None = None,
        server_manager: object | None = None,
        extension_store: "ExtensionStore | None" = None,
        default_cwd: str | None = None,
    ) -> None:
        super().__init__()
        self._on_user_input = on_user_input
        self._on_session_start = on_session_start
        self._on_close = on_close
        self._on_restart_app = on_restart_app
        self._on_model_change = on_model_change
        self._model_defaults = model_defaults or {}
        self._default_agent = default_agent
        self._session_store = session_store or GUIStore()
        self._agent_workdirs = agent_workdirs or {}
        self._server_manager = server_manager
        self._extension_store = extension_store
        self._default_cwd = default_cwd or ""
        self._active_session_id: str | None = None
        self._session_agents: dict[str, str] = {}
        self._session_cwds: dict[str, str] = {}
        self._session_titles: dict[str, str] = {}
        self._session_roles: dict[str, str] = {}
        self._session_extensions: dict[str, list[str]] = {}
        self._session_cycle_mode: dict[str, bool] = {}
        self._session_projects: dict[str, str] = {}
        self._chat_panels: dict[str, ChatPanel] = {}
        self._pending_tools: dict[str, ToolBubble] = {}
        self._files_visible = True
        self._usage_snapshots: dict[str, "AgentUsageSnapshot"] = {}
        self._usage_label: QLabel | None = None
        self._skill_store = SkillStore()
        self._project_store = ProjectStore()

        # Cycle mode state
        self._cycle_running = False
        self._cycle_session_id: str | None = None
        self._cycle_task = ""
        self._cycle_interval_s = 900
        self._cycle_max_iter = 0       # 0 = infinite
        self._cycle_iter_count = 0
        self._cycle_queued = False     # a run is pending, waiting for agent to finish
        self._agent_busy = False       # is agent currently processing a message?
        self._cycle_timer = QTimer()
        self._cycle_timer.setSingleShot(True)

        self._invoke.connect(lambda fn: fn())
        self._cycle_timer.timeout.connect(self._on_cycle_tick)

        self.setWindowTitle("Agent Commander")
        icon_path = theme.find_icon()
        if icon_path:
            icon = QIcon(icon_path)
            if not icon.isNull():
                self.setWindowIcon(icon)
        self.resize(window_width, window_height)
        self._build_ui()
        self._load_sessions()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: session list ──────────────────────────────────────────
        self._session_list = SessionListWidget(
            on_new_chat=self._on_new_chat,
            on_select=self._on_select_session,
            on_delete=self._on_delete_session,
        )
        root.addWidget(self._session_list)

        # ── Right: nav bar + content stack ─────────────────────────────
        right = QWidget()
        right.setStyleSheet(
            f"background-color: {theme.BG_APP};"
        )
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        rl.addWidget(self._build_nav_bar())

        self._content_stack = QStackedWidget()
        rl.addWidget(self._content_stack, stretch=1)

        # ── Panel 0: Chat (chat bubbles + right-side file tray) ─────────
        chat_container = QWidget()
        chat_container.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        cl = QVBoxLayout(chat_container)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        # Horizontal split: chat messages | file tray
        split = QWidget()
        split.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        sl = QHBoxLayout(split)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)

        left_col = QWidget()
        left_col.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        ll = QVBoxLayout(left_col)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)

        self._chat_stack = QStackedWidget()
        self._chat_stack.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        ll.addWidget(self._chat_stack, stretch=1)

        self._placeholder = QLabel("Click '+ New Chat' to start a conversation")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 16px;"
            f"background-color: {theme.BG_CHAT};"
        )
        self._chat_stack.addWidget(self._placeholder)

        self._input_bar = InputBar(
            on_submit=self._on_input_submit,
        )
        ll.addWidget(self._input_bar)

        # Cycle Mode settings bar (hidden by default)
        self._cycle_bar = CycleControlBar()
        self._cycle_bar.setVisible(False)
        ll.addWidget(self._cycle_bar)

        sl.addWidget(left_col, stretch=1)

        # Right-side Agent Tab tray (visible by default)
        self._file_tray = FileTrayPanel(
            on_cwd_change=self._on_cwd_change,
            on_role_change=self._on_role_change,
            on_cycle_mode_change=self._on_cycle_mode_toggled,
            on_extensions_change=self._on_extensions_change,
            on_project_change=self._on_project_change,
            skill_store=self._skill_store,
            extension_store=self._extension_store,
            project_store=self._project_store,
        )
        self._file_tray.refresh_roles()
        self._file_tray.refresh_extensions()
        self._file_tray.refresh_projects()
        self._file_tray.setFixedWidth(260)
        self._file_tray.setStyleSheet(
            f"background-color: {theme.BG_PANEL};"
        )
        self._file_tray.setVisible(self._files_visible)
        sl.addWidget(self._file_tray)
        self._input_bar.set_cwd(self._default_cwd)
        if self._files_visible:
            self._sync_file_tray()

        cl.addWidget(split, stretch=1)
        self._content_stack.addWidget(chat_container)          # index 0

        # ── Panel 1: Extensions ─────────────────────────────────────────
        from agent_commander.session.extension_store import ExtensionStore
        ext_store = self._extension_store or ExtensionStore()
        self._extensions_panel = ExtensionsPanel(extension_store=ext_store)
        self._content_stack.addWidget(self._extensions_panel)  # index 1

        # ── Panel 2: Settings ───────────────────────────────────────────
        self._settings_panel = SettingsPanel(
            server_manager=self._server_manager,
            on_model_change=self._on_model_change,
            model_defaults=self._model_defaults,
            on_restart_app=self._on_restart_app,
        )
        self._content_stack.addWidget(self._settings_panel)    # index 2

        # ── Panel 3: Team (Skill Library) ────────────────────────────────
        self._team_panel = TeamPanel(
            skill_store=self._skill_store,
            on_skill_changed=self._on_skill_changed,
        )
        self._content_stack.addWidget(self._team_panel)        # index 3

        # ── Panel 4: Projects ────────────────────────────────────────────
        self._projects_panel = ProjectsPanel(
            project_store=self._project_store,
            on_project_changed=self._on_project_store_changed,
        )
        self._content_stack.addWidget(self._projects_panel)    # index 4

        self._set_active_panel(_PANEL_CHAT)
        root.addWidget(right, stretch=1)

        # ── Status bar ──────────────────────────────────────────────────
        sb = self.statusBar()
        sb.setStyleSheet(
            f"QStatusBar {{ background-color: {theme.BG_PANEL};"
            f" color: {theme.TEXT_MUTED}; font-size: 11px; }}"
        )
        self._usage_label = QLabel("")
        self._usage_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._usage_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        sb.addPermanentWidget(self._usage_label)
        sb.showMessage("Ready")

    def _build_nav_bar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"background-color: {theme.BG_PANEL};"
        )
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        mode_hint = QLabel("Chat")
        self._chat_title_label = mode_hint
        mode_hint.setStyleSheet(
            f"color: {theme.TEXT}; font-size: 13px; font-weight: bold;"
            f"background: transparent; padding: 0 6px;"
        )
        layout.addWidget(mode_hint)
        layout.addStretch()

        self._mode_buttons: dict[int, QPushButton] = {}
        for panel_idx, label in _MODE_TOGGLES:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCheckable(True)
            btn.setStyleSheet(self._nav_btn_style(active=False))
            btn.clicked.connect(
                lambda checked=False, idx=panel_idx: self._toggle_mode_panel(idx)
            )
            layout.addWidget(btn)
            self._mode_buttons[panel_idx] = btn

        # Agent Tab toggle button — right-aligned, toggles side tray panel
        self._files_btn = QPushButton("Agent Tab")
        self._files_btn.setFixedHeight(30)
        self._files_btn.setCheckable(True)
        self._files_btn.setChecked(self._files_visible)
        self._files_btn.setStyleSheet(
            self._nav_btn_style(active=self._files_visible)
        )
        self._files_btn.clicked.connect(self._toggle_file_tray)
        layout.addWidget(self._files_btn)

        return bar

    @staticmethod
    def _nav_btn_style(active: bool) -> str:
        bg = theme.SESSION_ACTIVE_BG if active else theme.BG_PANEL
        color = theme.TEXT if active else theme.TEXT_MUTED
        return (
            f"QPushButton {{ background-color: {bg}; color: {color};"
            " border: none; border-radius: 7px;"
            " padding: 3px 12px; font-size: 12px; font-weight: bold; }"
            f"QPushButton:hover {{ background-color: {theme.SESSION_HOVER_BG};"
            f" color: {theme.TEXT}; }}"
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _toggle_mode_panel(self, idx: int) -> None:
        if self._content_stack.currentIndex() == idx:
            self._set_active_panel(_PANEL_CHAT)
            return
        self._set_active_panel(idx)

    def _set_active_panel(self, idx: int) -> None:
        self._content_stack.setCurrentIndex(idx)
        for panel_idx, btn in self._mode_buttons.items():
            active = panel_idx == idx
            btn.setChecked(active)
            btn.setStyleSheet(self._nav_btn_style(active=active))
        if idx == _PANEL_SETTINGS:
            self._settings_panel.refresh()
        elif idx == _PANEL_EXTENSIONS:
            self._extensions_panel.refresh()
        elif idx == _PANEL_TEAM:
            self._team_panel.refresh()
        elif idx == _PANEL_PROJECTS:
            self._projects_panel.refresh()
        elif idx == _PANEL_CHAT and self._active_session_id:
            panel = self._chat_panels.get(self._active_session_id)
            if panel is not None:
                panel.refresh_layout()
            self._file_tray.refresh_extensions()
        self._refresh_chat_title()

    def _toggle_file_tray(self) -> None:
        self._files_visible = not self._files_visible
        self._file_tray.setVisible(self._files_visible)
        self._files_btn.setChecked(self._files_visible)
        self._files_btn.setStyleSheet(self._nav_btn_style(active=self._files_visible))
        if self._files_visible:
            self._sync_file_tray()
        if self._active_session_id:
            panel = self._chat_panels.get(self._active_session_id)
            if panel is not None:
                panel.refresh_layout()

    def _sync_file_tray(self) -> None:
        """Update file tray to the active session's CWD or agent workdir."""
        tray = getattr(self, "_file_tray", None)
        if tray is None:
            return
        sid = self._active_session_id
        cwd = self._session_cwds.get(sid or "", "") if sid else ""
        if not cwd and sid:
            agent = self._session_agents.get(sid, self._default_agent)
            cwd = self._agent_workdirs.get(agent, "")
        if not cwd:
            cwd = self._default_cwd
        tray.set_workdir(cwd)

    def _on_cwd_change(self, cwd: str) -> None:
        sid = self._active_session_id
        if sid:
            self._session_cwds[sid] = cwd
            for meta in self._session_store.list_sessions():
                if meta.session_id == sid:
                    meta.workdir = cwd
                    self._session_store.upsert_meta(meta)
                    break
        else:
            self._default_cwd = cwd
        self._input_bar.set_cwd(cwd)
        self._sync_file_tray()

    def _on_role_change(self, skill_id: str) -> None:
        sid = self._active_session_id
        if not sid:
            return
        self._session_roles[sid] = skill_id
        for meta in self._session_store.list_sessions():
            if meta.session_id == sid:
                meta.active_skill_ids = [skill_id] if skill_id else []
                self._session_store.upsert_meta(meta)
                break

    def _on_extensions_change(self, active_ids: list[str]) -> None:
        sid = self._active_session_id
        if not sid:
            return
        self._session_extensions[sid] = list(active_ids)
        for meta in self._session_store.list_sessions():
            if meta.session_id == sid:
                meta.active_extension_ids = list(active_ids)
                self._session_store.upsert_meta(meta)
                break

    def _on_skill_changed(self) -> None:
        """Called after any Team panel create/update/delete — refreshes role combo."""
        self._file_tray.refresh_roles()
        sid = self._active_session_id
        if sid:
            self._file_tray.set_role(self._session_roles.get(sid, ""))

    def _on_project_store_changed(self) -> None:
        """Called after any Projects panel create/update/delete — refreshes project combo."""
        self._file_tray.refresh_projects()
        sid = self._active_session_id
        if sid:
            self._file_tray.set_project(self._session_projects.get(sid, ""))

    def _on_project_change(self, project_id: str) -> None:
        sid = self._active_session_id
        if not sid:
            return
        self._session_projects[sid] = project_id
        # Persist to session store
        for meta in self._session_store.list_sessions():
            if meta.session_id == sid:
                meta.project_id = project_id or None
                self._session_store.upsert_meta(meta)
                break
        # If the project has a workdir, switch the session's CWD to it
        if project_id:
            proj = self._project_store.get_project(project_id)
            if proj and proj.workdir:
                self._session_cwds[sid] = proj.workdir
                self._input_bar.set_cwd(proj.workdir)
                self._file_tray.set_workdir(proj.workdir)
                for meta in self._session_store.list_sessions():
                    if meta.session_id == sid:
                        meta.workdir = proj.workdir
                        self._session_store.upsert_meta(meta)
                        break

    def _restore_cycle_state_for_session(self, session_id: str) -> None:
        """Sync cycle-mode UI to the state saved for session_id."""
        active = self._session_cycle_mode.get(session_id, False)
        running = self._cycle_running and self._cycle_session_id == session_id

        self._file_tray.set_cycle_mode(active)
        self._cycle_bar.setVisible(active)
        self._input_bar.set_cycle_mode(
            active,
            on_cycle_click=self._on_cycle_btn_clicked if active else None,
        )
        self._input_bar.set_cycle_running(running)
        if active:
            # Lock/unlock fields; if not running, resets status to "Ready"
            self._cycle_bar.set_running(running)

    # ------------------------------------------------------------------
    # Cycle Mode
    # ------------------------------------------------------------------

    def _on_cycle_mode_toggled(self, active: bool) -> None:
        sid = self._active_session_id
        if sid:
            self._session_cycle_mode[sid] = active
        if not active and self._cycle_running and self._cycle_session_id == sid:
            self._stop_cycle()
        self._cycle_bar.setVisible(active)
        self._input_bar.set_cycle_mode(
            active,
            on_cycle_click=self._on_cycle_btn_clicked if active else None,
        )

    def _on_cycle_btn_clicked(self) -> None:
        """InputBar Run/Stop button clicked in cycle mode."""
        if self._cycle_running:
            self._stop_cycle()
        else:
            self._on_cycle_run_requested()

    def _on_cycle_run_requested(self) -> None:
        task = self._input_bar.get_text()
        if not task:
            self._cycle_bar.set_status("Type a task above first")
            return
        session_id = self._active_session_id
        if not session_id:
            self._cycle_bar.set_status("No active session")
            return
        self._cycle_running = True
        self._cycle_session_id = session_id
        self._cycle_task = task
        self._cycle_interval_s = self._cycle_bar.interval_seconds()
        self._cycle_max_iter = self._cycle_bar.max_iterations()
        self._cycle_iter_count = 0
        self._cycle_queued = False
        self._cycle_bar.set_running(True)
        self._input_bar.set_cycle_running(True)
        self._execute_cycle_iteration()

    def _execute_cycle_iteration(self) -> None:
        if not self._cycle_running:
            return
        if self._cycle_max_iter > 0 and self._cycle_iter_count >= self._cycle_max_iter:
            self._stop_cycle(done=True)
            return
        self._cycle_iter_count += 1
        total = f"/{self._cycle_max_iter}" if self._cycle_max_iter > 0 else ""
        self._cycle_bar.set_status(f"Running ({self._cycle_iter_count}{total})")
        self._input_bar.set_cycle_running(True)
        self._dispatch_cycle_message()
        # Schedule next tick
        self._cycle_timer.start(self._cycle_interval_s * 1000)
        self._cycle_bar.start_countdown(self._cycle_interval_s)

    def _dispatch_cycle_message(self) -> None:
        session_id = self._cycle_session_id
        if not session_id:
            return
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        agent = self._session_agents.get(session_id, self._default_agent)
        cwd = self._session_cwds.get(session_id) or None

        panel.add_user_message(self._cycle_task)
        ts = _now()
        self._session_store.append_message(
            session_id, StoredMessage(role="user", text=self._cycle_task, ts=ts)
        )

        metadata: dict | None = None
        role_id = self._session_roles.get(session_id, "")
        if role_id:
            role_content = self._skill_store.get_content(role_id)
            if role_content:
                metadata = {"role_content": role_content}

        ext_ids = self._session_extensions.get(session_id, [])
        if ext_ids and self._extension_store is not None:
            ext_ctx = self._extension_store.build_context(ext_ids)
            if ext_ctx:
                metadata = metadata or {}
                metadata["extension_context"] = ext_ctx
                metadata["active_extension_ids"] = ext_ids

        project_id = self._session_projects.get(session_id, "")
        if project_id:
            project_ctx = self._project_store.build_context(project_id)
            if project_ctx:
                metadata = metadata or {}
                metadata["project_context"] = project_ctx

        self._agent_busy = True
        if self._on_user_input:
            self._on_user_input(session_id, self._cycle_task, agent, cwd, metadata)

    def _on_cycle_tick(self) -> None:
        """Single-shot timer fired — time for the next iteration."""
        if not self._cycle_running:
            return
        if self._agent_busy:
            # Agent still processing — queue one run for when it finishes
            self._cycle_queued = True
            self._cycle_bar.set_status("Queued (agent busy…)")
        else:
            self._execute_cycle_iteration()

    def _stop_cycle(self, done: bool = False) -> None:
        stopped_session = self._cycle_session_id
        self._cycle_running = False
        self._cycle_queued = False
        self._cycle_timer.stop()

        # Update UI only if the user is currently viewing the session that had the cycle
        if self._active_session_id == stopped_session:
            self._cycle_bar.set_running(False)
            self._input_bar.set_cycle_running(False)
            if done:
                self._cycle_bar.set_status(
                    f"Done ({self._cycle_iter_count}/{self._cycle_max_iter})"
                )
            else:
                self._cycle_bar.set_status("Stopped")
            self._file_tray.set_cycle_mode(
                self._session_cycle_mode.get(stopped_session or "", False)
            )

    def _refresh_chat_title(self) -> None:
        label = getattr(self, "_chat_title_label", None)
        if label is None:
            return
        sid = self._active_session_id
        raw_title = self._session_titles.get(sid or "", "") or "Chat"
        metrics = QFontMetrics(label.font())
        avail = max(90, label.width() or 280)
        elided = metrics.elidedText(raw_title, Qt.TextElideMode.ElideRight, avail)
        label.setToolTip(raw_title if elided != raw_title else "")
        label.setText(elided)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _load_sessions(self) -> None:
        sessions = self._session_store.list_sessions()
        for meta in sessions:
            self._register_session(meta)
        if sessions:
            self._on_select_session(sessions[0].session_id)

    def _register_session(self, meta: SessionMeta) -> None:
        if meta.session_id in self._chat_panels:
            return
        panel = ChatPanel()
        for msg in self._session_store.load_messages(meta.session_id):
            panel.add_message(msg.role, msg.text)
        self._chat_panels[meta.session_id] = panel
        self._session_agents[meta.session_id] = meta.agent
        self._session_titles[meta.session_id] = meta.title or meta.session_id[:12]
        if meta.active_extension_ids:
            self._session_extensions[meta.session_id] = list(meta.active_extension_ids)
        if meta.active_skill_ids:
            self._session_roles[meta.session_id] = meta.active_skill_ids[0]
        if meta.project_id:
            self._session_projects[meta.session_id] = meta.project_id
        if meta.workdir:
            self._session_cwds[meta.session_id] = meta.workdir
        self._chat_stack.addWidget(panel)
        self._session_list.add_session(meta)

    def _on_new_chat(self) -> None:
        dlg = NewSessionDialog(parent=self, default_agent=self._default_agent)
        if dlg.exec() != NewSessionDialog.DialogCode.Accepted:
            return
        session_id, agent = dlg.result_data()
        meta = SessionMeta(
            session_id=session_id,
            title=f"Chat ({agent})",
            agent=agent,
            workdir="",
            created_at=_now(),
            updated_at=_now(),
        )
        self._session_store.upsert_meta(meta)
        self._register_session(meta)
        self._on_select_session(session_id)
        self._set_active_panel(_PANEL_CHAT)
        if self._on_session_start:
            self._on_session_start(session_id, agent, None)

    def _on_select_session(self, session_id: str) -> None:
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        self._active_session_id = session_id
        self._chat_stack.setCurrentWidget(panel)
        panel.refresh_layout()
        self._session_list.set_active(session_id)
        self._refresh_chat_title()
        # Restore saved CWD, role, extensions, and cycle mode for this session
        saved_cwd = self._session_cwds.get(session_id, self._default_cwd)
        self._input_bar.set_cwd(saved_cwd)
        self._sync_file_tray()
        self._file_tray.set_role(self._session_roles.get(session_id, ""))
        self._file_tray.set_extensions(self._session_extensions.get(session_id, []))
        self._file_tray.set_project(self._session_projects.get(session_id, ""))
        self._restore_cycle_state_for_session(session_id)

    def _on_delete_session(self, session_id: str) -> None:
        self._session_store.delete_session(session_id)

        panel = self._chat_panels.pop(session_id, None)
        if panel is not None:
            self._chat_stack.removeWidget(panel)
            panel.deleteLater()

        self._session_agents.pop(session_id, None)
        self._session_cwds.pop(session_id, None)
        self._session_titles.pop(session_id, None)
        self._session_roles.pop(session_id, None)
        self._session_extensions.pop(session_id, None)
        self._session_cycle_mode.pop(session_id, None)
        self._session_projects.pop(session_id, None)
        self._pending_tools.pop(session_id, None)
        # Stop cycle if it was running on the deleted session
        if self._cycle_session_id == session_id and self._cycle_running:
            self._stop_cycle()
        self._session_list.remove_session(session_id)

        if self._active_session_id == session_id:
            remaining = list(self._chat_panels.keys())
            if remaining:
                self._on_select_session(remaining[0])
            else:
                self._active_session_id = None
                self._chat_stack.setCurrentWidget(self._placeholder)
                self._input_bar.set_cwd(self._default_cwd)
                self._refresh_chat_title()

    def _on_input_submit(self, text: str) -> None:
        session_id = self._active_session_id
        if not session_id:
            return
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        agent = self._session_agents.get(session_id, self._default_agent)

        # Save and propagate current CWD
        cwd = self._input_bar.current_cwd() or None
        if cwd:
            self._session_cwds[session_id] = cwd

        panel.add_user_message(text)

        ts = _now()
        self._session_store.append_message(
            session_id, StoredMessage(role="user", text=text, ts=ts)
        )
        for meta in self._session_store.list_sessions():
            if meta.session_id == session_id:
                meta.updated_at = ts
                meta.message_count += 1
                self._session_store.upsert_meta(meta)
                break

        metadata: dict | None = None
        role_id = self._session_roles.get(session_id, "")
        if role_id:
            role_content = self._skill_store.get_content(role_id)
            if role_content:
                metadata = {"role_content": role_content}

        ext_ids = self._session_extensions.get(session_id, [])
        if ext_ids and self._extension_store is not None:
            ext_ctx = self._extension_store.build_context(ext_ids)
            if ext_ctx:
                metadata = metadata or {}
                metadata["extension_context"] = ext_ctx
                metadata["active_extension_ids"] = ext_ids

        project_id = self._session_projects.get(session_id, "")
        if project_id:
            project_ctx = self._project_store.build_context(project_id)
            if project_ctx:
                metadata = metadata or {}
                metadata["project_context"] = project_ctx

        self._agent_busy = True
        if self._on_user_input:
            self._on_user_input(session_id, text, agent, cwd, metadata)

        self.statusBar().showMessage(f"Sent to {agent}…", 4000)

    # ------------------------------------------------------------------
    # Thread bridge
    # ------------------------------------------------------------------

    def _run_on_ui(self, fn: Callable) -> None:
        self._invoke.emit(fn)

    # ------------------------------------------------------------------
    # Public interface (mirrors TriptychApp)
    # ------------------------------------------------------------------

    def show_status(self, text: str, timeout: int = 5000) -> None:
        """Display a message in the status bar (thread-safe via _run_on_ui)."""
        self._run_on_ui(lambda: self.statusBar().showMessage(text, timeout))

    def set_usage_placeholder(self, text: str) -> None:
        """Show initial usage placeholder (e.g. 'Codex: checking...')."""
        self._run_on_ui(lambda: self._set_usage_text(text, None))

    def update_usage(self, agent: str, snapshot: "AgentUsageSnapshot") -> None:
        """Thread-safe update of agent usage display."""
        self._run_on_ui(lambda: self._store_and_render_usage(agent, snapshot))

    def _store_and_render_usage(self, agent: str, snapshot: "AgentUsageSnapshot") -> None:
        prev = self._usage_snapshots.get(agent)
        if (snapshot.error or not snapshot.windows) and prev and prev.windows and not prev.error:
            return
        self._usage_snapshots[agent] = snapshot
        self._update_usage_ui()

    def _update_usage_ui(self) -> None:
        if self._usage_label is None:
            return
        if not self._usage_snapshots:
            return

        agent_parts: list[str] = []
        min_remaining: float | None = None

        for agent, snap in self._usage_snapshots.items():
            if snap.error:
                agent_parts.append(f"{agent.capitalize()}: checking...")
                continue
            if not snap.windows:
                agent_parts.append(f"{agent.capitalize()}: checking...")
                continue
            quota_windows = [w for w in snap.windows if w.has_quota]
            display_windows = snap.windows if len(quota_windows) <= 2 else [snap.primary]
            window_parts: list[str] = []
            for window in (display_windows or snap.windows[:1]):
                if window is None:
                    continue
                window_parts.append(window.format_status())
                if window.has_quota:
                    remaining = window.remaining_percent
                    if min_remaining is None or remaining < min_remaining:
                        min_remaining = remaining
            if window_parts:
                label = "  ·  ".join(window_parts)
                agent_parts.append(f"{agent.capitalize()}: {label}")

        if not agent_parts:
            return

        text = "    ·    ".join(agent_parts)
        self._set_usage_text(text, min_remaining)

    def _set_usage_text(self, text: str, remaining_percent: float | None) -> None:
        label = self._usage_label
        if label is None:
            return
        if remaining_percent is not None:
            if remaining_percent < _DANGER_THRESHOLD:
                color = theme.DANGER
            elif remaining_percent < _WARN_THRESHOLD:
                color = _COLOR_WARN
            else:
                color = theme.TEXT_MUTED
        else:
            color = theme.TEXT_MUTED
        label.setText(text)
        label.setStyleSheet(
            f"color: {color}; font-size: 11px; background: transparent;"
        )

    def receive_assistant_chunk(self, session_id: str, chunk: str, final: bool) -> None:
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        panel.append_assistant_chunk(chunk, final)
        if final:
            full_text = panel.get_last_assistant_text()
            if full_text:
                self._session_store.append_message(
                    session_id,
                    StoredMessage(role="assistant", text=full_text, ts=_now()),
                )
            self.statusBar().showMessage("Ready", 0)
            self._agent_busy = False
            # If a cycle iteration was queued while agent was busy, run it now
            if (
                self._cycle_running
                and self._cycle_queued
                and session_id == self._cycle_session_id
            ):
                self._cycle_queued = False
                self._cycle_timer.stop()
                self._execute_cycle_iteration()

    def receive_tool_start(self, session_id: str, name: str, args: str) -> None:
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        tb = panel.add_tool_start(name=name, args=args)
        self._pending_tools[session_id] = tb
        self.statusBar().showMessage(f"⚙ {name}…", 0)

    def receive_tool_end(self, session_id: str, name: str, result: str) -> None:
        panel = self._chat_panels.get(session_id)
        if panel is None:
            return
        panel.add_tool_end(name=name, result=result)
        self._pending_tools.pop(session_id, None)
        self.statusBar().showMessage("Ready", 3000)

    def run(self) -> None:
        self.show()
        inst = QApplication.instance()
        if inst is not None:
            inst.exec()

    def stop(self) -> None:
        self._settings_panel.cleanup()
        inst = QApplication.instance()
        if inst is not None:
            inst.quit()

    def closeEvent(self, event) -> None:
        self._settings_panel.cleanup()
        if self._on_close:
            self._on_close()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_chat_title()
