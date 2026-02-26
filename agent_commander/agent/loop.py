"""Agent loop for CLI-agent pass-through mode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from loguru import logger

from agent_commander.agent.context import ContextBuilder
from agent_commander.bus.events import InboundMessage, OutboundMessage
from agent_commander.bus.queue import MessageBus
from agent_commander.providers.runtime.session import AgentSession
from agent_commander.providers.provider import CLIAgentProvider
from agent_commander.providers.transport.proxy_session import ProxySession
from agent_commander.providers.runtime.filter import filter_noise_lines
from agent_commander.session.manager import SessionManager

StreamCallback = Callable[[InboundMessage, str, bool], Awaitable[None]]
TerminalCallback = Callable[[InboundMessage, str, bool], Awaitable[None]]
ToolCallback = Callable[[InboundMessage, str, bool], Awaitable[None]]


class AgentLoop:
    """
    Pass-through loop:
    user_msg -> CLI agent -> stream chunks -> final text.
    """

    def __init__(
        self,
        bus: MessageBus,
        workspace: Path,
        default_agent: str = "codex",
        cli_provider: Any | None = None,
        session_manager: SessionManager | None = None,
        stream_callback: StreamCallback | None = None,
        terminal_callback: TerminalCallback | None = None,
        tool_callback: ToolCallback | None = None,
    ) -> None:
        self.bus = bus
        self.workspace = workspace
        self.default_agent = default_agent
        self.provider = cli_provider or CLIAgentProvider()
        self.stream_callback = stream_callback
        self.terminal_callback = terminal_callback
        self.tool_callback = tool_callback

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self._agent_sessions: dict[str, AgentSession] = {}
        self._running = False

    async def run(self) -> None:
        """Run the loop and process inbound messages."""
        self._running = True
        logger.info("Agent loop started (CLI pass-through)")

        while self._running:
            try:
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                response = await self._process_message(msg)
                if response:
                    await self.bus.publish_outbound(response)
                    # Loop auto-responder: if loop_mode metadata is set, continue
                    resp_meta = dict(response.metadata or {})
                    if (
                        bool(resp_meta.get("loop_mode"))
                        and not bool(resp_meta.get("loop_stop"))
                        and not _detect_stop_signal(response.content)
                    ):
                        continuation = InboundMessage(
                            channel=msg.channel,
                            sender_id="system",
                            chat_id=msg.chat_id,
                            content=_build_loop_continuation_prompt(response.content),
                            metadata={**resp_meta, "auto_loop": True},
                        )
                        await self.bus.publish_inbound(continuation)
                        logger.debug("Loop continuation published for session {}", msg.chat_id)
            except Exception as exc:
                logger.exception("Error processing message")
                await self.bus.publish_outbound(
                    OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {exc}",
                    )
                )

    def stop(self) -> None:
        """Stop loop and close active agent sessions."""
        self._running = False
        self._close_all_agent_sessions()
        logger.info("Agent loop stopping")

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        origin_channel, origin_chat_id = self._resolve_origin(msg)
        session_key = f"{origin_channel}:{origin_chat_id}"
        logger.info(f"Processing message for session {session_key}")
        metadata = dict(msg.metadata or {})
        agent_key, cwd = self._resolve_agent_and_cwd(metadata)

        # Proxy API mode: no PTY prewarm/startup logic required.
        if self._is_proxy_mode():
            if bool(metadata.get("init_session")):
                if self.terminal_callback:
                    await self.terminal_callback(msg, "", True)
                logger.info(f"Prewarmed proxy session {session_key} [{agent_key}]")
                return None
            provider_session = ProxySession(agent_key=agent_key, cwd=cwd)
            return await self._run_turn(
                msg=msg,
                metadata=metadata,
                origin_channel=origin_channel,
                origin_chat_id=origin_chat_id,
                provider_session=provider_session,
            )

        agent_session = self._get_or_create_agent_session(session_key, msg.metadata)

        # Ensure fresh sessions complete startup handshake before first user turn.
        startup_timeout = 20.0
        if agent_session.agent.key == "gemini":
            ready = True
            agent_session.mark_startup_complete()
        else:
            ready = await asyncio.to_thread(
                agent_session.wait_until_ready,
                startup_timeout,
                self.provider.poll_interval_s,
                False,
            )

        # Session prewarm signal from GUI: start selected agent PTY without sending a turn.
        if bool(metadata.get("init_session")):
            if self.terminal_callback:
                startup_raw = "".join(agent_session.read_available_raw())
                if startup_raw:
                    await self.terminal_callback(msg, startup_raw, False)
                await self.terminal_callback(msg, "", True)
            if ready:
                logger.info(f"Prewarmed agent session {session_key} [{agent_session.agent.key}]")
            else:
                logger.warning(f"Prewarm timeout for session {session_key} [{agent_session.agent.key}]")
            return None

        if not ready:
            logger.warning(f"Session {session_key} not ready before turn; proceeding anyway")
            agent_session.mark_startup_complete()

        return await self._run_turn(
            msg=msg,
            metadata=metadata,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            provider_session=agent_session,
        )

    async def _run_turn(
        self,
        msg: InboundMessage,
        metadata: dict[str, object],
        origin_channel: str,
        origin_chat_id: str,
        provider_session: Any,
    ) -> OutboundMessage:
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        session_cwd = str(getattr(provider_session, "cwd", "") or metadata.get("cwd", str(self.workspace)) or str(self.workspace))

        prompt = self.context.build_cli_turn_prompt(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
            cwd=session_cwd,
        )

        chunks: list[str] = []
        streamed = False
        tool_events_sent = False

        async def _on_raw(raw_chunk: str) -> None:
            if self.terminal_callback and raw_chunk:
                await self.terminal_callback(msg, raw_chunk, False)

        async def _on_tool_event(tool_chunk: str) -> None:
            nonlocal tool_events_sent
            if self.tool_callback and tool_chunk:
                await self.tool_callback(msg, tool_chunk, False)
                tool_events_sent = True

        async for chunk in self.provider.send_and_receive(
            message=prompt,
            session=provider_session,
            on_raw=_on_raw if self.terminal_callback else None,
            on_tool_event=_on_tool_event if self.tool_callback else None,
        ):
            if not chunk:
                continue
            chunks.append(chunk)
            streamed = True
            if self.stream_callback:
                await self.stream_callback(msg, chunk, False)

        if self.stream_callback and streamed:
            await self.stream_callback(msg, "", True)
        if self.tool_callback and tool_events_sent:
            await self.tool_callback(msg, "", True)
        if self.terminal_callback:
            await self.terminal_callback(msg, "", True)

        raw_content = "".join(chunks).strip()
        if self._is_proxy_mode():
            final_content = raw_content
        else:
            final_content = filter_noise_lines(raw_content).strip()
        if not final_content:
            final_content = "I've completed processing but have no response to give."

        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        outbound_metadata = metadata
        outbound_metadata["streamed"] = streamed
        outbound_metadata["agent"] = provider_session.agent.key

        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content,
            metadata=outbound_metadata,
        )

    def _resolve_agent_and_cwd(self, metadata: dict[str, object]) -> tuple[str, str]:
        agent_key = str(metadata.get("agent", self.default_agent) or self.default_agent).lower()
        cwd = str(metadata.get("cwd", str(self.workspace)) or str(self.workspace))
        return agent_key, cwd

    def _is_proxy_mode(self) -> bool:
        return bool(getattr(self.provider, "mode", "") == "proxy_api")

    def _resolve_origin(self, msg: InboundMessage) -> tuple[str, str]:
        """Resolve destination channel/chat for system-origin messages."""
        if msg.channel == "system" and ":" in msg.chat_id:
            channel, chat_id = msg.chat_id.split(":", 1)
            return channel, chat_id
        return msg.channel, msg.chat_id

    def _get_or_create_agent_session(
        self,
        session_key: str,
        metadata: dict[str, object] | None,
    ) -> AgentSession:
        meta = metadata or {}
        agent_type = str(meta.get("agent", self.default_agent) or self.default_agent).lower()
        cwd = str(meta.get("cwd", str(self.workspace)) or str(self.workspace))

        current = self._agent_sessions.get(session_key)
        if current:
            if current.agent.key == agent_type and current.cwd == cwd:
                if current.agent.key != "gemini" and not current.is_running:
                    current.start()
                return current
            current.stop()

        created = AgentSession(agent_type=agent_type, cwd=cwd)
        if created.agent.key == "gemini":
            created.mark_startup_complete()
        else:
            created.start()
        self._agent_sessions[session_key] = created
        return created

    def _close_all_agent_sessions(self) -> None:
        for session in self._agent_sessions.values():
            try:
                session.stop()
            except Exception:
                pass
        self._agent_sessions.clear()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        agent: str | None = None,
        cwd: str | None = None,
    ) -> str:
        """
        Process one message directly (without bus dispatch).
        """
        resolved_channel = channel
        resolved_chat_id = chat_id
        if session_key:
            if ":" in session_key:
                left, right = session_key.split(":", 1)
                resolved_channel = left or resolved_channel
                resolved_chat_id = right or resolved_chat_id
            elif chat_id == "direct":
                resolved_chat_id = session_key

        metadata: dict[str, object] = {}
        if agent:
            metadata["agent"] = agent
        if cwd:
            metadata["cwd"] = cwd

        msg = InboundMessage(
            channel=resolved_channel,
            sender_id="user",
            chat_id=resolved_chat_id,
            content=content,
            metadata=metadata,
        )

        response = await self._process_message(msg)
        return response.content if response else ""


# ---------------------------------------------------------------------------
# Module-level loop helpers
# ---------------------------------------------------------------------------

def _detect_stop_signal(text: str) -> bool:
    """Return True if the agent response signals task completion."""
    return "[TASK_COMPLETE]" in text or "TASK_COMPLETE" in text.upper()


def _build_loop_continuation_prompt(prev_response: str) -> str:  # noqa: ARG001
    """Build the continuation prompt for the next loop iteration."""
    return "Continue. Check your plan and proceed with the next step."
