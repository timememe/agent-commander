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
        self._last_width = 0
        self._autosize_guard = False
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
        # Disable internal grid propagation so configure(height=target) controls
        # our size exactly instead of the internal CTkTextbox canvas overriding it.
        self.grid_propagate(False)

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

        # Bind to the inner text widget's <Configure> — it fires after the text widget
        # has been given its actual rendered width, so count(-displaylines) is correct.
        if tw is not None:
            tw.bind("<Configure>", self._on_textbox_configure, add=True)

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

    def _on_textbox_configure(self, event: object) -> None:
        """Re-run autosize when the inner text widget gets its actual rendered width."""
        w = int(getattr(event, "width", 0) or 0)
        if w > 10 and w != self._last_width:
            self._last_width = w
            # Use a small delay so Tk finishes computing the wrapped-line layout
            # before we call dlineinfo / count on the text widget.
            self.after(10, self._autosize_to_content)

    def _autosize_to_content(self) -> None:
        """
        Resize textbox height to fit rendered text lines.

        Primary method: dlineinfo("end-1c") gives the exact pixel offset of
        the last display line, so we don't need to guess line height.
        Fallback: count(-displaylines) * estimated line height.

        Uses a re-entrancy guard so recursive calls from update_idletasks()
        are skipped, and a change-guard so configure() is only called when
        the computed height differs from the last set value.
        """
        if self._autosize_guard:
            return
        text_widget = getattr(self, "_textbox", None)
        if text_widget is None:
            return
        if self.winfo_width() < 20:
            return  # <Configure> will fire again once the geometry manager assigns a real width

        self._autosize_guard = True
        try:
            target = self._measure_content_height(text_widget)
            if target != self._last_height:
                self._last_height = target
                self.configure(height=target)
                # Ensure parent frames relayout now rather than waiting for the
                # next idle cycle — important when called during streaming.
                try:
                    self.update_idletasks()
                except Exception:
                    pass
        finally:
            self._autosize_guard = False

    def _measure_content_height(self, text_widget: object) -> int:
        """Return the desired CTk-logical-pixel height for the current content.

        Strategy:
          1. count(-displaylines): works regardless of viewport, accurate after
             Tk has recomputed the layout (ensured by the 10ms delay in
             _on_textbox_configure).
          2. dlineinfo("end-1c"): pixel-accurate but only works when the last
             line is in the text widget's viewport.  Used as a cross-check.
        """
        line_height_px = max(18, int(theme.FONT_SIZE * 1.75))

        # --- primary: count display lines (viewport-independent) ---
        display_lines = 0
        try:
            counted = text_widget.count("1.0", "end-1c", "displaylines")  # type: ignore[union-attr]
            display_lines = int(counted[0]) if counted else 0
        except Exception:
            pass

        if display_lines > 0:
            target = max(self._min_height, display_lines * line_height_px + 8)
        else:
            # --- secondary: dlineinfo (pixel-accurate when content is visible) ---
            try:
                info = text_widget.dlineinfo("end-1c")  # type: ignore[union-attr]
                if info:
                    content_h_phys = int(info[1]) + int(info[3])
                    content_h_logical = self._reverse_widget_scaling(content_h_phys)
                    target = max(self._min_height, int(content_h_logical) + 8)
                else:
                    raise ValueError("dlineinfo returned None")
            except Exception:
                # --- last resort: logical line count ---
                try:
                    display_lines = int(str(text_widget.index("end-1c")).split(".")[0])  # type: ignore[union-attr]
                except Exception:
                    display_lines = 1
                target = max(self._min_height, display_lines * line_height_px + 8)

        return min(self._max_height, target)
