"""Gemini CLI usage probe via /stats command.

Flow
----
1. Start ``gemini`` CLI.
2. Wait up to 25s for either:
   - "Keep chat history" dialog → send ``\r`` to confirm and dismiss.
   - "Type your message" prompt → already ready.
3. Send ``/stats`` then two carriage returns:
   - First ``\r`` confirms the autocomplete selection.
   - Second ``\r`` executes the command.
4. Collect the stats panel and parse per-model usage rows.

Parsed output looks like (after ANSI stripping):
    │  Auto (Gemini 3) Usage
    │  Model          Reqs    Usage remaining
    │  gemini-2.5-flash   -   99.9% resets in 23h 49m
    │  gemini-2.5-pro     -  100.0% resets in 23h 9m
"""

from __future__ import annotations

import queue
import re
import threading
import time

from loguru import logger

from agent_commander.usage.models import AgentUsageSnapshot, RateWindow

# ---------------------------------------------------------------------------
# ANSI / parsing helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;]*[A-Za-z]|\][^\x07]*\x07|[PX^_].*?\x1b\\|.)"
)

# Dialog that may appear on first launch
_DIALOG_RE = re.compile(r"Keep chat history", re.IGNORECASE)

# Idle prompt indicator
_PROMPT_RE = re.compile(r"Type your message", re.IGNORECASE)

# Per-model row in /stats output:
#   gemini-2.5-flash   -   99.9% resets in 23h 49m
_MODEL_ROW_RE = re.compile(
    r"(gemini-[\w./-]+)\s+[-\d]+\s+([\d.]+)%\s+resets in\s+([\d]+h(?:\s*\d+m)?)",
    re.IGNORECASE,
)

# Tier / plan label
_TIER_RE = re.compile(r"Tier:\s*(.+?)(?:\s{2,}|$)", re.MULTILINE | re.IGNORECASE)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_gemini_stats(text: str) -> list[RateWindow]:
    """Extract per-model usage from /stats panel output."""
    clean = _strip_ansi(text)
    windows: list[RateWindow] = []

    for m in _MODEL_ROW_RE.finditer(clean):
        model = m.group(1).strip()
        remaining_pct = float(m.group(2))
        used_pct = 100.0 - remaining_pct
        reset_info = m.group(3).strip()
        windows.append(
            RateWindow(
                name=model,
                used_percent=used_pct,
                reset_info=reset_info,
            )
        )

    return windows


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------

def _run_reader_thread(backend: object, timeout_s: float) -> str:
    """Reader-thread + queue pattern to avoid blocking on PTY read()."""
    data_q: "queue.Queue[str]" = queue.Queue()
    stop_evt = threading.Event()

    def _reader() -> None:
        while not stop_evt.is_set():
            try:
                chunk = backend.read()  # type: ignore[attr-defined]
                if chunk:
                    data_q.put(chunk)
                else:
                    time.sleep(0.05)
            except Exception:
                break

    t = threading.Thread(target=_reader, daemon=True, name="gemini-probe-reader")
    t.start()

    buf = ""
    deadline = time.monotonic() + timeout_s
    dismissed = False

    while time.monotonic() < deadline:
        try:
            while True:
                buf += data_q.get_nowait()
        except queue.Empty:
            pass

        clean = _strip_ansi(buf)

        # Dismiss "Keep chat history" dialog with a single \r
        if _DIALOG_RE.search(clean) and not dismissed:
            logger.debug("[usage] gemini: dialog detected, dismissing with \\r")
            backend.write("\r")  # type: ignore[attr-defined]
            dismissed = True
            # Wait for dialog to close
            time.sleep(3.5)
            try:
                while True:
                    buf += data_q.get_nowait()
            except queue.Empty:
                pass
            continue

        # Stop when we reach the idle input prompt
        if _PROMPT_RE.search(clean):
            time.sleep(0.5)
            try:
                while True:
                    buf += data_q.get_nowait()
            except queue.Empty:
                pass
            break

        time.sleep(0.15)

    stop_evt.set()
    return buf


def _collect_stats_output(backend: object, timeout_s: float) -> str:
    """Send /stats and collect the stats panel."""
    data_q: "queue.Queue[str]" = queue.Queue()
    stop_evt = threading.Event()

    def _reader() -> None:
        while not stop_evt.is_set():
            try:
                chunk = backend.read()  # type: ignore[attr-defined]
                if chunk:
                    data_q.put(chunk)
                else:
                    time.sleep(0.05)
            except Exception:
                break

    t = threading.Thread(target=_reader, daemon=True, name="gemini-stats-reader")
    t.start()

    buf = ""
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        try:
            while True:
                buf += data_q.get_nowait()
        except queue.Empty:
            pass

        clean = _strip_ansi(buf)
        # Stop when model rows appear
        if _MODEL_ROW_RE.search(clean):
            time.sleep(1.0)
            try:
                while True:
                    buf += data_q.get_nowait()
            except queue.Empty:
                pass
            break

        time.sleep(0.15)

    stop_evt.set()
    return buf


async def fetch_gemini_info(
    command: str = "gemini",
    timeout_s: float = 25.0,
) -> AgentUsageSnapshot:
    """Probe Gemini CLI /stats command for per-model usage information.

    Handles the "Keep chat history" dialog automatically.
    Returns ``RateWindow`` objects with real usage percentages.
    """
    import asyncio

    from agent_commander.providers.runtime.backend import build_backend

    backend = None
    try:
        try:
            backend = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: build_backend(command, cols=200, rows=50),
            )
        except Exception as exc:
            logger.debug(f"[usage] gemini backend init failed: {exc}")
            return AgentUsageSnapshot(
                agent="gemini",
                error="Gemini CLI not found or failed to start",
            )

        # Phase 1: wait for prompt (handles dialog internally)
        prompt_buf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _run_reader_thread(backend, timeout_s),
        )

        if not _PROMPT_RE.search(_strip_ansi(prompt_buf)):
            logger.debug(
                f"[usage] Gemini prompt not found within {timeout_s}s "
                f"(chars={len(prompt_buf)})"
            )
            return AgentUsageSnapshot(
                agent="gemini",
                error="Prompt not detected",
            )

        # Phase 2: send /stats with double \r
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: backend.write("/stats\r"),  # type: ignore[attr-defined]
        )
        await asyncio.sleep(0.5)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: backend.write("\r"),  # type: ignore[attr-defined]
        )

        # Phase 3: collect stats output
        stats_buf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _collect_stats_output(backend, timeout_s=12.0),
        )

        windows = _parse_gemini_stats(stats_buf)
        if not windows:
            logger.debug(
                f"[usage] No stats data in gemini /stats output "
                f"(chars={len(stats_buf)})"
            )
            return AgentUsageSnapshot(
                agent="gemini",
                error="Could not parse stats data",
            )

        logger.debug(
            f"[usage] Gemini stats: "
            + ", ".join(
                f"{w.name} {w.remaining_percent:.1f}% left" for w in windows
            )
        )
        return AgentUsageSnapshot(agent="gemini", windows=windows)

    except Exception as exc:
        logger.debug(f"[usage] gemini probe error: {exc}")
        return AgentUsageSnapshot(agent="gemini", error=str(exc)[:120])

    finally:
        if backend is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, backend.close
                )
            except Exception:
                pass
