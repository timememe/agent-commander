"""PySide6 GUI theme — mirrors gui/theme.py color constants as QSS-compatible strings."""

from __future__ import annotations

import os
from pathlib import Path

BG_APP = "#0B1016"
BG_PANEL = "#101A26"
BG_INPUT = "#0D1621"
BG_CHAT = "#0A131C"
BG_SIDEBAR = "#0E1722"
BORDER = "#23364B"
TEXT = "#E2EAF4"
TEXT_MUTED = "#8FA3BA"
ACCENT = "#3FA8FF"
USER_BUBBLE = "#1E6144"
ASSISTANT_BUBBLE = "#1C2A3A"
SYSTEM_BUBBLE = "#253447"
STATUS_BG = "#0A121B"
SUCCESS = "#3CC57A"
DANGER = "#F06A6A"

# Session card backgrounds
SESSION_ACTIVE_BG = "#1C3249"
SESSION_NORMAL_BG = "#111C2A"
SESSION_HOVER_BG = "#172536"

# Agent avatar colors
AVATAR_CLAUDE = "#7C6FCD"
AVATAR_GEMINI = "#4285F4"
AVATAR_CODEX = "#10A37F"
AVATAR_DEFAULT = "#4A5568"

TOOL_BUBBLE = "#111A24"

FONT_FAMILY = "Segoe UI"
FONT_SIZE = 14


def agent_avatar_color(agent: str) -> str:
    return {
        "claude": AVATAR_CLAUDE,
        "gemini": AVATAR_GEMINI,
        "codex": AVATAR_CODEX,
    }.get((agent or "").lower(), AVATAR_DEFAULT)


def app_stylesheet() -> str:
    """Global QSS applied to QApplication."""
    return f"""
QMainWindow, QWidget {{
    background-color: {BG_APP};
    color: {TEXT};
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}px;
}}
QScrollArea {{
    background-color: {BG_CHAT};
    border: none;
}}
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 0px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
    background: none;
}}
QTextEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: none;
    border-radius: 0px;
    padding: 8px;
    font-family: "{FONT_FAMILY}";
    font-size: {FONT_SIZE}px;
}}
QTextEdit:focus {{
    border: none;
}}
QPushButton {{
    background-color: {ACCENT};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: bold;
    font-family: "{FONT_FAMILY}";
}}
QPushButton:hover {{
    background-color: #4AABFF;
}}
QPushButton:pressed {{
    background-color: #1A8AEE;
}}
QPushButton:disabled {{
    background-color: #1A3A5C;
    color: {TEXT_MUTED};
}}
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: none;
    border-radius: 0px;
    padding: 5px 8px;
}}
QLineEdit:focus {{
    border: none;
}}
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT};
    border: none;
    border-radius: 0px;
    padding: 4px 8px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    color: {TEXT};
    border: none;
    selection-background-color: {SESSION_ACTIVE_BG};
}}
QDialog {{
    background-color: {BG_PANEL};
}}
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QDialogButtonBox QPushButton {{
    min-width: 70px;
}}
"""


def find_icon() -> str | None:
    """Return absolute path to app icon for Qt runtime (dev + frozen)."""
    app_dir = os.environ.get("AGENT_COMMANDER_APP_DIR", "")
    root = Path(app_dir) if app_dir else Path(__file__).resolve().parents[2]
    for name in ("logo_w.ico", "logo_w.png", "agent_commander_logo.png"):
        p = root / name
        if p.exists():
            return str(p)
    return None
