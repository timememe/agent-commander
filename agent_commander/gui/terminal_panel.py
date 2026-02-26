"""Raw terminal output panel with per-session buffers."""

from __future__ import annotations

import customtkinter as ctk
try:
    import pyte
except ImportError:  # pragma: no cover - optional runtime dependency
    pyte = None

from agent_commander.gui import theme

# Keys allowed in read-only terminal (select, copy, navigation)
_ALLOWED_KEYSYMS = {
    "Left", "Right", "Up", "Down", "Home", "End",
    "Prior", "Next", "Shift_L", "Shift_R", "Control_L", "Control_R",
}
_CTRL_MASK = 0x4
_COPY_KEYCODES = {67}  # VK_C on Windows
_SELECT_ALL_KEYCODES = {65}  # VK_A on Windows


class TerminalPanel(ctk.CTkFrame):
    """Read-only PTY output panel with per-session terminal emulation."""

    def __init__(self, master: ctk.CTkBaseClass) -> None:
        super().__init__(
            master,
            fg_color=theme.COLOR_BG_CHAT,
            border_width=1,
            border_color=theme.COLOR_BORDER,
            corner_radius=10,
        )
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._text = ctk.CTkTextbox(
            self,
            font=(theme.FONT_FAMILY, 13),
            fg_color=theme.COLOR_BG_PANEL,
            border_width=0,
            text_color=theme.COLOR_TEXT,
            wrap="none",
        )
        self._text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

        # Block edits but allow selection + copy
        tw = getattr(self._text, "_textbox", None)
        if tw is not None:
            tw.bind("<Key>", self._block_edits, add=True)
            tw.bind("<Button-1>", lambda e: e.widget.focus_set(), add=True)
            tw.bind("<Control-c>", self._copy_selection, add=True)
            tw.bind("<Control-a>", self._select_all, add=True)
            tw.bind("<Control-C>", self._copy_selection, add=True)
            tw.bind("<Control-A>", self._select_all, add=True)
        else:
            self._text.bind("<Key>", self._block_edits, add=True)
            self._text.bind("<Button-1>", lambda e: e.widget.focus_set(), add=True)
            self._text.bind("<Control-c>", self._copy_selection, add=True)
            self._text.bind("<Control-a>", self._select_all, add=True)
            self._text.bind("<Control-C>", self._copy_selection, add=True)
            self._text.bind("<Control-A>", self._select_all, add=True)

        # Per-session terminal buffers: session_id -> accumulated text
        self._buffers: dict[str, str] = {}
        self._active_session: str = ""
        self._max_buffer = 200_000  # chars per session
        self._screens: dict[str, object] = {}
        self._streams: dict[str, object] = {}
        self._screen_cols = 140
        self._screen_rows = 36

    def set_active_session(self, session_id: str) -> None:
        """Switch displayed terminal output to a different session."""
        if session_id == self._active_session:
            return
        self._active_session = session_id
        self._render_buffer(session_id)

    def clear(self, session_id: str | None = None) -> None:
        """Clear buffer for a session (or active session)."""
        sid = session_id or self._active_session
        self._buffers.pop(sid, None)
        self._screens.pop(sid, None)
        self._streams.pop(sid, None)
        if sid == self._active_session:
            self._text.delete("1.0", "end")

    def append_text(self, chunk: str, session_id: str | None = None) -> None:
        """Append terminal output for a specific session."""
        if not chunk:
            return
        sid = session_id or self._active_session
        if pyte is None:
            buf = self._buffers.get(sid, "")
            buf += chunk
            if len(buf) > self._max_buffer:
                buf = buf[-self._max_buffer:]
            self._buffers[sid] = buf
        else:
            screen, stream = self._get_or_create_terminal(sid)
            try:
                stream.feed(chunk)
            except Exception:
                # Keep panel resilient on malformed control sequences.
                pass
            rendered = self._snapshot_screen(screen)
            if len(rendered) > self._max_buffer:
                rendered = rendered[-self._max_buffer:]
            self._buffers[sid] = rendered

        # Only update widget if this is the currently displayed session
        if sid == self._active_session:
            self._render_buffer(sid)

    def _render_buffer(self, session_id: str) -> None:
        """Load a session's buffer into the text widget."""
        buf = self._buffers.get(session_id, "")
        self._text.delete("1.0", "end")
        if buf:
            self._text.insert("1.0", buf)
            self._text.see("end")

    def _get_or_create_terminal(self, session_id: str) -> tuple["pyte.HistoryScreen", "pyte.Stream"]:
        screen = self._screens.get(session_id)
        stream = self._streams.get(session_id)
        if screen is None or stream is None:
            screen = pyte.HistoryScreen(self._screen_cols, self._screen_rows, history=5000)
            screen.set_mode(pyte.modes.LNM)
            stream = pyte.Stream(screen)
            self._screens[session_id] = screen
            self._streams[session_id] = stream
        return screen, stream

    @staticmethod
    def _snapshot_screen(screen: "pyte.HistoryScreen") -> str:
        history_lines: list[str] = []
        for line in screen.history.top:
            if isinstance(line, dict):
                cols = screen.columns
                history_lines.append(
                    "".join(line[x].data if x in line else " " for x in range(cols)).rstrip()
                )
            else:
                history_lines.append(str(line).rstrip())
        display_lines = [line.rstrip() for line in screen.display]
        lines = history_lines + display_lines
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)

    @staticmethod
    def _block_edits(event: "object") -> str | None:
        keysym = getattr(event, "keysym", "")
        state = getattr(event, "state", 0)
        ctrl = bool(state & _CTRL_MASK)
        keycode = int(getattr(event, "keycode", -1) or -1)
        key = keysym.lower()
        if keysym in _ALLOWED_KEYSYMS:
            return None
        if ctrl and (key in {"c", "с"} or keycode in _COPY_KEYCODES):
            return TerminalPanel._copy_selection(event)
        if ctrl and (key in {"a", "ф"} or keycode in _SELECT_ALL_KEYCODES):
            return TerminalPanel._select_all(event)
        if ctrl and keysym == "Insert":
            return None
        return "break"

    @staticmethod
    def _copy_selection(event: "object") -> str:
        widget = getattr(event, "widget", None)
        if widget is None:
            return "break"
        try:
            widget.event_generate("<<Copy>>")
        except Exception:
            pass
        return "break"

    @staticmethod
    def _select_all(event: "object") -> str:
        widget = getattr(event, "widget", None)
        if widget is None:
            return "break"
        try:
            widget.tag_add("sel", "1.0", "end-1c")
            widget.mark_set("insert", "1.0")
            widget.see("insert")
        except Exception:
            pass
        return "break"
