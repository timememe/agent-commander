"""Shared GUI theme defaults."""

from __future__ import annotations

import customtkinter as ctk

WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 800
FONT_SIZE = 14
FONT_FAMILY = "Segoe UI"

COLOR_BG_APP = "#0E1116"
COLOR_BG_PANEL = "#131A22"
COLOR_BG_INPUT = "#101722"
COLOR_BG_CHAT = "#0F141C"
COLOR_BG_SIDEBAR = "#10161F"
COLOR_BORDER = "#223247"
COLOR_TEXT = "#D9E2EF"
COLOR_TEXT_MUTED = "#93A3B8"
COLOR_ACCENT = "#2E9BFF"
COLOR_USER_BUBBLE = "#1B5E3A"
COLOR_ASSISTANT_BUBBLE = "#1D2734"
COLOR_SYSTEM_BUBBLE = "#263241"
COLOR_TOOL_BUBBLE = "#12181F"      # tool call log bubble (dark, compact)
COLOR_STATUS_BG = "#0B1119"
COLOR_SUCCESS = "#39C172"
COLOR_DANGER = "#EA5F5F"

# Agent avatar colors (circles in sidebar cards and chat bubbles)
COLOR_AVATAR_CLAUDE = "#7C6FCD"   # purple (Anthropic)
COLOR_AVATAR_GEMINI = "#4285F4"   # Google blue
COLOR_AVATAR_CODEX = "#10A37F"    # OpenAI green
COLOR_AVATAR_DEFAULT = "#4A5568"  # slate fallback
COLOR_AVATAR_USER = "#1B8C55"     # user bubble avatar

# Session card backgrounds
COLOR_SESSION_ACTIVE_BG = "#192B3E"  # active card bg
COLOR_SESSION_NORMAL_BG = "#111927"  # normal card bg
COLOR_SESSION_HOVER_BG = "#141E2C"   # hover card bg

# Bubble layout
BUBBLE_USER_LEFT_MARGIN = 160        # px left-padding for user bubbles (pushes right)
AVATAR_SIZE = 28                     # avatar circle diameter px


def agent_avatar_color(agent: str) -> str:
    """Return avatar color for a given agent name."""
    return {
        "claude": COLOR_AVATAR_CLAUDE,
        "gemini": COLOR_AVATAR_GEMINI,
        "codex": COLOR_AVATAR_CODEX,
    }.get((agent or "").lower(), COLOR_AVATAR_DEFAULT)


def find_icon() -> str | None:
    """Return absolute path to logo_w.ico, works in dev and frozen (PyInstaller) mode."""
    import os
    from pathlib import Path

    app_dir = os.environ.get("AGENT_COMMANDER_APP_DIR", "")
    root = Path(app_dir) if app_dir else Path(__file__).resolve().parents[2]
    ico = root / "logo_w.ico"
    return str(ico) if ico.exists() else None


def apply_window_icon(window: object) -> None:
    """Apply logo_w.ico to any Tk/CTk toplevel (title bar + taskbar).

    Uses after(50) to work around the Windows CTkToplevel race condition
    where iconbitmap() called synchronously in __init__ is silently ignored.
    """
    ico = find_icon()
    if ico is None:
        return
    try:
        window.after(50, lambda: window.iconbitmap(ico))  # type: ignore[union-attr]
    except Exception:
        pass


def setup_theme() -> None:
    """Apply global appearance settings."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
