"""Claude Code usage probe via /usage command.

Flow
----
1. Start ``claude`` (temporarily unset CLAUDECODE to avoid nested-session error).
2. Wait for the interactive prompt (❯ character) to appear.
3. Send ``/usage`` then two carriage returns:
   - First ``\r`` confirms the autocomplete selection.
   - Second ``\r`` executes the selected command.
4. Collect the output panel and parse ``N% used`` values for
   "Current session" and "Current week".
5. Return two ``RateWindow`` objects with real percentages.

Parsed output looks like (after ANSI stripping):
    Current session
    █████████████ 76% used
    Current week (all models)
    █▌                 9% used
    Resets Mar 6, 9:59am (Asia/Oral)
"""

from __future__ import annotations

import os
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

# Patterns in /usage output.
# TUI strips spaces during rendering so "Current session" may appear as
# "Currentsession" and "Resets Mar 6" may appear as "ResetsMar6…".
_SESSION_RE = re.compile(
    r"Current\s*session\s*.*?(\d+)\s*%\s*used", re.DOTALL | re.IGNORECASE
)
_WEEK_RE = re.compile(
    r"Current\s*week.*?(\d+)\s*%\s*used", re.DOTALL | re.IGNORECASE
)
_RESET_RE = re.compile(
    r"Resets\s*([A-Za-z].*?)(?:\n|$)", re.IGNORECASE
)

# Interactive prompt indicator
_PROMPT_RE = re.compile(r"\u276f")  # ❯


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_claude_usage(text: str) -> list[RateWindow]:
    """Extract session and weekly usage from /usage panel output."""
    clean = _strip_ansi(text)
    windows: list[RateWindow] = []

    session_m = _SESSION_RE.search(clean)
    week_m = _WEEK_RE.search(clean)
    reset_m = _RESET_RE.search(clean)
    reset_full = reset_m.group(1).strip() if reset_m else None

    # Shorten reset date: "Mar 6, 9:59am (Asia/Oral)" or "Mar6,9:59am..." → "Mar 6"
    if reset_full:
        # Insert space between letters and digits if stripped by TUI
        spaced = re.sub(r"([A-Za-z])(\d)", r"\1 \2", reset_full)
        date_m = re.search(r"([A-Za-z]+\s+\d+)", spaced)
        reset_info: str | None = date_m.group(1) if date_m else reset_full[:20]
    else:
        reset_info = None

    if session_m:
        used = float(session_m.group(1))
        windows.append(RateWindow(name="Session", used_percent=used))

    if week_m:
        used = float(week_m.group(1))
        windows.append(
            RateWindow(name="Week", used_percent=used, reset_info=reset_info)
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

    t = threading.Thread(target=_reader, daemon=True, name="claude-probe-reader")
    t.start()

    buf = ""
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        try:
            while True:
                buf += data_q.get_nowait()
        except queue.Empty:
            pass

        # Stop as soon as prompt is ready (❯ character)
        if _PROMPT_RE.search(_strip_ansi(buf)):
            time.sleep(0.5)
            try:
                while True:
                    buf += data_q.get_nowait()
            except queue.Empty:
                pass
            break

        time.sleep(0.1)

    stop_evt.set()
    return buf


def _collect_usage_output(backend: object, timeout_s: float) -> str:
    """Send /usage and collect the output panel."""
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

    t = threading.Thread(target=_reader, daemon=True, name="claude-usage-reader")
    t.start()

    buf = ""
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        try:
            while True:
                buf += data_q.get_nowait()
        except queue.Empty:
            pass

        # Stop when usage output is visible
        clean = _strip_ansi(buf)
        if "Current session" in clean and "% used" in clean:
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


async def fetch_claude_info(
    command: str = "claude",
    timeout_s: float = 20.0,
) -> AgentUsageSnapshot:
    """Probe Claude Code /usage command for plan usage information.

    Returns ``RateWindow`` objects for "Session" and "Week" with real
    usage percentages.
    """
    import asyncio

    from agent_commander.providers.runtime.backend import build_backend

    saved_claudecode = os.environ.pop("CLAUDECODE", None)

    backend = None
    try:
        try:
            backend = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: build_backend(command, cols=200, rows=60),
            )
        except Exception as exc:
            logger.debug(f"[usage] claude backend init failed: {exc}")
            return AgentUsageSnapshot(
                agent="claude",
                error="Claude CLI not found or failed to start",
            )

        # Phase 1: wait for prompt
        prompt_buf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _run_reader_thread(backend, timeout_s),
        )

        if not _PROMPT_RE.search(_strip_ansi(prompt_buf)):
            logger.debug(
                f"[usage] Claude prompt not found within {timeout_s}s "
                f"(chars={len(prompt_buf)})"
            )
            return AgentUsageSnapshot(
                agent="claude",
                error="Prompt not detected",
            )

        # Phase 2: send /usage with double \r (first selects autocomplete, second executes)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: backend.write("/usage\r"),  # type: ignore[attr-defined]
        )
        await asyncio.sleep(0.5)
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: backend.write("\r"),  # type: ignore[attr-defined]
        )

        # Phase 3: collect output
        usage_buf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _collect_usage_output(backend, timeout_s=12.0),
        )

        windows = _parse_claude_usage(usage_buf)
        if not windows:
            logger.debug(
                f"[usage] No usage data in claude /usage output "
                f"(chars={len(usage_buf)})"
            )
            return AgentUsageSnapshot(
                agent="claude",
                error="Could not parse usage data",
            )

        logger.debug(
            f"[usage] Claude usage: "
            + ", ".join(f"{w.name} {w.remaining_percent:.0f}% left" for w in windows)
        )
        return AgentUsageSnapshot(agent="claude", windows=windows)

    except Exception as exc:
        logger.debug(f"[usage] claude probe error: {exc}")
        return AgentUsageSnapshot(agent="claude", error=str(exc)[:120])

    finally:
        if saved_claudecode is not None:
            os.environ["CLAUDECODE"] = saved_claudecode
        if backend is not None:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, backend.close
                )
            except Exception:
                pass
