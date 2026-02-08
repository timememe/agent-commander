import os
import re
import shutil
import shlex
import subprocess
import threading
from collections import deque
from typing import Optional, Protocol

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.events import Click, Key
from textual.widgets import Label, RichLog, Static

ANSI_RE = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


class PTYBackend(Protocol):
    def read(self) -> str:
        ...

    def write(self, data: str) -> None:
        ...

    def close(self) -> None:
        ...


class UnixPexpectBackend:
    def __init__(self, command: str) -> None:
        import pexpect

        self._pexpect = pexpect
        self._proc = pexpect.spawn(
            command,
            encoding="utf-8",
            codec_errors="ignore",
            echo=False,
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

    def close(self) -> None:
        if self._proc.isalive():
            self._proc.close(force=True)


class WinptyBackend:
    def __init__(self, command: str) -> None:
        from winpty import Backend, PtyProcess

        env = dict(os.environ)
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")

        # Prefer ConPTY for better compatibility with modern interactive TUIs.
        launch_attempts = (
            {"backend": Backend.ConPTY},
            {"backend": Backend.WinPTY},
            {},
        )
        last_error: Optional[Exception] = None
        self._proc = None
        for extra in launch_attempts:
            try:
                self._proc = PtyProcess.spawn(command, env=env, **extra)
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

    def close(self) -> None:
        try:
            self._proc.close()
        except Exception:
            pass


class SubprocessFallbackBackend:
    def __init__(self, command: str) -> None:
        self._proc = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
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

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
        except Exception:
            pass


class ShellSession:
    def __init__(self, app: "TriptychApp", pane: "AgentPane", shell_command: str) -> None:
        self.app = app
        self.pane = pane
        self.shell_command = shell_command
        self.backend: Optional[PTYBackend] = None
        self._running = False
        self._reader: Optional[threading.Thread] = None

    def start(self) -> None:
        self.backend = self._build_backend(self.shell_command)
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _build_backend(self, command: str) -> PTYBackend:
        if os.name == "nt":
            try:
                return WinptyBackend(command)
            except Exception:
                return SubprocessFallbackBackend(command)
        return UnixPexpectBackend(command)

    def _read_loop(self) -> None:
        while self._running:
            if not self.backend:
                break
            data = self.backend.read()
            if data:
                self.app.call_from_thread(self.pane.receive_output, data)

    def send(self, data: str) -> None:
        if self.backend:
            self.backend.write(data)

    def stop(self) -> None:
        self._running = False
        if self.backend:
            self.backend.close()


class AgentPane(Vertical):
    can_focus = True

    def __init__(self, pane_id: str, title: str, startup_command: str) -> None:
        super().__init__(id=pane_id, classes="agent-pane")
        self.pane_id = pane_id
        self.title_text = title
        self.startup_command = startup_command
        self.rich_log: Optional[RichLog] = None
        self.session: Optional[ShellSession] = None
        self._plain_lines: deque[str] = deque(maxlen=5000)
        self._carry = ""

    def compose(self) -> ComposeResult:
        yield Label(self.title_text, classes="pane-title")
        self.rich_log = RichLog(wrap=False, markup=False, highlight=False, auto_scroll=True)
        yield self.rich_log

    def on_click(self, _: Click) -> None:
        self.focus()

    def on_focus(self, _event=None) -> None:
        self.add_class("focused")
        if isinstance(self.app, TriptychApp):
            self.app.refresh_status()

    def on_blur(self, _event=None) -> None:
        self.remove_class("focused")
        if isinstance(self.app, TriptychApp):
            self.app.refresh_status()

    def start(self, shell_command: str) -> None:
        if not isinstance(self.app, TriptychApp):
            return
        self.session = ShellSession(self.app, self, shell_command)
        self.session.start()
        if self.startup_command:
            self.session.send(self.startup_command + "\n")

    def stop(self) -> None:
        if self.session:
            self.session.stop()

    def send_text(self, text: str) -> None:
        if self.session:
            self.session.send(text)

    def receive_output(self, text: str) -> None:
        if self.rich_log:
            self.rich_log.write(Text.from_ansi(text), scroll_end=True)
        self._append_plain(strip_ansi(text))

    def _append_plain(self, text: str) -> None:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        parts = (self._carry + normalized).split("\n")
        self._carry = parts.pop() if parts else ""
        for line in parts:
            self._plain_lines.append(line)

    def grab_context(self, lines: int = 50) -> str:
        payload = list(self._plain_lines)[-lines:]
        if self._carry:
            payload.append(self._carry)
        return "\n".join(payload).strip()


class TriptychApp(App):
    CSS = """
    Screen {
        background: #050a08;
        color: #b7ffc8;
    }

    #pane-row {
        height: 1fr;
        layout: horizontal;
    }

    .agent-pane {
        width: 1fr;
        margin: 0 1;
        border: heavy #00ff66;
        background: #07160f;
    }

    .agent-pane:focus,
    .agent-pane.focused {
        border: heavy #ffd400;
    }

    .pane-title {
        height: 1;
        content-align: center middle;
        color: #ffd400;
        background: #153024;
        text-style: bold;
    }

    .agent-pane RichLog {
        height: 1fr;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #18331f;
        color: #e2ff6d;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("tab", "focus_next_pane", "Next Pane"),
        Binding("shift+tab", "focus_prev_pane", "Prev Pane"),
        Binding("f1", "select_source('claude')", "Source CLAUDE"),
        Binding("f2", "select_source('gemini')", "Source GEMINI"),
        Binding("f3", "select_source('codex')", "Source CODEX"),
        Binding("shift+f1", "pipe_to('claude')", "Send -> CLAUDE"),
        Binding("shift+f2", "pipe_to('gemini')", "Send -> GEMINI"),
        Binding("shift+f3", "pipe_to('codex')", "Send -> CODEX"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.panes: dict[str, AgentPane] = {}
        self.source_pane: Optional[str] = "claude"
        self._status_note = "Ready"

    def compose(self) -> ComposeResult:
        with Horizontal(id="pane-row"):
            yield AgentPane("claude", "CLAUDE", os.getenv("TRIPTYCH_CLAUDE_CMD", "claude"))
            yield AgentPane("gemini", "GEMINI", os.getenv("TRIPTYCH_GEMINI_CMD", "gemini"))
            yield AgentPane("codex", "CODEX", os.getenv("TRIPTYCH_CODEX_CMD", "codex"))
        yield Static("", id="status-bar")

    def on_mount(self) -> None:
        self.panes = {
            "claude": self.query_one("#claude", AgentPane),
            "gemini": self.query_one("#gemini", AgentPane),
            "codex": self.query_one("#codex", AgentPane),
        }
        shell_command = self._detect_shell_command()
        for pane in self.panes.values():
            pane.start(shell_command)
        self.panes["claude"].focus()
        self.refresh_status()

    def on_unmount(self) -> None:
        for pane in self.panes.values():
            pane.stop()

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

    def action_focus_next_pane(self) -> None:
        ids = ["claude", "gemini", "codex"]
        current = self._focused_pane_id()
        idx = ids.index(current) if current in ids else 0
        self.panes[ids[(idx + 1) % len(ids)]].focus()
        self.refresh_status()

    def action_focus_prev_pane(self) -> None:
        ids = ["claude", "gemini", "codex"]
        current = self._focused_pane_id()
        idx = ids.index(current) if current in ids else 0
        self.panes[ids[(idx - 1) % len(ids)]].focus()
        self.refresh_status()

    def action_select_source(self, pane_id: str) -> None:
        if pane_id in self.panes:
            self.source_pane = pane_id
            self._status_note = f"Source set to {pane_id.upper()}"
            self.refresh_status()

    def action_pipe_to(self, target_id: str) -> None:
        if target_id not in self.panes:
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
        self._status_note = f"Injected 50 lines: {self.source_pane.upper()} -> {target_id.upper()}"
        self.refresh_status()

    def on_key(self, event: Key) -> None:
        reserved = {
            "tab",
            "shift+tab",
            "f1",
            "f2",
            "f3",
            "shift+f1",
            "shift+f2",
            "shift+f3",
            "ctrl+q",
        }
        if event.key in reserved:
            return

        pane = self._focused_pane()
        if not pane:
            return

        if self._forward_key_to_pane(pane, event):
            event.stop()

    def _forward_key_to_pane(self, pane: AgentPane, event: Key) -> bool:
        if event.character:
            pane.send_text(event.character)
            return True

        key_map = {
            "enter": "\r",
            "backspace": "\x7f",
            "delete": "\x1b[3~",
            "up": "\x1b[A",
            "down": "\x1b[B",
            "left": "\x1b[D",
            "right": "\x1b[C",
            "home": "\x1b[H",
            "end": "\x1b[F",
            "pageup": "\x1b[5~",
            "pagedown": "\x1b[6~",
            "escape": "\x1b",
        }

        if event.key in key_map:
            pane.send_text(key_map[event.key])
            return True

        if event.key.startswith("ctrl+") and len(event.key) == 6:
            ctrl_char = event.key[-1]
            if "a" <= ctrl_char <= "z":
                pane.send_text(chr(ord(ctrl_char) - 96))
                return True

        if event.key == "ctrl+space":
            pane.send_text("\x00")
            return True

        return False

    def _focused_pane(self) -> Optional[AgentPane]:
        node = self.focused
        while node is not None and not isinstance(node, AgentPane):
            node = node.parent
        return node if isinstance(node, AgentPane) else None

    def _focused_pane_id(self) -> Optional[str]:
        pane = self._focused_pane()
        return pane.pane_id if pane else None

    def refresh_status(self) -> None:
        focus = (self._focused_pane_id() or "none").upper()
        source = (self.source_pane or "none").upper()
        status = (
            f"Focus:{focus}  Source:{source}  "
            f"F1/F2/F3 select source  Shift+F1/F2/F3 inject to target  "
            f"Tab cycle focus  Ctrl+Q quit  |  {self._status_note}"
        )
        self.query_one("#status-bar", Static).update(status)


if __name__ == "__main__":
    TriptychApp().run()
