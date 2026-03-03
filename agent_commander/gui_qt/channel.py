"""Qt GUI channel — mirrors GUIChannel interface, backed by PySide6."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

from agent_commander.bus.events import InboundMessage, OutboundMessage
from agent_commander.bus.queue import MessageBus
from agent_commander.session.gui_store import GUIStore

if TYPE_CHECKING:
    from agent_commander.session.skill_store import SkillStore
    from agent_commander.session.extension_store import ExtensionStore
    from agent_commander.session.project_store import ProjectStore
    from agent_commander.usage.monitor import UsageMonitor
    from agent_commander.gui_qt.app import QtApp


class QtChannel:
    """Bridge between the Qt GUI and the MessageBus.

    Identical external interface to GUIChannel; only the rendering backend
    (PySide6 instead of customtkinter) differs.
    """

    name = "gui"

    def __init__(
        self,
        bus: MessageBus,
        default_cwd: str | None = None,
        default_agent: str = "codex",
        window_width: int = 1400,
        window_height: int = 800,
        font_size: int = 0,
        agent_workdirs: dict[str, str] | None = None,
        notify_on_long_tasks: bool = True,
        long_task_notify_s: float = 12.0,
        server_manager: object | None = None,
        session_store: GUIStore | None = None,
        skill_store: "SkillStore | None" = None,
        cron_service: object | None = None,
        project_store: "ProjectStore | None" = None,
        extension_store: "ExtensionStore | None" = None,
        usage_monitors: "list[UsageMonitor] | None" = None,
    ) -> None:
        self.bus = bus
        self.default_cwd = default_cwd
        self.default_agent = default_agent
        self.window_width = window_width
        self.window_height = window_height
        self.font_size = font_size
        self.agent_workdirs = agent_workdirs or {}
        self.notify_on_long_tasks = notify_on_long_tasks
        self.long_task_notify_s = long_task_notify_s
        self.server_manager = server_manager
        self.session_store = session_store
        self.skill_store = skill_store
        self.cron_service = cron_service
        self.project_store = project_store
        self.extension_store = extension_store
        self.usage_monitors: list[UsageMonitor] = usage_monitors or []

        self._app: QtApp | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start Qt GUI in a separate thread; keep coroutine alive while GUI runs."""
        if self._thread and self._thread.is_alive():
            return

        self._loop = asyncio.get_running_loop()
        self._stopped.clear()

        self._thread = threading.Thread(
            target=self._run_gui,
            daemon=True,
            name="agent-commander-gui-qt",
        )
        self._thread.start()

        while not self._stopped.is_set():
            await asyncio.sleep(0.2)

    async def stop(self) -> None:
        """Stop Qt GUI runtime."""
        app = self._app
        if app:
            app.stop()
        self._stopped.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    # ------------------------------------------------------------------
    # Outbound (bus → GUI)
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Render a complete assistant message (non-streamed path)."""
        app = self._app
        if app is None:
            return
        streamed = bool((msg.metadata or {}).get("streamed"))
        if streamed:
            return
        app._run_on_ui(
            lambda: app.receive_assistant_chunk(
                session_id=msg.chat_id, chunk=msg.content, final=True
            )
        )

    async def emit_stream_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Deliver a streaming chunk to the active chat bubble."""
        app = self._app
        if app is None:
            return
        app._run_on_ui(
            lambda: app.receive_assistant_chunk(
                session_id=session_id, chunk=chunk, final=final
            )
        )

    async def emit_tool_start(self, session_id: str, name: str, args: str) -> None:
        """Tool call started (stub in v1)."""
        app = self._app
        if app is None:
            return
        app._run_on_ui(
            lambda: app.receive_tool_start(session_id=session_id, name=name, args=args)
        )

    async def emit_tool_end(self, session_id: str, name: str, result: str) -> None:
        """Tool call completed (stub in v1)."""
        app = self._app
        if app is None:
            return
        app._run_on_ui(
            lambda: app.receive_tool_end(session_id=session_id, name=name, result=result)
        )

    async def emit_terminal_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Terminal PTY output — not rendered in Qt v1."""

    # ------------------------------------------------------------------
    # Inbound (GUI → bus)
    # ------------------------------------------------------------------

    async def on_user_input(
        self,
        text: str,
        session_id: str,
        agent: str,
        cwd_override: str | None = None,
        extra_meta: dict | None = None,
    ) -> None:
        """Publish user message from the GUI into the inbound queue."""
        metadata: dict[str, object] = {"agent": agent}
        cwd = (cwd_override or "").strip() or self.agent_workdirs.get(agent) or self.default_cwd
        if cwd:
            metadata["cwd"] = cwd
        if extra_meta:
            metadata.update(extra_meta)
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id="user",
                chat_id=session_id,
                content=text,
                metadata=metadata,
            )
        )

    async def on_session_start(
        self,
        session_id: str,
        agent: str,
        cwd_override: str | None = None,
    ) -> None:
        """Prewarm a chat session by initialising the agent runtime."""
        metadata: dict[str, object] = {"agent": agent, "init_session": True}
        cwd = (cwd_override or "").strip() or self.agent_workdirs.get(agent) or self.default_cwd
        if cwd:
            metadata["cwd"] = cwd
        await self.bus.publish_inbound(
            InboundMessage(
                channel=self.name,
                sender_id="system",
                chat_id=session_id,
                content="",
                metadata=metadata,
            )
        )

    # ------------------------------------------------------------------
    # GUI thread runner
    # ------------------------------------------------------------------

    def _run_gui(self) -> None:
        import os
        import sys

        if os.name == "nt":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "AgentCommander.Desktop"
                )
            except Exception:
                pass

        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication

        from agent_commander.gui_qt.app import QtApp
        from agent_commander.gui_qt import theme

        qt_app = QApplication.instance()
        if qt_app is None:
            qt_app = QApplication(sys.argv)

        qt_app.setApplicationName("Agent Commander")
        icon_path = theme.find_icon()
        if icon_path:
            icon = QIcon(icon_path)
            if not icon.isNull():
                qt_app.setWindowIcon(icon)

        qt_app.setStyleSheet(theme.app_stylesheet())

        def _input_callback(
            session_id: str,
            text: str,
            agent: str,
            cwd_override: str | None = None,
            extra_meta: dict | None = None,
        ) -> None:
            loop = self._loop
            if loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(
                self.on_user_input(
                    text=text,
                    session_id=session_id,
                    agent=agent,
                    cwd_override=cwd_override,
                    extra_meta=extra_meta,
                ),
                loop,
            )
            future.add_done_callback(_swallow_exceptions)

        def _session_start_callback(
            session_id: str, agent: str, cwd_override: str | None = None
        ) -> None:
            loop = self._loop
            if loop is None:
                return
            future = asyncio.run_coroutine_threadsafe(
                self.on_session_start(
                    session_id=session_id,
                    agent=agent,
                    cwd_override=cwd_override,
                ),
                loop,
            )
            future.add_done_callback(_swallow_exceptions)

        def _close_callback() -> None:
            self._stopped.set()

        self._app = QtApp(
            on_user_input=_input_callback,
            on_session_start=_session_start_callback,
            on_close=_close_callback,
            default_agent=self.default_agent,
            window_width=self.window_width,
            window_height=self.window_height,
            session_store=self.session_store,
            agent_workdirs=self.agent_workdirs,
            server_manager=self.server_manager,
            extension_store=self.extension_store,
            default_cwd=self.default_cwd,
        )

        # Wire each usage monitor -> app now that the app object exists.
        if self.usage_monitors:
            app_ref = self._app

            names = " · ".join(
                f"{m.agent.capitalize()}: checking..." for m in self.usage_monitors
            )
            app_ref.set_usage_placeholder(names)

            for _monitor in self.usage_monitors:
                _agent = _monitor.agent

                def _make_cb(agent: str):
                    def _on_usage_update(snapshot: object) -> None:
                        app_ref.update_usage(agent, snapshot)  # type: ignore[arg-type]
                    return _on_usage_update

                _monitor.on_update = _make_cb(_agent)

        try:
            self._app.run()
        finally:
            self._stopped.set()


def _swallow_exceptions(fut: "asyncio.Future") -> None:
    try:
        fut.result()
    except Exception:
        pass
