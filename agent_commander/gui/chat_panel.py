"""Chat panel with bubble rendering and chunk streaming."""

from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

from agent_commander.gui import theme
from agent_commander.gui.widgets.chat_bubble import ChatBubble


@dataclass
class ChatMessage:
    """Message model used by ChatPanel."""

    role: str
    text: str


class ChatPanel(ctk.CTkFrame):
    """Central panel that renders chat bubbles."""

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

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._scroll.grid_columnconfigure(0, weight=1)

        self._bubbles: list[ChatBubble] = []
        self._streaming_bubble: ChatBubble | None = None
        self._search_query = ""
        self._search_hits: list[tuple[ChatBubble, int]] = []
        self._search_index = -1

        # Smart auto-scroll state
        self._auto_scroll = True
        self._fab_visible = False
        self._scroll_scheduled = False   # debounce flag

        # FAB scroll-to-bottom button
        self._fab = ctk.CTkButton(
            self,
            text="↓",
            width=36,
            height=36,
            corner_radius=18,
            fg_color=theme.COLOR_ACCENT,
            hover_color="#1A6EB5",
            font=(theme.FONT_FAMILY, 16, "bold"),
            command=self._scroll_to_bottom,
        )
        # Hidden initially; shown via place() when user scrolls up
        self._fab_visible = False

        # Bind scroll events after widget is realized
        self.after(100, self._bind_scroll_events)

    def _bind_scroll_events(self) -> None:
        canvas = getattr(self._scroll, "_parent_canvas", None)
        if canvas:
            canvas.bind("<MouseWheel>", self._on_user_scroll, add=True)
            canvas.bind("<Button-4>", self._on_user_scroll, add=True)
            canvas.bind("<Button-5>", self._on_user_scroll, add=True)

    def _on_user_scroll(self, event: object) -> None:
        delta = getattr(event, "delta", 0) or (
            120 if getattr(event, "num", 5) == 4 else -120
        )
        if delta > 0:  # scroll up
            self._auto_scroll = False
            self._show_fab()
        else:  # scroll down — check if at bottom
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas:
                try:
                    _, bottom = canvas.yview()
                    if bottom >= 0.99:
                        self._auto_scroll = True
                        self._hide_fab()
                except Exception:
                    pass

    def _show_fab(self) -> None:
        if not self._fab_visible:
            self._fab_visible = True
            self._fab.place(relx=1.0, rely=1.0, anchor="se", x=-14, y=-14)

    def _hide_fab(self) -> None:
        if self._fab_visible:
            self._fab_visible = False
            self._fab.place_forget()

    def _scroll_to_bottom(self) -> None:
        self._auto_scroll = True
        self._scroll_scheduled = False
        self._hide_fab()
        canvas = getattr(self._scroll, "_parent_canvas", None)
        if canvas:
            try:
                canvas.yview_moveto(1.0)
            except Exception:
                pass

    def _do_auto_scroll(self) -> None:
        """Schedule a single deferred scroll-to-bottom to avoid recursive scrollbar redraws."""
        if self._auto_scroll and not self._scroll_scheduled:
            self._scroll_scheduled = True
            self.after(30, self._perform_scroll)

    def _perform_scroll(self) -> None:
        self._scroll_scheduled = False
        if self._auto_scroll:
            canvas = getattr(self._scroll, "_parent_canvas", None)
            if canvas is not None:
                try:
                    canvas.yview_moveto(1.0)
                except Exception:
                    pass

    def clear(self) -> None:
        for bubble in self._bubbles:
            bubble.destroy()
        self._bubbles.clear()
        self._streaming_bubble = None
        self._search_query = ""
        self._search_hits = []
        self._search_index = -1
        self._auto_scroll = True
        self._scroll_scheduled = False
        self._hide_fab()

    def set_messages(self, messages: list[ChatMessage]) -> None:
        self.clear()
        for message in messages:
            self.add_message(message.role, message.text)

    def add_message(self, role: str, text: str) -> ChatBubble:
        bubble = ChatBubble(self._scroll, role=role, text=text)
        # Telegram-style: large opposite-side margin constrains bubble to ~65% width.
        # Avatar (28px) + gaps are inside the bubble; outer padx just limits the row.
        if role == "user":
            # Right side: push bubble right by leaving a large left margin
            bubble.pack(fill="x", padx=(180, 6), pady=(2, 4))
        elif role == "system":
            bubble.pack(fill="x", padx=(52, 52), pady=(2, 4))
        elif role == "tool_log":
            # Full width, subtle indent
            bubble.pack(fill="x", padx=(40, 40), pady=(2, 4))
        else:
            # Left side: large right margin keeps bubble in left ~70%
            bubble.pack(fill="x", padx=(6, 180), pady=(2, 4))
        self._bubbles.append(bubble)
        self._do_auto_scroll()
        return bubble

    def begin_assistant_stream(self) -> None:
        if self._streaming_bubble is None:
            self._streaming_bubble = self.add_message("assistant", "")
            self._streaming_bubble.start_spinner()

    def append_assistant_chunk(self, chunk: str, final: bool = False) -> None:
        # If _streaming_bubble is a tool_log (or wrong type), start a fresh assistant bubble
        if self._streaming_bubble is None or self._streaming_bubble.role != "assistant":
            if self._bubbles and self._bubbles[-1].role == "assistant":
                self._streaming_bubble = self._bubbles[-1]
            else:
                self.begin_assistant_stream()
        if self._streaming_bubble:
            self._streaming_bubble.append_text(chunk)
        if final:
            if self._streaming_bubble and self._streaming_bubble._spinning:
                self._streaming_bubble.stop_spinner()
            self._streaming_bubble = None
        self._do_auto_scroll()

    def begin_tool_stream(self) -> None:
        """Start a new tool_log bubble for tool call output."""
        self._streaming_bubble = self.add_message("tool_log", "")

    def append_tool_chunk(self, chunk: str, final: bool = False) -> None:
        """Append a chunk to the current tool_log bubble."""
        if self._streaming_bubble is None or self._streaming_bubble.role != "tool_log":
            if self._bubbles and self._bubbles[-1].role == "tool_log":
                self._streaming_bubble = self._bubbles[-1]
            else:
                self.begin_tool_stream()
        if self._streaming_bubble:
            self._streaming_bubble.append_text(chunk)
        if final:
            self._streaming_bubble = None
        self._do_auto_scroll()

    def clear_search(self) -> None:
        """Clear search highlights and state."""
        for bubble in self._bubbles:
            bubble.clear_search()
        self._search_query = ""
        self._search_hits = []
        self._search_index = -1

    def search(self, query: str, *, forward: bool = True) -> tuple[int, int]:
        """
        Search in rendered bubbles.

        Returns:
            Tuple of (active_index_1_based, total_hits). Returns (0, 0) if none.
        """
        token = (query or "").strip()
        if not token:
            self.clear_search()
            return (0, 0)

        if token != self._search_query:
            self._search_query = token
            self._search_hits = []
            self._search_index = -1
            for bubble in self._bubbles:
                count = bubble.search(token)
                for idx in range(count):
                    self._search_hits.append((bubble, idx))
        elif not self._search_hits:
            return (0, 0)

        total = len(self._search_hits)
        if total == 0:
            for bubble in self._bubbles:
                bubble.set_active_search_hit(None)
            return (0, 0)

        if self._search_index < 0:
            self._search_index = 0 if forward else total - 1
        elif forward:
            self._search_index = (self._search_index + 1) % total
        else:
            self._search_index = (self._search_index - 1 + total) % total

        for bubble in self._bubbles:
            bubble.set_active_search_hit(None)

        active_bubble, active_hit_index = self._search_hits[self._search_index]
        active_bubble.set_active_search_hit(active_hit_index)
        self._scroll_to_bubble(active_bubble)
        return (self._search_index + 1, total)

    def _scroll_to_bubble(self, bubble: ChatBubble) -> None:
        canvas = getattr(self._scroll, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            self.update_idletasks()
            frame_height = max(1, self._scroll.winfo_height())
            y = max(0, bubble.winfo_y() - 12)
            total_height = max(frame_height, self._scroll.winfo_reqheight())
            max_offset = max(1, total_height - frame_height)
            canvas.yview_moveto(min(1.0, y / max_offset))
        except Exception:
            pass
