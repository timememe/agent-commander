"""Snapshot-based response extraction for CLI agent terminals.

Adapted from AWS cli-agent-orchestrator approach:
instead of parsing a stream of chunks, we take a full terminal snapshot
and extract the response between known start/end markers.
"""

from __future__ import annotations

import re
from enum import Enum, auto


# ── Common ANSI / control character patterns ─────────────────────────────────

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
ANSI_FULL_RE = re.compile(
    r"\x1b\[[0-9;?]*[A-Za-z]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[()][0-9A-Za-z]"
    r"|\x1bP[^\x1b]*\x1b\\"
)
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class TerminalState(Enum):
    """Terminal lifecycle state (mirrors CAO TerminalStatus)."""

    IDLE = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    WAITING_USER_ANSWER = auto()
    ERROR = auto()


def strip_ansi(text: str) -> str:
    """Strip all ANSI escape sequences from text."""
    return ANSI_FULL_RE.sub("", text)


def strip_control(text: str) -> str:
    """Strip non-printable control characters (keep \\n, \\t, \\r)."""
    return CONTROL_CHAR_RE.sub("", text)


# ═══════════════════════════════════════════════════════════════════════════════
# Claude Code  (adapted from CAO providers/claude_code.py)
# ═══════════════════════════════════════════════════════════════════════════════

# ⏺ followed by optional ANSI then whitespace — marks response content
_CLAUDE_RESPONSE_RE = re.compile(r"⏺(?:\x1b\[[0-9;]*m)*\s+")
# Processing indicator: ✶ ... (esc to interrupt)
_CLAUDE_PROCESSING_RE = re.compile(r"[✶✢✽✻·✳].*….*\(esc to interrupt.*\)")
# Idle prompt: >  (with regular space or non-breaking space)
_CLAUDE_IDLE_RE = re.compile(r">\s*[\s\xa0]")
# Waiting for user selection: ❯ followed by numbered options
_CLAUDE_WAITING_RE = re.compile(r"❯.*\d+\.")
# Separator line
_CLAUDE_SEPARATOR_RE = re.compile(r"────────")


def claude_get_status(snapshot: str) -> TerminalState:
    """Determine Claude Code terminal state from full snapshot."""
    if not snapshot:
        return TerminalState.ERROR

    if _CLAUDE_PROCESSING_RE.search(snapshot):
        return TerminalState.PROCESSING

    if _CLAUDE_WAITING_RE.search(snapshot):
        return TerminalState.WAITING_USER_ANSWER

    if _CLAUDE_RESPONSE_RE.search(snapshot) and _CLAUDE_IDLE_RE.search(snapshot):
        return TerminalState.COMPLETED

    if _CLAUDE_IDLE_RE.search(snapshot):
        return TerminalState.IDLE

    return TerminalState.PROCESSING


def claude_extract_response(snapshot: str) -> str:
    """Extract Claude's response from terminal snapshot.

    Finds the last ⏺ marker, extracts text until the next > prompt
    or ──── separator, then strips ANSI and control characters.
    """
    matches = list(_CLAUDE_RESPONSE_RE.finditer(snapshot))
    if not matches:
        return ""

    last_match = matches[-1]
    remaining = snapshot[last_match.end():]

    lines = remaining.split("\n")
    response_lines: list[str] = []

    for line in lines:
        if _CLAUDE_IDLE_RE.match(line) or _CLAUDE_SEPARATOR_RE.search(line):
            break
        response_lines.append(line.strip())

    if not any(line.strip() for line in response_lines):
        return ""

    result = "\n".join(response_lines).strip()
    result = ANSI_RE.sub("", result)
    result = strip_control(result)
    return result.strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Codex CLI  (adapted from CAO providers/codex.py)
# ═══════════════════════════════════════════════════════════════════════════════

_CODEX_IDLE_RE = re.compile(r"(?:❯|›|codex>)")
_CODEX_IDLE_END_RE = re.compile(r"(?:^\s*(?:❯|›|codex>)\s*)\s*\Z", re.MULTILINE)
_CODEX_ASSISTANT_RE = re.compile(r"^(?:assistant|codex|agent)\s*:", re.IGNORECASE | re.MULTILINE)
_CODEX_USER_RE = re.compile(r"^You\b", re.IGNORECASE | re.MULTILINE)
_CODEX_PROCESSING_RE = re.compile(
    r"\b(thinking|working|running|executing|processing|analyzing)\b", re.IGNORECASE
)
_CODEX_WAITING_RE = re.compile(r"^(?:Approve|Allow)\b.*\b(?:y/n|yes/no)\b", re.MULTILINE)
_CODEX_ERROR_RE = re.compile(
    r"^(?:Error:|ERROR:|Traceback \(most recent call last\):|panic:)", re.MULTILINE
)


def codex_get_status(snapshot: str) -> TerminalState:
    """Determine Codex terminal state from snapshot."""
    if not snapshot:
        return TerminalState.ERROR

    clean = strip_ansi(snapshot)
    tail = "\n".join(clean.splitlines()[-25:])

    last_user = None
    for m in _CODEX_USER_RE.finditer(clean):
        last_user = m

    after_user = clean[last_user.start():] if last_user else clean
    has_assistant = bool(last_user and _CODEX_ASSISTANT_RE.search(after_user))
    has_idle_end = bool(_CODEX_IDLE_END_RE.search(clean))

    if last_user is not None and not has_assistant:
        if _CODEX_WAITING_RE.search(after_user):
            return TerminalState.WAITING_USER_ANSWER
        if _CODEX_ERROR_RE.search(after_user):
            return TerminalState.ERROR
    elif last_user is None:
        if _CODEX_WAITING_RE.search(tail):
            return TerminalState.WAITING_USER_ANSWER
        if _CODEX_ERROR_RE.search(tail):
            return TerminalState.ERROR

    if has_idle_end:
        if last_user is not None and has_assistant:
            return TerminalState.COMPLETED
        return TerminalState.IDLE

    return TerminalState.PROCESSING


def codex_extract_response(snapshot: str) -> str:
    """Extract Codex response from terminal snapshot."""
    clean = strip_ansi(snapshot)

    matches = list(_CODEX_ASSISTANT_RE.finditer(clean))
    if not matches:
        return ""

    last_match = matches[-1]
    start = last_match.end()

    idle_after = _CODEX_IDLE_END_RE.search(clean[start:])
    end = start + idle_after.start() if idle_after else len(clean)

    result = clean[start:end].strip()
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Gemini CLI
# ═══════════════════════════════════════════════════════════════════════════════

_GEMINI_RESPONSE_RE = re.compile(r"[✦✧]\s*")
_GEMINI_IDLE_RE = re.compile(r"(?:❯|>)\s*$", re.MULTILINE)


def gemini_get_status(snapshot: str) -> TerminalState:
    """Determine Gemini terminal state from snapshot."""
    if not snapshot:
        return TerminalState.ERROR

    clean = strip_ansi(snapshot)

    has_response = bool(_GEMINI_RESPONSE_RE.search(clean))
    has_idle = bool(_GEMINI_IDLE_RE.search(clean))

    if has_response and has_idle:
        return TerminalState.COMPLETED
    if has_idle:
        return TerminalState.IDLE
    return TerminalState.PROCESSING


def gemini_extract_response(snapshot: str) -> str:
    """Extract Gemini response from snapshot (or raw subprocess output)."""
    clean = strip_ansi(snapshot)

    matches = list(_GEMINI_RESPONSE_RE.finditer(clean))
    if not matches:
        # Fallback for non-interactive mode: return cleaned text as-is
        return strip_control(clean).strip()

    last_match = matches[-1]
    remaining = clean[last_match.end():]

    lines = remaining.split("\n")
    response_lines: list[str] = []
    for line in lines:
        if _GEMINI_IDLE_RE.match(line):
            break
        response_lines.append(line)

    result = "\n".join(response_lines).strip()
    return strip_control(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Dispatch by agent key
# ═══════════════════════════════════════════════════════════════════════════════

_STATUS_DISPATCH = {
    "claude": claude_get_status,
    "codex": codex_get_status,
    "gemini": gemini_get_status,
}

_EXTRACT_DISPATCH = {
    "claude": claude_extract_response,
    "codex": codex_extract_response,
    "gemini": gemini_extract_response,
}


def get_terminal_state(agent_key: str, snapshot: str) -> TerminalState:
    """Get terminal state for given agent from a full snapshot."""
    fn = _STATUS_DISPATCH.get(agent_key)
    if fn is None:
        return TerminalState.PROCESSING
    return fn(snapshot)


def extract_response(agent_key: str, snapshot: str) -> str:
    """Extract agent response from a full terminal snapshot."""
    fn = _EXTRACT_DISPATCH.get(agent_key)
    if fn is None:
        return strip_ansi(snapshot).strip()
    return fn(snapshot)
