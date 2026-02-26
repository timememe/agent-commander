"""In-chat text search state and navigation."""

from __future__ import annotations

from agent_commander.gui.chat_panel import ChatPanel


class SearchHandler:
    """Manages in-chat search state, deduplication, and navigation."""

    def __init__(self) -> None:
        self._last_query = ""

    @property
    def last_query(self) -> str:
        return self._last_query

    def run(self, forward: bool, chat_panel: ChatPanel, query: str) -> tuple[int, int]:
        """Run search or navigate to next/prev match.

        Deduplicates: a fresh search from the top is started when *query*
        differs from the last query; otherwise navigation continues in the
        requested direction.

        Returns:
            (current_index, total_matches)
        """
        if query != self._last_query:
            self._last_query = query
            index, total = chat_panel.search(query, forward=True)
        else:
            index, total = chat_panel.search(query, forward=forward)
        return index, total

    def clear(self, chat_panel: ChatPanel) -> None:
        """Reset last query and remove search highlights from chat panel."""
        self._last_query = ""
        chat_panel.clear_search()
