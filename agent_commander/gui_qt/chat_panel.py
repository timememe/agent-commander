"""Chat panel — scrollable area with user/assistant bubbles + tool call entries."""

from __future__ import annotations

import math

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QTextOption
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme


# ---------------------------------------------------------------------------
# Markdown view (assistant bubbles)
# ---------------------------------------------------------------------------

class _MarkdownView(QTextBrowser):
    """Read-only QTextBrowser auto-sized to its markdown content."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenExternalLinks(True)
        self.setFrameStyle(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self._max_text_width = 616

        self.document().setDefaultStyleSheet(
            f"body {{ color: {theme.TEXT}; font-family: \"{theme.FONT_FAMILY}\";"
            f"        font-size: {theme.FONT_SIZE}px; }}"
            f"code {{ font-family: Consolas, monospace; background-color: #1A2332;"
            f"        padding: 2px 4px; border-radius: 0px; color: #A8D8FF; }}"
            f"pre  {{ background-color: #1A2332; padding: 8px; border-radius: 0px; }}"
            f"a    {{ color: {theme.ACCENT}; }}"
            f"blockquote {{ margin-left: 4px;"
            f"             padding-left: 8px; color: {theme.TEXT_MUTED}; }}"
        )
        self.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; }"
        )

        self.document().contentsChanged.connect(self._fit_height)
        self._text = ""

    def set_max_text_width(self, width: int) -> None:
        self._max_text_width = max(140, int(width))
        self.setMaximumWidth(self._max_text_width)
        self._fit_height()

    def set_markdown(self, text: str) -> None:
        self._text = text
        self.setMarkdown(text)

    def append_markdown(self, chunk: str) -> None:
        self._text += chunk
        self.setMarkdown(self._text)

    def get_text(self) -> str:
        return self._text

    def _fit_height(self) -> None:
        doc_h = self.document().documentLayout().documentSize().height()
        h = max(28, math.ceil(doc_h) + 14)
        if self.height() != h:
            self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_height()

    def sizeHint(self) -> QSize:
        viewport_w = self.viewport().width()
        width = viewport_w if viewport_w > 0 else self._max_text_width
        width = min(self._max_text_width, max(70, width))
        doc_h = self.document().documentLayout().documentSize().height()
        return QSize(width + 2, max(28, math.ceil(doc_h) + 14))


# ---------------------------------------------------------------------------
# Message bubbles
# ---------------------------------------------------------------------------

class MessageBubble(QFrame):
    """Chat message bubble — plain text for user, markdown for assistant."""

    def __init__(self, role: str, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._role = role
        self._inner_h_pad = 24

        bg = theme.USER_BUBBLE if role == "user" else theme.ASSISTANT_BUBBLE
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border-radius: 14px; }}"
        )
        self.setMaximumWidth(640)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        inner = QVBoxLayout(self)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(0)

        if role == "user":
            self._label = QLabel(text)
            self._label.setWordWrap(True)
            self._label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            self._label.setStyleSheet(
                f"color: {theme.TEXT}; background: transparent;"
                f"font-size: {theme.FONT_SIZE}px;"
            )
            inner.addWidget(self._label)
            self._md_view = None
        else:
            self._label = None
            self._md_view = _MarkdownView()
            self._md_view.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            if text:
                self._md_view.set_markdown(text)
            inner.addWidget(self._md_view)

        self._text = text

    def append_text(self, chunk: str) -> None:
        self._text += chunk
        if self._md_view is not None:
            self._md_view.append_markdown(chunk)
        elif self._label is not None:
            self._label.setText(self._text)

    def get_text(self) -> str:
        return self._text

    def set_max_bubble_width(self, width: int) -> None:
        limit = max(240, int(width))
        if self._md_view is not None:
            content_limit = max(140, limit - self._inner_h_pad)
            text = (self._text or "").strip()
            if text:
                metrics = self._md_view.fontMetrics()
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    lines = [text]
                longest = max(
                    (metrics.horizontalAdvance(line[:220]) for line in lines),
                    default=metrics.horizontalAdvance(" "),
                ) + 14
                text_len = len(text)
                target_content = longest
                if len(lines) > 1:
                    target_content = max(target_content, int(content_limit * 0.52))
                if text_len > 100 and len(lines) == 1:
                    target_content = max(target_content, int(content_limit * 0.62))
                if text_len > 220:
                    target_content = max(target_content, int(content_limit * 0.72))
                if text_len <= 12:
                    target_content = min(target_content, int(content_limit * 0.34))
                if text_len <= 36:
                    target_content = min(target_content, int(content_limit * 0.52))
                target_content = min(content_limit, max(90, target_content))
            else:
                target_content = 90
            target_bubble_w = min(limit, target_content + self._inner_h_pad)
            self.setFixedWidth(target_bubble_w)
            self._md_view.set_max_text_width(target_content)
        else:
            if self.maximumWidth() != limit:
                self.setMaximumWidth(limit)
            if self.minimumWidth() != 0:
                self.setMinimumWidth(0)
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        if self._label is not None:
            content_limit = max(140, limit - self._inner_h_pad)
            text = (self._text or "").strip()
            if text:
                metrics = self._label.fontMetrics()
                lines = text.splitlines() or [text]
                natural = max(
                    (metrics.horizontalAdvance(line) for line in lines if line),
                    default=metrics.horizontalAdvance(" "),
                ) + 14
                text_len = len(text)
                if text_len > 100:
                    natural = max(natural, int(content_limit * 0.62))
                if "\n" in text:
                    natural = max(natural, int(content_limit * 0.52))
                target = min(content_limit, max(90, natural))
            else:
                target = 90
            self._label.setFixedWidth(target)
        self.updateGeometry()


# ---------------------------------------------------------------------------
# Tool call bubble
# ---------------------------------------------------------------------------

class ToolBubble(QFrame):
    """Compact inline record of a tool call (name + args → result)."""

    def __init__(self, name: str, args: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.TOOL_BUBBLE}; border-radius: 6px;"
            "          border: none; }"
        )
        self.setMaximumWidth(640)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)
        layout.setSpacing(6)

        self._icon = QLabel("⚙")
        self._icon.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: transparent; font-size: 12px;"
        )
        layout.addWidget(self._icon)

        self._name_label = QLabel(name)
        self._name_label.setStyleSheet(
            "color: #A8D8FF; background: transparent;"
            "font-family: Consolas, monospace; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self._name_label)

        # Args preview (truncated)
        args_preview = args.replace("\n", " ")[:80]
        if len(args) > 80:
            args_preview += "…"
        self._args_label = QLabel(args_preview)
        self._args_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: transparent;"
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        layout.addWidget(self._args_label, stretch=1)

        self._status_label = QLabel("running…")
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: transparent; font-size: 11px;"
        )
        layout.addWidget(self._status_label)

    def set_result(self, result: str) -> None:
        preview = result.strip().replace("\n", " ")[:100]
        if len(result.strip()) > 100:
            preview += "…"
        self._icon.setText("✓")
        self._icon.setStyleSheet(
            f"color: {theme.SUCCESS}; background: transparent; font-size: 12px;"
        )
        self._status_label.setText(preview or "done")
        self._status_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; background: transparent; font-size: 11px;"
        )

    def set_max_bubble_width(self, width: int) -> None:
        self.setMaximumWidth(max(300, int(width)))
        self.updateGeometry()


# ---------------------------------------------------------------------------
# Chat panel
# ---------------------------------------------------------------------------

class ChatPanel(QScrollArea):
    """Scrollable chat panel: message bubbles + tool call records."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet(f"background-color: {theme.BG_CHAT}; border: none;")

        self._content = QWidget()
        self._content.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        self._layout = QVBoxLayout(self._content)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(8)
        self._layout.setContentsMargins(12, 12, 12, 12)

        self.setWidget(self._content)

        self._current_assistant_bubble: MessageBubble | None = None
        self._pending_tool: ToolBubble | None = None  # last in-flight tool call
        self._message_bubbles: list[MessageBubble] = []
        self._tool_bubbles: list[ToolBubble] = []
        self._constraint_refresh_scheduled = False

        self.verticalScrollBar().rangeChanged.connect(self._scroll_to_bottom)
        self._schedule_constraint_refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_constraint_refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_bubble_constraints()
        self._schedule_constraint_refresh()

    def _schedule_constraint_refresh(self) -> None:
        if self._constraint_refresh_scheduled:
            return
        self._constraint_refresh_scheduled = True
        QTimer.singleShot(0, self._run_scheduled_constraint_refresh)

    def _run_scheduled_constraint_refresh(self) -> None:
        self._constraint_refresh_scheduled = False
        self._update_bubble_constraints()

    def _update_bubble_constraints(self) -> None:
        viewport_w = self.viewport().width() or self.width()
        if viewport_w < 220:
            return
        margins = self._layout.contentsMargins()
        usable_w = viewport_w - margins.left() - margins.right()
        if usable_w < 220:
            return
        msg_limit = max(240, int(usable_w * 0.66))
        tool_limit = max(300, int(usable_w * 0.92))
        for bubble in self._message_bubbles:
            bubble.set_max_bubble_width(msg_limit)
        for bubble in self._tool_bubbles:
            bubble.set_max_bubble_width(tool_limit)

    def _scroll_to_bottom(self) -> None:
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def _make_row(self, widget: QWidget, align: str) -> QWidget:
        """Wrap widget in an HBox row with left or right alignment."""
        row = QWidget()
        row.setStyleSheet(f"background-color: {theme.BG_CHAT};")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if align == "right":
            row_layout.addStretch()
            row_layout.addWidget(widget)
        elif align == "left":
            row_layout.addWidget(widget)
            row_layout.addStretch()
        else:  # full width (tool bubbles)
            row_layout.addWidget(widget)
        return row

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_message(self, role: str, text: str) -> None:
        """Add a complete message bubble (history load or non-streaming)."""
        bubble = MessageBubble(role=role, text=text)
        align = "right" if role == "user" else "left"
        row = self._make_row(bubble, align)
        self._layout.addWidget(row)
        self._message_bubbles.append(bubble)
        self._update_bubble_constraints()
        self._schedule_constraint_refresh()
        if role == "assistant":
            self._current_assistant_bubble = bubble
        else:
            self._current_assistant_bubble = None
        self._pending_tool = None

    def add_user_message(self, text: str) -> None:
        self._current_assistant_bubble = None
        self._pending_tool = None
        self.add_message("user", text)

    def append_assistant_chunk(self, chunk: str, final: bool) -> None:
        """Append streaming chunk — creates bubble on first chunk."""
        if self._current_assistant_bubble is None:
            bubble = MessageBubble(role="assistant", text="")
            row = self._make_row(bubble, "left")
            self._layout.addWidget(row)
            self._message_bubbles.append(bubble)
            self._update_bubble_constraints()
            self._schedule_constraint_refresh()
            self._current_assistant_bubble = bubble
        self._current_assistant_bubble.append_text(chunk)
        self._schedule_constraint_refresh()
        if final:
            self._current_assistant_bubble = None

    def add_tool_start(self, name: str, args: str) -> ToolBubble:
        """Insert a tool-call bubble (call returns it for later update)."""
        self._current_assistant_bubble = None
        tb = ToolBubble(name=name, args=args)
        row = self._make_row(tb, "full")
        self._layout.addWidget(row)
        self._tool_bubbles.append(tb)
        self._update_bubble_constraints()
        self._schedule_constraint_refresh()
        self._pending_tool = tb
        return tb

    def refresh_layout(self) -> None:
        self._update_bubble_constraints()
        self._schedule_constraint_refresh()

    def add_tool_end(self, name: str, result: str) -> None:
        """Update the pending tool bubble with its result."""
        if self._pending_tool is not None:
            self._pending_tool.set_result(result)
            self._pending_tool = None

    def get_last_assistant_text(self) -> str:
        """Return full accumulated text of the most recent assistant bubble."""
        if self._current_assistant_bubble is not None:
            return self._current_assistant_bubble.get_text()
        for i in range(self._layout.count() - 1, -1, -1):
            item = self._layout.itemAt(i)
            if item is None:
                continue
            row = item.widget()
            if row is None:
                continue
            rl = row.layout()
            if rl is None:
                continue
            for j in range(rl.count()):
                child = rl.itemAt(j)
                if child is None:
                    continue
                w = child.widget()
                if isinstance(w, MessageBubble) and w._role == "assistant":
                    return w.get_text()
        return ""
