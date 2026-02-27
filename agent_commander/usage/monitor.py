"""Background usage monitor – polls agent rate-limit windows periodically.

Ported from CodexBar/UsageStore.swift timer logic.

Usage:
    monitor = UsageMonitor(agent="codex", command="codex")
    monitor.on_update = my_callback   # set before start()
    monitor.on_notify = send_notification
    await monitor.start()
    ...
    monitor.stop()
"""

from __future__ import annotations

import asyncio
from typing import Callable

from loguru import logger

from agent_commander.usage.models import AgentUsageSnapshot

OnUsageUpdate = Callable[[AgentUsageSnapshot], None]
OnNotify = Callable[[str, str], None]  # (title, message)

# Primary window remaining-% below which we fire a "depleted" notification.
DEPLETION_THRESHOLD = 10.0


class UsageMonitor:
    """Async background poller for agent rate-limit status."""

    def __init__(
        self,
        agent: str,
        command: str,
        interval_s: float = 60.0,
    ) -> None:
        self.agent = agent
        self.command = command
        self.interval_s = interval_s

        # Callbacks – set these before calling start().
        self.on_update: OnUsageUpdate | None = None
        self.on_notify: OnNotify | None = None

        self._task: asyncio.Task | None = None
        self._running = False
        self._last_snapshot: AgentUsageSnapshot | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background polling task."""
        self._running = True
        self._task = asyncio.create_task(
            self._loop(),
            name=f"usage-monitor-{self.agent}",
        )
        logger.info(
            f"[usage] Monitor started for {self.agent!r}, "
            f"interval={self.interval_s}s"
        )

    def stop(self) -> None:
        """Cancel the background task."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    @property
    def last_snapshot(self) -> AgentUsageSnapshot | None:
        return self._last_snapshot

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        # First fetch happens immediately on start.
        await self._fetch_and_publish()
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._fetch_and_publish()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[usage] Monitor loop error: {exc}")

    async def _fetch_and_publish(self) -> None:
        try:
            snapshot = await self._fetch()
        except Exception as exc:
            logger.debug(f"[usage] fetch() raised: {exc}")
            return

        prev = self._last_snapshot
        self._last_snapshot = snapshot

        if self.on_update is not None:
            try:
                self.on_update(snapshot)
            except Exception as exc:
                logger.debug(f"[usage] on_update callback error: {exc}")

        self._check_depletion(prev, snapshot)

    async def _fetch(self) -> AgentUsageSnapshot:
        if self.agent == "codex":
            from agent_commander.usage.codex_probe import fetch_codex_status

            return await fetch_codex_status(command=self.command)

        if self.agent == "claude":
            from agent_commander.usage.claude_probe import fetch_claude_info

            return await fetch_claude_info(command=self.command)

        if self.agent == "gemini":
            from agent_commander.usage.gemini_probe import fetch_gemini_info

            return await fetch_gemini_info(command=self.command)

        return AgentUsageSnapshot(
            agent=self.agent,
            error="No probe available for this agent",
        )

    def _check_depletion(
        self,
        prev: AgentUsageSnapshot | None,
        current: AgentUsageSnapshot,
    ) -> None:
        """Fire notification when primary window crosses the depletion threshold.

        Skipped for label-only windows (e.g. Claude plan info) since they
        carry no real percentage data.
        """
        if self.on_notify is None:
            return
        primary = current.primary
        if primary is None or not primary.has_quota:
            return  # no % data → nothing to threshold-check

        prev_primary = prev.primary if prev else None
        prev_remaining = (
            prev_primary.remaining_percent
            if (prev_primary is not None and prev_primary.has_quota)
            else 100.0
        )
        curr_remaining = primary.remaining_percent

        # Crossing downward → depleted.
        if prev_remaining >= DEPLETION_THRESHOLD > curr_remaining:
            self.on_notify(
                "Agent Limit Alert",
                f"{self.agent.capitalize()}: {primary.name} limit nearly depleted "
                f"({curr_remaining:.0f}% left)",
            )
        # Crossing upward → restored (e.g. quota window reset).
        elif prev_remaining < DEPLETION_THRESHOLD <= curr_remaining:
            self.on_notify(
                "Agent Limit Restored",
                f"{self.agent.capitalize()}: {primary.name} limit restored "
                f"({curr_remaining:.0f}% left)",
            )
