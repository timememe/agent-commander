"""GUI channel bridge for MessageBus integration."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent_commander.bus.events import InboundMessage, OutboundMessage
from agent_commander.bus.queue import MessageBus
from agent_commander.gui.app import TriptychApp
from agent_commander.session.extension_store import ExtensionStore
from agent_commander.session.gui_store import GUIStore
from agent_commander.session.skill_store import SkillStore

if TYPE_CHECKING:
    from agent_commander.cron.service import CronService
    from agent_commander.cron.types import CronJob
    from agent_commander.session.project_store import ProjectStore


@dataclass(frozen=True)
class GUIInbound:
    """Input payload from GUI to bus."""

    session_id: str
    text: str
    agent: str
    cwd: str | None = None


class GUIChannel:
    """Bridge between GUI events and message bus."""

    name = "gui"

    def __init__(
        self,
        bus: MessageBus,
        default_cwd: str | None = None,
        default_agent: str = "codex",
        window_width: int = 1400,
        window_height: int = 800,
        agent_workdirs: dict[str, str] | None = None,
        notify_on_long_tasks: bool = True,
        long_task_notify_s: float = 12.0,
        server_manager: object | None = None,
        session_store: GUIStore | None = None,
        skill_store: SkillStore | None = None,
        cron_service: "CronService | None" = None,
        project_store: "ProjectStore | None" = None,
        extension_store: ExtensionStore | None = None,
    ) -> None:
        self.bus = bus
        self.default_cwd = default_cwd
        self.default_agent = default_agent
        self.window_width = window_width
        self.window_height = window_height
        self.agent_workdirs = agent_workdirs or {}
        self.notify_on_long_tasks = notify_on_long_tasks
        self.long_task_notify_s = long_task_notify_s
        self.server_manager = server_manager
        self.session_store = session_store
        self.skill_store = skill_store
        self.cron_service = cron_service
        self.project_store = project_store
        self.extension_store = extension_store

        self._app: TriptychApp | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    async def start(self) -> None:
        """Start GUI in separate thread and keep coroutine alive while GUI runs."""
        if self._thread and self._thread.is_alive():
            return

        self._loop = asyncio.get_running_loop()
        self._stopped.clear()

        # Register cron job callback if service is available
        if self.cron_service is not None:
            self.cron_service.on_job = self._handle_cron_job

        self._thread = threading.Thread(target=self._run_gui, daemon=True, name="agent-commander-gui")
        self._thread.start()

        while not self._stopped.is_set():
            await asyncio.sleep(0.2)

    async def _handle_cron_job(self, job: "CronJob") -> str | None:
        """Called by CronService when a scheduled job fires."""
        session_id = (job.payload.channel or "").strip()
        if not session_id:
            return None
        agent = self.default_agent
        cwd = self.default_cwd
        message = job.payload.message or "Run scheduled task."
        await self.on_user_input(
            text=message,
            session_id=session_id,
            agent=agent,
            cwd_override=cwd,
        )
        return None

    async def stop(self) -> None:
        """Stop GUI runtime."""
        app = self._app
        if app:
            app.stop()
        self._stopped.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=1.0)

    async def send(self, msg: OutboundMessage) -> None:
        """Render assistant response on GUI."""
        app = self._app
        if app is None:
            return
        streamed = bool((msg.metadata or {}).get("streamed"))
        if streamed:
            return
        app.receive_assistant_chunk(session_id=msg.chat_id, chunk=msg.content, final=True)

    async def emit_stream_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Streaming assistant text for chat panel (filtered output)."""
        app = self._app
        if app is None:
            return
        app.receive_assistant_chunk(session_id=session_id, chunk=chunk, final=final)

    async def emit_tool_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Streaming tool call log for separate tool_log bubble in chat."""
        app = self._app
        if app is None:
            return
        app.receive_tool_chunk(session_id=session_id, chunk=chunk, final=final)

    async def emit_terminal_chunk(self, session_id: str, chunk: str, final: bool = False) -> None:
        """Streaming terminal text for terminal panel (raw PTY output)."""
        app = self._app
        if app is None:
            return
        if chunk:
            app.receive_terminal_chunk(chunk, session_id=session_id)

    async def on_user_input(
        self,
        text: str,
        session_id: str,
        agent: str,
        cwd_override: str | None = None,
        extra_meta: dict | None = None,
    ) -> None:
        """Publish user input from GUI into inbound queue."""
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
        """Prewarm a chat session by starting selected agent runtime immediately."""
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

    def _run_gui(self) -> None:
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

            def _done_callback(fut: "asyncio.Future[None]") -> None:
                try:
                    fut.result()
                except Exception:
                    pass

            future.add_done_callback(_done_callback)

        def _session_start_callback(session_id: str, agent: str, cwd_override: str | None = None) -> None:
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

            def _done_callback(fut: "asyncio.Future[None]") -> None:
                try:
                    fut.result()
                except Exception:
                    pass

            future.add_done_callback(_done_callback)

        def _schedule_create_callback(session_id: str, prompt: str, cron_expr: str) -> None:
            cron_svc = self.cron_service
            loop = self._loop
            if cron_svc is None or loop is None:
                return

            async def _do_register() -> None:
                from agent_commander.cron.types import CronSchedule
                cron_svc.add_job(
                    name=f"sched-{session_id[:12]}",
                    schedule=CronSchedule(kind="cron", expr=cron_expr),
                    message=prompt or "Run scheduled task.",
                    channel=session_id,
                )

            asyncio.run_coroutine_threadsafe(_do_register(), loop)

        def _schedule_delete_callback(session_id: str) -> None:
            cron_svc = self.cron_service
            loop = self._loop
            if cron_svc is None or loop is None:
                return

            async def _do_remove() -> None:
                await cron_svc.remove_jobs_by_channel(session_id)

            asyncio.run_coroutine_threadsafe(_do_remove(), loop)

        def _close_callback() -> None:
            self._stopped.set()

        self._app = TriptychApp(
            on_user_input=_input_callback,
            on_session_start=_session_start_callback,
            on_schedule_create=_schedule_create_callback,
            on_delete_session=_schedule_delete_callback,
            on_close=_close_callback,
            default_agent=self.default_agent,
            window_width=self.window_width,
            window_height=self.window_height,
            notify_on_long_tasks=self.notify_on_long_tasks,
            long_task_notify_s=self.long_task_notify_s,
            server_manager=self.server_manager,
            session_store=self.session_store,
            skill_store=self.skill_store,
            project_store=self.project_store,
            extension_store=self.extension_store,
        )
        try:
            self._app.run()
        finally:
            self._stopped.set()
