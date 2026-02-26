"""Persistence helpers for GUI runtime state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowState:
    """Stored window geometry."""

    width: int
    height: int
    x: int
    y: int


def default_state_path() -> Path:
    """Return default path for persisted GUI state."""
    return Path.home() / ".agent-commander" / "gui_state.json"


def load_window_state(path: Path | None = None) -> WindowState | None:
    """Load persisted window geometry from disk."""
    target = path or default_state_path()
    if not target.exists():
        return None

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return WindowState(
            width=int(payload["width"]),
            height=int(payload["height"]),
            x=int(payload["x"]),
            y=int(payload["y"]),
        )
    except Exception:
        return None


def save_window_state(state: WindowState, path: Path | None = None) -> None:
    """Persist window geometry to disk."""
    target = path or default_state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "width": state.width,
        "height": state.height,
        "x": state.x,
        "y": state.y,
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
