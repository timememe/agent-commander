"""GUI event contracts and lightweight signal bus."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

EventHandler = Callable[[object], None]


@dataclass(frozen=True)
class UISessionSwitch:
    """Session selection event."""

    session_id: str


@dataclass(frozen=True)
class UIUserInput:
    """User input submitted from input bar."""

    session_id: str
    text: str
    agent: str
    timestamp: datetime


@dataclass(frozen=True)
class UIChunk:
    """Assistant chunk delivered to GUI."""

    session_id: str
    text: str
    final: bool = False


@dataclass(frozen=True)
class UISystemMessage:
    """System status/error message for chat surface."""

    session_id: str
    text: str


class EventHub:
    """Simple in-process pub/sub for GUI modules."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        self._handlers[event_name].append(handler)

    def publish(self, event_name: str, payload: object) -> None:
        for handler in list(self._handlers.get(event_name, [])):
            handler(payload)
