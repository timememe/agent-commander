"""Codex rate-limit probe.

Ports the core logic from CodexBar/CodexStatusProbe.swift to Python.
Reuses the project's existing PTY backend (WinptyBackend on Windows,
pexpect on Unix) so no new dependencies are needed.

How it works:
  1. Spawn: codex -s read-only -a untrusted  (safe/non-destructive mode)
  2. Wait ~1.5 s for the CLI to start
  3. Send:  /status<newline>
  4. Collect output until "Weekly limit" line appears or timeout
  5. Strip ANSI, parse rate-window lines
  6. Kill the process
"""

from __future__ import annotations

import asyncio
import re
import time

from loguru import logger

from agent_commander.usage.models import AgentUsageSnapshot, RateWindow


# ---------------------------------------------------------------------------
# ANSI / text helpers
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(
    r"\x1b(?:\[[0-9;]*[A-Za-z]|\][^\x07]*\x07|[PX^_].*?\x1b\\|.)"
)
# Old CodexBar format: "5h limit: 75% left (resets in 3h 45m)"
_5H_RE = re.compile(r"5[h\-](?:hour)?\s+limit", re.IGNORECASE)
_WEEKLY_RE = re.compile(r"weekly\s+limit", re.IGNORECASE)
# Both old and new formats
_PCT_LEFT_RE = re.compile(r"(\d+)\s*%\s+left", re.IGNORECASE)
_PCT_USED_RE = re.compile(r"(\d+)\s*%\s+used", re.IGNORECASE)
_RESET_RE = re.compile(r"resets?\s+in\s+([\w ,]+)", re.IGNORECASE)
# New TUI status-bar format (codex v0.100+):
#   "gpt-5.3-codex high · 100% left · ~/path"
# The separator is U+00B7 (·) or › or similar.
_TUI_STATUS_RE = re.compile(
    r"[\u00b7\u203a>]\s*(\d+)%\s+left", re.IGNORECASE
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _parse_used_percent(line: str) -> float | None:
    m = _PCT_LEFT_RE.search(line)
    if m:
        return 100.0 - float(m.group(1))
    m = _PCT_USED_RE.search(line)
    if m:
        return float(m.group(1))
    return None


def _parse_reset_info(line: str) -> str | None:
    m = _RESET_RE.search(line)
    if m:
        return f"resets in {m.group(1).strip()}"
    return None


def parse_codex_status_text(text: str) -> list[RateWindow]:
    """Parse raw codex PTY output into a RateWindow list.

    Supports two formats:

    **Old CodexBar format** (codex < v0.100):
      ``5h limit: 75% left (resets in 3h 45m)``
      ``Weekly limit: 60% left (resets in 6d 2h)``

    **New TUI status-bar format** (codex v0.100+, gpt-5.x-codex):
      ``gpt-5.3-codex high · 100% left · ~/path``
      Visible in the startup splash screen – no ``/status`` command needed.
    """
    clean = _strip_ansi(text)
    windows: list[RateWindow] = []

    # --- Pass 1: old explicit-window format ---
    for line in clean.splitlines():
        line = line.strip()
        if not line:
            continue
        if _5H_RE.search(line):
            used = _parse_used_percent(line)
            if used is not None:
                windows.append(
                    RateWindow(
                        name="5h",
                        used_percent=used,
                        reset_info=_parse_reset_info(line),
                    )
                )
        elif _WEEKLY_RE.search(line):
            used = _parse_used_percent(line)
            if used is not None:
                windows.append(
                    RateWindow(
                        name="Weekly",
                        used_percent=used,
                        reset_info=_parse_reset_info(line),
                    )
                )

    if windows:
        return windows

    # --- Pass 2: new TUI status-bar format "model · N% left · dir" ---
    for line in clean.splitlines():
        m = _TUI_STATUS_RE.search(line)
        if m:
            remaining = float(m.group(1))
            windows.append(
                RateWindow(
                    name="Quota",
                    used_percent=100.0 - remaining,
                )
            )
            break

    return windows


# ---------------------------------------------------------------------------
# Async probe
# ---------------------------------------------------------------------------

def _run_reader_thread(backend: object, timeout_s: float) -> str:
    """Blocking helper: reads from PTY backend in a dedicated thread.

    ``WinptyBackend.read()`` is a blocking call – when the codex TUI is
    waiting for user input it blocks forever.  Running the loop in a
    plain thread lets asyncio stay responsive via ``run_in_executor``.

    The reader thread puts chunks into a ``queue.Queue``.  The calling
    code (``fetch_codex_status``) drains that queue from the asyncio side
    without ever blocking.
    """
    import queue
    import threading

    data_q: "queue.Queue[str]" = queue.Queue()
    stop_evt = threading.Event()

    def _reader() -> None:
        while not stop_evt.is_set():
            try:
                chunk = backend.read()  # type: ignore[attr-defined]
                if chunk:
                    data_q.put(chunk)
                else:
                    # No data yet – yield a bit to avoid busy-spin
                    time.sleep(0.05)
            except Exception:
                break

    t = threading.Thread(target=_reader, daemon=True, name="codex-probe-reader")
    t.start()

    buf = ""
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        # Drain everything currently in the queue (non-blocking)
        drained = False
        try:
            while True:
                buf += data_q.get_nowait()
                drained = True
        except queue.Empty:
            pass

        if drained:
            clean = _strip_ansi(buf)
            # Stop as soon as we have parseable data
            if _TUI_STATUS_RE.search(clean) or (
                _5H_RE.search(clean) and _WEEKLY_RE.search(clean)
            ):
                # Tiny grace period then final drain
                time.sleep(0.15)
                try:
                    while True:
                        buf += data_q.get_nowait()
                except queue.Empty:
                    pass
                break

        time.sleep(0.1)

    stop_evt.set()
    # The reader thread is a daemon; it will unblock (or raise) as soon as
    # the backend is closed by the caller.
    return buf


async def fetch_codex_status(
    command: str = "codex",
    timeout_s: float = 10.0,
) -> AgentUsageSnapshot:
    """Fetch Codex rate limits via PTY probe.

    Spawns ``codex -s read-only -a untrusted`` and reads the startup
    TUI screen which already contains the rate-limit percentage in its
    status bar (``model · N% left · dir``).  No ``/status`` command needed.

    Uses the project's existing WinptyBackend/UnixPexpectBackend; the
    blocking ``read()`` call is isolated in a background thread so the
    asyncio event loop stays responsive.
    """
    from agent_commander.providers.runtime.backend import build_backend

    full_command = f"{command} -s read-only -a untrusted"
    backend = None

    try:
        backend = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: build_backend(full_command, cols=200, rows=50),
        )
    except Exception as exc:
        logger.debug(f"[usage] codex backend init failed: {exc}")
        return AgentUsageSnapshot(
            agent="codex",
            error="Codex CLI not found or failed to start",
        )

    try:
        # Run the blocking reader loop in a thread-pool thread so that
        # the asyncio event loop (GUI, timers, etc.) remains unblocked.
        output_buf = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _run_reader_thread(backend, timeout_s),
        )

        windows = parse_codex_status_text(output_buf)
        if not windows:
            logger.debug(
                f"[usage] No rate-limit data in codex output "
                f"(chars={len(output_buf)})"
            )
            return AgentUsageSnapshot(
                agent="codex",
                error="No rate limit data in output",
            )

        logger.debug(
            f"[usage] Codex windows: {[w.format_status() for w in windows]}"
        )
        return AgentUsageSnapshot(agent="codex", windows=windows)

    except Exception as exc:
        logger.debug(f"[usage] codex probe error: {exc}")
        return AgentUsageSnapshot(agent="codex", error=str(exc)[:120])

    finally:
        if backend is not None:
            try:
                # Close in executor so taskkill doesn't block the loop either
                await asyncio.get_event_loop().run_in_executor(
                    None, backend.close
                )
            except Exception:
                pass
