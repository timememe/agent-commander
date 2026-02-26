"""Session wrapper for an interactive CLI agent process."""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

try:
    import pyte
except ImportError:  # pragma: no cover - optional runtime dependency
    pyte = None

from loguru import logger

from agent_commander.providers.agent_registry import AgentDef, get_agent_def
from agent_commander.providers.marker_parser import TerminalState, extract_response, get_terminal_state
from agent_commander.providers.pty_backend import PTYBackend, build_backend

ANSI_RE = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
# Extended: also catch OSC sequences (\x1b]...\x07 or \x1b]...\x1b\\)
ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
ANSI_FULL_RE = re.compile(
    r"\x1B[@-_][0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)"  # OSC
    r"|\x1BP[^\x1B]*\x1B\\"  # DCS
    r"|\x1B[()][0-9A-Za-z]"  # charset select
)


class AgentSession:
    """Manage one CLI-agent PTY session."""

    def __init__(
        self,
        agent_type: str,
        cwd: str | None = None,
        cols: int = 80,
        rows: int = 24,
    ) -> None:
        self.agent: AgentDef = get_agent_def(agent_type)
        self.cwd = str(Path(cwd).expanduser()) if cwd else None
        self.cols = cols
        self.rows = rows

        self._backend: Optional[PTYBackend] = None
        self._running = False
        self._reader_thread: Optional[threading.Thread] = None
        self._raw_queue: queue.Queue[str] = queue.Queue()
        self._text_queue: queue.Queue[str] = queue.Queue()
        self._prompt_ready = threading.Event()
        self._render_lock = threading.Lock()
        self._prompt_regexes = [
            re.compile(pattern, re.MULTILINE)
            for pattern in self.agent.prompt_patterns
        ]
        self._startup_prompt_handled = False
        self._startup_completed = threading.Event()

        self._screen = None
        self._stream = None
        if pyte is not None and self.agent.key != "gemini":
            self._screen = pyte.HistoryScreen(cols, rows, history=5000)
            self._screen.set_mode(pyte.modes.LNM)
            self._stream = pyte.Stream(self._screen)
        self._last_render = ""
        self._last_render_lines: list[str] = []

    @property
    def is_running(self) -> bool:
        """Return True when session process is alive."""
        return self._running

    def start(self) -> None:
        """Start CLI process and output reader thread."""
        if self._running:
            return

        command = self.agent.resolve_command()
        self._backend = build_backend(
            command=command,
            cols=self.cols,
            rows=self.rows,
            cwd=self.cwd,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def _read_loop(self) -> None:
        while self._running:
            backend = self._backend
            if backend is None:
                break
            data = backend.read()
            if data:
                self._raw_queue.put(data)
                text_delta = self._to_clean_text(data)
                if text_delta:
                    self._text_queue.put(text_delta)
                    self._handle_startup_prompts(text_delta)
                else:
                    self._handle_startup_prompts(data)
                self._update_prompt_state()

    def send(self, text: str) -> None:
        """Send text to CLI process stdin."""
        if self._backend is None:
            raise RuntimeError("Agent session is not started")
        self._backend.write(text)

    def submit(self, text: str) -> None:
        """Send a user message and finish with Enter."""
        payload = text if text.endswith(("\r", "\n")) else f"{text}\r"
        self.send(payload)
        # Codex can treat large/multiline payloads as pasted content token
        # and keep focus in composer; one extra Enter confirms submit.
        if self.agent.key == "codex" and (len(text) > 800 or "\n" in text):
            self.send("\r")

    def prepare_for_response(self, clear_raw: bool = True) -> None:
        """Clear readiness state and buffered output before a new turn.

        Args:
            clear_raw: When False, keep raw PTY buffer so terminal panel can
                consume full unfiltered startup/runtime output.
        """
        self._prompt_ready.clear()
        if clear_raw:
            self._drain_queue(self._raw_queue)
        self._drain_queue(self._text_queue)

    def read_available(self, max_chunks: int = 64) -> list[str]:
        """Drain clean text chunks without blocking."""
        chunks: list[str] = []
        for _ in range(max_chunks):
            try:
                chunks.append(self._text_queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    def read_available_raw(self, max_chunks: int = 64) -> list[str]:
        """Drain raw terminal chunks without blocking."""
        chunks: list[str] = []
        for _ in range(max_chunks):
            try:
                chunks.append(self._raw_queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    def is_prompt_ready(self) -> bool:
        """Return True when terminal tail matches prompt readiness markers."""
        return self._prompt_ready.is_set()

    def should_suppress_chat_output(self) -> bool:
        """Return True while startup handshake/noise is still in progress."""
        return not self._startup_completed.is_set()

    def mark_startup_complete(self) -> None:
        """Force startup completion flag (fallback when prompt detection is unavailable)."""
        self._startup_completed.set()

    def wait_until_ready(
        self,
        timeout_s: float = 20.0,
        poll_interval_s: float = 0.05,
        drain_output: bool = True,
    ) -> bool:
        """
        Block until prompt is ready (used for startup prewarm).

        Returns:
            True if prompt became ready within timeout, else False.
        """
        started = time.monotonic()
        while self._running and (time.monotonic() - started) < timeout_s:
            if self.is_prompt_ready():
                self._startup_completed.set()
                if drain_output:
                    self._drain_queue(self._raw_queue)
                    self._drain_queue(self._text_queue)
                return True
            time.sleep(max(0.01, poll_interval_s))
        return self.is_prompt_ready()

    def run_noninteractive_turn(self, text: str, timeout_s: float = 120.0) -> str:
        """
        Run one non-interactive turn (Gemini fallback on Windows).

        Uses `-p ""` and passes prompt via stdin to avoid command-line length
        limits with large context payloads.
        """
        if self.agent.key != "gemini":
            raise RuntimeError("run_noninteractive_turn is only supported for gemini")

        command = f'{self.agent.resolve_command()} -p ""'
        try:
            completed = subprocess.run(
                command,
                input=text,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout_s,
            )
        except Exception as exc:
            return str(exc)

        stdout = (completed.stdout or "").strip()
        stderr = (completed.stderr or "").strip()
        if stdout and stderr:
            return f"{stdout}\n{stderr}".strip()
        return stdout or stderr

    def get_snapshot(self) -> str:
        """Return full terminal screen text (like tmux capture-pane).

        This is the pyte-rendered screen content — ANSI codes are already
        interpreted but may remain in history lines.
        """
        with self._render_lock:
            if self._screen is not None:
                try:
                    return self._snapshot_text()
                except Exception:
                    pass
            return self._last_render

    def get_terminal_state(self) -> TerminalState:
        """Determine agent terminal state from current snapshot."""
        snapshot = self.get_snapshot()
        return get_terminal_state(self.agent.key, snapshot)

    def extract_response(self) -> str:
        """Extract the agent's last response from current terminal snapshot."""
        snapshot = self.get_snapshot()
        if snapshot:
            # Log last 500 chars of snapshot for debugging marker matching
            tail = snapshot[-500:] if len(snapshot) > 500 else snapshot
            logger.debug(f"[snapshot] agent={self.agent.key} len={len(snapshot)} tail=|{tail!r}|")
        result = extract_response(self.agent.key, snapshot)
        if result:
            logger.debug(f"[extract] agent={self.agent.key} result_len={len(result)} preview={result[:200]!r}")
        return result

    def resize(self, cols: int, rows: int) -> None:
        """Resize PTY dimensions."""
        self.cols = cols
        self.rows = rows
        if self._backend is not None:
            self._backend.resize(cols, rows)
        if self._screen is not None:
            with self._render_lock:
                try:
                    self._screen.resize(rows, cols)
                except Exception:
                    pass

    def stop(self) -> None:
        """Stop reader and close PTY process."""
        self._running = False
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None

    def restart(self) -> None:
        """Restart PTY backend for this session."""
        self.stop()
        self.start()

    def _to_clean_text(self, data: str) -> str:
        """Convert raw PTY data to clean text via pyte VTE or fallback.

        This does ANSI stripping and delta computation only.
        NO noise filtering here — that happens later in CLIAgentProvider
        so that _text_queue still feeds prompt detection and startup handlers.
        """
        if self._stream is None:
            cleaned = self._fallback_clean(data)
            if not cleaned:
                return ""
            self._last_render = (self._last_render + cleaned)[-20000:]
            return cleaned

        with self._render_lock:
            try:
                self._stream.feed(data)
                rendered = self._snapshot_text()
            except Exception:
                return self._fallback_clean(data)

            if rendered == self._last_render:
                return ""

            delta = self._compute_smart_delta(rendered)
            self._last_render = rendered
            self._last_render_lines = rendered.splitlines()

            return delta if delta else ""

    def _compute_smart_delta(self, rendered: str) -> str:
        """Extract only genuinely new content from a screen render.

        Instead of naively checking startswith (which breaks on redraws),
        we do a line-level diff: find the first divergence point between
        old and new lines, and return only the new/changed portion.
        On full redraws (agent cleared screen), we detect this and
        return only the meaningful new lines, not the entire dump.
        """
        new_lines = rendered.splitlines()
        old_lines = self._last_render_lines

        if not old_lines:
            return rendered

        # Fast path: new text appended at end (common case — streaming)
        if rendered.startswith(self._last_render):
            return rendered[len(self._last_render):]

        # Line-level diff: find where old and new diverge
        common_prefix_len = 0
        for i, (old_line, new_line) in enumerate(zip(old_lines, new_lines)):
            if old_line == new_line:
                common_prefix_len = i + 1
            else:
                break

        new_portion = new_lines[common_prefix_len:]
        if not new_portion:
            return ""

        # If the screen was largely rewritten (common prefix < 20% of old)
        # this is likely a full redraw (e.g. spinner/TUI repaint).
        # Return the new portion but let the noise filter handle it.
        return "\n".join(new_portion)

    def _snapshot_text(self) -> str:
        history_lines = [self._history_line_to_text(line) for line in self._screen.history.top]
        display_lines = [line.rstrip() for line in self._screen.display]
        lines = history_lines + display_lines
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    def _history_line_to_text(self, line: object) -> str:
        if self._screen is None:
            return str(line).rstrip()
        if isinstance(line, dict):
            cols = self._screen.columns
            return "".join(line[x].data if x in line else " " for x in range(cols)).rstrip()
        return str(line).rstrip()

    def _fallback_clean(self, data: str) -> str:
        cleaned = ANSI_FULL_RE.sub("", data)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        return "".join(ch for ch in cleaned if ch == "\n" or ch == "\t" or ord(ch) >= 32)

    def _update_prompt_state(self) -> None:
        tail = self._tail_text()
        if tail and any(regex.search(tail) for regex in self._prompt_regexes):
            self._prompt_ready.set()
            self._startup_completed.set()
            return
        self._prompt_ready.clear()

    def _handle_startup_prompts(self, text: str) -> None:
        """Handle known one-time startup prompts from CLI agents.

        - Codex: "update available" menu → send "2" (skip)
        - Claude Code: "Yes, I trust this folder" dialog → send "1" + Enter
        """
        if self._startup_prompt_handled:
            return

        lowered = text.lower()
        agent_key = self.agent.key

        # Codex: update menu
        if agent_key == "codex":
            if "update available" in lowered or "press enter to continue" in lowered:
                try:
                    self.send("2\r")
                except Exception:
                    pass
                self._startup_prompt_handled = True
                return

        # Claude Code: trust folder dialog
        if agent_key == "claude":
            if "yes, i trust this folder" in lowered or "trust this folder" in lowered:
                try:
                    # Send "1" to select "Yes, I trust this folder" then Enter
                    self.send("1\r")
                except Exception:
                    pass
                self._startup_prompt_handled = True
                return

    def _tail_text(self, lines: int = 8) -> str:
        with self._render_lock:
            if not self._last_render:
                return ""
            parts = self._last_render.splitlines()
            return "\n".join(parts[-lines:])

    def _drain_queue(self, q: "queue.Queue[str]") -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return
