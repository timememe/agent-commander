"""Provider interfaces."""

import asyncio
from typing import Any, AsyncIterator, Awaitable, Callable

from loguru import logger

from agent_commander.providers.runtime.markers import TerminalState
from agent_commander.providers.runtime.filter import filter_noise_lines


class CLIAgentProvider:
    """Provider that gets responses from CLI-agent sessions via snapshots.

    Instead of parsing a stream of PTY chunks, we:
    1. Submit the message to the agent
    2. Stream raw PTY output to the terminal panel (for live view)
    3. Poll for turn completion using snapshot-based state detection
    4. On completion, take a full terminal snapshot and extract the response
    """

    def __init__(
        self,
        poll_interval_s: float = 0.05,
        idle_settle_s: float = 0.20,
        turn_timeout_s: float = 300.0,
        snapshot_interval_s: float = 1.0,
    ) -> None:
        self.poll_interval_s = poll_interval_s
        self.idle_settle_s = idle_settle_s
        self.turn_timeout_s = turn_timeout_s
        self.snapshot_interval_s = snapshot_interval_s

    async def send_and_receive(
        self,
        message: str,
        session: "AgentSession",
        on_raw: Callable[[str], Awaitable[None]] | None = None,
    ) -> AsyncIterator[str]:
        """
        Send one message to CLI agent and yield response when complete.

        Raw PTY output is streamed to on_raw callback in real time (terminal panel).
        The clean response is extracted from a terminal snapshot after completion.
        """
        logger.debug(f"[send_and_receive] agent={session.agent.key}, msg_len={len(message)}")

        # Gemini fallback: run in non-interactive mode per-turn.
        if session.agent.key == "gemini":
            output = await asyncio.to_thread(
                session.run_noninteractive_turn,
                message,
                self.turn_timeout_s,
            )
            logger.debug(f"[gemini] raw output len={len(output or '')}")
            if on_raw is not None and output:
                await on_raw(output + "\n")
            from agent_commander.providers.runtime.markers import gemini_extract_response
            extracted = gemini_extract_response(output)
            cleaned = filter_noise_lines(extracted) if extracted else ""
            logger.debug(f"[gemini] extracted={len(extracted)}, cleaned={len(cleaned)}")
            if cleaned.strip():
                yield cleaned
            return

        if not session.is_running:
            logger.debug("[send_and_receive] starting session")
            session.start()

        # Keep raw queue so terminal gets full, unfiltered PTY output.
        session.prepare_for_response(clear_raw=False)
        self._submit_with_recovery(message, session)
        logger.debug("[send_and_receive] message submitted, entering poll loop")

        loop = asyncio.get_running_loop()
        started_at = loop.time()
        last_output_at = started_at
        last_snapshot_at = started_at
        got_output = False
        last_yielded_response = ""

        while True:
            # Stream raw PTY output to terminal panel
            raw_chunks = session.read_available_raw()
            if raw_chunks and on_raw is not None:
                raw_block = "".join(raw_chunks)
                if raw_block:
                    await on_raw(raw_block)

            # Track that we're getting output (for completion detection)
            text_chunks = session.read_available()
            if text_chunks:
                if not got_output:
                    logger.debug(f"[poll] first text output received")
                got_output = True
                last_output_at = loop.time()

            now = loop.time()

            # Periodic snapshot: extract response progressively for chat
            if got_output and (now - last_snapshot_at) >= self.snapshot_interval_s:
                last_snapshot_at = now
                response = await asyncio.to_thread(session.extract_response)
                logger.debug(f"[snapshot] response_len={len(response or '')}, prev_len={len(last_yielded_response)}")
                if response and response != last_yielded_response:
                    # Yield only the new portion
                    if response.startswith(last_yielded_response):
                        delta = response[len(last_yielded_response):]
                    else:
                        delta = response
                    last_yielded_response = response
                    cleaned = filter_noise_lines(delta)
                    if cleaned.strip():
                        yield cleaned

            # Turn completion: check terminal state from snapshot
            if got_output and (now - last_output_at) >= self.idle_settle_s:
                state = await asyncio.to_thread(session.get_terminal_state)
                logger.debug(f"[poll] idle check: state={state}, idle_for={now - last_output_at:.2f}s")
                if state in (TerminalState.COMPLETED, TerminalState.IDLE):
                    logger.debug(f"[poll] turn complete: {state}")
                    break

            if (now - started_at) >= self.turn_timeout_s:
                logger.warning(f"[poll] turn timeout after {self.turn_timeout_s}s")
                break

            await asyncio.sleep(self.poll_interval_s)

        # Final snapshot: extract complete response
        final_response = await asyncio.to_thread(session.extract_response)
        logger.debug(f"[final] response_len={len(final_response or '')}, yielded_so_far={len(last_yielded_response)}")
        if final_response and final_response != last_yielded_response:
            if final_response.startswith(last_yielded_response):
                delta = final_response[len(last_yielded_response):]
            else:
                delta = final_response
            cleaned = filter_noise_lines(delta)
            if cleaned.strip():
                yield cleaned

        # Flush remaining raw output at turn end
        if on_raw is not None:
            raw_chunks = session.read_available_raw()
            if raw_chunks:
                raw_block = "".join(raw_chunks)
                if raw_block:
                    await on_raw(raw_block)

    async def send_and_collect(self, message: str, session: "AgentSession") -> str:
        """Collect full response as one string."""
        parts: list[str] = []
        async for chunk in self.send_and_receive(message=message, session=session):
            parts.append(chunk)
        return "".join(parts).strip()

    def _submit_with_recovery(self, message: str, session: "AgentSession") -> None:
        """Submit turn; restart PTY once if backend is closed."""
        try:
            session.submit(message)
            return
        except Exception as exc:
            if "closed" not in str(exc).lower():
                raise

        session.restart()
        session.prepare_for_response(clear_raw=False)
        session.submit(message)
