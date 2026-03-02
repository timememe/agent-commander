"""Chat bubble widget — Telegram-style layout."""

from __future__ import annotations

import re
from datetime import datetime

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.gui.widgets.markdown_view import MarkdownView

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"
ROLE_TOOL_LOG = "tool_log"

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ToolCallItem(ctk.CTkFrame):
    """Compact row for a single live tool call: spinner → name(args) → result preview."""

    _SPIN_FRAMES = _SPINNER_FRAMES

    def __init__(self, master: ctk.CTkBaseClass, name: str, args: str) -> None:
        super().__init__(master, fg_color="transparent", corner_radius=0, width=0, height=0)
        self.grid_columnconfigure(1, weight=1)

        self._name = name
        self._running = True
        self._expanded = False
        self._spin_idx = 0
        self._after_id: str | None = None
        self._result_text = ""

        # Spinner / status icon
        self._icon_label = ctk.CTkLabel(
            self, text="⠋",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.COLOR_ACCENT,
            width=16, anchor="w",
        )
        self._icon_label.grid(row=0, column=0, sticky="w", padx=(0, 3))

        # name(args preview)
        raw = args.replace("\n", " ").strip()
        args_preview = raw[:60] + "..." if len(raw) > 60 else raw
        self._call_label = ctk.CTkLabel(
            self,
            text=f"{name}({args_preview})",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._call_label.grid(row=0, column=1, sticky="ew")

        # Result preview (row 1, hidden until complete)
        self._result_label = ctk.CTkLabel(
            self, text="",
            font=(theme.FONT_FAMILY, 10),
            text_color="#4A6A8A",
            anchor="w",
        )
        # Full result textbox (row 2, created and shown on click)
        self._result_box: ctk.CTkTextbox | None = None

        for w in (self, self._icon_label, self._call_label):
            w.bind("<Button-1>", lambda _e: self._on_click())

        self._tick_spinner()

    def complete(self, result: str) -> None:
        """Stop spinner and show result preview."""
        self._running = False
        self._result_text = result
        if self._after_id:
            try:
                self.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._icon_label.configure(text="●", text_color=theme.COLOR_ACCENT)
        lines = result.strip().splitlines()
        preview = (lines[0] or "")[:120] if lines else ""
        extra = len(lines) - 1
        suffix = f"  … +{extra} lines" if extra > 0 else ""
        self._result_label.configure(text=f"⎿  {preview}{suffix}")
        self._result_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 4), pady=(0, 2))
        self._result_label.bind("<Button-1>", lambda _e: self._on_click())

    def _on_click(self) -> None:
        if not self._result_text or self._running:
            return
        self._expanded = not self._expanded
        if self._expanded:
            if self._result_box is None:
                n_lines = min(8, max(3, self._result_text.count("\n") + 1))
                self._result_box = ctk.CTkTextbox(
                    self,
                    height=n_lines * 15 + 8,
                    font=("Consolas", 10),
                    state="normal",
                    wrap="none",
                    fg_color=theme.COLOR_BG_APP,
                    text_color=theme.COLOR_TEXT_MUTED,
                    border_width=0,
                )
                self._result_box.insert("1.0", self._result_text)
                self._result_box.configure(state="disabled")
            self._result_box.grid(row=2, column=0, columnspan=2, sticky="ew", padx=(20, 4), pady=(2, 4))
        else:
            if self._result_box:
                self._result_box.grid_remove()

    def _tick_spinner(self) -> None:
        if not self._running:
            return
        try:
            self._icon_label.configure(text=self._SPIN_FRAMES[self._spin_idx % len(self._SPIN_FRAMES)])
            self._spin_idx += 1
            self._after_id = self.after(120, self._tick_spinner)
        except Exception:
            self._running = False

_BUBBLE_COLORS = {
    ROLE_USER: theme.COLOR_USER_BUBBLE,
    ROLE_ASSISTANT: theme.COLOR_ASSISTANT_BUBBLE,
    ROLE_SYSTEM: theme.COLOR_SYSTEM_BUBBLE,
    ROLE_TOOL_LOG: theme.COLOR_TOOL_BUBBLE,
}
_AVATAR_COLORS = {
    ROLE_USER: theme.COLOR_AVATAR_USER,
    ROLE_ASSISTANT: theme.COLOR_AVATAR_CLAUDE,
    ROLE_SYSTEM: theme.COLOR_AVATAR_DEFAULT,
}
_AVATAR_INITIALS = {ROLE_USER: "U", ROLE_ASSISTANT: "A", ROLE_SYSTEM: "S"}


class ChatBubble(ctk.CTkFrame):
    """
    Single chat message bubble.

    Layout (Telegram-style):
      • user:      [content_frame | avatar]   — bubble fills row, avatar pinned right
      • assistant: [avatar | content_frame]   — avatar pinned left
      • system:    [content_frame]            — no avatar, center-padded externally

    The outer ChatBubble is transparent and sized by chat_panel padx.
    content_frame takes all available width (weight=1), so text wraps naturally
    at whatever width the panel allocates.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        role: str,
        text: str = "",
    ) -> None:
        super().__init__(master, fg_color="transparent", border_width=0, corner_radius=0, width=0, height=0)
        self.role = role
        self._text = text
        self._search_hits: list[tuple[str, str]] = []
        self._copy_button: ctk.CTkButton | None = None
        self._spinning = False
        self._spinner_frame_idx = 0
        self._spinner_after_id: str | None = None
        self._collapsed = False
        self._tool_call_count = 0
        self._header_label: ctk.CTkLabel | None = None
        self._toggle_label: ctk.CTkLabel | None = None
        self._items_frame: ctk.CTkFrame | None = None
        self._tool_items: list[ToolCallItem] = []

        av_size = theme.AVATAR_SIZE
        bubble_color = _BUBBLE_COLORS.get(role, theme.COLOR_ASSISTANT_BUBBLE)

        if role == ROLE_USER:
            # col 0: content (expands), col 1: avatar (fixed)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)

            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=14, border_width=0, width=0, height=0)
            content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
            content_frame.grid_columnconfigure(0, weight=1)

            _make_avatar(self, _AVATAR_INITIALS[ROLE_USER], _AVATAR_COLORS[ROLE_USER], av_size).grid(
                row=0, column=1, sticky="n", pady=6
            )

        elif role == ROLE_SYSTEM:
            # Single column, no avatar
            self.grid_columnconfigure(0, weight=1)
            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=10, border_width=0, width=0, height=0)
            content_frame.grid(row=0, column=0, sticky="nsew", pady=2)
            content_frame.grid_columnconfigure(0, weight=1)

        elif role == ROLE_TOOL_LOG:
            # Full-width log panel with left accent border, no avatar
            self.grid_columnconfigure(0, weight=1)
            outer = ctk.CTkFrame(
                self, fg_color=bubble_color, corner_radius=8,
                border_width=1, border_color=theme.COLOR_BORDER,
                width=0, height=0,
            )
            outer.grid(row=0, column=0, sticky="nsew", pady=(2, 4))
            outer.grid_columnconfigure(1, weight=1)
            # Left accent strip
            ctk.CTkFrame(outer, fg_color=theme.COLOR_ACCENT, corner_radius=0, width=3, height=0).grid(
                row=0, column=0, sticky="ns", padx=(0, 0)
            )
            content_frame = ctk.CTkFrame(outer, fg_color="transparent", corner_radius=0, width=0, height=0)
            content_frame.grid(row=0, column=1, sticky="nsew")
            content_frame.grid_columnconfigure(0, weight=1)
            # Clickable header row (toggle expand/collapse)
            _hdr = ctk.CTkFrame(content_frame, fg_color="transparent", width=0, height=0)
            _hdr.grid(row=0, column=0, sticky="ew", padx=(8, 8), pady=(4, 4))
            _hdr.grid_columnconfigure(0, weight=1)
            self._header_label = ctk.CTkLabel(
                _hdr, text="⚙ Tool calls", anchor="w",
                font=(theme.FONT_FAMILY, 10, "bold"),
                text_color=theme.COLOR_TEXT_MUTED,
            )
            self._header_label.grid(row=0, column=0, sticky="w")
            self._toggle_label = ctk.CTkLabel(
                _hdr, text="▶",
                font=(theme.FONT_FAMILY, 10),
                text_color=theme.COLOR_TEXT_MUTED,
            )
            self._toggle_label.grid(row=0, column=1, sticky="e", padx=(4, 0))
            for _w in (_hdr, self._header_label, self._toggle_label):
                _w.bind("<Button-1>", lambda _e: self._toggle_tool_log())

        else:  # assistant / default
            # col 0: avatar (fixed), col 1: content (expands)
            self.grid_columnconfigure(0, weight=0)
            self.grid_columnconfigure(1, weight=1)

            _make_avatar(self, _AVATAR_INITIALS[ROLE_ASSISTANT], _AVATAR_COLORS[ROLE_ASSISTANT], av_size).grid(
                row=0, column=0, sticky="n", padx=(2, 6), pady=6
            )

            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=14, border_width=0, width=0, height=0)
            content_frame.grid(row=0, column=1, sticky="nsew", pady=2)
            content_frame.grid_columnconfigure(0, weight=1)

        self._content_frame = content_frame

        # ── Copy button (assistant only, top-right) ──
        _body_row = 0
        if role == ROLE_ASSISTANT:
            self._copy_button = ctk.CTkButton(
                content_frame,
                text="Copy code",
                width=84,
                height=22,
                font=(theme.FONT_FAMILY, 10),
                command=self._copy_code_blocks,
            )
            self._copy_button.grid(row=0, column=0, sticky="e", padx=(0, 8), pady=(6, 0))
            self._copy_button.grid_remove()
            _body_row = 1
        elif role == ROLE_TOOL_LOG:
            _body_row = 1  # row 0 = header label

        # ── Braille spinner (hidden initially) ──
        self._spinner_label = ctk.CTkLabel(
            content_frame,
            text=_SPINNER_FRAMES[0],
            font=(theme.FONT_FAMILY, 18),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="w",
        )
        self._spinner_label.grid(row=_body_row, column=0, sticky="w", padx=12, pady=(8, 4))
        self._spinner_label.grid_remove()

        # ── Markdown body ──
        self._body = MarkdownView(content_frame, height=10)
        _body_padx = (6, 6) if role == ROLE_TOOL_LOG else (10, 10)
        _body_pady = (2, 4) if role == ROLE_TOOL_LOG else (8, 2)
        self._body.grid(row=_body_row, column=0, sticky="nsew", padx=_body_padx, pady=_body_pady)
        self._body.set_markdown(text)

        # ── Timestamp ──
        self._timestamp_label = ctk.CTkLabel(
            content_frame,
            text=datetime.now().strftime("%H:%M"),
            font=(theme.FONT_FAMILY, 10),
            text_color=theme.COLOR_TEXT_MUTED,
            anchor="e",
        )
        self._timestamp_label.grid(row=_body_row + 1, column=0, sticky="e", padx=(8, 10), pady=(0, 6))

        self._refresh_copy_button()

        # Tool log starts collapsed — body and timestamp hidden
        if role == ROLE_TOOL_LOG:
            self._collapsed = True
            self._body.grid_remove()
            self._timestamp_label.grid_remove()
            self._update_tool_header()

    # ── Public API ──────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        self._body.set_markdown(text)
        self._timestamp_label.configure(text=datetime.now().strftime("%H:%M"))
        self._refresh_copy_button()

    def append_text(self, chunk: str) -> None:
        if not chunk:
            return
        if self._spinning:
            self.stop_spinner()
        self._text += chunk
        self._body.append_markdown(chunk)
        if self.role == ROLE_TOOL_LOG:
            self._update_tool_header()
        else:
            self._timestamp_label.configure(text=datetime.now().strftime("%H:%M"))
            self._refresh_copy_button()

    def start_spinner(self) -> None:
        if self._spinning:
            return
        self._spinning = True
        self._spinner_frame_idx = 0
        self._body.grid_remove()
        self._spinner_label.grid()
        self._tick_spinner()

    def stop_spinner(self) -> None:
        self._spinning = False
        if self._spinner_after_id:
            try:
                self.after_cancel(self._spinner_after_id)
            except Exception:
                pass
            self._spinner_after_id = None
        self._spinner_label.grid_remove()
        if not self._collapsed:
            self._body.grid()

    def search(self, query: str) -> int:
        self._search_hits = self._body.highlight_query(query)
        return len(self._search_hits)

    def add_tool_item(self, name: str, args: str) -> ToolCallItem:
        """Create and append a live ToolCallItem inside the items frame."""
        if self._items_frame is None:
            self._items_frame = ctk.CTkFrame(self._content_frame, fg_color="transparent", width=0, height=0)
            self._items_frame.grid_columnconfigure(0, weight=1)
            self._items_frame.grid(row=1, column=0, sticky="ew", padx=(8, 8), pady=(2, 4))
            if self._collapsed:
                self._items_frame.grid_remove()
        item = ToolCallItem(self._items_frame, name=name, args=args)
        item.grid(row=len(self._tool_items), column=0, sticky="ew", padx=(4, 4), pady=(1, 1))
        self._tool_items.append(item)
        self._update_tool_header()
        return item

    def complete_tool_item(self, name: str, result: str) -> None:
        """Complete the last running ToolCallItem matching name (or any running item)."""
        for item in reversed(self._tool_items):
            if item._name == name and item._running:
                item.complete(result)
                return
        for item in reversed(self._tool_items):
            if item._running:
                item.complete(result)
                return

    def clear_search(self) -> None:
        self._search_hits = []
        self._body.clear_search()
        self._body.set_active_match(None)

    def set_active_search_hit(self, index: int | None) -> None:
        if index is None or index < 0 or index >= len(self._search_hits):
            self._body.set_active_match(None)
            self._content_frame.configure(border_width=0)
            return
        self._body.set_active_match(self._search_hits[index])
        self._content_frame.configure(border_width=2, border_color=theme.COLOR_ACCENT)

    # ── Private ─────────────────────────────────────────────────────────────

    def _toggle_tool_log(self) -> None:
        if self.role != ROLE_TOOL_LOG:
            return
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._body.grid_remove()
            if self._items_frame is not None:
                self._items_frame.grid_remove()
            self._timestamp_label.grid_remove()
            if self._toggle_label:
                self._toggle_label.configure(text="▶")
        else:
            if self._text:
                self._body.grid()
            if self._items_frame is not None:
                self._items_frame.grid()
            self._timestamp_label.grid()
            if self._toggle_label:
                self._toggle_label.configure(text="▼")

    def _update_tool_header(self) -> None:
        if self.role != ROLE_TOOL_LOG or self._header_label is None:
            return
        if self._tool_items:
            count = len(self._tool_items)
        else:
            count = len(re.findall(r"`\w+\(", self._text))
        self._tool_call_count = count
        if count:
            noun = "tool call" if count == 1 else "tool calls"
            self._header_label.configure(text=f"⚙ {count} {noun}")
        else:
            self._header_label.configure(text="⚙ Tool calls")
        chevron = "▼" if not self._collapsed else "▶"
        if self._toggle_label:
            self._toggle_label.configure(text=chevron)

    def _tick_spinner(self) -> None:
        if not self._spinning:
            return
        try:
            frame = _SPINNER_FRAMES[self._spinner_frame_idx % len(_SPINNER_FRAMES)]
            self._spinner_label.configure(text=frame)
            self._spinner_frame_idx += 1
            self._spinner_after_id = self.after(120, self._tick_spinner)
        except Exception:
            self._spinning = False

    def _extract_code_blocks(self) -> list[str]:
        pattern = re.compile(r"```(?:[\w.+-]+)?\s*\n(.*?)```", re.DOTALL)
        blocks = [b.strip("\n") for b in pattern.findall(self._text)]
        return [b for b in blocks if b.strip()]

    def _refresh_copy_button(self) -> None:
        btn = self._copy_button
        if btn is None:
            return
        blocks = self._extract_code_blocks()
        if not blocks:
            btn.grid_remove()
            return
        label = "Copy code" if len(blocks) == 1 else f"Copy code ({len(blocks)})"
        btn.configure(text=label)
        btn.grid()

    def _copy_code_blocks(self) -> None:
        blocks = self._extract_code_blocks()
        if not blocks:
            return
        payload = "\n\n---\n\n".join(blocks)
        self.clipboard_clear()
        self.clipboard_append(payload)
        btn = self._copy_button
        if btn is None:
            return
        original = btn.cget("text")
        btn.configure(text="Copied")
        self.after(1200, lambda: btn.configure(text=original))


def _make_avatar(master: ctk.CTkBaseClass, initial: str, color: str, size: int) -> ctk.CTkLabel:
    return ctk.CTkLabel(
        master,
        text=initial,
        width=size,
        height=size,
        corner_radius=size // 2,
        fg_color=color,
        text_color="#FFFFFF",
        font=(theme.FONT_FAMILY, 11, "bold"),
    )
