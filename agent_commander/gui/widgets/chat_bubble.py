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
        super().__init__(master, fg_color="transparent", border_width=0, corner_radius=0)
        self.role = role
        self._text = text
        self._search_hits: list[tuple[str, str]] = []
        self._copy_button: ctk.CTkButton | None = None
        self._spinning = False
        self._spinner_frame_idx = 0
        self._spinner_after_id: str | None = None

        av_size = theme.AVATAR_SIZE
        bubble_color = _BUBBLE_COLORS.get(role, theme.COLOR_ASSISTANT_BUBBLE)

        if role == ROLE_USER:
            # col 0: content (expands), col 1: avatar (fixed)
            self.grid_columnconfigure(0, weight=1)
            self.grid_columnconfigure(1, weight=0)

            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=14, border_width=0)
            content_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=2)
            content_frame.grid_columnconfigure(0, weight=1)

            _make_avatar(self, _AVATAR_INITIALS[ROLE_USER], _AVATAR_COLORS[ROLE_USER], av_size).grid(
                row=0, column=1, sticky="n", pady=6
            )

        elif role == ROLE_SYSTEM:
            # Single column, no avatar
            self.grid_columnconfigure(0, weight=1)
            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=10, border_width=0)
            content_frame.grid(row=0, column=0, sticky="nsew", pady=2)
            content_frame.grid_columnconfigure(0, weight=1)

        elif role == ROLE_TOOL_LOG:
            # Full-width log panel with left accent border, no avatar
            self.grid_columnconfigure(0, weight=1)
            outer = ctk.CTkFrame(
                self, fg_color=bubble_color, corner_radius=8,
                border_width=1, border_color=theme.COLOR_BORDER,
            )
            outer.grid(row=0, column=0, sticky="nsew", pady=(2, 4))
            outer.grid_columnconfigure(1, weight=1)
            # Left accent strip
            ctk.CTkFrame(outer, fg_color=theme.COLOR_ACCENT, corner_radius=0, width=3).grid(
                row=0, column=0, sticky="ns", padx=(0, 0)
            )
            content_frame = ctk.CTkFrame(outer, fg_color="transparent", corner_radius=0)
            content_frame.grid(row=0, column=1, sticky="nsew")
            content_frame.grid_columnconfigure(0, weight=1)
            # Header label
            ctk.CTkLabel(
                content_frame, text="🔧 Tool calls", anchor="w",
                font=(theme.FONT_FAMILY, 10, "bold"),
                text_color=theme.COLOR_TEXT_MUTED,
            ).grid(row=0, column=0, sticky="w", padx=(8, 8), pady=(5, 0))

        else:  # assistant / default
            # col 0: avatar (fixed), col 1: content (expands)
            self.grid_columnconfigure(0, weight=0)
            self.grid_columnconfigure(1, weight=1)

            _make_avatar(self, _AVATAR_INITIALS[ROLE_ASSISTANT], _AVATAR_COLORS[ROLE_ASSISTANT], av_size).grid(
                row=0, column=0, sticky="n", padx=(2, 6), pady=6
            )

            content_frame = ctk.CTkFrame(self, fg_color=bubble_color, corner_radius=14, border_width=0)
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
        self._body.grid()

    def search(self, query: str) -> int:
        self._search_hits = self._body.highlight_query(query)
        return len(self._search_hits)

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
