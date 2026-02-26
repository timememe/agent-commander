"""Minimal markdown-capable text view for Tkinter."""

from __future__ import annotations

import customtkinter as ctk

from agent_commander.gui import theme

# Keys that are allowed even in read-only mode (selection, copy, navigation)
_ALLOWED_KEYS = {
    "c", "a",  # Ctrl+C (copy), Ctrl+A (select all)
}
_ALLOWED_ALT_LAYOUT_KEYS = {
    "с", "ф",  # Russian layout: Ctrl+С (copy), Ctrl+Ф (select all)
}
_ALLOWED_KEYSYMS = {
    "Left", "Right", "Up", "Down", "Home", "End",
    "Prior", "Next",  # Page Up/Down
    "Shift_L", "Shift_R", "Control_L", "Control_R",
}
_CTRL_MASK = 0x4
_COPY_KEYCODES = {67}  # VK_C on Windows
_SELECT_ALL_KEYCODES = {65}  # VK_A on Windows


class MarkdownView(ctk.CTkTextbox):
    """Read-only markdown text surface.

    This widget keeps ``state='normal'`` so the user can select and copy
    text naturally. Editing keystrokes are blocked via a ``<Key>``
    binding that returns ``'break'`` for anything that is not
    navigation/copy/select-all.
    """

    def __init__(self, master: ctk.CTkBaseClass, *, wrap: str = "word", **kwargs: object) -> None:
        self._min_height = int(kwargs.pop("min_height", 36))
        self._max_height = int(kwargs.pop("max_height", 2000))
        self._last_height = 0
        super().__init__(
            master,
            wrap=wrap,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE),
            fg_color="transparent",
            text_color=theme.COLOR_TEXT,
            border_width=0,
            activate_scrollbars=False,
            **kwargs,
        )
        # Keep state normal so selection works; block edits via key handler
        self.tag_config("search_hit", background="#4A3F1D", foreground=theme.COLOR_TEXT)
        self.tag_config("search_active", background="#C58E2A", foreground="#111111")

        # Bind on the inner text widget to intercept before CTk processing
        tw = getattr(self, "_textbox", None)
        if tw is not None:
            tw.bind("<Key>", self._block_edits, add=True)
            tw.bind("<Control-c>", self._copy_selection, add=True)
            tw.bind("<Control-a>", self._select_all, add=True)
            tw.bind("<Control-C>", self._copy_selection, add=True)
            tw.bind("<Control-A>", self._select_all, add=True)
        else:
            self.bind("<Key>", self._block_edits, add=True)
            self.bind("<Control-c>", self._copy_selection, add=True)
            self.bind("<Control-a>", self._select_all, add=True)
            self.bind("<Control-C>", self._copy_selection, add=True)
            self.bind("<Control-A>", self._select_all, add=True)

        # Ensure widget receives focus on click so Ctrl+C works reliably.
        if tw is not None:
            tw.bind("<Button-1>", lambda e: e.widget.focus_set(), add=True)
        else:
            self.bind("<Button-1>", lambda e: e.widget.focus_set(), add=True)

        self.after_idle(self._autosize_to_content)

    def set_markdown(self, text: str) -> None:
        """Replace full text content."""
        self.delete("1.0", "end")
        if text:
            self.insert("1.0", text)
        self.after_idle(self._autosize_to_content)

    def append_markdown(self, text: str) -> None:
        """Append text chunk."""
        if not text:
            return
        self.insert("end", text)
        self.see("end")
        self.after_idle(self._autosize_to_content)

    @staticmethod
    def _block_edits(event: "object") -> str | None:
        """Allow selection/copy/navigation, block everything else."""
        keysym = getattr(event, "keysym", "")
        state = getattr(event, "state", 0)
        ctrl = bool(state & _CTRL_MASK)
        keycode = int(getattr(event, "keycode", -1) or -1)
        key = keysym.lower()

        # Always allow navigation keys
        if keysym in _ALLOWED_KEYSYMS:
            return None

        # Copy/select-all in any layout (text key or physical key position).
        if ctrl and (key in {"c", "с"} or keycode in _COPY_KEYCODES):
            return MarkdownView._copy_selection(event)
        if ctrl and (key in {"a", "ф"} or keycode in _SELECT_ALL_KEYCODES):
            return MarkdownView._select_all(event)

        # Keep legacy allowlist behavior for already supported layouts.
        if ctrl and key in _ALLOWED_KEYS | _ALLOWED_ALT_LAYOUT_KEYS:
            return None
        if ctrl and keysym == "Insert":
            return None

        # Block everything else (typing, delete, backspace, paste, etc.)
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

    def clear_search(self) -> None:
        """Clear search highlighting tags."""
        self.tag_remove("search_hit", "1.0", "end")
        self.tag_remove("search_active", "1.0", "end")

    def highlight_query(self, query: str) -> list[tuple[str, str]]:
        """Highlight all query occurrences and return ranges."""
        self.clear_search()
        token = (query or "").strip()
        if not token:
            return []

        hits: list[tuple[str, str]] = []
        index = "1.0"
        while True:
            start = self.search(token, index, stopindex="end", nocase=True)
            if not start:
                break
            end = f"{start}+{len(token)}c"
            self.tag_add("search_hit", start, end)
            hits.append((start, end))
            index = end
        return hits

    def set_active_match(self, hit: tuple[str, str] | None) -> None:
        """Mark one active match and scroll it into view."""
        self.tag_remove("search_active", "1.0", "end")
        if hit is not None:
            start, end = hit
            self.tag_add("search_active", start, end)
            self.see(start)

    def _autosize_to_content(self) -> None:
        """
        Resize textbox height to fit rendered text lines.

        Guards against measuring before layout is complete: if the widget
        hasn't been given a real width yet (winfo_width < 20), defers the
        measurement by 60 ms to avoid tk's count(-displaylines) returning
        a wildly large value when width ≈ 1 px (every char on its own line).
        Uses a change-guard so configure() is only called when height changes.
        """
        text_widget = getattr(self, "_textbox", None)
        if text_widget is None:
            return

        # Widget not laid out yet — wait for geometry to propagate
        if self.winfo_width() < 20:
            self.after(60, self._autosize_to_content)
            return

        try:
            counted = text_widget.count("1.0", "end-1c", "displaylines")
            display_lines = int(counted[0]) if counted else 1
        except Exception:
            try:
                display_lines = int(str(text_widget.index("end-1c")).split(".")[0])
            except Exception:
                display_lines = 1

        line_height_px = max(18, int(theme.FONT_SIZE * 1.75))
        target = max(self._min_height, display_lines * line_height_px + 8)
        target = min(self._max_height, target)
        if target != self._last_height:
            self._last_height = target
            self.configure(height=target)
