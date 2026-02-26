"""Filter terminal noise from CLI agent output.

Removes spinners, TUI chrome, progress bars, status lines, and other
non-content output that should not appear in chat messages.

Agent-specific noise handled:
- Claude Code: trust dialog, ──── borders, tool-use headers, security guide
- Gemini CLI: ░▀▄ logo/borders, status bar, placeholder, /auth lines
- Codex CLI: pasted-content echo, context-left status, › prompt chrome
"""

from __future__ import annotations

import re

# ── Compiled patterns ─────────────────────────────────────────────────────────

# Braille spinner characters (⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏ and variants)
SPINNER_BRAILLE_RE = re.compile(
    r"[\u2800-\u28ff]"
)

# Common ASCII/Unicode spinners: ⣾⣽⣻⢿⡿⣟⣯⣷ |/-\ ◐◑◒◓ ⠋⠙ etc.
# Note: excludes plain `-` followed by space+text (markdown lists).
SPINNER_LINE_RE = re.compile(
    r"^[\s]*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷|/\\◐◑◒◓●○◉◎]"
    r"\s+.{0,60}\.{0,3}\s*$"
)

# Box-drawing characters (used for TUI frames/borders)
BOX_DRAWING_RE = re.compile(r"^[\s\u2500-\u257f\u2580-\u259f\u2502\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c]+$")

# Lines that are only whitespace + box-drawing + decorative chars
DECORATIVE_LINE_RE = re.compile(
    r"^[\s─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┘├┤┬┴┼╌╍╎╏═║╔╗╚╝╠╣╦╩╬"
    r"\u2500-\u257f\u2580-\u259f\u2800-\u28ff\-=_~*+]+$"
)

# Lines made entirely of block elements (Gemini logo, borders)
# ░▒▓█▀▄▌▐ and similar
BLOCK_ELEMENTS_RE = re.compile(r"^[\s░▒▓█▀▄▌▐\u2580-\u259f]+$")

# Status/progress lines with memory, rate, percentage
STATUS_MEM_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:kb|mb|gb)\b", re.IGNORECASE)
STATUS_RATE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:tok/s|tokens?/s|it/s|t/s)\b", re.IGNORECASE)
PROGRESS_PCT_RE = re.compile(r"\b\d{1,3}%")
PROGRESS_BAR_RE = re.compile(r"[█▓▒░]{3,}|[=>{3,}|[\#]{3,}")

# Common TUI hint/placeholder lines
TUI_HINT_RE = re.compile(
    r"type\s+(a\s+)?(?:your\s+)?message|"
    r"@path/to/file|"
    r"press\s+enter|"
    r"enter\s+to\s+confirm|"
    r"esc\s+to\s+(cancel|undo|close)|"
    r"ctrl[+\-]c\s+to\s+(quit|exit|cancel)|"
    r"/help\s+for\s+commands|"
    r"security\s+guide",
    re.IGNORECASE,
)

# Model info / status bar lines (e.g. "/model claude-3.5 128kb")
MODEL_STATUS_RE = re.compile(
    r"(?:/model\s+\S+|"
    r"no\s+sandbox|"
    r"auto-?compact|"
    r"\bcontext\s*:\s*\d+|"
    r"\bcost\s*:\s*\$[\d.]+)",
    re.IGNORECASE,
)

# File count summary lines (e.g. "5 files changed")
FILE_HINT_RE = re.compile(r"^\s*\d+\s+\S+\s+files?\s*$", re.IGNORECASE)

# Repeated dot/ellipsis lines (thinking indicators)
THINKING_RE = re.compile(r"^[\s.…⋯·•]+$")

# Claude Code specific: tool-use header lines like "⏎ Read(file.py)"
TOOL_HEADER_RE = re.compile(
    r"^[\s⏎↩⮐➤▶►▸‣→›»]?\s*"
    r"(Read|Write|Edit|Bash|Search|Glob|Grep|List|Exec|WebFetch|WebSearch|TodoRead|TodoWrite)"
    r"\s*\(.*\)\s*$"
)

# Lines that are just a cursor marker or empty prompt
CURSOR_ONLY_RE = re.compile(r"^[\s❯>$›»▸►→\-_|]*$")

# ── Agent-specific patterns ───────────────────────────────────────────────────

# Codex: echo of pasted content "› [Pasted Content 8905 chars]"
CODEX_PASTED_RE = re.compile(
    r"^\s*›?\s*(?:\[)?\s*Pasted\s+Content\s+\d+\s+chars?\s*(?:\])?\s*$",
    re.IGNORECASE,
)
CODEX_PASTED_REPEATED_RE = re.compile(
    r"^\s*(?:›?\s*(?:\[)?\s*Pasted\s+Content\s+\d+\s+chars?\s*(?:\])?\s*)+$",
    re.IGNORECASE,
)

# Codex: context status line "100% context left"
CODEX_CONTEXT_RE = re.compile(
    r"^\s*\d{1,3}%\s+context\s+left\s*$",
    re.IGNORECASE,
)

# Claude Code: trust dialog lines
CLAUDE_TRUST_RE = re.compile(
    r"(?:yes,?\s+i\s+trust\s+this\s+folder|"
    r"no,?\s+exit|"
    r"quick\s+safety\s+check|"
    r"is\s+this\s+a\s+project\s+you\s+created|"
    r"claude\s+code'?l?l?\s+be\s+able\s+to\s+read|"
    r"accessing\s+workspace|"
    r"well-known\s+open\s+source)",
    re.IGNORECASE,
)

# Gemini: auth/trust/permission info lines
GEMINI_CHROME_RE = re.compile(
    r"(?:logged\s+in\s+with\s+google|"
    r"/auth\b|"
    r"loaded\s+cached\s+credentials|"
    r"hook\s+registry\s+initialized|"
    r"this\s+folder\s+is\s+untrusted|"
    r"project\s+settings.*will\s+not\s+be\s+applied|"
    r"will\s+not\s+be\s+applied\s+for\s+this\s+folder|"
    r"use\s+the\s+/permissions\s+command|"
    r"\d+\s+GEMINI\.md\s+file)",
    re.IGNORECASE,
)

# Gemini: bottom status bar "~\.agent-commander\workspace  untrusted  Auto (Gemini 3) /model |"
GEMINI_STATUS_BAR_RE = re.compile(
    r"(?:untrusted|trusted)\s+.*(?:/model|Auto\s*\()",
    re.IGNORECASE,
)


def is_noise_line(line: str) -> bool:
    """Check if a single line is terminal noise (not meaningful content)."""
    stripped = line.strip()
    if not stripped:
        return True

    # ── Generic TUI noise ──

    if BOX_DRAWING_RE.fullmatch(stripped):
        return True

    if DECORATIVE_LINE_RE.fullmatch(stripped):
        return True

    if BLOCK_ELEMENTS_RE.fullmatch(stripped):
        return True

    if THINKING_RE.fullmatch(stripped):
        return True

    if CURSOR_ONLY_RE.fullmatch(stripped):
        return True

    if FILE_HINT_RE.fullmatch(stripped):
        return True

    if SPINNER_LINE_RE.fullmatch(stripped):
        return True

    if TUI_HINT_RE.search(stripped):
        return True

    # Status bar lines: contain model info AND memory/rate info
    if MODEL_STATUS_RE.search(stripped) and (
        STATUS_MEM_RE.search(stripped) or STATUS_RATE_RE.search(stripped)
    ):
        return True

    # ── Codex-specific ──

    if CODEX_PASTED_RE.fullmatch(stripped):
        return True
    if CODEX_PASTED_REPEATED_RE.fullmatch(stripped):
        return True

    if CODEX_CONTEXT_RE.fullmatch(stripped):
        return True

    # ── Claude Code-specific ──

    if CLAUDE_TRUST_RE.search(stripped):
        return True

    # ── Gemini-specific ──

    if GEMINI_CHROME_RE.search(stripped):
        return True

    if GEMINI_STATUS_BAR_RE.search(stripped):
        return True

    return False


def is_repaint_noise(text: str) -> bool:
    """Check if an entire text block is just TUI repaint noise.

    Returns True when every non-empty line is noise — meaning
    the whole block can be safely discarded.
    """
    meaningful = 0
    for raw_line in text.splitlines():
        if not raw_line.strip():
            continue
        if not is_noise_line(raw_line):
            meaningful += 1

    return meaningful == 0


def filter_noise_lines(text: str) -> str:
    """Remove noise lines from text while preserving content lines.

    Unlike is_repaint_noise (all-or-nothing), this strips individual
    noise lines from a mixed block. Use this for post-processing
    the final assembled response.
    """
    result_lines: list[str] = []
    in_code_block = False

    for line in text.splitlines():
        stripped = line.strip()

        # Track code blocks — never filter inside them
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            result_lines.append(line)
            continue

        if in_code_block:
            result_lines.append(line)
            continue

        if is_noise_line(line):
            continue

        result_lines.append(line)

    # Remove trailing empty lines
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    return "\n".join(result_lines)


def normalize_signature(text: str) -> str:
    """Produce a normalized signature for deduplication.

    Two text blocks with the same signature are considered
    the same content (e.g. a spinner that only differs by
    the spinner character or a timestamp).
    """
    normalized = text.lower()
    normalized = re.sub(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", "<time>", normalized)
    normalized = PROGRESS_PCT_RE.sub("<pct>", normalized)
    normalized = STATUS_MEM_RE.sub("<mem>", normalized)
    normalized = STATUS_RATE_RE.sub("<rate>", normalized)
    normalized = SPINNER_BRAILLE_RE.sub("", normalized)
    normalized = re.sub(r"[\u2580-\u259f]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:800]
