"""Session list widget — left panel with chat list and "+ New Chat" button."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from agent_commander.gui_qt import theme
from agent_commander.session.gui_store import SessionMeta


class SessionCard(QFrame):
    """Clickable card representing one chat session in the list."""

    def __init__(
        self,
        meta: SessionMeta,
        on_select: Callable[[str], None],
        on_delete: Callable[[str], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._session_id = meta.session_id
        self._on_select = on_select
        self._on_delete = on_delete
        self._active = False
        self._raw_title = meta.title or meta.session_id[:12]

        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._apply_style(active=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._title_label = QLabel(self._raw_title)
        self._title_label.setMinimumWidth(0)
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._title_label.setStyleSheet(
            f"color: {theme.TEXT}; font-weight: bold; font-size: {theme.FONT_SIZE}px;"
            " background: transparent;"
        )
        layout.addWidget(self._title_label)

        agent_color = theme.agent_avatar_color(meta.agent)
        self._agent_label = QLabel(meta.agent.upper() if meta.agent else "—")
        self._agent_label.setStyleSheet(
            f"color: {agent_color}; font-size: 10px; background: transparent;"
        )
        layout.addWidget(self._agent_label)

        self._preview_label = QLabel("")
        self._preview_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        self._preview_label.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        self._preview_label.setWordWrap(False)
        layout.addWidget(self._preview_label)
        self._sync_title_text()

    def _apply_style(self, active: bool) -> None:
        bg = theme.SESSION_ACTIVE_BG if active else theme.SESSION_NORMAL_BG
        self.setStyleSheet(
            f"QFrame {{ background-color: {bg}; border: none; }}"
            f"QFrame:hover {{ background-color: {theme.SESSION_HOVER_BG}; }}"
        )
        self._active = active

    def set_active(self, active: bool) -> None:
        self._apply_style(active)

    def update_meta(self, meta: SessionMeta) -> None:
        self._raw_title = meta.title or meta.session_id[:12]
        self._sync_title_text()
        agent_color = theme.agent_avatar_color(meta.agent)
        self._agent_label.setText(meta.agent.upper() if meta.agent else "—")
        self._agent_label.setStyleSheet(
            f"color: {agent_color}; font-size: 10px; background: transparent;"
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_title_text()

    def _sync_title_text(self) -> None:
        metrics = self._title_label.fontMetrics()
        avail = max(60, self._title_label.width() or (self.width() - 24))
        self._title_label.setMaximumWidth(avail)
        self._title_label.setText(
            metrics.elidedText(self._raw_title, Qt.TextElideMode.ElideRight, avail)
        )

    def set_preview(self, text: str) -> None:
        preview = text.replace("\n", " ")[:50]
        self._preview_label.setText(preview)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_select(self._session_id)
        super().mousePressEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {theme.BG_PANEL}; color: {theme.TEXT};"
            f"         border: 1px solid {theme.BORDER}; }}"
            f"QMenu::item:selected {{ background-color: {theme.SESSION_ACTIVE_BG}; }}"
        )
        delete_action = menu.addAction("Delete chat")
        action = menu.exec(event.globalPos())
        if action == delete_action:
            self._on_delete(self._session_id)


class SessionListWidget(QWidget):
    """Left panel: '+ New Chat' button + scrollable list of session cards."""

    def __init__(
        self,
        on_new_chat: Callable[[], None],
        on_select: Callable[[str], None],
        on_delete: Callable[[str], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._on_select = on_select
        self._on_delete = on_delete or (lambda _: None)
        self._cards: dict[str, SessionCard] = {}
        self._active_id: str | None = None
        self._scroll: QScrollArea | None = None

        self.setFixedWidth(280)
        self.setStyleSheet(
            f"background-color: {theme.BG_SIDEBAR};"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        new_btn = QPushButton("+ New Chat")
        new_btn.setFixedHeight(44)
        new_btn.setStyleSheet(
            f"QPushButton {{ background-color: {theme.ACCENT}; color: white;"
            f" border: none; border-radius: 0px; font-weight: bold; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: #4AABFF; }}"
            f"QPushButton:pressed {{ background-color: #1A8AEE; }}"
        )
        new_btn.clicked.connect(on_new_chat)
        root.addWidget(new_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {theme.BG_SIDEBAR}; border: none; }}"
        )
        scroll.setViewportMargins(0, 0, 0, 0)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet(f"background-color: {theme.BG_SIDEBAR};")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(8, 6, 8, 6)
        self._cards_layout.setSpacing(4)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll.setWidget(self._cards_container)
        root.addWidget(scroll, stretch=1)

    def add_session(self, meta: SessionMeta) -> None:
        if meta.session_id in self._cards:
            return
        card = SessionCard(
            meta=meta,
            on_select=self._on_select,
            on_delete=self._on_delete,
        )
        self._cards[meta.session_id] = card
        self._cards_layout.insertWidget(0, card)
        self._sync_card_widths()

    def update_session(self, meta: SessionMeta) -> None:
        card = self._cards.get(meta.session_id)
        if card:
            card.update_meta(meta)

    def set_active(self, session_id: str) -> None:
        if self._active_id and self._active_id in self._cards:
            self._cards[self._active_id].set_active(False)
        self._active_id = session_id
        if session_id in self._cards:
            self._cards[session_id].set_active(True)
        self._sync_card_widths()

    def remove_session(self, session_id: str) -> None:
        card = self._cards.pop(session_id, None)
        if card is None:
            return
        self._cards_layout.removeWidget(card)
        card.deleteLater()
        if self._active_id == session_id:
            self._active_id = None
        self._sync_card_widths()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_card_widths()

    def _sync_card_widths(self) -> None:
        if not self._cards:
            return
        margins = self._cards_layout.contentsMargins()
        avail = self._cards_container.width() - margins.left() - margins.right()
        if self._scroll is not None and self._scroll.verticalScrollBar().isVisible():
            avail -= self._scroll.verticalScrollBar().width()
        avail = max(120, avail)
        for card in self._cards.values():
            card.setMaximumWidth(avail)
