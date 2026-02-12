import os
import shutil
import shlex
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font
import json
import glob
import ctypes
from queue import Queue, Empty
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Protocol

import customtkinter as ctk
import pyte
import re

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    TKDND_AVAILABLE = True
except Exception:
    DND_FILES = ""
    TkinterDnD = None
    TKDND_AVAILABLE = False

from datetime import datetime
from orchestrator_store import OrchestratorStore, TaskRecord, ProjectRecord, utc_now_iso
from event_contract import (
    DefaultSignalAdapter,
    SIGNAL_ASSISTANT_MESSAGE,
    SIGNAL_CHOICE_REQUEST,
    SIGNAL_CHOICE_SELECTED,
    SIGNAL_SYSTEM_EVENT,
    SIGNAL_USER_MESSAGE,
    extract_choice_payload as extract_signal_choice_payload,
    normalize_choice_payload as normalize_signal_choice_payload,
)

ANSI_RE = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
SPINNER_BRAILLE_RE = re.compile(r"[\u280b\u2819\u2839\u2838\u283c\u2834\u2826\u2827\u2807\u280f]")
BOX_UI_LINE_RE = re.compile(r"^[\s\u2500-\u257f\u2580-\u259f]+$")
FILE_HINT_LINE_RE = re.compile(r"^\s*\d+\s+\S+\s+files?\s*$", re.IGNORECASE)
STATUS_MEM_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kb|mb|gb)\b", re.IGNORECASE)
STATUS_RATE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:tok/s|tokens/s|it/s)\b", re.IGNORECASE)


def _normalize_terminal_signature(text: str) -> str:
    normalized = text.lower()
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "<time>", normalized)
    normalized = re.sub(r"\b\d+%\b", "<pct>", normalized)
    normalized = STATUS_MEM_RE.sub("<mem>", normalized)
    normalized = STATUS_RATE_RE.sub("<rate>", normalized)
    normalized = SPINNER_BRAILLE_RE.sub("", normalized)
    normalized = re.sub(r"[\u2580-\u259f]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:800]


def _is_terminal_repaint_noise(text: str) -> bool:
    meaningful_lines = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if BOX_UI_LINE_RE.fullmatch(line):
            continue
        compact = re.sub(r"\s+", " ", line).strip()
        lower = compact.lower()
        if "type your message" in lower and "@path/to/file" in lower:
            continue
        if FILE_HINT_LINE_RE.fullmatch(compact):
            continue
        if ("/model" in lower or "no sandbox" in lower) and STATUS_MEM_RE.search(lower):
            continue
        meaningful_lines.append(compact)
    return len(meaningful_lines) == 0

# ── Color palette ──────────────────────────────────────────────────────────────

BG_DARK = "#050a08"
PANE_BG = "#07160f"
TEXT_COLOR = "#b7ffc8"
TITLE_BG = "#153024"
TITLE_COLOR = "#ffd400"
BORDER_NORMAL = "#00ff66"
BORDER_FOCUSED = "#ffd400"
STATUS_BG = "#18331f"
STATUS_COLOR = "#e2ff6d"

BUTTON_BG = "#1a3d2a"
BUTTON_HOVER = "#245738"
INPUT_BG = "#0c1f14"
INPUT_BORDER = "#1a5c35"
SEND_BG = "#2a6e3f"
SEND_HOVER = "#358a4e"

# Simple UI palette for main controls (3 colors)
UI_PRIMARY = "#2f7cf6"
UI_PRIMARY_HOVER = "#2568cc"
UI_NEUTRAL = "#1f2b3a"
UI_NEUTRAL_HOVER = "#2a3a4e"
UI_ACCENT = "#f2b84b"
DANGER_BG = "#7a2f2f"
DANGER_HOVER = "#9c3c3c"

# Task strip colors
STRIP_BG = "#0f2a1c"
STRIP_BORDER = "#1a5c35"
STATUS_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "todo":        ("#2a4a3a", "#aaaaaa"),
    "in_progress": ("#1a4a2e", "#58ff8a"),
    "paused":      ("#4a3a1a", "#ffd466"),
    "blocked":     ("#4a1a1a", "#ff6666"),
    "done":        ("#1a3a4a", "#66ccff"),
}

# Project strip colors (blueish to distinguish from task strip)
PROJECT_STRIP_BG = "#0f1c2a"
PROJECT_STRIP_BORDER = "#1a3d5c"
PROJECT_STATUS_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "active":   ("#1a4a2e", "#58ff8a"),
    "paused":   ("#4a3a1a", "#ffd466"),
    "archived": ("#2a3a4a", "#88aacc"),
}

# Binding-type border colors
BORDER_PROJECT = "#4488ff"   # blue border for project-bound pane
BORDER_TASK = "#ffd400"      # yellow border for task-bound pane

FONT_FAMILY = "Consolas" if sys.platform == "win32" else "Monaco"
FONT_SIZE = 11

# ── Available agent CLIs ──────────────────────────────────────────────────────

SETUP_AGENT_DEFS: list[tuple[str, str, str, str]] = [
    ("claude", "Claude Code", "TRIPTYCH_CLAUDE_CMD", "claude"),
    ("gemini", "Gemini CLI", "TRIPTYCH_GEMINI_CMD", "gemini"),
    ("codex", "Codex CLI", "TRIPTYCH_CODEX_CMD", "codex"),
]
SETUP_AGENT_IDS = [agent_id for agent_id, _, _, _ in SETUP_AGENT_DEFS]
AGENT_COMMANDS = list(SETUP_AGENT_IDS)
COMMON_CACHE_DIRNAME = "main_cache"
SETUP_STATE_FILENAME = "agent_setup.json"
LAUNCHER_CHECK_FILENAME = "launcher_agent_check.json"
STARTER_WORKSPACE_DIRNAME = "starter_workspace"
EVENT_TEXT_LIMIT = 12000
CHAT_EVENT_LIMIT = 500

# ── Slash commands per agent ──────────────────────────────────────────────────

SLASH_COMMANDS: dict[str, list[tuple[str, str]]] = {
    "claude": [
        ("/add-dir", "Add additional working directories"),
        ("/agents", "Manage custom AI subagents"),
        ("/bug", "Report bugs"),
        ("/clear", "Clear conversation history"),
        ("/compact", "Compact conversation context"),
        ("/config", "Open settings"),
        ("/cost", "Show token usage"),
        ("/doctor", "Check CLI environment health"),
        ("/help", "Show available commands"),
        ("/init", "Initialize project with CLAUDE.md"),
        ("/login", "Switch Anthropic account"),
        ("/logout", "Sign out"),
        ("/mcp", "Manage MCP servers"),
        ("/memory", "Edit memory files"),
        ("/model", "Select or change model"),
        ("/permissions", "View/update permissions"),
        ("/pr_comments", "View pull request comments"),
        ("/review", "Request code review"),
        ("/rewind", "Rewind conversation/code"),
        ("/sandbox", "Toggle sandboxed bash mode"),
        ("/status", "Show status tab"),
        ("/terminal-setup", "Install Shift+Enter newline binding"),
        ("/usage", "Show usage/rate limits"),
        ("/vim", "Enter vim mode"),
    ],
    "gemini": [
        ("/about", "About Gemini CLI"),
        ("/auth", "Change auth method"),
        ("/bug", "Report an issue"),
        ("/chat", "Manage chat checkpoints"),
        ("/clear", "Clear conversation history"),
        ("/compress", "Summarize conversation history"),
        ("/copy", "Copy last output"),
        ("/docs", "Open full CLI documentation"),
        ("/editor", "Open external editor mode"),
        ("/extensions", "Manage extensions"),
        ("/help", "Show available commands"),
        ("/ide", "Manage IDE integration"),
        ("/mcp", "Manage MCP servers"),
        ("/memory", "Manage AI memory"),
        ("/privacy", "Show privacy notice"),
        ("/quit", "Exit Gemini CLI"),
        ("/stats", "Show token/session stats"),
        ("/theme", "Change visual theme"),
        ("/tools", "List tools or show tool details"),
    ],
    "codex": [
        ("/add-dir", "Add additional working directories"),
        ("/agents", "Manage custom agents"),
        ("/approvals", "Adjust approval settings"),
        ("/bug", "Report an issue"),
        ("/clear", "Clear conversation history"),
        ("/compact", "Compact conversation"),
        ("/config", "Open config panel"),
        ("/cost", "Show token usage"),
        ("/doctor", "Check installation health"),
        ("/help", "Show available commands"),
        ("/history", "Show command history"),
        ("/init", "Create AGENTS.md"),
        ("/login", "Switch OpenAI account"),
        ("/logout", "Sign out"),
        ("/mcp", "Manage MCP servers"),
        ("/memory", "Edit memory files"),
        ("/model", "Change model/reasoning effort"),
        ("/permissions", "View/update permissions"),
        ("/pr_comments", "View pull request comments"),
        ("/prompts", "Manage reusable prompts"),
        ("/quit", "Exit Codex CLI"),
        ("/review", "Request code review"),
        ("/status", "Show session status"),
        ("/terminal-setup", "Install Shift+Enter newline binding"),
        ("/undo", "Undo previous action"),
        ("/upgrade", "Upgrade Codex CLI"),
    ],
    "_default": [
        ("/help", "Show available commands"),
        ("/clear", "Clear conversation history"),
        ("/quit", "Exit current agent"),
    ],
}

# ── PTY Backends ───────────────────────────────────────────────────────────────


class PTYBackend(Protocol):
    def read(self) -> str: ...
    def write(self, data: str) -> None: ...
    def resize(self, cols: int, rows: int) -> None: ...
    def close(self) -> None: ...


class UnixPexpectBackend:
    def __init__(self, command: str, cols: int, rows: int) -> None:
        import pexpect

        self._pexpect = pexpect
        self._proc = pexpect.spawn(
            command, encoding="utf-8", codec_errors="ignore", echo=False,
            dimensions=(rows, cols),
        )

    def read(self) -> str:
        try:
            return self._proc.read_nonblocking(size=4096, timeout=0.1)
        except self._pexpect.TIMEOUT:
            return ""
        except self._pexpect.EOF:
            return ""

    def write(self, data: str) -> None:
        self._proc.send(data)

    def resize(self, cols: int, rows: int) -> None:
        self._proc.setwinsize(rows, cols)

    def close(self) -> None:
        if self._proc.isalive():
            self._proc.close(force=True)


class WinptyBackend:
    def __init__(self, command: str, cols: int, rows: int) -> None:
        from winpty import Backend, PtyProcess

        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")

        # Claude/Gemini TUI agents behave better on modern ConPTY.
        launch_attempts = (
            {"backend": Backend.ConPTY},
            {"backend": Backend.WinPTY},
            {},
        )
        last_error: Optional[Exception] = None
        self._proc = None
        for extra in launch_attempts:
            try:
                self._proc = PtyProcess.spawn(
                    command,
                    dimensions=(rows, cols),
                    env=env,
                    **extra,
                )
                break
            except Exception as exc:
                last_error = exc

        if self._proc is None:
            raise RuntimeError("Failed to start PTY backend") from last_error

    def read(self) -> str:
        try:
            return self._proc.read(4096)
        except Exception:
            return ""

    def write(self, data: str) -> None:
        self._proc.write(data)

    def resize(self, cols: int, rows: int) -> None:
        try:
            self._proc.setwinsize(rows, cols)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._proc.close()
        except Exception:
            pass


class SubprocessFallbackBackend:
    def __init__(self, command: str, cols: int, rows: int) -> None:
        self._proc = subprocess.Popen(
            command, shell=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="ignore", bufsize=1,
        )

    def read(self) -> str:
        if not self._proc.stdout:
            return ""
        chunk = self._proc.stdout.read(1)
        return chunk or ""

    def write(self, data: str) -> None:
        if self._proc.stdin:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def resize(self, cols: int, rows: int) -> None:
        pass  # subprocess doesn't support resize

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass


# ── Shell Session ──────────────────────────────────────────────────────────────


class ShellSession:
    def __init__(self, pane: "AgentPane", shell_command: str,
                 cols: int, rows: int) -> None:
        self.pane = pane
        self.shell_command = shell_command
        self.backend: Optional[PTYBackend] = None
        self._running = False
        self._reader: Optional[threading.Thread] = None
        self._cols = cols
        self._rows = rows

    def start(self) -> None:
        self.backend = self._build_backend(self.shell_command)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _build_backend(self, command: str) -> PTYBackend:
        if os.name == "nt":
            try:
                return WinptyBackend(command, self._cols, self._rows)
            except Exception:
                return SubprocessFallbackBackend(command, self._cols, self._rows)
        return UnixPexpectBackend(command, self._cols, self._rows)

    def _read_loop(self) -> None:
        while self._running:
            if not self.backend:
                break
            data = self.backend.read()
            if data:
                self.pane._data_queue.put(data)

    def send(self, data: str) -> None:
        if self.backend:
            self.backend.write(data)

    def resize(self, cols: int, rows: int) -> None:
        self._cols = cols
        self._rows = rows
        if self.backend:
            self.backend.resize(cols, rows)

    def stop(self) -> None:
        self._running = False
        if self.backend:
            self.backend.close()


# ── Agent Pane ─────────────────────────────────────────────────────────────────


class AgentPane(ctk.CTkFrame):
    def __init__(self, master: tk.Widget, pane_id: str, title: str,
                 startup_command: str, app: "TriptychApp") -> None:
        super().__init__(master, fg_color=PANE_BG, border_color=BORDER_NORMAL,
                         border_width=2, corner_radius=6)
        self.pane_id = pane_id
        self.title_text = title
        self.startup_command = startup_command
        self.app = app
        self._shell_command: Optional[str] = None
        self._startup_after_id: Optional[str] = None
        self._startup_flush_after_id: Optional[str] = None
        self._startup_ready = False
        self._pending_terminal_submits: list[str] = []
        self.session: Optional[ShellSession] = None
        self._cwd: Optional[str] = None
        self._data_queue: Queue[str] = Queue()

        # Virtual terminal — initial size, will be recalculated on first render
        self._term_cols = 80
        self._term_rows = 24
        self._screen = pyte.HistoryScreen(
            self._term_cols, self._term_rows, history=5000
        )
        self._screen.set_mode(pyte.modes.LNM)
        self._stream = pyte.Stream(self._screen)
        self._prev_render = ""
        self._fallback_lines: list[str] = []
        self._fallback_carry = ""
        self._last_output_event_signature = ""
        self._last_output_event_ts = 0.0

        # ── Title label (clickable — opens assign menu) ──────────────────
        self.title_label = ctk.CTkLabel(
            self, text=f"{title} \u25be", height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TITLE_COLOR, fg_color=TITLE_BG, corner_radius=4,
            cursor="hand2",
        )
        self.title_label.pack(fill="x", padx=4, pady=(4, 2))

        # ── Task strip (hidden until a task is attached) ─────────────────
        self._attached_task_id: Optional[int] = None

        self.task_strip = ctk.CTkFrame(
            self, fg_color=STRIP_BG, height=30, corner_radius=3,
            border_color=STRIP_BORDER, border_width=1,
        )
        # Do NOT pack yet — shown only when a task is attached.

        self._strip_info_label = ctk.CTkLabel(
            self.task_strip, text="", height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_COLOR, fg_color="transparent", anchor="w",
        )
        self._strip_info_label.pack(side="left", padx=(6, 4), fill="x", expand=True)

        self._strip_badge = ctk.CTkLabel(
            self.task_strip, text="todo", height=22, width=80,
            font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
            text_color="#aaaaaa", fg_color="#2a4a3a", corner_radius=3,
        )
        self._strip_badge.pack(side="left", padx=(0, 4))

        self._strip_run_btn = ctk.CTkButton(
            self.task_strip, text="\u25b6 Run", width=52, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, corner_radius=3,
            command=self._on_strip_run,
        )
        self._strip_run_btn.pack(side="left", padx=(0, 2))

        self._strip_pause_btn = ctk.CTkButton(
            self.task_strip, text="\u23f8 Pause", width=58, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=self._on_strip_pause,
        )
        # Pause starts hidden; shown only when in_progress

        self._strip_done_btn = ctk.CTkButton(
            self.task_strip, text="\u2713 Done", width=52, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=self._on_strip_done,
        )
        self._strip_done_btn.pack(side="left", padx=(0, 2))

        self._strip_detach_btn = ctk.CTkButton(
            self.task_strip, text="x", width=24, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color="#ff6666", corner_radius=3,
            command=self._on_strip_detach,
        )
        self._strip_detach_btn.pack(side="left", padx=(0, 4))

        # ── Project strip (hidden until a project is attached) ────────────
        self._attached_project_id: Optional[int] = None

        self.project_strip = ctk.CTkFrame(
            self, fg_color=PROJECT_STRIP_BG, height=30, corner_radius=3,
            border_color=PROJECT_STRIP_BORDER, border_width=1,
        )

        self._proj_strip_info_label = ctk.CTkLabel(
            self.project_strip, text="", height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_COLOR, fg_color="transparent", anchor="w",
        )
        self._proj_strip_info_label.pack(side="left", padx=(6, 4), fill="x", expand=True)

        self._proj_strip_badge = ctk.CTkLabel(
            self.project_strip, text="active", height=22, width=80,
            font=ctk.CTkFont(family=FONT_FAMILY, size=9, weight="bold"),
            text_color="#58ff8a", fg_color="#1a4a2e", corner_radius=3,
        )
        self._proj_strip_badge.pack(side="left", padx=(0, 4))

        self._proj_strip_enter_btn = ctk.CTkButton(
            self.project_strip, text="\u25b6 Start", width=62, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, corner_radius=3,
            command=self._on_proj_strip_enter,
        )
        self._proj_strip_enter_btn.pack(side="left", padx=(0, 2))

        self._proj_strip_log_btn = ctk.CTkButton(
            self.project_strip, text="\u25b6 Run", width=56, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=self._on_proj_strip_log,
        )
        self._proj_strip_log_btn.pack(side="left", padx=(0, 2))

        self._proj_strip_save_btn = ctk.CTkButton(
            self.project_strip, text="Save", width=48, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color="#2a4a6e", hover_color="#35608a",
            text_color=TITLE_COLOR, corner_radius=3,
            command=self._on_proj_strip_save,
        )
        # Save starts hidden; shown after Log

        self._proj_strip_detach_btn = ctk.CTkButton(
            self.project_strip, text="x", width=24, height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color="#ff6666", corner_radius=3,
            command=self._on_proj_strip_detach,
        )
        self._proj_strip_detach_btn.pack(side="left", padx=(0, 4))

        # ── Output text area ──────────────────────────────────────────────
        self.output = tk.Text(
            self, bg=PANE_BG, fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
            font=(FONT_FAMILY, FONT_SIZE), wrap="none", relief="flat",
            borderwidth=0, highlightthickness=0, padx=6, pady=4,
            cursor="xterm",
        )
        self.output.pack(fill="both", expand=True, padx=4, pady=(0, 2))
        self.output.config(state="disabled")

        # Scrollbar
        self.scrollbar = ctk.CTkScrollbar(self.output, command=self.output.yview)
        self.output.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        # ── Toolbar: folder picker + slash + agent selector ───────────────
        self.toolbar = ctk.CTkFrame(self, fg_color="transparent", height=32)
        self.toolbar.pack(fill="x", padx=4, pady=(0, 2))

        self.folder_btn = ctk.CTkButton(
            self.toolbar, text="Folder", width=70, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=4,
            command=self._pick_folder,
        )
        self.folder_btn.pack(side="left", padx=(0, 4))

        self.slash_btn = ctk.CTkButton(
            self.toolbar, text="/", width=32, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TITLE_COLOR, corner_radius=4,
            command=self._show_slash_menu,
        )
        self.slash_btn.pack(side="left", padx=(0, 4))

        self.close_pane_btn = ctk.CTkButton(
            self.toolbar, text="x", width=32, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TITLE_COLOR, corner_radius=4,
            command=self._remove_pane_from_ui,
        )
        self.close_pane_btn.pack(side="left", padx=(0, 4))


        self.folder_label = ctk.CTkLabel(
            self.toolbar, text="~", height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color="#6a9a7a", fg_color="transparent", anchor="w",
        )
        self.folder_label.pack(side="left", padx=(0, 8), fill="x", expand=True)

        self._agent_var = ctk.StringVar(value=startup_command)
        self.agent_menu = ctk.CTkOptionMenu(
            self.toolbar, values=AGENT_COMMANDS, variable=self._agent_var,
            width=120, height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            text_color=TEXT_COLOR, corner_radius=4,
            dropdown_fg_color=PANE_BG, dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
            command=self._on_agent_changed,
        )
        self.agent_menu.pack(side="right")

        # ── Prompt input area ─────────────────────────────────────────────
        self.prompt_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.prompt_frame.pack(fill="x", padx=4, pady=(0, 4))

        self.prompt_input = ctk.CTkTextbox(
            self.prompt_frame, height=60,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
            fg_color=INPUT_BG, text_color=TEXT_COLOR,
            border_color=INPUT_BORDER, border_width=1,
            corner_radius=4, wrap="word",
        )
        self.prompt_input.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.prompt_input.bind("<Control-Return>", self._on_send_prompt)
        self.prompt_input.bind("<Control-KP_Enter>", self._on_send_prompt)
        self.prompt_input.bind("<KeyRelease>", self._on_prompt_key)

        self.send_btn = ctk.CTkButton(
            self.prompt_frame, text="Send\n\u23ce", width=50, height=60,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, corner_radius=4,
            command=self._send_prompt,
        )
        self.send_btn.pack(side="right")

        # ── Bindings ──────────────────────────────────────────────────────
        self.output.bind("<Key>", self._on_key)
        self.output.bind("<Button-1>", self._on_click)
        self.output.bind("<Button-3>", self._on_right_click)
        self.output.bind("<Configure>", self._on_output_resize)
        self.title_label.bind("<Button-1>", lambda e: self._show_assign_popup())
        self.bind("<Button-1>", self._on_click)

        # ── Render loop (poll queue every 50ms) ───────────────────────────
        self._poll_id: Optional[str] = None
        self._start_poll()

    def _build_title_text(self) -> str:
        agent = self.startup_command.upper()
        if self._attached_task_id:
            task = self.app._store.get_task(self._attached_task_id)
            if task:
                return f"{agent} | #{task.id} {task.title[:30]} \u25be"
        if self._attached_project_id:
            project = self.app._store.get_project(self._attached_project_id)
            if project:
                return f"{agent} | {project.name[:30]} \u25be"
        return f"{agent} \u25be"

    def _refresh_title(self) -> None:
        self.title_label.configure(text=self._build_title_text())

    # ── Border color by binding type ──────────────────────────────────

    def _current_border_color(self) -> str:
        if self._attached_project_id:
            return BORDER_PROJECT
        if self._attached_task_id:
            return BORDER_TASK
        return BORDER_NORMAL

    # ── Render loop ───────────────────────────────────────────────────────

    def _start_poll(self) -> None:
        self._poll_id = self.after(50, self._poll_output)

    def _poll_output(self) -> None:
        dirty = False
        chunks_for_event: list[str] = []
        try:
            while True:
                data = self._data_queue.get_nowait()
                chunks_for_event.append(data)
                try:
                    self._stream.feed(data)
                except Exception:
                    # Keep UI alive even if parser hits unsupported escape sequences.
                    self._append_fallback_text(data)
                dirty = True
        except Empty:
            pass

        if chunks_for_event:
            self._record_terminal_output_event("".join(chunks_for_event))

        if dirty:
            self._render_display()

        self._poll_id = self.after(50, self._poll_output)

    def _record_terminal_output_event(self, text: str) -> None:
        if not text:
            return
        cleaned = ANSI_RE.sub("", text)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = "".join(
            ch for ch in cleaned
            if ch == "\n" or ch == "\t" or ord(ch) >= 32
        )
        if not cleaned.strip():
            return
        if _is_terminal_repaint_noise(cleaned):
            return
        signature = self._terminal_output_signature(cleaned)
        if not signature:
            return
        now = time.monotonic()
        # Avoid event spam from TUI repaint loops (e.g. "you can type message").
        if signature == self._last_output_event_signature and (now - self._last_output_event_ts) < 20.0:
            return
        self._last_output_event_signature = signature
        self._last_output_event_ts = now
        self.app._record_event(
            self.pane_id,
            "terminal_output",
            {"text": cleaned},
            agent=self.startup_command,
        )

    def _terminal_output_signature(self, text: str) -> str:
        return _normalize_terminal_signature(text)

    def _history_line_to_text(self, line: object) -> str:
        if isinstance(line, dict):
            cols = self._screen.columns
            return "".join(
                line[x].data if x in line else " "
                for x in range(cols)
            ).rstrip()
        return str(line).rstrip()

    def _append_fallback_text(self, data: str) -> None:
        cleaned = ANSI_RE.sub("", data)
        cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
        cleaned = "".join(
            ch for ch in cleaned
            if ch == "\n" or ch == "\t" or ord(ch) >= 32
        )
        if not cleaned:
            return

        parts = (self._fallback_carry + cleaned).split("\n")
        self._fallback_carry = parts.pop() if parts else ""
        for line in parts:
            self._fallback_lines.append(line)
        if len(self._fallback_lines) > 5000:
            self._fallback_lines = self._fallback_lines[-5000:]

    def _snapshot_terminal_lines(self) -> list[str]:
        history_lines = [
            self._history_line_to_text(line)
            for line in self._screen.history.top
        ]
        display_lines = [line.rstrip() for line in self._screen.display]
        lines = history_lines + display_lines
        if self._fallback_lines:
            lines.extend(self._fallback_lines)
        if self._fallback_carry:
            lines.append(self._fallback_carry)
        return lines

    def _render_display(self) -> None:
        # Build display from VT history + current visible terminal.
        lines = self._snapshot_terminal_lines()

        # Strip trailing empty lines
        while lines and lines[-1] == "":
            lines.pop()

        rendered = "\n".join(lines)
        if rendered == self._prev_render:
            return
        self._prev_render = rendered

        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        if rendered:
            self.output.insert("1.0", rendered)
        self.output.see("end")
        self.output.config(state="disabled")

    # ── Resize sync ──────────────────────────────────────────────────────

    def _on_output_resize(self, event: tk.Event) -> None:
        font = tkinter.font.Font(family=FONT_FAMILY, size=FONT_SIZE)
        char_w = font.measure("M")
        char_h = font.metrics("linespace")
        if char_w <= 0 or char_h <= 0:
            return
        cols = max(20, event.width // char_w)
        rows = max(5, event.height // char_h)
        if cols == self._term_cols and rows == self._term_rows:
            return
        self._term_cols = cols
        self._term_rows = rows
        # Resize virtual terminal
        try:
            self._screen.resize(rows, cols)
        except Exception:
            pass
        # Resize PTY so the process knows the new dimensions
        if self.session:
            self.session.resize(cols, rows)

    # ── Click / focus ─────────────────────────────────────────────────────

    def _on_click(self, _event: tk.Event) -> None:
        self.focus_pane()

    def _on_right_click(self, event: tk.Event) -> None:
        menu = tk.Menu(
            self, tearoff=0,
            bg=PANE_BG, fg=TEXT_COLOR, activebackground=BUTTON_HOVER,
            activeforeground=TITLE_COLOR, font=(FONT_FAMILY, FONT_SIZE),
            bd=1, relief="solid",
        )
        menu.add_command(label="Copy", command=self._copy_selection)
        menu.add_command(label="Select All", command=self._select_all)
        menu.add_separator()
        menu.add_command(label="Copy All Output", command=self._copy_all)
        menu.tk_popup(event.x_root, event.y_root)

    def _copy_selection(self) -> None:
        try:
            text = self.output.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _select_all(self) -> None:
        self.output.tag_add(tk.SEL, "1.0", tk.END)

    def _copy_all(self) -> None:
        text = self.output.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)

    def _update_folder_label(self) -> None:
        folder = self._cwd
        if not folder:
            self.folder_label.configure(text="~")
            return

        short = folder
        home = os.path.expanduser("~")
        if folder.startswith(home):
            short = "~" + folder[len(home):]
        self.folder_label.configure(text=short)

    # ── Toolbar actions ───────────────────────────────────────────────────

    def _pick_folder(self) -> None:
        initial = self._cwd or os.path.expanduser("~")
        folder = filedialog.askdirectory(initialdir=initial)
        if folder:
            self._cwd = folder
            self._update_folder_label()
            if self.session and self.startup_command:
                self.restart_session()
                self.app._status_note = f"{self.pane_id.upper()}: restarted in {folder}"
                self.app.refresh_status()
            elif self.session:
                self.send_text(f"cd \"{folder}\"\r")

    def _show_slash_menu(self) -> None:
        cmds = SLASH_COMMANDS.get(self.startup_command, SLASH_COMMANDS["_default"])
        menu = tk.Menu(
            self, tearoff=0,
            bg=PANE_BG, fg=TEXT_COLOR, activebackground=BUTTON_HOVER,
            activeforeground=TITLE_COLOR, font=(FONT_FAMILY, FONT_SIZE),
            bd=1, relief="solid",
        )
        for cmd, desc in cmds:
            menu.add_command(
                label=f"{cmd:12s}  {desc}",
                command=lambda c=cmd: self._send_slash(c),
            )
        x = self.slash_btn.winfo_rootx()
        y = self.slash_btn.winfo_rooty() - len(cmds) * 22
        menu.tk_popup(x, y)

    def _send_slash(self, cmd: str) -> None:
        self._submit_terminal_input(cmd, source="slash_menu")
        self.app._status_note = f"{self.pane_id.upper()}: {cmd}"
        self.app.refresh_status()

    def _remove_pane_from_ui(self) -> None:
        self.focus_pane()
        self.app._remove_pane(self.pane_id)

    def _on_agent_changed(self, choice: str) -> None:
        prev = self.startup_command
        self.startup_command = choice
        self._refresh_title()
        if self.session and prev != choice:
            self.restart_session()
            self.app._status_note = f"{self.pane_id.upper()} \u2192 {choice} (restarted)"
        else:
            self.app._status_note = f"{self.pane_id.upper()} \u2192 {choice}"
        self.app.refresh_status()

    # ── Task strip controls ───────────────────────────────────────────────

    def show_task_strip(self, task: TaskRecord) -> None:
        self._attached_task_id = task.id
        display = f"#{task.id}: {task.title}"
        if len(display) > 40:
            display = display[:37] + "..."
        self._strip_info_label.configure(text=display)
        self._update_strip_badge(task.status)
        self._update_strip_buttons(task.status)
        self._refresh_title()
        self.task_strip.pack(fill="x", padx=4, pady=(0, 2), after=self.title_label)
        self._update_border()

    def hide_task_strip(self) -> None:
        self._attached_task_id = None
        self.task_strip.pack_forget()
        self._refresh_title()
        self._update_border()

    def _update_strip_badge(self, status: str) -> None:
        bg, fg = STATUS_BADGE_COLORS.get(status, ("#2a4a3a", "#aaaaaa"))
        self._strip_badge.configure(text=status, fg_color=bg, text_color=fg)

    def _update_strip_buttons(self, status: str) -> None:
        if status == "in_progress":
            self._strip_pause_btn.pack(side="left", padx=(0, 2),
                                       after=self._strip_run_btn)
        else:
            self._strip_pause_btn.pack_forget()

        if status == "done":
            self._strip_run_btn.configure(state="disabled")
            self._strip_done_btn.configure(state="disabled")
        else:
            self._strip_run_btn.configure(state="normal")
            self._strip_done_btn.configure(state="normal")

    def _on_strip_run(self) -> None:
        if not self._attached_task_id:
            return
        task = self.app._store.get_task(self._attached_task_id)
        if not task:
            self.app._status_note = f"Task #{self._attached_task_id} not found."
            self.app.refresh_status()
            self._on_strip_detach()
            return

        self.app._record_event(
            self.pane_id,
            "ui_task_run_clicked",
            {"task_id": task.id, "task_title": task.title},
            task_id=task.id,
            agent=self.startup_command,
        )

        folder = task.folder or self._cwd or "(not set)"
        parts = [f"Working directory: {folder}"]
        parts.append(f"Task: {task.title}")
        if task.goal.strip():
            parts.append(f"Goal: {task.goal}")
        if task.dod.strip():
            parts.append(f"Definition of Done: {task.dod}")
        parts.append("")
        parts.append("Begin working on this task.")
        prompt = "\n".join(parts)

        self._submit_terminal_input(prompt, source="task_strip_run")

        prev_status = task.status
        self.app._store.update_task_status(task.id, "in_progress")
        self.app._record_event(
            self.pane_id,
            "task_status_changed",
            {"task_id": task.id, "from": prev_status, "to": "in_progress", "source": "task_strip_run"},
            task_id=task.id,
            agent=self.startup_command,
        )
        self._update_strip_badge("in_progress")
        self._update_strip_buttons("in_progress")
        self.app._refresh_task_board()
        self.app._status_note = f"Task #{task.id} sent to {self.pane_id.upper()}"
        self.app.refresh_status()

    def _on_strip_pause(self) -> None:
        if not self._attached_task_id:
            return
        task = self.app._store.get_task(self._attached_task_id)
        if not task:
            self._on_strip_detach()
            return
        prev_status = task.status
        self.app._store.update_task_status(self._attached_task_id, "paused")
        self.app._record_event(
            self.pane_id,
            "task_status_changed",
            {"task_id": task.id, "from": prev_status, "to": "paused", "source": "task_strip_pause"},
            task_id=task.id,
            agent=self.startup_command,
        )
        self._update_strip_badge("paused")
        self._update_strip_buttons("paused")
        self.app._refresh_task_board()
        self.app._status_note = f"Task #{self._attached_task_id} paused"
        self.app.refresh_status()

    def _on_strip_done(self) -> None:
        if not self._attached_task_id:
            return
        task = self.app._store.get_task(self._attached_task_id)
        if not task:
            self._on_strip_detach()
            return
        prev_status = task.status
        self.app._store.update_task_status(self._attached_task_id, "done")
        self.app._record_event(
            self.pane_id,
            "task_status_changed",
            {"task_id": task.id, "from": prev_status, "to": "done", "source": "task_strip_done"},
            task_id=task.id,
            agent=self.startup_command,
        )
        self._update_strip_badge("done")
        self._update_strip_buttons("done")
        self.app._refresh_task_board()
        self.app._status_note = f"Task #{self._attached_task_id} marked done"
        self.app.refresh_status()

    def _on_strip_detach(self) -> None:
        task_id = self._attached_task_id
        self.hide_task_strip()
        self.app._pane_task_bindings.pop(self.pane_id, None)
        self.app._store.clear_pane_binding(self.pane_id)
        self.app._record_event(
            self.pane_id,
            "task_detached",
            {"task_id": task_id, "source": "task_strip_detach"},
            task_id=task_id or 0,
            agent=self.startup_command,
        )
        self.app._status_note = f"Detached task #{task_id} from {self.pane_id.upper()}"
        self.app.refresh_status()

    # ── Project strip controls ──────────────────────────────────────────

    def show_project_strip(self, project: ProjectRecord) -> None:
        self.hide_task_strip()
        self._attached_project_id = project.id
        display = f"P#{project.id}: {project.name}"
        if len(display) > 40:
            display = display[:37] + "..."
        self._proj_strip_info_label.configure(text=display)
        self._update_proj_strip_badge(project.status)
        self._proj_strip_save_btn.pack_forget()
        self._refresh_title()
        self.project_strip.pack(fill="x", padx=4, pady=(0, 2),
                                after=self.title_label)
        self._update_border()

    def hide_project_strip(self) -> None:
        self._attached_project_id = None
        self.project_strip.pack_forget()
        self._proj_strip_save_btn.pack_forget()
        self._refresh_title()
        self._update_border()

    def _update_proj_strip_badge(self, status: str) -> None:
        bg, fg = PROJECT_STATUS_BADGE_COLORS.get(status, ("#2a4a3a", "#aaaaaa"))
        self._proj_strip_badge.configure(text=status, fg_color=bg, text_color=fg)

    def _on_proj_strip_enter(self) -> None:
        if not self._attached_project_id:
            return
        project = self.app._store.get_project(self._attached_project_id)
        if not project:
            self.app._status_note = f"Project #{self._attached_project_id} not found."
            self.app.refresh_status()
            self._on_proj_strip_detach()
            return

        self.app._record_event(
            self.pane_id,
            "ui_project_start_clicked",
            {"project_id": project.id, "project_name": project.name},
            agent=self.startup_command,
        )

        context_path = os.path.join(project.folder, "PROJECT_CONTEXT.md")
        if not os.path.isfile(context_path):
            self.app._status_note = f"No PROJECT_CONTEXT.md in {project.folder}"
            self.app.refresh_status()
            return

        try:
            with open(context_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            self.app._status_note = f"Error reading context: {exc}"
            self.app.refresh_status()
            return

        prompt = (
            f"Project: {project.name}\n"
            f"Folder: {project.folder}\n\n"
            "Here is the current project context document:\n\n"
            f"{content}\n\n"
            "Continue working on this project based on the context above."
        )
        self._submit_terminal_input(prompt, source="project_strip_start")
        self.app._status_note = f"Project context sent to {self.pane_id.upper()}"
        self.app.refresh_status()

    def _on_proj_strip_log(self) -> None:
        if not self._attached_project_id:
            return
        project = self.app._store.get_project(self._attached_project_id)
        if not project:
            self._on_proj_strip_detach()
            return

        self.app._record_event(
            self.pane_id,
            "ui_project_log_clicked",
            {"project_id": project.id, "project_name": project.name},
            agent=self.startup_command,
        )

        prompt = (
            "Please summarize what you accomplished in this iteration. "
            "Format your response as:\n"
            "Done: <what was completed>\n"
            "Next: <what should be done next>\n\n"
            "Keep it concise (3-5 bullet points each)."
        )
        self._submit_terminal_input(prompt, source="project_strip_log")
        self._proj_strip_save_btn.pack(side="left", padx=(0, 2),
                                       after=self._proj_strip_log_btn)
        self.app._status_note = f"Requested iteration log from {self.pane_id.upper()}"
        self.app.refresh_status()

    def _on_proj_strip_save(self) -> None:
        if not self._attached_project_id:
            return
        project = self.app._store.get_project(self._attached_project_id)
        if not project:
            self._on_proj_strip_detach()
            return

        context_path = os.path.join(project.folder, "PROJECT_CONTEXT.md")
        output_text = self.grab_context(30)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        agent_name = self.startup_command or "unknown"

        entry = (
            f"\n### {now} -- {agent_name}\n"
            f"{output_text}\n"
        )

        try:
            existing = ""
            if os.path.isfile(context_path):
                with open(context_path, "r", encoding="utf-8") as f:
                    existing = f.read()

            marker = "## Iteration Log"
            if marker in existing:
                idx = existing.index(marker) + len(marker)
                updated = existing[:idx] + "\n" + entry + existing[idx:]
            else:
                updated = existing + f"\n{marker}\n{entry}"

            with open(context_path, "w", encoding="utf-8") as f:
                f.write(updated)

            self.app._record_event(
                self.pane_id,
                "project_iteration_saved",
                {"project_id": project.id, "path": context_path},
                agent=self.startup_command,
            )
            self.app._status_note = f"Iteration saved to PROJECT_CONTEXT.md"
        except Exception as exc:
            self.app._record_event(
                self.pane_id,
                "project_iteration_save_failed",
                {"project_id": project.id, "path": context_path, "error": str(exc)},
                agent=self.startup_command,
            )
            self.app._status_note = f"Error saving iteration: {exc}"

        self._proj_strip_save_btn.pack_forget()
        self.app.refresh_status()

    def _on_proj_strip_detach(self) -> None:
        project_id = self._attached_project_id
        self.hide_project_strip()
        self.app._pane_project_bindings.pop(self.pane_id, None)
        self.app._store.clear_pane_project_binding(self.pane_id)
        self.app._record_event(
            self.pane_id,
            "project_detached",
            {"project_id": project_id, "source": "project_strip_detach"},
            agent=self.startup_command,
        )
        self.app._status_note = f"Detached project #{project_id} from {self.pane_id.upper()}"
        self.app.refresh_status()

    # ── Assign popup (tasks + projects) ──────────────────────────────────

    def _show_assign_popup(self) -> None:
        self.focus_pane()
        tasks = self.app._store.list_tasks()
        projects = self.app._store.list_projects()

        if not tasks and not projects:
            self.app._status_note = "No tasks or projects. Create one first."
            self.app.refresh_status()
            return

        menu = tk.Menu(
            self, tearoff=0,
            bg=PANE_BG, fg=TEXT_COLOR, activebackground=BUTTON_HOVER,
            activeforeground=TITLE_COLOR, font=(FONT_FAMILY, FONT_SIZE),
            bd=1, relief="solid",
        )

        if tasks:
            menu.add_command(label="\u2500\u2500 Tasks \u2500\u2500", state="disabled")
            for task in tasks:
                marker = {"todo": "\u2022", "in_progress": "\u25b6",
                          "paused": "\u23f8", "blocked": "!", "done": "\u2713"
                          }.get(task.status, "?")
                label = f"{marker} #{task.id}: {task.title[:40]}"
                menu.add_command(
                    label=label,
                    command=lambda t_id=task.id: self.app._attach_task_to_pane(
                        self.pane_id, t_id
                    ),
                )

        if projects:
            if tasks:
                menu.add_separator()
            menu.add_command(label="\u2500\u2500 Projects \u2500\u2500", state="disabled")
            for proj in projects:
                marker = {"active": "\u25cf", "paused": "\u23f8",
                          "archived": "\u2610"}.get(proj.status, "?")
                label = f"{marker} P#{proj.id}: {proj.name[:40]}"
                menu.add_command(
                    label=label,
                    command=lambda p_id=proj.id: self.app._attach_project_to_pane(
                        self.pane_id, p_id
                    ),
                )

        if self._attached_task_id or self._attached_project_id:
            menu.add_separator()
            if self._attached_task_id:
                menu.add_command(label="Detach current task",
                                 command=self._on_strip_detach)
            if self._attached_project_id:
                menu.add_command(label="Detach current project",
                                 command=self._on_proj_strip_detach)

        x = self.title_label.winfo_rootx()
        y = self.title_label.winfo_rooty() + self.title_label.winfo_height()
        menu.tk_popup(x, y)

    # ── Prompt input ──────────────────────────────────────────────────────

    def _on_prompt_key(self, event: tk.Event) -> None:
        text = self.prompt_input.get("1.0", "end-1c")
        if text == "/":
            cmds = SLASH_COMMANDS.get(self.startup_command, SLASH_COMMANDS["_default"])
            menu = tk.Menu(
                self, tearoff=0,
                bg=PANE_BG, fg=TEXT_COLOR, activebackground=BUTTON_HOVER,
                activeforeground=TITLE_COLOR, font=(FONT_FAMILY, FONT_SIZE),
                bd=1, relief="solid",
            )
            for cmd, desc in cmds:
                menu.add_command(
                    label=f"{cmd:12s}  {desc}",
                    command=lambda c=cmd: self._pick_slash_from_prompt(c),
                )
            x = self.prompt_input.winfo_rootx() + 10
            y = self.prompt_input.winfo_rooty() - len(cmds) * 22
            menu.tk_popup(x, y)

    def _pick_slash_from_prompt(self, cmd: str) -> None:
        self.prompt_input.delete("1.0", "end")
        self._submit_terminal_input(cmd, source="prompt_slash")
        self.app._status_note = f"{self.pane_id.upper()}: {cmd}"
        self.app.refresh_status()

    def _on_send_prompt(self, _event: tk.Event = None) -> str:
        self._send_prompt()
        return "break"

    def _paste_to_terminal(self, text: str, submit: bool = True) -> None:
        """Send text as bracketed paste to avoid per-line shell execution."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.send_text("\x1b[200~" + normalized + "\x1b[201~")
        if submit:
            self.send_text("\r")

    def _send_direct_text(self, text: str) -> None:
        """Send plain text bytes as if user typed in terminal input."""
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        self.send_text(normalized)

    def _submit_terminal_input_now(self, text: str) -> None:
        agent = (self.startup_command or "").strip().lower()
        if text.strip().startswith("/") or agent in {"claude", "gemini"}:
            # Slash commands and these TUIs behave best with direct typed input.
            self._send_direct_text(text)
            # A small delay helps the TUI separate input from submit.
            self.after(50, lambda: self.send_text("\r"))
        else:
            self._paste_to_terminal(text, submit=True)

    def _flush_pending_terminal_submits(self) -> None:
        self._startup_flush_after_id = None
        if not self.session:
            return
        if self.startup_command and not self._startup_ready:
            return
        pending = self._pending_terminal_submits[:]
        self._pending_terminal_submits.clear()
        for text in pending:
            self._submit_terminal_input_now(text)

    def _submit_terminal_input(self, text: str, source: str = "terminal_input") -> None:
        stripped = text.strip()
        if not stripped:
            return
        self.app._record_event(
            self.pane_id,
            "terminal_input_submitted",
            {"text": stripped, "source": source},
            agent=self.startup_command,
        )
        if not self.session:
            if self._shell_command:
                self.start(self._shell_command)
            else:
                self.app._record_event(
                    self.pane_id,
                    "terminal_input_dropped",
                    {"text": stripped, "source": source, "reason": "no_session"},
                    agent=self.startup_command,
                )
                return
        if self.startup_command and not self._startup_ready:
            self._pending_terminal_submits.append(text)
            if self._startup_after_id is None and self.session:
                self._startup_after_id = self.after(50, self._run_startup_command)
            return
        self._submit_terminal_input_now(text)

    def _send_prompt(self) -> None:
        text = self.prompt_input.get("1.0", "end-1c")
        if not text.strip():
            return

        self._submit_terminal_input(text, source="prompt_input")
        self.prompt_input.delete("1.0", "end")

    def _run_startup_command(self) -> None:
        self._startup_after_id = None
        if not self.session or not self.startup_command:
            return
        if self._cwd:
            self.session.send(f"cd \"{self._cwd}\"\r")
        self.session.send(self.startup_command + "\r")
        self._startup_ready = True
        if self._startup_flush_after_id:
            self.after_cancel(self._startup_flush_after_id)
        # Give CLI a short moment to initialize before sending buffered prompts.
        self._startup_flush_after_id = self.after(350, self._flush_pending_terminal_submits)

    def _reset_terminal_buffers(self) -> None:
        self._screen = pyte.HistoryScreen(
            self._term_cols, self._term_rows, history=5000
        )
        self._screen.set_mode(pyte.modes.LNM)
        self._stream = pyte.Stream(self._screen)
        self._prev_render = ""
        self._fallback_lines = []
        self._fallback_carry = ""
        self._last_output_event_signature = ""
        self._last_output_event_ts = 0.0

        self.output.config(state="normal")
        self.output.delete("1.0", "end")
        self.output.config(state="disabled")

    def restart_session(self) -> None:
        if not self._shell_command:
            return
        self.start(self._shell_command)

    # ── Focus ─────────────────────────────────────────────────────────────

    def focus_pane(self) -> None:
        self.output.focus_set()
        self.configure(border_color=BORDER_FOCUSED)
        self.app.on_pane_focused(self.pane_id)

    def blur_pane(self) -> None:
        self.configure(border_color=self._current_border_color())

    def _update_border(self) -> None:
        is_focused = (self.app._focused_id == self.pane_id)
        if is_focused:
            self.configure(border_color=BORDER_FOCUSED)
        else:
            self.configure(border_color=self._current_border_color())

    # ── Key handling ──────────────────────────────────────────────────────

    def _on_key(self, event: tk.Event) -> str:
        ctrl = bool(event.state & 0x4)

        # Ctrl+C → copy selection
        if ctrl and event.keysym.lower() == "c":
            self._copy_selection()
            return "break"

        # Ctrl+A → select all
        if ctrl and event.keysym.lower() == "a":
            self._select_all()
            return "break"

        # Let the app handle global bindings
        if self.app.handle_global_key(event):
            return "break"

        # Forward to PTY
        self._forward_key(event)
        return "break"

    def _forward_key(self, event: tk.Event) -> bool:
        key_map = {
            "Return": "\r",
            "BackSpace": "\x7f",
            "Delete": "\x1b[3~",
            "Up": "\x1b[A",
            "Down": "\x1b[B",
            "Left": "\x1b[D",
            "Right": "\x1b[C",
            "Home": "\x1b[H",
            "End": "\x1b[F",
            "Prior": "\x1b[5~",
            "Next": "\x1b[6~",
            "Escape": "\x1b",
            "Tab": "\t",
        }

        if event.keysym in key_map:
            self.send_text(key_map[event.keysym])
            return True

        # Ctrl+key (except c/a which are handled above)
        if event.state & 0x4 and event.keysym != "??":
            ch = event.keysym.lower()
            if len(ch) == 1 and "a" <= ch <= "z":
                self.send_text(chr(ord(ch) - 96))
                return True

        # Regular character
        if event.char and len(event.char) == 1 and ord(event.char) >= 32:
            self.send_text(event.char)
            return True

        return False

    # ── Session lifecycle ─────────────────────────────────────────────────

    def start(self, shell_command: str) -> None:
        self._shell_command = shell_command
        if self._startup_after_id:
            self.after_cancel(self._startup_after_id)
            self._startup_after_id = None
        if self._startup_flush_after_id:
            self.after_cancel(self._startup_flush_after_id)
            self._startup_flush_after_id = None
        if self.session:
            self.session.stop()

        self._pending_terminal_submits.clear()
        self._startup_ready = not bool(self.startup_command)
        self._reset_terminal_buffers()
        self.session = ShellSession(
            self, shell_command, self._term_cols, self._term_rows
        )
        self.session.start()
        if self.startup_command:
            # Send startup command shortly after PTY boot to avoid early-drop input.
            self._startup_after_id = self.after(120, self._run_startup_command)

    def stop(self) -> None:
        if self._startup_after_id:
            self.after_cancel(self._startup_after_id)
            self._startup_after_id = None
        if self._startup_flush_after_id:
            self.after_cancel(self._startup_flush_after_id)
            self._startup_flush_after_id = None
        if self._poll_id:
            self.after_cancel(self._poll_id)
        if self.session:
            self.session.stop()

    def send_text(self, text: str) -> None:
        if self.session:
            self.session.send(text)

    def grab_context(self, lines: int = 50) -> str:
        return "\n".join(self._snapshot_terminal_lines()[-lines:]).strip()


# ── Chat Mode Widgets ─────────────────────────────────────────────────────────

SIDEBAR_WIDTH = 300
PREVIEW_HEIGHT = 110
EXPLORER_WIDTH = 320


class ChatSidebar(ctk.CTkFrame):
    """Left sidebar for chat mode — lists Projects and Tasks in two sections."""

    def __init__(self, master: tk.Widget, app: "TriptychApp") -> None:
        super().__init__(master, fg_color=PANE_BG, border_color=INPUT_BORDER,
                         border_width=1, width=SIDEBAR_WIDTH)
        self.app = app
        self.pack_propagate(False)

        # ── Panes section (grid agent windows) ──
        pane_header = ctk.CTkFrame(self, fg_color=TITLE_BG, height=34)
        pane_header.pack(fill="x", padx=4, pady=(4, 0))
        pane_header.pack_propagate(False)
        ctk.CTkLabel(
            pane_header, text="Panes",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            pane_header, text="- Remove", width=76, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=self._on_remove_pane_clicked,
        ).pack(side="right", padx=(2, 4))
        ctk.CTkButton(
            pane_header, text="+ New", width=60, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=self._on_add_pane_clicked,
        ).pack(side="right", padx=(4, 0))

        self._pane_scroll = ctk.CTkScrollableFrame(
            self, fg_color=PANE_BG, height=100,
        )
        self._pane_scroll.pack(fill="x", padx=4, pady=(2, 4))

        # ── Projects section ──
        proj_header = ctk.CTkFrame(self, fg_color=TITLE_BG, height=34)
        proj_header.pack(fill="x", padx=4, pady=(4, 0))
        proj_header.pack_propagate(False)
        ctk.CTkLabel(
            proj_header, text="Projects",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            proj_header, text="+ New", width=60, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=app._show_new_project_dialog,
        ).pack(side="right", padx=4)

        self._proj_scroll = ctk.CTkScrollableFrame(
            self, fg_color=PANE_BG, height=200,
        )
        self._proj_scroll.pack(fill="x", padx=4, pady=(2, 4))

        # ── Tasks section ──
        task_header = ctk.CTkFrame(self, fg_color=TITLE_BG, height=34)
        task_header.pack(fill="x", padx=4, pady=(4, 0))
        task_header.pack_propagate(False)
        ctk.CTkLabel(
            task_header, text="Tasks",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            task_header, text="+ New", width=60, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, corner_radius=3,
            command=app._show_new_task_dialog,
        ).pack(side="right", padx=4)

        self._task_scroll = ctk.CTkScrollableFrame(
            self, fg_color=PANE_BG,
        )
        self._task_scroll.pack(fill="both", expand=True, padx=4, pady=(2, 4))

        self._item_widgets: list[ctk.CTkFrame] = []

    def _selected_pane_id(self) -> Optional[str]:
        key = self.app._chat_selected_key or ""
        if key.startswith("pane_"):
            pane_id = key.split("_", 1)[1]
            if pane_id in self.app.panes:
                return pane_id
        if self.app._focused_id and self.app._focused_id in self.app.panes:
            return self.app._focused_id
        return None

    def _on_add_pane_clicked(self) -> None:
        self.app._add_pane(source_pane_id=self._selected_pane_id())

    def _on_remove_pane_clicked(self) -> None:
        self.app._remove_pane(pane_id=self._selected_pane_id())

    def refresh(self) -> None:
        for w in self._item_widgets:
            w.destroy()
        self._item_widgets.clear()

        # Grid panes
        for pane_id, pane in self.app.panes.items():
            agent = pane.startup_command.upper()
            # Show binding info if any
            if pane._attached_project_id:
                proj = self.app._store.get_project(pane._attached_project_id)
                label = f"{agent} | {proj.name[:20]}" if proj else agent
            elif pane._attached_task_id:
                task = self.app._store.get_task(pane._attached_task_id)
                label = f"{agent} | #{task.id} {task.title[:20]}" if task else agent
            else:
                label = agent
            row = self._make_item_row(
                self._pane_scroll, key=f"pane_{pane_id}",
                icon="\u25a3", label=f"{pane_id.upper()}: {label}",
                color_hint=BORDER_NORMAL,
            )
            self._item_widgets.append(row)

        for proj in self.app._projects:
            icon = {"active": "\u25cf", "paused": "\u23f8",
                    "archived": "\u2610"}.get(proj.status, "?")
            row = self._make_item_row(
                self._proj_scroll, key=f"project_{proj.id}",
                icon=icon, label=proj.name, color_hint=BORDER_PROJECT,
            )
            self._item_widgets.append(row)

        for task in self.app._tasks:
            icon = {"todo": "\u2022", "in_progress": "\u25b6", "paused": "\u23f8",
                    "blocked": "!", "done": "\u2713"}.get(task.status, "?")
            row = self._make_item_row(
                self._task_scroll, key=f"task_{task.id}",
                icon=icon, label=f"#{task.id} {task.title}", color_hint=BORDER_TASK,
            )
            self._item_widgets.append(row)

    def _make_item_row(self, parent: ctk.CTkScrollableFrame, key: str,
                       icon: str, label: str, color_hint: str = "") -> ctk.CTkFrame:
        selected = (key == self.app._chat_selected_key)
        bg = TITLE_BG if selected else "transparent"
        border = color_hint or BORDER_NORMAL
        row = ctk.CTkFrame(parent, fg_color=bg, height=32, corner_radius=3,
                           border_color=border, border_width=2 if selected else 0)
        row.pack(fill="x", pady=1)
        row.pack_propagate(False)

        ctk.CTkLabel(
            row, text=icon, width=20,
            font=ctk.CTkFont(family=FONT_FAMILY, size=12),
            text_color=TITLE_COLOR if selected else TEXT_COLOR,
        ).pack(side="left", padx=(6, 2))

        display = label if len(label) <= 32 else label[:29] + "..."
        ctk.CTkLabel(
            row, text=display,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TITLE_COLOR if selected else TEXT_COLOR, anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=2)

        for widget in [row] + list(row.winfo_children()):
            widget.bind("<Button-1>", lambda e, k=key: self.app._chat_select_item(k))

        return row


class PreviewCard(ctk.CTkFrame):
    """Top area in chat mode — shows details of the selected project/task."""

    def __init__(self, master: tk.Widget, app: "TriptychApp") -> None:
        super().__init__(master, fg_color=STRIP_BG, border_color=STRIP_BORDER,
                         border_width=1, height=PREVIEW_HEIGHT, corner_radius=4)
        self.app = app
        self.pack_propagate(False)

        self._title_label = ctk.CTkLabel(
            self, text="Select an item", height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=13, weight="bold"),
            text_color=TITLE_COLOR, anchor="w",
        )
        self._title_label.pack(fill="x", padx=10, pady=(8, 2))

        self._info_label = ctk.CTkLabel(
            self, text="", height=18,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=TEXT_COLOR, anchor="w",
        )
        self._info_label.pack(fill="x", padx=10, pady=(0, 2))

        self._desc_label = ctk.CTkLabel(
            self, text="", height=18,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color="#6a9a7a", anchor="w",
        )
        self._desc_label.pack(fill="x", padx=10, pady=(0, 4))

        self._btn_row = ctk.CTkFrame(self, fg_color="transparent", height=30)
        self._btn_row.pack(fill="x", padx=10, pady=(0, 6))
        self._action_buttons: list[ctk.CTkButton] = []

    def show_task(self, task: "TaskRecord") -> None:
        self._clear_buttons()
        self._title_label.configure(text=f"Task #{task.id}: {task.title}")
        folder = task.folder or "(no folder)"
        self._info_label.configure(
            text=f"Status: {task.status}  |  Folder: {folder}  |  Priority: {task.priority}"
        )
        goal = task.goal.strip() or "-"
        if len(goal) > 100:
            goal = goal[:100] + "..."
        self._desc_label.configure(text=f"Goal: {goal}")

        self._add_btn("\u25b6 Run", SEND_BG, SEND_HOVER, TITLE_COLOR,
                      lambda: self.app._chat_action_run_task(task.id))
        if task.status == "in_progress":
            self._add_btn("\u23f8 Pause", BUTTON_BG, BUTTON_HOVER, TEXT_COLOR,
                          lambda: self.app._chat_action_pause_task(task.id))
        self._add_btn("\u2713 Done", BUTTON_BG, BUTTON_HOVER, TEXT_COLOR,
                      lambda: self.app._chat_action_done_task(task.id))
        self._add_btn("Edit", BUTTON_BG, BUTTON_HOVER, TEXT_COLOR,
                      lambda: self.app._show_edit_task_dialog(task.id))
        self._add_btn("Delete", DANGER_BG, DANGER_HOVER, "#ffe5e5",
                      lambda: self.app._chat_action_delete_task(task.id))

    def show_project(self, project: "ProjectRecord") -> None:
        self._clear_buttons()
        self._title_label.configure(text=f"Project: {project.name}")
        self._info_label.configure(
            text=f"Status: {project.status}  |  Folder: {project.folder}"
        )
        desc = project.description.strip() or "-"
        if len(desc) > 100:
            desc = desc[:100] + "..."
        self._desc_label.configure(text=desc)

        self._add_btn("\u25b6 Start", SEND_BG, SEND_HOVER, TITLE_COLOR,
                      lambda: self.app._chat_action_enter_project(project.id))
        self._add_btn("\u25b6 Run", BUTTON_BG, BUTTON_HOVER, TEXT_COLOR,
                      lambda: self.app._chat_action_log_project(project.id))
        self._add_btn("Edit", BUTTON_BG, BUTTON_HOVER, TEXT_COLOR,
                      lambda: self.app._show_edit_project_dialog(project.id))
        self._add_btn("Delete", DANGER_BG, DANGER_HOVER, "#ffe5e5",
                      lambda: self.app._chat_action_delete_project(project.id))

    def show_pane(self, pane: "AgentPane") -> None:
        self._clear_buttons()
        agent = pane.startup_command.upper()
        self._title_label.configure(text=f"Pane: {pane.pane_id.upper()} ({agent})")
        folder = pane._cwd or "(no folder)"
        binding = "free"
        if pane._attached_task_id:
            task = pane.app._store.get_task(pane._attached_task_id)
            binding = f"Task #{task.id}: {task.title}" if task else "task"
        elif pane._attached_project_id:
            proj = pane.app._store.get_project(pane._attached_project_id)
            binding = f"Project: {proj.name}" if proj else "project"
        self._info_label.configure(text=f"Folder: {folder}  |  Binding: {binding}")
        self._desc_label.configure(text="Grid pane — use toolbar to manage")

    def show_empty(self) -> None:
        self._clear_buttons()
        self._title_label.configure(text="Select an item from the sidebar")
        self._info_label.configure(text="")
        self._desc_label.configure(text="")

    def _clear_buttons(self) -> None:
        for btn in self._action_buttons:
            btn.destroy()
        self._action_buttons.clear()

    def _add_btn(self, text: str, fg: str, hover: str, tc: str,
                 command: object) -> None:
        btn = ctk.CTkButton(
            self._btn_row, text=text, width=80, height=24,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=fg, hover_color=hover,
            text_color=tc, corner_radius=3, command=command,
        )
        btn.pack(side="left", padx=(0, 6))
        self._action_buttons.append(btn)


class ChatConversationPanel(ctk.CTkFrame):
    """Chat-style surface backed by persisted events."""

    def __init__(self, master: tk.Widget, app: "TriptychApp") -> None:
        super().__init__(
            master,
            fg_color=PANE_BG,
            border_color=INPUT_BORDER,
            border_width=1,
            corner_radius=4,
        )
        self.app = app
        self._context_key: Optional[str] = None
        self._pane_id: Optional[str] = None
        self._task_id: Optional[int] = None
        self._render_signature: Optional[tuple] = None
        self._seen_choice_request_source_ids: set[int] = set()
        self._pending_choice: Optional[dict] = None
        self._signal_adapter = DefaultSignalAdapter()
        self._events_cache: list = []
        self._events_scope = "pane"
        self._last_event_id = 0
        self._events_context_signature: Optional[tuple] = None

        header = ctk.CTkFrame(self, fg_color=TITLE_BG, height=34, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        self._title_label = ctk.CTkLabel(
            header,
            text="Conversation",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TITLE_COLOR,
            anchor="w",
        )
        self._title_label.pack(side="left", padx=(10, 6))

        self._chat_mode_btn = ctk.CTkButton(
            header,
            text="Chat",
            width=56,
            height=22,
            fg_color=SEND_BG,
            hover_color=SEND_HOVER,
            text_color=TITLE_COLOR,
            corner_radius=3,
            command=lambda: self.app._chat_set_surface_mode("chat"),
        )
        self._chat_mode_btn.pack(side="right", padx=(0, 6), pady=6)

        self._terminal_mode_btn = ctk.CTkButton(
            header,
            text="Terminal",
            width=78,
            height=22,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            corner_radius=3,
            command=lambda: self.app._chat_set_surface_mode("terminal"),
        )
        self._terminal_mode_btn.pack(side="right", padx=(0, 4), pady=6)

        self._messages = ctk.CTkScrollableFrame(self, fg_color="#09120e")
        self._messages.pack(fill="both", expand=True, padx=6, pady=(6, 4))

        input_row = ctk.CTkFrame(self, fg_color="transparent")
        input_row.pack(fill="x", padx=6, pady=(0, 6))

        self._input = ctk.CTkTextbox(
            input_row,
            height=68,
            font=ctk.CTkFont(family=FONT_FAMILY, size=FONT_SIZE),
            fg_color=INPUT_BG,
            text_color=TEXT_COLOR,
            border_color=INPUT_BORDER,
            border_width=1,
            corner_radius=4,
            wrap="word",
        )
        self._input.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self._input.bind("<Control-Return>", self._on_send_hotkey)
        self._input.bind("<Control-KP_Enter>", self._on_send_hotkey)

        self._send_btn = ctk.CTkButton(
            input_row,
            text="Send",
            width=78,
            height=68,
            fg_color=SEND_BG,
            hover_color=SEND_HOVER,
            text_color=TITLE_COLOR,
            corner_radius=4,
            command=self._send_from_chat_input,
        )
        self._send_btn.pack(side="right")

        self._input_hint = ctk.CTkLabel(
            self,
            text="Ctrl+Enter to send",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color="#6a9a7a",
            anchor="w",
        )
        self._input_hint.pack(fill="x", padx=10, pady=(0, 6))

        self._poll_id: Optional[str] = None
        self._start_poll()

    def _start_poll(self) -> None:
        self._poll_id = self.after(800, self._poll_updates)

    def _poll_updates(self) -> None:
        self._poll_id = None
        if self.winfo_exists() and self.app._layout_mode == "chat":
            self.refresh_events()
        self._start_poll()

    def destroy(self) -> None:
        if self._poll_id:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        super().destroy()

    def set_surface_mode(self, mode: str) -> None:
        is_chat = (mode == "chat")
        if is_chat:
            self._chat_mode_btn.configure(fg_color=SEND_BG, text_color=TITLE_COLOR)
            self._terminal_mode_btn.configure(fg_color=BUTTON_BG, text_color=TEXT_COLOR)
        else:
            self._chat_mode_btn.configure(fg_color=BUTTON_BG, text_color=TEXT_COLOR)
            self._terminal_mode_btn.configure(fg_color=SEND_BG, text_color=TITLE_COLOR)

    def set_context(self, key: Optional[str], pane_id: Optional[str], task_id: Optional[int]) -> None:
        self._context_key = key
        self._pane_id = pane_id
        self._task_id = task_id
        self._pending_choice = None
        self._events_cache = []
        self._events_scope = "pane"
        self._last_event_id = 0
        self._events_context_signature = None
        self._render_signature = None
        if key:
            self._title_label.configure(text=f"Conversation: {key}")
        else:
            self._title_label.configure(text="Conversation")
        self._update_input_hint()
        self.refresh_events(force=True)

    def focus_input(self) -> None:
        self._input.focus_set()

    def _update_input_hint(self) -> None:
        if self._pending_choice:
            opts = self._pending_choice.get("options", [])
            nums = [str(int(item.get("number", 0))) for item in opts if int(item.get("number", 0))]
            nums_text = "/".join(nums) if nums else "number"
            self._input_hint.configure(
                text=f"Action required: click a choice button or type {nums_text} and press Send",
                text_color="#f2b84b",
            )
            return
        self._input_hint.configure(text="Ctrl+Enter to send", text_color="#6a9a7a")

    def refresh_events(self, force: bool = False) -> None:
        context_signature = (self._context_key, self._pane_id, self._task_id)
        if force or context_signature != self._events_context_signature:
            events = self._load_context_events()
            self._events_cache = list(events)
            self._last_event_id = events[-1].id if events else 0
            self._events_context_signature = context_signature
        else:
            delta = self._load_context_events_since(self._last_event_id)
            if delta:
                self._events_cache.extend(delta)
                if len(self._events_cache) > CHAT_EVENT_LIMIT:
                    self._events_cache = self._events_cache[-CHAT_EVENT_LIMIT:]
                self._last_event_id = self._events_cache[-1].id if self._events_cache else 0
        events = self._events_cache
        last_id = events[-1].id if events else 0
        signature = (self._context_key, self._pane_id, self._task_id, len(events), last_id)
        if not force and signature == self._render_signature:
            return
        self._render_signature = signature

        messages, options = self._build_messages(events)
        self._render_messages(messages, options)

    def _load_context_events(self) -> list:
        if not self._pane_id:
            self._events_scope = "pane"
            return []
        if self._task_id:
            events = self.app._store.list_events(
                limit=CHAT_EVENT_LIMIT,
                pane_id=self._pane_id,
                task_id=self._task_id,
            )
            if events:
                self._events_scope = "task"
                return events
        self._events_scope = "pane"
        return self.app._store.list_events(
            limit=CHAT_EVENT_LIMIT,
            pane_id=self._pane_id,
        )

    def _load_context_events_since(self, after_id: int) -> list:
        if not self._pane_id or after_id <= 0:
            return []
        if self._events_scope == "task" and self._task_id:
            return self.app._store.list_events_since(
                event_id=after_id,
                limit=CHAT_EVENT_LIMIT,
                pane_id=self._pane_id,
                task_id=self._task_id,
            )
        return self.app._store.list_events_since(
            event_id=after_id,
            limit=CHAT_EVENT_LIMIT,
            pane_id=self._pane_id,
        )

    def _build_messages(self, events: list) -> tuple[list[dict], Optional[dict]]:
        messages: list[dict] = []
        selected_source_ids: set[int] = set()
        detected_payloads: list[dict] = []
        last_output_signature: Optional[str] = None

        for event in events:
            signal = self._signal_adapter.normalize(event)
            payload = signal.payload
            event_type = signal.event_type

            if signal.kind == SIGNAL_USER_MESSAGE:
                text = signal.text
                if text:
                    messages.append(
                        {
                            "role": "user",
                            "text": text,
                            "created_at": signal.created_at,
                            "event_id": signal.id,
                        }
                    )
                continue

            if signal.kind == SIGNAL_ASSISTANT_MESSAGE:
                text = signal.text
                if _is_terminal_repaint_noise(text):
                    continue
                output_sig = self._terminal_chunk_signature(text)
                if output_sig and output_sig == last_output_signature:
                    continue
                last_output_signature = output_sig
                if messages and messages[-1]["role"] == "assistant":
                    prev_text = str(messages[-1]["text"])
                    messages[-1]["text"] = prev_text + text
                    messages[-1]["event_id"] = signal.id
                else:
                    messages.append(
                        {
                            "role": "assistant",
                            "text": text,
                            "created_at": signal.created_at,
                            "event_id": signal.id,
                        }
                    )
                continue

            if signal.kind == SIGNAL_CHOICE_SELECTED:
                source_event_id = signal.source_event_id
                if source_event_id > 0:
                    selected_source_ids.add(source_event_id)

            if signal.kind == SIGNAL_CHOICE_REQUEST:
                source_event_id = signal.source_event_id
                if source_event_id > 0:
                    self._seen_choice_request_source_ids.add(source_event_id)
                    normalized = self._normalize_choice_payload(
                        {
                            "source_event_id": source_event_id,
                            "question": signal.question,
                            "options": signal.options,
                        }
                    )
                    if normalized:
                        detected_payloads.append(normalized)
                continue

            if signal.kind == SIGNAL_SYSTEM_EVENT or signal.kind == SIGNAL_CHOICE_SELECTED:
                system_text = self._format_system_event(event_type, payload, signal.created_at)
            else:
                system_text = ""
            if system_text:
                messages.append(
                    {
                        "role": "system",
                        "text": system_text,
                        "created_at": signal.created_at,
                        "event_id": signal.id,
                    }
                )

        pending_choice = self._resolve_pending_choice(
            messages=messages,
            selected_source_ids=selected_source_ids,
            detected_payloads=detected_payloads,
        )
        return messages, pending_choice

    def _terminal_chunk_signature(self, text: str) -> str:
        return _normalize_terminal_signature(text)

    def _extract_choice_payload(self, text: str) -> Optional[dict]:
        return extract_signal_choice_payload(text)

    def _normalize_choice_payload(self, payload: dict) -> Optional[dict]:
        return normalize_signal_choice_payload(payload)

    def _resolve_pending_choice(
        self,
        messages: list[dict],
        selected_source_ids: set[int],
        detected_payloads: list[dict],
    ) -> Optional[dict]:
        # Prefer fresh parse from the latest assistant message to keep text exact.
        for msg in reversed(messages):
            if msg.get("role") != "assistant":
                continue
            source_event_id = int(msg.get("event_id", 0) or 0)
            if source_event_id <= 0 or source_event_id in selected_source_ids:
                continue
            text = str(msg.get("text", ""))
            parsed = self._extract_choice_payload(text)
            if not parsed:
                continue
            payload = {
                "source_event_id": source_event_id,
                "question": parsed.get("question", "Choose one option."),
                "options": parsed.get("options", []),
            }
            if source_event_id not in self._seen_choice_request_source_ids:
                self._seen_choice_request_source_ids.add(source_event_id)
                self.app._record_event(
                    self._pane_id or "",
                    "assistant_choice_request_detected",
                    payload,
                    task_id=self._task_id,
                    agent=self._active_agent(),
                )
            return payload

        # Fallback to already persisted choice requests.
        for payload in reversed(detected_payloads):
            source_event_id = int(payload.get("source_event_id", 0) or 0)
            if source_event_id <= 0 or source_event_id in selected_source_ids:
                continue
            return payload
        return None

    def _active_agent(self) -> str:
        pane = self.app.panes.get(self._pane_id or "")
        return pane.startup_command if pane else ""

    def _format_system_event(self, event_type: str, payload: dict, created_at: str) -> str:
        if event_type == "task_status_changed":
            task_id = payload.get("task_id", "?")
            from_status = payload.get("from", "")
            to_status = payload.get("to", "")
            return f"[{created_at}] Task #{task_id}: {from_status} -> {to_status}"
        if event_type == "task_attached":
            task_id = payload.get("task_id", "?")
            return f"[{created_at}] Attached task #{task_id}"
        if event_type == "project_attached":
            project_name = payload.get("project_name", "")
            return f"[{created_at}] Attached project: {project_name}"
        if event_type == "context_injected":
            src = payload.get("source_pane", "")
            dst = payload.get("target_pane", "")
            return f"[{created_at}] Injected context: {src} -> {dst}"
        if event_type == "task_created":
            return f"[{created_at}] Task created: {payload.get('task_title', '')}"
        if event_type == "project_created":
            return f"[{created_at}] Project created: {payload.get('project_name', '')}"
        if event_type in {"pane_created", "pane_removed"}:
            pane_id = payload.get("pane_id", "")
            return f"[{created_at}] {event_type.replace('_', ' ').title()}: {pane_id}"
        if event_type.startswith("ui_"):
            short = event_type.replace("ui_", "").replace("_", " ").title()
            return f"[{created_at}] {short}"
        if event_type in {"project_iteration_saved", "project_iteration_save_failed"}:
            return f"[{created_at}] {event_type.replace('_', ' ').title()}"
        if event_type in {"task_deleted", "project_deleted"}:
            return f"[{created_at}] {event_type.replace('_', ' ').title()}"
        if event_type == "assistant_choice_selected":
            number = payload.get("choice_number", "")
            title = str(payload.get("choice_title", "")).strip()
            if title:
                return f"[{created_at}] Selected option {number}: {title}"
            return f"[{created_at}] Selected option {number}"
        return ""

    def _render_messages(self, messages: list[dict], options_payload: Optional[dict]) -> None:
        for child in self._messages.winfo_children():
            child.destroy()

        self._pending_choice = options_payload
        self._update_input_hint()

        if not messages and not options_payload:
            ctk.CTkLabel(
                self._messages,
                text="No conversation events yet.",
                text_color="#6a9a7a",
                anchor="w",
            ).pack(fill="x", padx=8, pady=8)
            return

        for msg in messages:
            role = str(msg.get("role", "system"))
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            frame = ctk.CTkFrame(self._messages, fg_color="transparent")
            frame.pack(fill="x", padx=6, pady=4)

            if role == "user":
                bubble = ctk.CTkFrame(frame, fg_color="#1a3d2a", corner_radius=6)
                bubble.pack(anchor="e")
                label_color = TITLE_COLOR
            elif role == "assistant":
                bubble = ctk.CTkFrame(frame, fg_color="#132236", corner_radius=6)
                bubble.pack(anchor="w")
                label_color = TEXT_COLOR
            else:
                bubble = ctk.CTkFrame(frame, fg_color="#2a2a17", corner_radius=6)
                bubble.pack(anchor="center")
                label_color = "#e8e1a0"

            ctk.CTkLabel(
                bubble,
                text=text,
                text_color=label_color,
                justify="left",
                anchor="w",
                wraplength=700,
                font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            ).pack(fill="x", padx=10, pady=8)

        if options_payload:
            opts = options_payload.get("options", [])
            source_event_id = int(options_payload.get("source_event_id", 0) or 0)
            question = str(options_payload.get("question", "Choose one option.")).strip()
            if opts and source_event_id > 0:
                card = ctk.CTkFrame(
                    self._messages,
                    fg_color="#18261a",
                    border_color="#f2b84b",
                    border_width=1,
                    corner_radius=8,
                )
                card.pack(fill="x", padx=6, pady=(6, 10))

                ctk.CTkLabel(
                    card,
                    text="Action required",
                    text_color="#f2b84b",
                    font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
                    anchor="w",
                ).pack(fill="x", padx=10, pady=(8, 2))

                ctk.CTkLabel(
                    card,
                    text=question,
                    text_color=TEXT_COLOR,
                    justify="left",
                    anchor="w",
                    wraplength=720,
                    font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                ).pack(fill="x", padx=10, pady=(0, 8))

                for item in opts:
                    number = int(item.get("number", 0))
                    title = str(item.get("title", "")).strip()
                    if number <= 0 or not title:
                        continue
                    row = ctk.CTkFrame(card, fg_color="#132015", corner_radius=6)
                    row.pack(fill="x", padx=10, pady=(0, 6))

                    badge = ctk.CTkLabel(
                        row,
                        text=str(number),
                        width=28,
                        height=22,
                        text_color=TITLE_COLOR,
                        fg_color=BUTTON_BG,
                        corner_radius=3,
                        font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
                    )
                    badge.pack(side="left", padx=(6, 8), pady=6)

                    ctk.CTkLabel(
                        row,
                        text=title,
                        text_color=TEXT_COLOR,
                        justify="left",
                        anchor="w",
                        wraplength=560,
                        font=ctk.CTkFont(family=FONT_FAMILY, size=11),
                    ).pack(side="left", fill="x", expand=True, padx=(0, 8), pady=6)

                    option_button_text = f"{number}. {title}"
                    ctk.CTkButton(
                        row,
                        text=option_button_text,
                        width=420,
                        height=26,
                        fg_color=SEND_BG,
                        hover_color=SEND_HOVER,
                        text_color=TITLE_COLOR,
                        corner_radius=3,
                        command=lambda n=number, sid=source_event_id, t=title: self._select_option(
                            n, sid, t, source="chat_choice_button"
                        ),
                    ).pack(side="right", padx=(0, 6), pady=6)

                ctk.CTkLabel(
                    card,
                    text="Tip: type option number (e.g. 1/2/3) and press Send.",
                    text_color="#b6caa5",
                    anchor="w",
                    font=ctk.CTkFont(family=FONT_FAMILY, size=10),
                ).pack(fill="x", padx=10, pady=(0, 8))

    def _on_send_hotkey(self, _event: tk.Event = None) -> str:
        self._send_from_chat_input()
        return "break"

    def _send_from_chat_input(self) -> None:
        text = self._input.get("1.0", "end-1c").strip()
        if not text:
            return
        pane = self.app.panes.get(self._pane_id or "")
        if not pane:
            self.app._status_note = "No active pane bound for this chat."
            self.app.refresh_status()
            return
        choice_match = re.match(r"^\s*(\d{1,2})(?:\b|[\)\.\:\-])", text)
        if self._pending_choice and choice_match:
            number = int(choice_match.group(1))
            source_event_id = int(self._pending_choice.get("source_event_id", 0) or 0)
            option_title = ""
            for item in self._pending_choice.get("options", []):
                try:
                    if int(item.get("number", 0) or 0) == number:
                        option_title = str(item.get("title", "")).strip()
                        break
                except Exception:
                    continue
            if source_event_id > 0 and option_title:
                self._input.delete("1.0", "end")
                self._select_option(number, source_event_id, option_title, source="chat_choice_text")
                return
        pane._submit_terminal_input(text, source="chat_panel_input")
        self._input.delete("1.0", "end")
        self.app._status_note = f"Sent message to {pane.pane_id.upper()} via chat panel"
        self.app.refresh_status()
        self.refresh_events(force=True)

    def _select_option(self, number: int, source_event_id: int, title: str, source: str) -> None:
        pane = self.app.panes.get(self._pane_id or "")
        if not pane:
            self.app._status_note = "No active pane for option selection."
            self.app.refresh_status()
            return
        pane._submit_terminal_input(str(number), source=source)
        self.app._record_event(
            pane.pane_id,
            "assistant_choice_selected",
            {
                "source_event_id": source_event_id,
                "choice_number": number,
                "choice_title": title,
                "input_source": source,
            },
            task_id=self._task_id,
            agent=pane.startup_command,
        )
        self.app._status_note = f"Selected option {number} for {pane.pane_id.upper()}"
        self.app.refresh_status()
        self.refresh_events(force=True)


class ChatFileExplorer(ctk.CTkFrame):
    """Right-side file tree for chat mode."""

    _HIDDEN_NAMES = {".git", "node_modules", ".venv", "__pycache__", ".idea", ".vscode"}

    def __init__(self, master: tk.Widget, app: "TriptychApp") -> None:
        super().__init__(
            master,
            width=EXPLORER_WIDTH,
            fg_color=PANE_BG,
            border_color=INPUT_BORDER,
            border_width=1,
            corner_radius=4,
        )
        self.app = app
        self.pack_propagate(False)
        self._root_path: Optional[str] = None
        self._context_key: Optional[str] = None
        self._node_paths: dict[str, str] = {}
        self._loaded_nodes: set[str] = set()

        header = ctk.CTkFrame(self, fg_color=TITLE_BG, height=32, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="Explorer",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(side="left", padx=(8, 4))

        ctk.CTkButton(
            header,
            text="Refresh",
            width=68,
            height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            corner_radius=3,
            command=self.refresh,
        ).pack(side="right", padx=(0, 6), pady=4)

        ctk.CTkButton(
            header,
            text="Open",
            width=56,
            height=22,
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            corner_radius=3,
            command=self._open_root_folder,
        ).pack(side="right", padx=(0, 4), pady=4)

        self._path_label = ctk.CTkLabel(
            self,
            text="No folder selected",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color="#7eb896",
            anchor="w",
        )
        self._path_label.pack(fill="x", padx=8, pady=(6, 4))

        self._drop_hint = ctk.CTkLabel(
            self,
            text="Drop files here",
            font=ctk.CTkFont(family=FONT_FAMILY, size=9),
            text_color="#6a9a7a",
            anchor="w",
        )
        self._drop_hint.pack(fill="x", padx=8, pady=(0, 4))

        tree_host = ctk.CTkFrame(self, fg_color="#0b1a12")
        tree_host.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        style = ttk.Style(self)
        try:
            if "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Explorer.Treeview",
            background="#0b1a12",
            fieldbackground="#0b1a12",
            foreground=TEXT_COLOR,
            borderwidth=0,
            relief="flat",
            bordercolor="#0b1a12",
            lightcolor="#0b1a12",
            darkcolor="#0b1a12",
            rowheight=22,
        )
        style.map(
            "Explorer.Treeview",
            background=[("selected", "#245738")],
            foreground=[("selected", TITLE_COLOR)],
        )
        style.configure(
            "Explorer.Vertical.TScrollbar",
            troughcolor="#0f2419",
            background="#245738",
            bordercolor="#0f2419",
            arrowcolor=TEXT_COLOR,
            lightcolor="#0f2419",
            darkcolor="#0f2419",
        )

        self._tree = ttk.Treeview(tree_host, show="tree", style="Explorer.Treeview")
        self._tree.pack(side="left", fill="both", expand=True)
        self._tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        self._scroll = ttk.Scrollbar(
            tree_host, orient="vertical", command=self._tree.yview, style="Explorer.Vertical.TScrollbar"
        )
        self._scroll.pack(side="right", fill="y")
        self._tree.configure(yscrollcommand=self._scroll.set)

        self._dnd_ready = False
        if self.app._dnd_enabled and DND_FILES:
            try:
                self._tree.drop_target_register(DND_FILES)
                self._tree.dnd_bind("<<Drop>>", self._on_drop_files)
                self._dnd_ready = True
            except Exception:
                self._dnd_ready = False

        if self._dnd_ready:
            self._drop_hint.configure(text="Drag files/folders here to copy into current root")
        else:
            self._drop_hint.configure(text="Drag-and-drop unavailable (tkinterdnd2 not active)")

    def set_root(self, root_path: Optional[str], context_key: Optional[str]) -> None:
        self._context_key = context_key
        normalized = os.path.abspath(root_path) if root_path else None
        if not normalized or not os.path.isdir(normalized):
            self._root_path = None
            self._path_label.configure(text="No folder selected")
            self._clear_tree()
            self._tree.insert("", "end", text="(no files to show)")
            return

        self._root_path = normalized
        self._path_label.configure(text=self._format_path(normalized))
        self.refresh()

    def refresh(self) -> None:
        if not self._root_path or not os.path.isdir(self._root_path):
            self._clear_tree()
            self._tree.insert("", "end", text="(no files to show)")
            return

        self._clear_tree()
        root_name = os.path.basename(self._root_path.rstrip("\\/")) or self._root_path
        root_id = self._tree.insert("", "end", text=f"[D] {root_name}", open=True)
        self._node_paths[root_id] = self._root_path
        self._populate_children(root_id, self._root_path)

    def _open_root_folder(self) -> None:
        if not self._root_path or not os.path.isdir(self._root_path):
            return
        try:
            if os.name == "nt":
                os.startfile(self._root_path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self._root_path])
            else:
                subprocess.Popen(["xdg-open", self._root_path])
        except Exception:
            pass

    def _on_tree_open(self, _event: tk.Event) -> None:
        node_id = self._tree.focus()
        path = self._node_paths.get(node_id)
        if not path or not os.path.isdir(path):
            return
        if node_id in self._loaded_nodes:
            return
        self._populate_children(node_id, path)

    def _on_tree_double_click(self, _event: tk.Event) -> None:
        node_id = self._tree.focus()
        path = self._node_paths.get(node_id)
        if not path or not os.path.exists(path):
            return
        if os.path.isdir(path):
            return
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def _on_drop_files(self, event: tk.Event) -> str:
        if not self._root_path or not os.path.isdir(self._root_path):
            self.app._status_note = "Explorer drop ignored: no active root folder."
            self.app.refresh_status()
            return "break"

        dropped = self._parse_dropped_paths(getattr(event, "data", ""))
        if not dropped:
            self.app._status_note = "Explorer drop ignored: no valid files."
            self.app.refresh_status()
            return "break"

        copied = 0
        errors: list[str] = []
        for src_path in dropped:
            try:
                self._copy_into_root(src_path, self._root_path)
                copied += 1
            except Exception as exc:
                errors.append(f"{os.path.basename(src_path)} ({exc})")

        self.refresh()
        if copied and not errors:
            self.app._status_note = f"Explorer: copied {copied} item(s)."
        elif copied:
            self.app._status_note = (
                f"Explorer: copied {copied} item(s), {len(errors)} failed."
            )
        else:
            self.app._status_note = "Explorer: drop failed."
        self.app.refresh_status()
        return "break"

    def _parse_dropped_paths(self, raw_data: str) -> list[str]:
        if not raw_data:
            return []
        parts: list[str] = []
        token = ""
        in_braces = False
        for ch in raw_data.strip():
            if ch == "{":
                if not in_braces:
                    in_braces = True
                    if token.strip():
                        parts.append(token.strip())
                    token = ""
                    continue
            if ch == "}":
                if in_braces:
                    in_braces = False
                    if token.strip():
                        parts.append(token.strip())
                    token = ""
                    continue
            if ch.isspace() and not in_braces:
                if token.strip():
                    parts.append(token.strip())
                token = ""
                continue
            token += ch
        if token.strip():
            parts.append(token.strip())

        result: list[str] = []
        for item in parts:
            path = item.strip().strip('"')
            if not path:
                continue
            candidates = [
                os.path.normpath(path),
                os.path.normpath(path.replace("\\\\", "\\")),
                os.path.normpath(path.replace("\\", "/")),
                os.path.normpath(path.replace("/", "\\")),
            ]
            for candidate in candidates:
                if candidate and os.path.exists(candidate):
                    result.append(candidate)
                    break
        return result

    def _copy_into_root(self, src_path: str, root_path: str) -> None:
        name = os.path.basename(src_path.rstrip("\\/")) or os.path.basename(src_path)
        if not name:
            raise ValueError("invalid name")
        dest_path = self._unique_target_path(root_path, name)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dest_path)
        else:
            shutil.copy2(src_path, dest_path)

    def _unique_target_path(self, root_path: str, name: str) -> str:
        candidate = os.path.join(root_path, name)
        if not os.path.exists(candidate):
            return candidate
        base, ext = os.path.splitext(name)
        idx = 1
        while True:
            candidate = os.path.join(root_path, f"{base} ({idx}){ext}")
            if not os.path.exists(candidate):
                return candidate
            idx += 1

    def _populate_children(self, parent_id: str, folder_path: str) -> None:
        for child in self._tree.get_children(parent_id):
            self._tree.delete(child)
            self._node_paths.pop(child, None)

        try:
            entries = list(os.scandir(folder_path))
        except (PermissionError, OSError):
            self._tree.insert(parent_id, "end", text="(access denied)")
            self._loaded_nodes.add(parent_id)
            return

        def visible(entry: os.DirEntry) -> bool:
            name = entry.name
            if name in self._HIDDEN_NAMES:
                return False
            if name.startswith("."):
                return False
            return True

        dirs = [e for e in entries if visible(e) and e.is_dir(follow_symlinks=False)]
        files = [e for e in entries if visible(e) and not e.is_dir(follow_symlinks=False)]
        dirs.sort(key=lambda e: e.name.lower())
        files.sort(key=lambda e: e.name.lower())

        for entry in dirs + files:
            full_path = entry.path
            is_dir = entry.is_dir(follow_symlinks=False)
            prefix = "[D]" if is_dir else "[F]"
            item_id = self._tree.insert(parent_id, "end", text=f"{prefix} {entry.name}", open=False)
            self._node_paths[item_id] = full_path
            if is_dir:
                self._tree.insert(item_id, "end", text="...")

        self._loaded_nodes.add(parent_id)

    def _clear_tree(self) -> None:
        for item_id in self._tree.get_children(""):
            self._tree.delete(item_id)
        self._node_paths.clear()
        self._loaded_nodes.clear()

    def _format_path(self, path: str) -> str:
        if len(path) <= 64:
            return path
        return "..." + path[-61:]


# ── Main Application ──────────────────────────────────────────────────────────


if TKDND_AVAILABLE:
    class DnDCTk(TkinterDnD.DnDWrapper, ctk.CTk):
        pass
else:
    class DnDCTk(ctk.CTk):
        pass


class TriptychApp(DnDCTk):
    def __init__(self) -> None:
        super().__init__(fg_color=BG_DARK)
        self.title("Agent Commander")
        self.geometry("1400x800")
        self.minsize(900, 500)

        ctk.set_appearance_mode("dark")
        self._dnd_enabled = False
        if TKDND_AVAILABLE and TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self._dnd_enabled = True
            except Exception:
                self._dnd_enabled = False

        self.panes: dict[str, AgentPane] = {}
        self._pane_seq = 0
        self.source_pane: Optional[str] = None
        self._focused_id: Optional[str] = None
        self._status_note = "Ready"
        self._shell_command = self._detect_shell_command()
        self._project_root = os.path.dirname(os.path.abspath(__file__))
        self._app_icon_photo: Optional[tk.PhotoImage] = None
        self._apply_window_icon()
        self._cache_dir = os.path.join(self._project_root, COMMON_CACHE_DIRNAME)
        os.makedirs(self._cache_dir, exist_ok=True)
        self._setup_state_path = os.path.join(self._cache_dir, SETUP_STATE_FILENAME)
        self._launcher_check_path = os.path.join(self._cache_dir, LAUNCHER_CHECK_FILENAME)
        self._agent_detected: dict[str, bool] = self._load_detected_agents()
        self._selected_agent_ids: list[str] = self._resolve_selected_agents()
        self._enabled_start_agent_ids: list[str] = [
            agent_id for agent_id in self._selected_agent_ids if self._agent_detected.get(agent_id, False)
        ]
        self._store = OrchestratorStore(
            os.path.join(self._cache_dir, "orchestrator.db")
        )
        self._tasks: list[TaskRecord] = []
        self._tasks_by_id: dict[int, TaskRecord] = {}
        self._projects: list[ProjectRecord] = []
        self._projects_by_id: dict[int, ProjectRecord] = {}
        self._task_choices: dict[str, tuple] = {}
        self._selected_task_id: Optional[int] = None
        self._pane_task_bindings: dict[str, int] = self._store.list_pane_bindings()
        self._pane_project_bindings: dict[str, int] = self._store.list_pane_project_bindings()

        # ── Chat mode state ──────────────────────────────────────────────
        self._layout_mode: str = "grid"
        self._chat_surface_mode: str = "chat"
        self._chat_selected_key: Optional[str] = None
        self._chat_active_pane: Optional[AgentPane] = None

        # ── Pane row ──────────────────────────────────────────────────────
        self.main_menu = ctk.CTkFrame(
            self, fg_color=UI_NEUTRAL, border_color=UI_NEUTRAL_HOVER, border_width=1
        )
        self.main_menu.pack(fill="x", padx=6, pady=(6, 2))

        self.main_menu_label = ctk.CTkLabel(
            self.main_menu, text="Main Menu",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=UI_ACCENT,
        )
        self.main_menu_label.pack(side="left", padx=(10, 8), pady=6)

        self.main_menu_left = ctk.CTkFrame(self.main_menu, fg_color="transparent")
        self.main_menu_left.pack(side="left", pady=4)

        self.main_menu_right = ctk.CTkFrame(self.main_menu, fg_color="transparent")
        self.main_menu_right.pack(side="right", pady=4)

        self.main_add_pane_btn = ctk.CTkButton(
            self.main_menu_left, text="+ Add Agent", width=120, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color=UI_PRIMARY, hover_color=UI_PRIMARY_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._add_pane,
        )
        self.main_add_pane_btn.pack(side="left", padx=(0, 8), pady=4)

        self.setup_agents_btn = ctk.CTkButton(
            self.main_menu_right, text="Setup Wizard", width=120, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_NEUTRAL, hover_color=UI_NEUTRAL_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._open_agent_setup_dialog,
        )
        self.setup_agents_btn.pack(side="right", padx=(0, 8), pady=4)

        self.layout_toggle_btn = ctk.CTkButton(
            self.main_menu_left, text="\u2630 Chat Mode", width=120, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11, weight="bold"),
            fg_color=UI_NEUTRAL, hover_color=UI_NEUTRAL_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._toggle_layout_mode,
        )
        self.layout_toggle_btn.pack(side="left", padx=(0, 8), pady=4)

        self.main_cache_btn = ctk.CTkButton(
            self.main_menu_right, text="Main Cache", width=110, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_NEUTRAL, hover_color=UI_NEUTRAL_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._open_common_cache,
        )
        self.main_cache_btn.pack(side="right", padx=(0, 8), pady=4)

        self.task_board = ctk.CTkFrame(
            self, fg_color=UI_NEUTRAL, border_color=UI_NEUTRAL_HOVER, border_width=1
        )
        self.task_board.pack(fill="x", padx=6, pady=(2, 2))

        self.task_board_label = ctk.CTkLabel(
            self.task_board, text="Manager",
            font=ctk.CTkFont(family=FONT_FAMILY, size=12, weight="bold"),
            text_color=UI_ACCENT,
        )
        self.task_board_label.pack(side="left", padx=(10, 8), pady=6)

        self.task_new_btn = ctk.CTkButton(
            self.task_board, text="New Task", width=90, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_PRIMARY, hover_color=UI_PRIMARY_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._show_new_task_dialog,
        )
        self.task_new_btn.pack(side="left", padx=(0, 6), pady=4)

        self.project_new_btn = ctk.CTkButton(
            self.task_board, text="New Project", width=110, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_PRIMARY, hover_color=UI_PRIMARY_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._show_new_project_dialog,
        )
        self.project_new_btn.pack(side="left", padx=(0, 6), pady=4)

        self.task_sep_left = ctk.CTkFrame(
            self.task_board, width=1, height=26, fg_color=UI_NEUTRAL_HOVER
        )
        self.task_sep_left.pack(side="left", padx=(2, 8), pady=4)

        self._task_choice_var = ctk.StringVar(value="No tasks")
        self.task_choice_menu = ctk.CTkOptionMenu(
            self.task_board,
            values=["No tasks"],
            variable=self._task_choice_var,
            width=420,
            height=28,
            fg_color=UI_NEUTRAL,
            button_color=UI_NEUTRAL_HOVER,
            button_hover_color=UI_PRIMARY,
            text_color="#f8fbff",
            dropdown_fg_color=UI_NEUTRAL,
            dropdown_hover_color=UI_NEUTRAL_HOVER,
            dropdown_text_color=TEXT_COLOR,
            command=self._on_task_choice,
        )
        self.task_choice_menu.pack(side="left", padx=(0, 8), pady=4, fill="x", expand=True)

        self.task_sep_right = ctk.CTkFrame(
            self.task_board, width=1, height=26, fg_color=UI_NEUTRAL_HOVER
        )
        self.task_sep_right.pack(side="left", padx=(0, 8), pady=4)

        self.edit_btn = ctk.CTkButton(
            self.task_board, text="Edit", width=72, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_NEUTRAL, hover_color=UI_NEUTRAL_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._show_edit_dialog,
        )
        self.edit_btn.pack(side="left", padx=(0, 8), pady=4)

        self.templates_btn = ctk.CTkButton(
            self.task_board, text="Load Templates", width=124, height=28,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            fg_color=UI_NEUTRAL, hover_color=UI_NEUTRAL_HOVER,
            text_color="#f8fbff", corner_radius=4,
            command=self._load_starter_templates,
        )
        self.templates_btn.pack(side="left", padx=(0, 8), pady=4)

        self.task_summary_label = ctk.CTkLabel(
            self.task_board, text="No tasks yet.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            text_color=UI_ACCENT,
            anchor="w",
        )
        self.task_summary_label.pack(side="left", padx=(4, 0), pady=6)

        self.pane_row = ctk.CTkFrame(self, fg_color="transparent")
        self.pane_row.pack(fill="both", expand=True, padx=6, pady=(2, 2))

        pane_defs: list[tuple[str, str, str]] = []
        for agent_id in self._enabled_start_agent_ids:
            pane_defs.append(
                (
                    agent_id,
                    agent_id.upper(),
                    self._resolve_agent_command(agent_id),
                )
            )

        for i, (pid, title, cmd) in enumerate(pane_defs, start=1):
            # Pane parent stays the app root so the same widget can be shown
            # in either grid container or chat container via geometry `in_`.
            pane = AgentPane(self, pid, title, cmd, self)
            self.panes[pid] = pane
            self._pane_seq = max(self._pane_seq, i)

        if not pane_defs:
            self._status_note = (
                "No selected agents are installed. Run launcher setup again or install Claude/Gemini/Codex."
            )

        self._reflow_panes()
        self.source_pane = next(iter(self.panes), None)
        self._focused_id = self.source_pane
        for bound_pane_id in list(self._pane_task_bindings):
            if bound_pane_id not in self.panes:
                self._store.clear_pane_binding(bound_pane_id)
                self._pane_task_bindings.pop(bound_pane_id, None)
        for bound_pane_id in list(self._pane_project_bindings):
            if bound_pane_id not in self.panes:
                self._store.clear_pane_project_binding(bound_pane_id)
                self._pane_project_bindings.pop(bound_pane_id, None)
        self._refresh_task_board()
        self._seed_starter_templates_if_empty()

        # Restore task strips for persisted bindings
        for bound_pane_id, bound_task_id in self._pane_task_bindings.items():
            pane = self.panes.get(bound_pane_id)
            task = self._store.get_task(bound_task_id)
            if pane and task:
                pane.show_task_strip(task)

        # Restore project strips for persisted bindings
        for bound_pane_id, bound_project_id in self._pane_project_bindings.items():
            pane = self.panes.get(bound_pane_id)
            project = self._store.get_project(bound_project_id)
            if pane and project:
                pane.show_project_strip(project)

        # ── Chat mode containers (initially hidden) ─────────────────────
        self._chat_container = ctk.CTkFrame(self, fg_color="transparent")
        # NOT packed — only shown in chat mode

        self._chat_sidebar = ChatSidebar(self._chat_container, self)
        self._chat_sidebar.pack(side="left", fill="y", padx=(0, 4))

        self._chat_right = ctk.CTkFrame(self._chat_container, fg_color="transparent")
        self._chat_right.pack(side="left", fill="both", expand=True)

        self._chat_preview = PreviewCard(self._chat_right, self)
        self._chat_preview.pack(fill="x", padx=0, pady=(0, 4))

        self._chat_body = ctk.CTkFrame(self._chat_right, fg_color="transparent")
        self._chat_body.pack(fill="both", expand=True)

        self._chat_pane_area = ctk.CTkFrame(self._chat_body, fg_color="transparent")
        self._chat_pane_area.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self._chat_conversation = ChatConversationPanel(self._chat_pane_area, self)
        self._chat_conversation.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        self._chat_conversation.lift()
        self._chat_conversation.set_surface_mode(self._chat_surface_mode)

        self._chat_explorer = ChatFileExplorer(self._chat_body, self)
        self._chat_explorer.pack(side="left", fill="y")

        # ── Status bar ────────────────────────────────────────────────────
        self.status_bar = ctk.CTkLabel(
            self, text="", height=26,
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=STATUS_COLOR, fg_color=STATUS_BG,
            corner_radius=4, anchor="w",
        )
        self.status_bar.pack(fill="x", padx=6, pady=(2, 6))

        # ── Start sessions ────────────────────────────────────────────────
        for pane in self.panes.values():
            pane.start(self._shell_command)

        # Initial focus
        if self._focused_id and self._focused_id in self.panes:
            self.after(100, lambda: self.panes[self._focused_id].focus_pane())
        self.refresh_status()
        self.after(140, self._switch_to_chat_mode)

        # Cleanup on close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_window_icon(self) -> None:
        png_path = os.path.join(self._project_root, "logo_w.png")
        ico_path = os.path.join(self._project_root, "logo_w.ico")

        if os.name == "nt":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "AgentCommander.App"
                )
            except Exception:
                pass

        if not os.path.isfile(ico_path) and os.path.isfile(png_path):
            try:
                from PIL import Image

                with Image.open(png_path) as img:
                    img = img.convert("RGBA")
                    img.save(
                        ico_path,
                        format="ICO",
                        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
                    )
            except Exception:
                pass

        if os.path.isfile(ico_path):
            try:
                self.iconbitmap(default=ico_path)
            except Exception:
                pass

        if os.path.isfile(png_path):
            try:
                self._app_icon_photo = tk.PhotoImage(file=png_path)
                self.iconphoto(True, self._app_icon_photo)
            except Exception:
                self._app_icon_photo = None

    def _safe_read_json(self, path: str) -> dict:
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _safe_write_json(self, path: str, payload: dict) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _task_id_for_event(self, pane_id: str, explicit_task_id: Optional[int] = None) -> int:
        if explicit_task_id is not None:
            return int(explicit_task_id)
        pane = self.panes.get(pane_id)
        if pane and pane._attached_task_id:
            return int(pane._attached_task_id)
        return int(self._pane_task_bindings.get(pane_id, 0) or 0)

    def _normalize_event_payload(self, payload: object) -> object:
        if payload is None:
            return {"_schema": "signal.v1"}
        if isinstance(payload, dict):
            normalized: dict[str, object] = dict(payload)
            normalized.setdefault("_schema", "signal.v1")
            text = normalized.get("text")
            if isinstance(text, str) and len(text) > EVENT_TEXT_LIMIT:
                normalized["text"] = text[-EVENT_TEXT_LIMIT:]
                normalized["truncated"] = True
                normalized["original_length"] = len(text)
            return normalized
        if isinstance(payload, (list, tuple)):
            return list(payload)
        return {"value": str(payload)}

    def _record_event(
        self,
        pane_id: str,
        event_type: str,
        payload: object = None,
        task_id: Optional[int] = None,
        agent: Optional[str] = None,
    ) -> None:
        if not hasattr(self, "_store"):
            return
        pane = self.panes.get(pane_id)
        resolved_agent = agent if agent is not None else (pane.startup_command if pane else "")
        resolved_task_id = self._task_id_for_event(pane_id, task_id)
        normalized_payload = self._normalize_event_payload(payload)
        try:
            self._store.append_event(
                pane_id=pane_id,
                task_id=resolved_task_id,
                agent=resolved_agent or "",
                event_type=event_type,
                payload=normalized_payload,
            )
        except Exception:
            # Event logging should never block UI workflows.
            pass

    def _normalize_agent_ids(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            agent_id = item.strip().lower()
            if agent_id in SETUP_AGENT_IDS and agent_id not in normalized:
                normalized.append(agent_id)
        return normalized

    def _resolve_agent_command(self, agent_id: str) -> str:
        for known_id, _, env_var, default_cmd in SETUP_AGENT_DEFS:
            if known_id == agent_id:
                return os.getenv(env_var, default_cmd)
        return agent_id

    def _detect_agents_local(self) -> dict[str, bool]:
        detected: dict[str, bool] = {}
        for agent_id in SETUP_AGENT_IDS:
            cmd = self._resolve_agent_command(agent_id)
            try:
                token = shlex.split(cmd)[0] if cmd else ""
            except Exception:
                token = cmd.strip().split(" ")[0] if cmd else ""
            detected[agent_id] = bool(token and shutil.which(token))
        return detected

    def _load_detected_agents(self) -> dict[str, bool]:
        raw = self._safe_read_json(self._launcher_check_path)
        detected_raw = raw.get("detected_agents")
        if not isinstance(detected_raw, dict):
            detected = self._detect_agents_local()
            self._safe_write_json(
                self._launcher_check_path,
                {
                    "version": 1,
                    "source": "app_fallback",
                    "checked_at": utc_now_iso(),
                    "detected_agents": detected,
                },
            )
            return detected
        detected: dict[str, bool] = {}
        for agent_id in SETUP_AGENT_IDS:
            detected[agent_id] = bool(detected_raw.get(agent_id, False))
        return detected

    def _refresh_detected_agents(self) -> None:
        self._agent_detected = self._detect_agents_local()
        self._safe_write_json(
            self._launcher_check_path,
            {
                "version": 1,
                "source": "app_refresh",
                "checked_at": utc_now_iso(),
                "detected_agents": self._agent_detected,
            },
        )

    def _save_setup_state(self, selected_agents: list[str], auto_completed: bool = False) -> None:
        payload = {
            "version": 1,
            "setup_complete": True,
            "selected_agents": selected_agents,
            "detected_agents": self._agent_detected,
            "auto_completed": auto_completed,
            "updated_at": utc_now_iso(),
        }
        self._safe_write_json(self._setup_state_path, payload)

    def _resolve_selected_agents(self) -> list[str]:
        setup_state = self._safe_read_json(self._setup_state_path)
        selected = self._normalize_agent_ids(setup_state.get("selected_agents"))
        setup_complete = bool(setup_state.get("setup_complete"))
        all_detected = all(self._agent_detected.get(agent_id, False) for agent_id in SETUP_AGENT_IDS)

        if setup_complete:
            if selected:
                return selected
            selected = list(SETUP_AGENT_IDS)
            self._save_setup_state(selected, auto_completed=False)
            return selected

        if all_detected:
            selected = list(SETUP_AGENT_IDS)
            self._save_setup_state(selected, auto_completed=True)
            return selected

        initial_selected = selected or [aid for aid in SETUP_AGENT_IDS if self._agent_detected.get(aid, False)]
        if not initial_selected:
            initial_selected = list(SETUP_AGENT_IDS)
        chosen = self._show_agent_setup_wizard(initial_selected)
        if not chosen:
            chosen = initial_selected
        self._save_setup_state(chosen, auto_completed=False)
        return chosen

    def _show_agent_setup_wizard(self, initial_selected: list[str]) -> Optional[list[str]]:
        dialog = ctk.CTkToplevel(self)
        dialog.title("Agent Setup")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 620, 360
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        result: dict[str, Optional[list[str]]] = {"selected": None}

        card = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        card.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            card,
            text="First Run Setup",
            font=ctk.CTkFont(family=FONT_FAMILY, size=16, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            card,
            text="Choose which agent CLIs you want to use. Only installed agents will auto-start in panes.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_COLOR,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 10))

        checks_frame = ctk.CTkFrame(card, fg_color="transparent")
        checks_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        vars_by_agent: dict[str, tk.BooleanVar] = {}
        for agent_id, display_name, _, _ in SETUP_AGENT_DEFS:
            installed = self._agent_detected.get(agent_id, False)
            var = tk.BooleanVar(value=(agent_id in initial_selected))
            vars_by_agent[agent_id] = var

            row = ctk.CTkFrame(checks_frame, fg_color="#10261a", corner_radius=6)
            row.pack(fill="x", pady=4)
            row.grid_columnconfigure(0, weight=1)

            ctk.CTkCheckBox(
                row,
                text=display_name,
                variable=var,
                onvalue=True,
                offvalue=False,
                text_color=TEXT_COLOR,
                fg_color=SEND_BG,
                hover_color=SEND_HOVER,
            ).grid(row=0, column=0, sticky="w", padx=10, pady=8)

            status_text = "Installed" if installed else "Not detected"
            status_color = "#58ff8a" if installed else "#ff8a8a"
            ctk.CTkLabel(
                row,
                text=status_text,
                text_color=status_color,
                font=ctk.CTkFont(family=FONT_FAMILY, size=10, weight="bold"),
            ).grid(row=0, column=1, sticky="e", padx=10)

        hint_label = ctk.CTkLabel(
            card,
            text="",
            text_color="#ff8a8a",
            font=ctk.CTkFont(family=FONT_FAMILY, size=10),
            anchor="w",
        )
        hint_label.pack(fill="x", padx=12, pady=(0, 6))

        def select_installed() -> None:
            for agent_id, var in vars_by_agent.items():
                var.set(bool(self._agent_detected.get(agent_id, False)))
            hint_label.configure(text="")

        def select_all() -> None:
            for var in vars_by_agent.values():
                var.set(True)
            hint_label.configure(text="")

        def save() -> None:
            selected_ids = [agent_id for agent_id, var in vars_by_agent.items() if var.get()]
            if not selected_ids:
                hint_label.configure(text="Select at least one agent.")
                return
            result["selected"] = selected_ids
            dialog.destroy()

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))

        ctk.CTkButton(
            btn_row,
            text="Select Installed",
            width=130,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=select_installed,
        ).pack(side="left")

        ctk.CTkButton(
            btn_row,
            text="Select All",
            width=100,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=select_all,
        ).pack(side="left", padx=(8, 0))

        ctk.CTkButton(
            btn_row,
            text="Save Setup",
            width=120,
            fg_color=SEND_BG,
            hover_color=SEND_HOVER,
            text_color=TITLE_COLOR,
            command=save,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", save)
        self.wait_window(dialog)
        return result["selected"]

    def _open_agent_setup_dialog(self) -> None:
        self._refresh_detected_agents()
        initial = self._selected_agent_ids or list(SETUP_AGENT_IDS)
        chosen = self._show_agent_setup_wizard(initial)
        if not chosen:
            return

        self._selected_agent_ids = chosen
        self._enabled_start_agent_ids = [
            agent_id for agent_id in chosen if self._agent_detected.get(agent_id, False)
        ]
        self._save_setup_state(chosen, auto_completed=False)

        enabled_now = ", ".join(agent_id.upper() for agent_id in self._enabled_start_agent_ids) or "none"
        if self._enabled_start_agent_ids:
            self._status_note = (
                f"Agent setup saved ({enabled_now}). Restart app to apply startup panes."
            )
        else:
            self._status_note = "Agent setup saved, but no selected agents are currently installed."
        self.refresh_status()

    # ── Shell detection ───────────────────────────────────────────────────

    def _detect_shell_command(self) -> str:
        override = os.getenv("TRIPTYCH_SHELL")
        if override:
            return override
        if os.name == "nt":
            win_shell = os.getenv("TRIPTYCH_WIN_SHELL")
            if win_shell:
                return win_shell
            if shutil.which("pwsh.exe"):
                return "pwsh.exe -NoLogo"
            return "powershell.exe -NoLogo"
        shell = os.getenv("SHELL", "/bin/bash")
        parsed = shlex.split(shell)
        return " ".join(parsed) if parsed else "/bin/bash"

    def _open_common_cache(self) -> None:
        cache_dir = os.path.join(self._project_root, COMMON_CACHE_DIRNAME)
        os.makedirs(cache_dir, exist_ok=True)

        try:
            if os.name == "nt":
                os.startfile(cache_dir)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", cache_dir])
            else:
                subprocess.Popen(["xdg-open", cache_dir])
            self._status_note = f"Opened {COMMON_CACHE_DIRNAME}"
        except Exception as exc:
            self._status_note = f"Failed to open {COMMON_CACHE_DIRNAME}: {exc}"
        self.refresh_status()

    # ── Focus management ──────────────────────────────────────────────────

    def _task_display_label(self, task: TaskRecord) -> str:
        return f"#{task.id} [{task.status}] {task.title}"

    def _task_summary_text(self, task: Optional[TaskRecord]) -> str:
        if not task:
            return "No tasks yet."
        folder = task.folder or "(no folder)"
        goal = task.goal.strip() or "-"
        if len(goal) > 72:
            goal = goal[:72].rstrip() + "..."
        return f"{self._task_display_label(task)} | folder: {folder} | goal: {goal}"

    def _refresh_task_board(self, selected_task_id: Optional[int] = None) -> None:
        self._tasks = self._store.list_tasks()
        self._tasks_by_id = {task.id: task for task in self._tasks}
        self._projects = self._store.list_projects()
        self._projects_by_id = {p.id: p for p in self._projects}
        self._task_choices = {}

        if not self._tasks and not self._projects:
            self._selected_task_id = None
            self.task_choice_menu.configure(values=["No items"])
            self._task_choice_var.set("No items")
            self.task_summary_label.configure(text="No tasks or projects yet.")
            self.refresh_status()
            return

        labels: list[str] = []
        for task in self._tasks:
            label = self._task_display_label(task)
            labels.append(label)
            self._task_choices[label] = ("task", task.id)
        for proj in self._projects:
            label = f"P#{proj.id} [{proj.status}] {proj.name}"
            labels.append(label)
            self._task_choices[label] = ("project", proj.id)

        self.task_choice_menu.configure(values=labels)

        # Try to keep selection
        if selected_task_id and selected_task_id in self._tasks_by_id:
            candidate_label = next(
                (l for l, v in self._task_choices.items()
                 if v == ("task", selected_task_id)), labels[0]
            )
        elif self._selected_task_id and self._selected_task_id in self._tasks_by_id:
            candidate_label = next(
                (l for l, v in self._task_choices.items()
                 if v == ("task", self._selected_task_id)), labels[0]
            )
        else:
            candidate_label = labels[0]

        self._task_choice_var.set(candidate_label)
        choice_val = self._task_choices.get(candidate_label)
        if choice_val and choice_val[0] == "task":
            self._selected_task_id = choice_val[1]
            self.task_summary_label.configure(
                text=self._task_summary_text(self._tasks_by_id.get(choice_val[1]))
            )
        elif choice_val and choice_val[0] == "project":
            self._selected_task_id = None
            proj = self._projects_by_id.get(choice_val[1])
            if proj:
                self.task_summary_label.configure(
                    text=f"P#{proj.id} [{proj.status}] {proj.name} | folder: {proj.folder}"
                )

        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()

        self.refresh_status()

    def _on_task_choice(self, choice: str) -> None:
        choice_val = self._task_choices.get(choice)
        if not choice_val:
            return
        kind, item_id = choice_val
        if kind == "task":
            self._selected_task_id = item_id
            self.task_summary_label.configure(
                text=self._task_summary_text(self._tasks_by_id.get(item_id))
            )
        elif kind == "project":
            self._selected_task_id = None
            proj = self._projects_by_id.get(item_id)
            if proj:
                self.task_summary_label.configure(
                    text=f"P#{proj.id} [{proj.status}] {proj.name} | folder: {proj.folder}"
                )
        self.refresh_status()

    def _show_new_task_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("New Task")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 620, 370
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        title_var = ctk.StringVar(value="")
        focused_pane = self.panes.get(self._focused_id or "")
        default_folder = focused_pane._cwd if focused_pane and focused_pane._cwd else ""
        folder_var = ctk.StringVar(value=default_folder)
        status_var = ctk.StringVar(value="todo")
        priority_var = ctk.StringVar(value="2")

        frame = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame,
            text="Create Task",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 8))

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row1, text="Title", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row1,
            textvariable=title_var,
            width=470,
            fg_color=INPUT_BG,
            text_color=TEXT_COLOR,
            border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row2, text="Folder", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row2,
            textvariable=folder_var,
            width=370,
            fg_color=INPUT_BG,
            text_color=TEXT_COLOR,
            border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse_folder() -> None:
            initial = folder_var.get().strip() or os.path.expanduser("~")
            picked = filedialog.askdirectory(initialdir=initial)
            if picked:
                folder_var.set(picked)

        ctk.CTkButton(
            row2,
            text="Browse",
            width=80,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=browse_folder,
        ).pack(side="left")

        row3 = ctk.CTkFrame(frame, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row3, text="Status", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row3,
            values=["todo", "in_progress", "paused", "blocked", "done"],
            variable=status_var,
            width=150,
            fg_color=BUTTON_BG,
            button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG,
            dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(row3, text="Priority", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row3,
            values=["1", "2", "3", "4", "5"],
            variable=priority_var,
            width=120,
            fg_color=BUTTON_BG,
            button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG,
            dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left")

        ctk.CTkLabel(frame, text="Goal", anchor="w").pack(anchor="w", padx=12, pady=(0, 4))
        goal_box = ctk.CTkTextbox(
            frame,
            height=84,
            fg_color=INPUT_BG,
            text_color=TEXT_COLOR,
            border_color=INPUT_BORDER,
            border_width=1,
        )
        goal_box.pack(fill="x", padx=12, pady=(0, 8))

        row4 = ctk.CTkFrame(frame, fg_color="transparent")
        row4.pack(fill="x", padx=12, pady=(2, 10))

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        def create_task() -> None:
            title = title_var.get().strip()
            if not title:
                self._status_note = "Task title is required."
                self.refresh_status()
                return

            task = self._store.create_task(
                title=title,
                folder=folder_var.get().strip(),
                goal=goal_box.get("1.0", "end-1c"),
                status=status_var.get().strip() or "todo",
                priority=int(priority_var.get().strip() or "2"),
            )
            self._record_event(
                "",
                "task_created",
                {"task_id": task.id, "task_title": task.title, "source": "new_task_dialog"},
                task_id=task.id,
            )
            self._write_task_brief(task)
            dialog.grab_release()
            dialog.destroy()
            self._status_note = f"Created task #{task.id}"
            self._refresh_task_board(selected_task_id=task.id)

        ctk.CTkButton(
            row4,
            text="Cancel",
            width=90,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            row4,
            text="Create",
            width=100,
            fg_color=SEND_BG,
            hover_color=SEND_HOVER,
            text_color=TITLE_COLOR,
            command=create_task,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)

    # ── Project creation dialog ──────────────────────────────────────────

    def _show_new_project_dialog(self) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("New Project")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 620, 460
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        name_var = ctk.StringVar(value="")
        focused_pane = self.panes.get(self._focused_id or "")
        default_folder = focused_pane._cwd if focused_pane and focused_pane._cwd else ""
        folder_var = ctk.StringVar(value=default_folder)

        frame = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame, text="Create Project",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 8))

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row1, text="Name", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row1, textvariable=name_var, width=470,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row2, text="Folder *", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row2, textvariable=folder_var, width=370,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse_folder() -> None:
            initial = folder_var.get().strip() or os.path.expanduser("~")
            picked = filedialog.askdirectory(initialdir=initial)
            if picked:
                folder_var.set(picked)

        ctk.CTkButton(
            row2, text="Browse", width=80,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=browse_folder,
        ).pack(side="left")

        ctk.CTkLabel(frame, text="Description", anchor="w").pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        desc_box = ctk.CTkTextbox(
            frame, height=60,
            fg_color=INPUT_BG, text_color=TEXT_COLOR,
            border_color=INPUT_BORDER, border_width=1,
        )
        desc_box.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(frame, text="Instructions (for PROJECT_CONTEXT.md)", anchor="w").pack(
            anchor="w", padx=12, pady=(0, 4)
        )
        instr_box = ctk.CTkTextbox(
            frame, height=80,
            fg_color=INPUT_BG, text_color=TEXT_COLOR,
            border_color=INPUT_BORDER, border_width=1,
        )
        instr_box.pack(fill="x", padx=12, pady=(0, 8))

        row_btns = ctk.CTkFrame(frame, fg_color="transparent")
        row_btns.pack(fill="x", padx=12, pady=(2, 10))

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        def create_project() -> None:
            name = name_var.get().strip()
            folder = folder_var.get().strip()
            if not name:
                self._status_note = "Project name is required."
                self.refresh_status()
                return
            if not folder:
                self._status_note = "Project folder is required."
                self.refresh_status()
                return

            description = desc_box.get("1.0", "end-1c").strip()
            instructions = instr_box.get("1.0", "end-1c").strip()

            project = self._store.create_project(
                name=name, folder=folder, description=description,
            )
            self._record_event(
                "",
                "project_created",
                {"project_id": project.id, "project_name": project.name, "source": "new_project_dialog"},
            )
            self._ensure_project_context_file(project, instructions)
            self._write_project_brief(project)

            dialog.grab_release()
            dialog.destroy()
            self._status_note = f"Created project #{project.id}: {project.name}"
            self._refresh_task_board()

        ctk.CTkButton(
            row_btns, text="Cancel", width=90,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            row_btns, text="Create", width=100,
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, command=create_project,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)

    # ── Edit dialog ────────────────────────────────────────────────────

    def _show_edit_dialog(self) -> None:
        choice_label = self._task_choice_var.get()
        choice_val = self._task_choices.get(choice_label)
        if not choice_val:
            self._status_note = "Nothing selected to edit."
            self.refresh_status()
            return

        kind, item_id = choice_val
        if kind == "task":
            self._show_edit_task_dialog(item_id)
        elif kind == "project":
            self._show_edit_project_dialog(item_id)

    def _show_edit_task_dialog(self, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            self._status_note = f"Task #{task_id} not found."
            self.refresh_status()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Edit Task #{task.id}")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 620, 370
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        title_var = ctk.StringVar(value=task.title)
        folder_var = ctk.StringVar(value=task.folder)
        status_var = ctk.StringVar(value=task.status)
        priority_var = ctk.StringVar(value=str(task.priority))

        frame = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame, text=f"Edit Task #{task.id}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 8))

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row1, text="Title", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row1, textvariable=title_var, width=470,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row2, text="Folder", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row2, textvariable=folder_var, width=370,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse_folder() -> None:
            initial = folder_var.get().strip() or os.path.expanduser("~")
            picked = filedialog.askdirectory(initialdir=initial)
            if picked:
                folder_var.set(picked)

        ctk.CTkButton(
            row2, text="Browse", width=80,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=browse_folder,
        ).pack(side="left")

        row3 = ctk.CTkFrame(frame, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row3, text="Status", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row3, values=["todo", "in_progress", "paused", "blocked", "done"],
            variable=status_var, width=150,
            fg_color=BUTTON_BG, button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG, dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(row3, text="Priority", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row3, values=["1", "2", "3", "4", "5"],
            variable=priority_var, width=120,
            fg_color=BUTTON_BG, button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG, dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left")

        ctk.CTkLabel(frame, text="Goal", anchor="w").pack(anchor="w", padx=12, pady=(0, 4))
        goal_box = ctk.CTkTextbox(
            frame, height=84,
            fg_color=INPUT_BG, text_color=TEXT_COLOR,
            border_color=INPUT_BORDER, border_width=1,
        )
        goal_box.pack(fill="x", padx=12, pady=(0, 8))
        goal_box.insert("1.0", task.goal)

        row4 = ctk.CTkFrame(frame, fg_color="transparent")
        row4.pack(fill="x", padx=12, pady=(2, 10))

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        def delete_task() -> None:
            if not self._delete_task(task.id, parent=dialog):
                return
            if dialog.winfo_exists():
                dialog.grab_release()
                dialog.destroy()

        def save() -> None:
            with self._store._connect() as conn:
                conn.execute(
                    "UPDATE tasks SET title=?, folder=?, goal=?, status=?, priority=?, updated_at=? WHERE id=?",
                    (title_var.get().strip(), folder_var.get().strip(),
                     goal_box.get("1.0", "end-1c").strip(),
                     status_var.get(), int(priority_var.get()),
                     utc_now_iso(), task.id),
                )
            dialog.grab_release()
            dialog.destroy()
            self._status_note = f"Updated task #{task.id}"
            self._refresh_task_board(selected_task_id=task.id)
            # Update brief
            updated = self._store.get_task(task.id)
            if updated:
                self._write_task_brief(updated)
                # Update strip if attached to any pane
                for pid, pane in self.panes.items():
                    if pane._attached_task_id == task.id:
                        pane.show_task_strip(updated)

        ctk.CTkButton(
            row4, text="Delete", width=100,
            fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color="#ffe5e5", command=delete_task,
        ).pack(side="left")
        ctk.CTkButton(
            row4, text="Cancel", width=90,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            row4, text="Save", width=100,
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, command=save,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)

    def _show_edit_project_dialog(self, project_id: int) -> None:
        project = self._store.get_project(project_id)
        if not project:
            self._status_note = f"Project #{project_id} not found."
            self.refresh_status()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Edit Project #{project.id}")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 620, 340
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        name_var = ctk.StringVar(value=project.name)
        folder_var = ctk.StringVar(value=project.folder)
        status_var = ctk.StringVar(value=project.status)

        frame = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame, text=f"Edit Project #{project.id}",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 8))

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row1, text="Name", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row1, textvariable=name_var, width=470,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row2, text="Folder", width=80, anchor="w").pack(side="left")
        ctk.CTkEntry(
            row2, textvariable=folder_var, width=370,
            fg_color=INPUT_BG, text_color=TEXT_COLOR, border_color=INPUT_BORDER,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        def browse_folder() -> None:
            initial = folder_var.get().strip() or os.path.expanduser("~")
            picked = filedialog.askdirectory(initialdir=initial)
            if picked:
                folder_var.set(picked)

        ctk.CTkButton(
            row2, text="Browse", width=80,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=browse_folder,
        ).pack(side="left")

        row3 = ctk.CTkFrame(frame, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row3, text="Status", width=80, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row3, values=["active", "paused", "archived"],
            variable=status_var, width=150,
            fg_color=BUTTON_BG, button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG, dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left")

        ctk.CTkLabel(frame, text="Description", anchor="w").pack(anchor="w", padx=12, pady=(0, 4))
        desc_box = ctk.CTkTextbox(
            frame, height=70,
            fg_color=INPUT_BG, text_color=TEXT_COLOR,
            border_color=INPUT_BORDER, border_width=1,
        )
        desc_box.pack(fill="x", padx=12, pady=(0, 8))
        desc_box.insert("1.0", project.description)

        row4 = ctk.CTkFrame(frame, fg_color="transparent")
        row4.pack(fill="x", padx=12, pady=(2, 10))

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        def delete_project() -> None:
            if not self._delete_project(project.id, parent=dialog):
                return
            if dialog.winfo_exists():
                dialog.grab_release()
                dialog.destroy()

        def save() -> None:
            with self._store._connect() as conn:
                conn.execute(
                    "UPDATE projects SET name=?, folder=?, description=?, status=?, updated_at=? WHERE id=?",
                    (name_var.get().strip(), folder_var.get().strip(),
                     desc_box.get("1.0", "end-1c").strip(),
                     status_var.get(), utc_now_iso(), project.id),
                )
            dialog.grab_release()
            dialog.destroy()
            self._status_note = f"Updated project #{project.id}"
            self._refresh_task_board()
            # Update brief
            updated = self._store.get_project(project.id)
            if updated:
                self._write_project_brief(updated)
                # Update strip if attached to any pane
                for pid, pane in self.panes.items():
                    if pane._attached_project_id == project.id:
                        pane.show_project_strip(updated)

        ctk.CTkButton(
            row4, text="Delete", width=100,
            fg_color=DANGER_BG, hover_color=DANGER_HOVER,
            text_color="#ffe5e5", command=delete_project,
        ).pack(side="left")
        ctk.CTkButton(
            row4, text="Cancel", width=90,
            fg_color=BUTTON_BG, hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR, command=cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            row4, text="Save", width=100,
            fg_color=SEND_BG, hover_color=SEND_HOVER,
            text_color=TITLE_COLOR, command=save,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)

    # ── Project file helpers ─────────────────────────────────────────────

    def _slugify(self, text: str) -> str:
        slug = re.sub(r'[^\w\s-]', '', text.lower().strip())
        return re.sub(r'[-\s]+', '_', slug)[:40]

    def _ensure_project_context_file(
        self, project: ProjectRecord, instructions: str = ""
    ) -> None:
        os.makedirs(project.folder, exist_ok=True)
        context_path = os.path.join(project.folder, "PROJECT_CONTEXT.md")
        if os.path.exists(context_path):
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = (
            f"# Project: {project.name}\n\n"
            f"## Description\n{project.description}\n\n"
            f"## Instructions\n{instructions or '(Fill in project instructions here)'}\n\n"
            f"## Current State\n(What is done, what is in progress)\n\n"
            f"## Last Iteration\nAgent: - | {now}\n"
            f"Done: Project created\nNext: Begin implementation\n\n"
            f"## Iteration Log\n### {now} -- System\n- Project initialized\n"
        )
        with open(context_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_project_brief(self, project: ProjectRecord) -> None:
        projects_dir = os.path.join(
            self._project_root, COMMON_CACHE_DIRNAME, "projects"
        )
        os.makedirs(projects_dir, exist_ok=True)
        slug = self._slugify(project.name)
        brief_path = os.path.join(projects_dir, f"{project.id}_{slug}.md")
        content = (
            f"# {project.name}\n"
            f"- Path: {project.folder}\n"
            f"- Status: {project.status}\n"
            f"- Created: {project.created_at}\n"
            f"- Description: {project.description}\n"
        )
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _write_task_brief(self, task: TaskRecord) -> None:
        tasks_dir = os.path.join(
            self._project_root, COMMON_CACHE_DIRNAME, "tasks"
        )
        os.makedirs(tasks_dir, exist_ok=True)
        slug = self._slugify(task.title)
        brief_path = os.path.join(tasks_dir, f"{task.id}_{slug}.md")
        content = (
            f"# Task #{task.id}: {task.title}\n"
            f"- Folder: {task.folder or '(none)'}\n"
            f"- Status: {task.status}\n"
            f"- Priority: {task.priority}\n"
            f"- Created: {task.created_at}\n"
        )
        if task.goal.strip():
            content += f"- Goal: {task.goal}\n"
        if task.dod.strip():
            content += f"- DoD: {task.dod}\n"
        with open(brief_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _remove_brief_files(self, kind: str, item_id: int) -> None:
        if kind == "task":
            base_dir = os.path.join(self._project_root, COMMON_CACHE_DIRNAME, "tasks")
        elif kind == "project":
            base_dir = os.path.join(self._project_root, COMMON_CACHE_DIRNAME, "projects")
        else:
            return
        if not os.path.isdir(base_dir):
            return
        pattern = os.path.join(base_dir, f"{item_id}_*.md")
        for path in glob.glob(pattern):
            try:
                os.remove(path)
            except OSError:
                continue

    def _detach_task_from_all_panes(self, task_id: int) -> list[str]:
        detached: list[str] = []
        for pane_id, pane in self.panes.items():
            if pane._attached_task_id == task_id or self._pane_task_bindings.get(pane_id) == task_id:
                if pane._attached_task_id == task_id:
                    pane.hide_task_strip()
                self._pane_task_bindings.pop(pane_id, None)
                self._store.clear_pane_binding(pane_id)
                detached.append(pane_id)
        stale = [pid for pid, tid in self._pane_task_bindings.items() if tid == task_id]
        for pane_id in stale:
            self._pane_task_bindings.pop(pane_id, None)
            self._store.clear_pane_binding(pane_id)
        return detached

    def _detach_project_from_all_panes(self, project_id: int) -> list[str]:
        detached: list[str] = []
        for pane_id, pane in self.panes.items():
            if pane._attached_project_id == project_id or self._pane_project_bindings.get(pane_id) == project_id:
                if pane._attached_project_id == project_id:
                    pane.hide_project_strip()
                self._pane_project_bindings.pop(pane_id, None)
                self._store.clear_pane_project_binding(pane_id)
                detached.append(pane_id)
        stale = [pid for pid, pid_value in self._pane_project_bindings.items() if pid_value == project_id]
        for pane_id in stale:
            self._pane_project_bindings.pop(pane_id, None)
            self._store.clear_pane_project_binding(pane_id)
        return detached

    def _chat_select_fallback_item(self) -> None:
        if self._layout_mode != "chat" or not hasattr(self, "_chat_sidebar"):
            return

        fallback_key: Optional[str] = None
        if self._focused_id and self._focused_id in self.panes:
            fallback_key = f"pane_{self._focused_id}"
        elif self.panes:
            fallback_key = f"pane_{next(iter(self.panes))}"
        elif self._projects:
            fallback_key = f"project_{self._projects[0].id}"
        elif self._tasks:
            fallback_key = f"task_{self._tasks[0].id}"

        if fallback_key:
            self._chat_select_item(fallback_key)
            return

        self._chat_selected_key = None
        if self._chat_active_pane:
            self._forget_pane_widget(self._chat_active_pane)
            self._chat_active_pane = None
        self._chat_preview.show_empty()
        self._chat_explorer.set_root(None, None)
        if hasattr(self, "_chat_conversation"):
            self._chat_conversation.set_context(None, None, None)
            self._chat_apply_surface_mode()
        self._chat_sidebar.refresh()
        self.refresh_status()

    def _delete_task(self, task_id: int, parent: Optional[tk.Widget] = None) -> bool:
        task = self._store.get_task(task_id)
        if not task:
            self._status_note = f"Task #{task_id} not found."
            self.refresh_status()
            return False

        answer = messagebox.askyesno(
            "Delete Task",
            f"Delete task #{task.id}: {task.title}?\n\nThis cannot be undone.",
            parent=parent or self,
        )
        if not answer:
            return False

        detached = self._detach_task_from_all_panes(task.id)
        deleted = self._store.delete_task(task.id)
        if not deleted:
            self._status_note = f"Failed to delete task #{task.id}"
            self.refresh_status()
            return False

        self._remove_brief_files("task", task.id)
        self._refresh_task_board()
        self._record_event(
            "",
            "task_deleted",
            {"task_id": task.id, "task_title": task.title, "detached_panes": detached},
            task_id=task.id,
        )

        if self._chat_selected_key == f"task_{task.id}":
            self._chat_selected_key = None
        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()
            self._chat_select_fallback_item()

        pane_note = ""
        if detached:
            pane_note = f" (detached from {', '.join(pid.upper() for pid in detached)})"
        self._status_note = f"Deleted task #{task.id}: {task.title}{pane_note}"
        self.refresh_status()
        return True

    def _delete_project(self, project_id: int, parent: Optional[tk.Widget] = None) -> bool:
        project = self._store.get_project(project_id)
        if not project:
            self._status_note = f"Project #{project_id} not found."
            self.refresh_status()
            return False

        answer = messagebox.askyesno(
            "Delete Project",
            f"Delete project #{project.id}: {project.name}?\n\nThis cannot be undone.",
            parent=parent or self,
        )
        if not answer:
            return False

        detached = self._detach_project_from_all_panes(project.id)
        deleted = self._store.delete_project(project.id)
        if not deleted:
            self._status_note = f"Failed to delete project #{project.id}"
            self.refresh_status()
            return False

        self._remove_brief_files("project", project.id)
        self._refresh_task_board()
        self._record_event(
            "",
            "project_deleted",
            {"project_id": project.id, "project_name": project.name, "detached_panes": detached},
        )

        if self._chat_selected_key == f"project_{project.id}":
            self._chat_selected_key = None
        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()
            self._chat_select_fallback_item()

        pane_note = ""
        if detached:
            pane_note = f" (detached from {', '.join(pid.upper() for pid in detached)})"
        self._status_note = f"Deleted project #{project.id}: {project.name}{pane_note}"
        self.refresh_status()
        return True

    def _build_starter_templates(self) -> tuple[list[dict[str, str]], list[dict[str, str | int]]]:
        starter_root = os.path.join(self._cache_dir, STARTER_WORKSPACE_DIRNAME)
        projects = [
            {
                "name": "Quickstart Project",
                "folder": os.path.join(starter_root, "quickstart_project"),
                "description": "Safe sandbox for trying project workflows and iteration logging.",
                "instructions": (
                    "Goal: explore Agent Commander flow end-to-end.\n"
                    "1) Read files in this folder.\n"
                    "2) Add notes into PROJECT_CONTEXT.md.\n"
                    "3) Produce a short Done/Next summary."
                ),
            },
            {
                "name": "Automation Playground",
                "folder": os.path.join(starter_root, "automation_playground"),
                "description": "Use this project to prototype scripts and command automation ideas.",
                "instructions": (
                    "Start with simple automation examples.\n"
                    "Keep the context concise and append each iteration in Iteration Log."
                ),
            },
        ]
        tasks: list[dict[str, str | int]] = [
            {
                "title": "First task: send prompt to agent",
                "folder": os.path.join(starter_root, "quickstart_project"),
                "goal": "Attach this task to any pane and run it from chat mode.",
                "dod": "Agent responds with a short 3-step plan and current next action.",
                "status": "todo",
                "priority": 1,
            },
            {
                "title": "Review workspace files",
                "folder": os.path.join(starter_root, "quickstart_project"),
                "goal": "Open file explorer in chat mode and inspect folders/files.",
                "dod": "Explorer tree is used at least once with one file opened from terminal.",
                "status": "todo",
                "priority": 2,
            },
            {
                "title": "Create and log a mini iteration",
                "folder": os.path.join(starter_root, "automation_playground"),
                "goal": "Use project log flow to store one Done/Next update.",
                "dod": "PROJECT_CONTEXT.md contains a new iteration entry.",
                "status": "todo",
                "priority": 2,
            },
        ]
        return projects, tasks

    def _apply_starter_templates(self, replace_existing: bool) -> tuple[int, int]:
        current_tasks = self._store.list_tasks()
        current_projects = self._store.list_projects()
        for task in current_tasks:
            if replace_existing:
                self._detach_task_from_all_panes(task.id)
                self._store.delete_task(task.id)
                self._remove_brief_files("task", task.id)
        for project in current_projects:
            if replace_existing:
                self._detach_project_from_all_panes(project.id)
                self._store.delete_project(project.id)
                self._remove_brief_files("project", project.id)

        if not replace_existing and (current_tasks or current_projects):
            return 0, 0

        self._pane_task_bindings = self._store.list_pane_bindings()
        self._pane_project_bindings = self._store.list_pane_project_bindings()

        projects, tasks = self._build_starter_templates()
        for spec in projects:
            folder = str(spec["folder"])
            os.makedirs(folder, exist_ok=True)
            project = self._store.create_project(
                name=str(spec["name"]),
                folder=folder,
                description=str(spec["description"]),
            )
            self._ensure_project_context_file(project, str(spec["instructions"]))
            self._write_project_brief(project)
        for spec in tasks:
            folder = str(spec["folder"])
            os.makedirs(folder, exist_ok=True)
            task = self._store.create_task(
                title=str(spec["title"]),
                folder=folder,
                goal=str(spec["goal"]),
                dod=str(spec["dod"]),
                status=str(spec["status"]),
                priority=int(spec["priority"]),
            )
            self._write_task_brief(task)

        self._refresh_task_board()
        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()
            self._chat_select_fallback_item()

        return len(tasks), len(projects)

    def _seed_starter_templates_if_empty(self) -> None:
        tasks_count, projects_count = self._apply_starter_templates(replace_existing=False)
        if tasks_count or projects_count:
            self._status_note = (
                f"Starter templates loaded: {tasks_count} tasks, {projects_count} projects."
            )
            self.refresh_status()

    def _load_starter_templates(self) -> None:
        current_tasks = self._store.list_tasks()
        current_projects = self._store.list_projects()

        answer = messagebox.askyesno(
            "Load Starter Templates",
            (
                "Replace current tasks/projects with starter templates?\n\n"
                f"Current data: {len(current_tasks)} tasks, {len(current_projects)} projects.\n"
                "This will delete current manager items."
            ),
            parent=self,
        )
        if not answer:
            return

        tasks_count, projects_count = self._apply_starter_templates(replace_existing=True)
        self._status_note = (
            f"Loaded starter templates: {tasks_count} tasks, {projects_count} projects."
        )
        self.refresh_status()

    def _attach_selected_task_to_focused(self) -> None:
        if not self._focused_id or self._focused_id not in self.panes:
            self._status_note = "No focused pane."
            self.refresh_status()
            return
        if not self._selected_task_id:
            self._status_note = "No selected task."
            self.refresh_status()
            return
        self._attach_task_to_pane(self._focused_id, self._selected_task_id)

    def _attach_task_to_pane(self, pane_id: str, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            self._status_note = f"Task #{task_id} not found."
            self.refresh_status()
            return
        pane = self.panes.get(pane_id)
        if not pane:
            return

        # Clear project binding if any (mutual exclusion)
        if pane._attached_project_id:
            pane.hide_project_strip()
            self._pane_project_bindings.pop(pane_id, None)

        self._pane_task_bindings[pane_id] = task_id
        self._store.set_pane_binding(pane_id, task_id)

        # Sync folder: if task has a folder different from pane's cwd, restart
        if task.folder and task.folder != (pane._cwd or ""):
            pane._cwd = task.folder
            pane._update_folder_label()
            if pane.session:
                pane.restart_session()

        pane.show_task_strip(task)
        self._record_event(
            pane_id,
            "task_attached",
            {"task_id": task.id, "task_title": task.title, "source": "manager_attach"},
            task_id=task.id,
            agent=pane.startup_command,
        )
        self._status_note = f"Attached task #{task_id} to {pane_id.upper()}"
        self._refresh_task_board()

    def _attach_project_to_pane(self, pane_id: str, project_id: int) -> None:
        project = self._store.get_project(project_id)
        if not project:
            self._status_note = f"Project #{project_id} not found."
            self.refresh_status()
            return
        pane = self.panes.get(pane_id)
        if not pane:
            return

        # Clear task binding if any (mutual exclusion)
        if pane._attached_task_id:
            pane.hide_task_strip()
            self._pane_task_bindings.pop(pane_id, None)

        self._pane_project_bindings[pane_id] = project_id
        self._store.set_pane_project_binding(pane_id, project_id)

        # Sync folder
        if project.folder and project.folder != (pane._cwd or ""):
            pane._cwd = project.folder
            pane._update_folder_label()
            if pane.session:
                pane.restart_session()

        pane.show_project_strip(project)
        self._record_event(
            pane_id,
            "project_attached",
            {"project_id": project.id, "project_name": project.name, "source": "manager_attach"},
            agent=pane.startup_command,
        )
        self._status_note = f"Attached project #{project_id} to {pane_id.upper()}"
        self._refresh_task_board()

    def _clear_focused_task_binding(self) -> None:
        if not self._focused_id or self._focused_id not in self.panes:
            self._status_note = "No focused pane."
            self.refresh_status()
            return

        pane = self.panes[self._focused_id]
        if pane._attached_task_id:
            pane.hide_task_strip()
            self._pane_task_bindings.pop(self._focused_id, None)
            self._store.clear_pane_binding(self._focused_id)
            self._status_note = f"Cleared task binding for {self._focused_id.upper()}"
        elif pane._attached_project_id:
            pane.hide_project_strip()
            self._pane_project_bindings.pop(self._focused_id, None)
            self._store.clear_pane_project_binding(self._focused_id)
            self._status_note = f"Cleared project binding for {self._focused_id.upper()}"
        else:
            self._status_note = f"No binding on {self._focused_id.upper()}"
        self.refresh_status()

    def _task_for_pane(self, pane_id: Optional[str]) -> Optional[TaskRecord]:
        if not pane_id:
            return None
        task_id = self._pane_task_bindings.get(pane_id)
        if not task_id:
            return None
        task = self._tasks_by_id.get(task_id)
        if task:
            return task
        return self._store.get_task(task_id)

    def _project_for_pane(self, pane_id: Optional[str]) -> Optional[ProjectRecord]:
        if not pane_id:
            return None
        project_id = self._pane_project_bindings.get(pane_id)
        if not project_id:
            return None
        return self._store.get_project(project_id)

    def _reflow_panes(self) -> None:
        total_cols = max(self.pane_row.grid_size()[0], len(self.panes))
        for col in range(total_cols + 1):
            self.pane_row.columnconfigure(col, weight=0)

        for col, pane in enumerate(self.panes.values()):
            self.pane_row.columnconfigure(col, weight=1)
            pane.grid_forget()
            pane.grid(in_=self.pane_row, row=0, column=col, sticky="nsew", padx=3, pady=2)

        self.pane_row.rowconfigure(0, weight=1)

    def _next_dynamic_pane_id(self) -> str:
        while True:
            self._pane_seq += 1
            pane_id = f"pane{self._pane_seq}"
            if pane_id not in self.panes:
                return pane_id

    def _create_pane(self, startup_cmd: str, cwd: Optional[str]) -> None:
        pane_id = self._next_dynamic_pane_id()
        pane = AgentPane(self, pane_id, f"PANE {self._pane_seq}", startup_cmd, self)
        if cwd:
            pane._cwd = cwd
            pane._update_folder_label()
        self.panes[pane_id] = pane
        self._reflow_panes()
        pane.start(self._shell_command)
        pane.focus_pane()

        if not self.source_pane or self.source_pane not in self.panes:
            self.source_pane = pane_id

        self._record_event(
            pane_id,
            "pane_created",
            {"pane_id": pane_id, "agent": startup_cmd, "cwd": cwd or ""},
            agent=startup_cmd,
        )
        cwd_note = f" @ {cwd}" if cwd else ""
        self._status_note = f"Added {pane_id.upper()} ({startup_cmd}{cwd_note})"
        self.refresh_status()
        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()
            self._chat_select_item(f"pane_{pane_id}")

    def _show_new_pane_dialog(self, initial_agent: str, initial_cwd: Optional[str]) -> None:
        dialog = ctk.CTkToplevel(self)
        dialog.title("New Pane Setup")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        width, height = 520, 240
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - width) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - height) // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        agent_var = ctk.StringVar(value=initial_agent)
        folder_var = ctk.StringVar(value=initial_cwd or "")

        frame = ctk.CTkFrame(dialog, fg_color="#0d2016", border_color="#1f5a3b", border_width=1)
        frame.pack(fill="both", expand=True, padx=12, pady=12)

        ctk.CTkLabel(
            frame,
            text="Create New Terminal Pane",
            font=ctk.CTkFont(family=FONT_FAMILY, size=14, weight="bold"),
            text_color=TITLE_COLOR,
        ).pack(anchor="w", padx=12, pady=(10, 6))

        ctk.CTkLabel(
            frame,
            text="Pick agent and optional working folder before launch.",
            font=ctk.CTkFont(family=FONT_FAMILY, size=11),
            text_color=TEXT_COLOR,
        ).pack(anchor="w", padx=12, pady=(0, 10))

        row1 = ctk.CTkFrame(frame, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(row1, text="Agent", width=70, anchor="w").pack(side="left")
        ctk.CTkOptionMenu(
            row1,
            values=AGENT_COMMANDS,
            variable=agent_var,
            width=150,
            height=28,
            fg_color=BUTTON_BG,
            button_color=BUTTON_HOVER,
            button_hover_color=SEND_BG,
            dropdown_fg_color=PANE_BG,
            dropdown_hover_color=BUTTON_HOVER,
            dropdown_text_color=TEXT_COLOR,
        ).pack(side="left")

        row2 = ctk.CTkFrame(frame, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkLabel(row2, text="Folder", width=70, anchor="w").pack(side="left")
        folder_entry = ctk.CTkEntry(
            row2,
            textvariable=folder_var,
            width=300,
            fg_color=INPUT_BG,
            text_color=TEXT_COLOR,
            border_color=INPUT_BORDER,
        )
        folder_entry.pack(side="left", padx=(0, 6), fill="x", expand=True)

        def browse_folder() -> None:
            initial = folder_var.get().strip() or os.path.expanduser("~")
            picked = filedialog.askdirectory(initialdir=initial)
            if picked:
                folder_var.set(picked)

        ctk.CTkButton(
            row2,
            text="Browse",
            width=80,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=browse_folder,
        ).pack(side="left")

        row3 = ctk.CTkFrame(frame, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(6, 10))

        def cancel() -> None:
            dialog.grab_release()
            dialog.destroy()

        def create() -> None:
            agent = agent_var.get().strip() or "codex"
            folder = folder_var.get().strip() or None
            dialog.grab_release()
            dialog.destroy()
            self._create_pane(agent, folder)

        ctk.CTkButton(
            row3,
            text="Cancel",
            width=90,
            fg_color=BUTTON_BG,
            hover_color=BUTTON_HOVER,
            text_color=TEXT_COLOR,
            command=cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            row3,
            text="Create Pane",
            width=110,
            fg_color=SEND_BG,
            hover_color=SEND_HOVER,
            text_color=TITLE_COLOR,
            command=create,
        ).pack(side="right")

        dialog.protocol("WM_DELETE_WINDOW", cancel)

    def _add_pane(self, source_pane_id: Optional[str] = None) -> None:
        focused = self.panes.get(source_pane_id or self._focused_id or "")
        startup_cmd = (
            focused.startup_command
            if focused
            else os.getenv("TRIPTYCH_CODEX_CMD", "codex")
        )
        initial_cwd = focused._cwd if focused else None
        self._show_new_pane_dialog(startup_cmd, initial_cwd)

    def _remove_pane(self, pane_id: Optional[str] = None) -> None:
        if len(self.panes) <= 1:
            self._status_note = "Cannot remove the last pane."
            self.refresh_status()
            return

        if pane_id and pane_id in self.panes:
            target_id = pane_id
        else:
            target_id = self._focused_id if self._focused_id in self.panes else next(iter(self.panes))
        self._pane_task_bindings.pop(target_id, None)
        self._store.clear_pane_binding(target_id)
        self._pane_project_bindings.pop(target_id, None)
        self._store.clear_pane_project_binding(target_id)
        pane = self.panes.pop(target_id)
        self._record_event(
            target_id,
            "pane_removed",
            {"pane_id": target_id, "agent": pane.startup_command},
            task_id=0,
            agent=pane.startup_command,
        )
        pane.stop()
        pane.destroy()
        if getattr(self, "_chat_active_pane", None) is pane:
            self._chat_active_pane = None
        self._reflow_panes()

        if self.source_pane == target_id:
            self.source_pane = next(iter(self.panes), None)

        self._focused_id = next(iter(self.panes), None)
        if self._focused_id and self._focused_id in self.panes:
            self.after(30, lambda: self.panes[self._focused_id].focus_pane())

        self._status_note = f"Removed {target_id.upper()}"
        self.refresh_status()
        if self._layout_mode == "chat" and hasattr(self, "_chat_sidebar"):
            self._chat_sidebar.refresh()
            removed_key = f"pane_{target_id}"
            if self._chat_selected_key == removed_key or not self._chat_selected_key:
                self._chat_select_fallback_item()
            else:
                self._chat_select_item(self._chat_selected_key)

    def _remove_focused_pane(self) -> None:
        self._remove_pane(self._focused_id)

    def on_pane_focused(self, pane_id: str) -> None:
        self._focused_id = pane_id
        for pid, pane in self.panes.items():
            if pid != pane_id:
                pane.blur_pane()
        self.refresh_status()

    def _cycle_focus(self, direction: int) -> None:
        ids = list(self.panes.keys())
        if not ids:
            return
        idx = ids.index(self._focused_id) if self._focused_id in ids else 0
        next_id = ids[(idx + direction) % len(ids)]
        self.panes[next_id].focus_pane()

    # ── Global key handler ────────────────────────────────────────────────

    def handle_global_key(self, event: tk.Event) -> bool:
        keysym = event.keysym
        state = event.state

        shift = bool(state & 0x1)
        ctrl = bool(state & 0x4)

        if ctrl and keysym.lower() == "q":
            self._on_close()
            return True
        if ctrl and keysym.lower() == "n":
            self._add_pane()
            return True
        if ctrl and shift and keysym.lower() == "w":
            self._remove_focused_pane()
            return True

        if keysym == "Tab" and not shift:
            self._cycle_focus(1)
            return True
        if keysym == "ISO_Left_Tab" or (keysym == "Tab" and shift):
            self._cycle_focus(-1)
            return True

        if not shift and keysym in ("F1", "F2", "F3"):
            idx_map = {"F1": 0, "F2": 1, "F3": 2}
            ids = list(self.panes.keys())
            idx = idx_map[keysym]
            if idx >= len(ids):
                self._status_note = f"No pane assigned to {keysym}."
                self.refresh_status()
                return True
            self.source_pane = ids[idx]
            self._status_note = f"Source set to {ids[idx].upper()}"
            self.refresh_status()
            return True

        if shift and keysym in ("F1", "F2", "F3"):
            idx_map = {"F1": 0, "F2": 1, "F3": 2}
            ids = list(self.panes.keys())
            idx = idx_map[keysym]
            if idx >= len(ids):
                self._status_note = f"No target pane assigned to Shift+{keysym}."
                self.refresh_status()
                return True
            self._pipe_to(ids[idx])
            return True

        return False

    # ── Piping ────────────────────────────────────────────────────────────

    def _pipe_to(self, target_id: str) -> None:
        if target_id not in self.panes:
            self._status_note = f"Target pane {target_id.upper()} is missing."
            self.refresh_status()
            return
        if not self.source_pane or self.source_pane not in self.panes:
            self._status_note = "Pick a source first (F1/F2/F3)."
            self.refresh_status()
            return
        if self.source_pane == target_id:
            self._status_note = "Source and target are the same."
            self.refresh_status()
            return

        source = self.panes[self.source_pane]
        target = self.panes[target_id]
        payload = source.grab_context(50)
        if not payload:
            self._status_note = "No context in source buffer yet."
            self.refresh_status()
            return

        target.send_text(payload + "\n")
        self._record_event(
            target_id,
            "context_injected",
            {
                "source_pane": self.source_pane,
                "target_pane": target_id,
                "lines": 50,
                "text": payload,
            },
            task_id=self._pane_task_bindings.get(target_id, 0),
            agent=target.startup_command,
        )
        self._status_note = (
            f"Injected 50 lines: {self.source_pane.upper()} -> {target_id.upper()}"
        )
        self.refresh_status()

    # ── Status bar ────────────────────────────────────────────────────────

    def refresh_status(self) -> None:
        if not hasattr(self, "status_bar"):
            return

        if self._layout_mode == "chat":
            selected = self._chat_selected_key or "none"
            chat_pane_count = len(self.panes)
            status = (
                f"  Mode: CHAT ({self._chat_surface_mode.upper()})    Selected: {selected}    "
                f"Active sessions: {chat_pane_count}    "
                f"Ctrl+Q quit    |    {self._status_note}"
            )
            self.status_bar.configure(text=status)
            return

        focus = (self._focused_id or "none").upper()
        source = (self.source_pane or "none").upper()
        pane_count = len(self.panes)

        focused_task = self._task_for_pane(self._focused_id)
        focused_project = self._project_for_pane(self._focused_id)
        if focused_task:
            t = focused_task.title
            if len(t) > 28:
                t = t[:28].rstrip() + "..."
            binding_text = f"Task#{focused_task.id}:{focused_task.status}:{t}"
        elif focused_project:
            n = focused_project.name
            if len(n) > 28:
                n = n[:28].rstrip() + "..."
            binding_text = f"Proj#{focused_project.id}:{focused_project.status}:{n}"
        else:
            binding_text = "none"

        status = (
            f"  Panes: {pane_count}    Focus: {focus}    Binding: {binding_text}    Source: {source}    "
            f"F1/F2/F3 select source    Shift+F1/F2/F3 inject to target    "
            f"Tab cycle focus    Ctrl+N add pane    Ctrl+Shift+W remove pane    "
            f"Ctrl+Q quit    |    {self._status_note}"
        )
        self.status_bar.configure(text=status)

    # ── Layout mode toggle ────────────────────────────────────────────────

    def _toggle_layout_mode(self) -> None:
        if self._layout_mode == "grid":
            self._switch_to_chat_mode()
        else:
            self._switch_to_grid_mode()

    def _chat_set_surface_mode(self, mode: str) -> None:
        if mode not in {"chat", "terminal"}:
            return
        self._chat_surface_mode = mode
        if hasattr(self, "_chat_conversation"):
            self._chat_conversation.set_surface_mode(mode)
        if self._layout_mode == "chat":
            self._chat_apply_surface_mode()
            self._status_note = (
                "Chat surface active" if mode == "chat" else "Raw terminal surface active"
            )
            self.refresh_status()

    def _chat_apply_surface_mode(self) -> None:
        if not hasattr(self, "_chat_conversation"):
            return
        pane = self._chat_active_pane
        if self._chat_surface_mode == "terminal":
            if not pane:
                self._chat_conversation.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
                self._chat_conversation.lift()
                return
            self._chat_conversation.place_forget()
            if pane:
                self._forget_pane_widget(pane)
                self._chat_pane_area.update_idletasks()
                pane.place(in_=self._chat_pane_area, relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
                pane.lift()
                self.after_idle(lambda p=pane: self._chat_refresh_active_pane_layout(p))
                pane.focus_pane()
            return

        if pane:
            self._forget_pane_widget(pane)
        self._chat_conversation.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        self._chat_conversation.lift()
        self._chat_conversation.focus_input()

    def _switch_to_chat_mode(self) -> None:
        self._layout_mode = "chat"
        self.layout_toggle_btn.configure(text="\u2630 Grid Mode")
        self._chat_conversation.set_surface_mode(self._chat_surface_mode)

        # Hide grid-mode widgets
        self.task_board.pack_forget()
        self.pane_row.pack_forget()

        # Show chat container (between main_menu and status_bar)
        self._chat_container.pack(fill="both", expand=True, padx=6, pady=(2, 2),
                                  after=self.main_menu)

        # Refresh data and sidebar
        self._refresh_task_board()
        self._chat_sidebar.refresh()
        self._chat_container.update_idletasks()

        # Select current item if available, otherwise fallback.
        target_key = self._chat_selected_key
        if not target_key:
            if self._focused_id and self._focused_id in self.panes:
                target_key = f"pane_{self._focused_id}"
            elif self.panes:
                first_pane = next(iter(self.panes))
                target_key = f"pane_{first_pane}"
            elif self._projects:
                target_key = f"project_{self._projects[0].id}"
            elif self._tasks:
                target_key = f"task_{self._tasks[0].id}"

        if target_key:
            self._chat_select_item(target_key)
        else:
            self._chat_preview.show_empty()
            self._chat_explorer.set_root(None, None)
            self._chat_conversation.set_context(None, None, None)
            self._chat_apply_surface_mode()

        self._status_note = "Switched to Chat mode"
        self.refresh_status()

    def _switch_to_grid_mode(self) -> None:
        self._layout_mode = "grid"
        self.layout_toggle_btn.configure(text="\u2630 Chat Mode")

        # Hide chat container and active pane
        if self._chat_active_pane:
            self._forget_pane_widget(self._chat_active_pane)
        self._chat_container.pack_forget()

        # Return borrowed grid panes
        for pane in self.panes.values():
            if getattr(pane, "_chat_borrowed", False):
                pane._chat_borrowed = False  # type: ignore[attr-defined]
                self._forget_pane_widget(pane)

        # Restore grid widgets
        self.task_board.pack(fill="x", padx=6, pady=(2, 2), after=self.main_menu)
        self.pane_row.pack(fill="both", expand=True, padx=6, pady=(2, 2),
                           after=self.task_board)
        self._reflow_panes()

        if self._focused_id and self._focused_id in self.panes:
            self.after(30, lambda: self.panes[self._focused_id].focus_pane())

        self._status_note = "Switched to Grid mode"
        self.refresh_status()

    # ── Chat mode: select / show / actions ─────────────────────────────

    def _chat_select_item(self, key: str) -> None:
        self._chat_selected_key = key

        if key.startswith("project_"):
            project_id = int(key.split("_", 1)[1])
            project = self._store.get_project(project_id)
            if project:
                self._chat_preview.show_project(project)
        elif key.startswith("task_"):
            task_id = int(key.split("_", 1)[1])
            task = self._store.get_task(task_id)
            if task:
                self._chat_preview.show_task(task)
        elif key.startswith("pane_"):
            pane_id = key.split("_", 1)[1]
            pane = self.panes.get(pane_id)
            if pane:
                self._chat_preview.show_pane(pane)

        root_folder = self._chat_resolve_folder_for_key(key)
        self._chat_explorer.set_root(root_folder, key)
        self._chat_show_pane_for_key(key)
        self._chat_sidebar.refresh()
        self.refresh_status()

    def _forget_pane_widget(self, pane: AgentPane) -> None:
        try:
            if not pane.winfo_exists():
                return
            manager = pane.winfo_manager()
        except Exception:
            return
        if manager == "pack":
            pane.pack_forget()
        elif manager == "grid":
            pane.grid_forget()
        elif manager == "place":
            pane.place_forget()

    def _chat_find_bound_pane_for_task(self, task_id: int) -> Optional[str]:
        if self._focused_id and self._pane_task_bindings.get(self._focused_id) == task_id:
            return self._focused_id
        for pane_id, bound_task_id in self._pane_task_bindings.items():
            if bound_task_id == task_id and pane_id in self.panes:
                return pane_id
        return None

    def _chat_find_bound_pane_for_project(self, project_id: int) -> Optional[str]:
        if self._focused_id and self._pane_project_bindings.get(self._focused_id) == project_id:
            return self._focused_id
        for pane_id, bound_project_id in self._pane_project_bindings.items():
            if bound_project_id == project_id and pane_id in self.panes:
                return pane_id
        return None

    def _chat_resolve_pane_for_key(self, key: str) -> Optional[AgentPane]:
        pane_id: Optional[str] = None
        if key.startswith("pane_"):
            pane_id = key.split("_", 1)[1]
        elif key.startswith("task_"):
            task_id = int(key.split("_", 1)[1])
            pane_id = self._chat_find_bound_pane_for_task(task_id)
        elif key.startswith("project_"):
            project_id = int(key.split("_", 1)[1])
            pane_id = self._chat_find_bound_pane_for_project(project_id)

        if not pane_id:
            if self._focused_id and self._focused_id in self.panes:
                pane_id = self._focused_id
            elif self.panes:
                pane_id = next(iter(self.panes))

        if not pane_id:
            return None
        return self.panes.get(pane_id)

    def _chat_folder_for_pane(self, pane: Optional[AgentPane]) -> Optional[str]:
        if not pane:
            return None
        if pane._cwd:
            return pane._cwd
        if pane._attached_task_id:
            task = self._store.get_task(pane._attached_task_id)
            if task and task.folder:
                return task.folder
        if pane._attached_project_id:
            project = self._store.get_project(pane._attached_project_id)
            if project and project.folder:
                return project.folder
        return None

    def _chat_resolve_folder_for_key(self, key: str) -> Optional[str]:
        if key.startswith("project_"):
            project_id = int(key.split("_", 1)[1])
            project = self._store.get_project(project_id)
            if project and project.folder:
                return project.folder
        elif key.startswith("task_"):
            task_id = int(key.split("_", 1)[1])
            task = self._store.get_task(task_id)
            if task and task.folder:
                return task.folder
        elif key.startswith("pane_"):
            pane_id = key.split("_", 1)[1]
            return self._chat_folder_for_pane(self.panes.get(pane_id))

        return self._chat_folder_for_pane(self._chat_resolve_pane_for_key(key))

    def _chat_show_pane_for_key(self, key: str) -> None:
        prev_active = self._chat_active_pane
        pane = self._chat_resolve_pane_for_key(key)
        if prev_active and prev_active is not pane:
            self._forget_pane_widget(prev_active)
        self._chat_active_pane = pane
        task_id: Optional[int] = None
        if key.startswith("task_"):
            task_id = int(key.split("_", 1)[1])
        pane_id = pane.pane_id if pane else None

        if pane:
            pane._chat_borrowed = True  # type: ignore[attr-defined]

        self._chat_conversation.set_context(key, pane_id, task_id)
        self._chat_apply_surface_mode()

    def _chat_refresh_active_pane_layout(self, pane: AgentPane) -> None:
        if self._layout_mode != "chat" or self._chat_surface_mode != "terminal" or self._chat_active_pane is not pane:
            return
        self._chat_pane_area.update_idletasks()
        pane.place(in_=self._chat_pane_area, relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)
        pane.lift()

    def _chat_action_run_task(self, task_id: int) -> None:
        task = self._store.get_task(task_id)
        if not task:
            return
        key = f"task_{task_id}"
        self._chat_show_pane_for_key(key)
        pane = self._chat_active_pane
        if not pane:
            self._status_note = "No active pane available."
            self.refresh_status()
            return

        self._record_event(
            pane.pane_id,
            "ui_task_run_clicked",
            {"task_id": task.id, "task_title": task.title, "source": "chat_preview_run"},
            task_id=task.id,
            agent=pane.startup_command,
        )
        self._attach_task_to_pane(pane.pane_id, task_id)

        folder = task.folder or pane._cwd or "(not set)"
        parts = [f"Working directory: {folder}", f"Task: {task.title}"]
        if task.goal.strip():
            parts.append(f"Goal: {task.goal}")
        if task.dod.strip():
            parts.append(f"Definition of Done: {task.dod}")
        parts += ["", "Begin working on this task."]
        pane._submit_terminal_input("\n".join(parts), source="chat_task_run")

        prev_status = task.status
        self._store.update_task_status(task.id, "in_progress")
        self._record_event(
            pane.pane_id,
            "task_status_changed",
            {"task_id": task.id, "from": prev_status, "to": "in_progress", "source": "chat_task_run"},
            task_id=task.id,
            agent=pane.startup_command,
        )
        self._refresh_task_board()
        updated = self._store.get_task(task_id)
        if updated:
            self._chat_preview.show_task(updated)
        self._chat_sidebar.refresh()
        self._status_note = f"Task #{task_id} sent to {pane.pane_id.upper()}"
        self.refresh_status()

    def _chat_action_pause_task(self, task_id: int) -> None:
        task_before = self._store.get_task(task_id)
        pane_id = self._chat_find_bound_pane_for_task(task_id) or (self._focused_id or "")
        pane = self.panes.get(pane_id) if pane_id else None
        self._store.update_task_status(task_id, "paused")
        self._record_event(
            pane_id,
            "task_status_changed",
            {
                "task_id": task_id,
                "from": task_before.status if task_before else "",
                "to": "paused",
                "source": "chat_task_pause",
            },
            task_id=task_id,
            agent=pane.startup_command if pane else "",
        )
        self._refresh_task_board()
        task = self._store.get_task(task_id)
        if task:
            self._chat_preview.show_task(task)
        self._chat_sidebar.refresh()
        self._status_note = f"Task #{task_id} paused"
        self.refresh_status()

    def _chat_action_done_task(self, task_id: int) -> None:
        task_before = self._store.get_task(task_id)
        pane_id = self._chat_find_bound_pane_for_task(task_id) or (self._focused_id or "")
        pane = self.panes.get(pane_id) if pane_id else None
        self._store.update_task_status(task_id, "done")
        self._record_event(
            pane_id,
            "task_status_changed",
            {
                "task_id": task_id,
                "from": task_before.status if task_before else "",
                "to": "done",
                "source": "chat_task_done",
            },
            task_id=task_id,
            agent=pane.startup_command if pane else "",
        )
        self._refresh_task_board()
        task = self._store.get_task(task_id)
        if task:
            self._chat_preview.show_task(task)
        self._chat_sidebar.refresh()
        self._status_note = f"Task #{task_id} done"
        self.refresh_status()

    def _chat_action_delete_task(self, task_id: int) -> None:
        self._delete_task(task_id)

    def _chat_action_enter_project(self, project_id: int) -> None:
        project = self._store.get_project(project_id)
        if not project:
            return
        key = f"project_{project_id}"
        self._chat_show_pane_for_key(key)
        pane = self._chat_active_pane
        if not pane:
            self._status_note = "No active pane available."
            self.refresh_status()
            return

        self._record_event(
            pane.pane_id,
            "ui_project_start_clicked",
            {"project_id": project.id, "project_name": project.name, "source": "chat_preview_start"},
            agent=pane.startup_command,
        )
        self._attach_project_to_pane(pane.pane_id, project_id)

        context_path = os.path.join(project.folder, "PROJECT_CONTEXT.md")
        if not os.path.isfile(context_path):
            self._status_note = f"No PROJECT_CONTEXT.md in {project.folder}"
            self.refresh_status()
            return

        try:
            with open(context_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            self._status_note = f"Error reading context: {exc}"
            self.refresh_status()
            return

        prompt = (
            f"Project: {project.name}\nFolder: {project.folder}\n\n"
            f"Here is the current project context document:\n\n{content}\n\n"
            f"Continue working on this project based on the context above."
        )
        pane._submit_terminal_input(prompt, source="chat_project_start")
        self._status_note = f"Project context sent to {pane.pane_id.upper()}"
        self.refresh_status()

    def _chat_action_log_project(self, project_id: int) -> None:
        key = f"project_{project_id}"
        self._chat_show_pane_for_key(key)
        pane = self._chat_active_pane
        if not pane:
            self._status_note = "No active pane available."
            self.refresh_status()
            return
        project = self._store.get_project(project_id)
        self._record_event(
            pane.pane_id,
            "ui_project_log_clicked",
            {
                "project_id": project_id,
                "project_name": project.name if project else "",
                "source": "chat_preview_log",
            },
            agent=pane.startup_command,
        )
        prompt = (
            "Please summarize what you accomplished in this iteration. "
            "Format your response as:\n"
            "Done: <what was completed>\n"
            "Next: <what should be done next>\n\n"
            "Keep it concise (3-5 bullet points each)."
        )
        pane._submit_terminal_input(prompt, source="chat_project_log")
        self._status_note = f"Requested iteration log from {pane.pane_id.upper()}"
        self.refresh_status()

    def _chat_action_delete_project(self, project_id: int) -> None:
        self._delete_project(project_id)

    # ── Cleanup ───────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        for pane in self.panes.values():
            pane.stop()
        self.destroy()


if __name__ == "__main__":
    app = TriptychApp()
    app.mainloop()
