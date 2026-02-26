"""Registry of supported CLI agents."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDef:
    """CLI agent metadata."""

    key: str
    name: str
    command: str
    env_override: str
    prompt_patterns: tuple[str, ...]

    def resolve_command(self) -> str:
        """Resolve command from env override or default command."""
        value = os.getenv(self.env_override, "").strip()
        return value or self.command


AGENT_DEFS: dict[str, AgentDef] = {
    "claude": AgentDef(
        key="claude",
        name="Claude Code",
        command="claude",
        env_override="AGENT_COMMANDER_CLAUDE_CMD",
        prompt_patterns=(r"❯\s*$", r"\$\s*$"),
    ),
    "gemini": AgentDef(
        key="gemini",
        name="Gemini CLI",
        command="gemini",
        env_override="AGENT_COMMANDER_GEMINI_CMD",
        prompt_patterns=(r"❯\s*$", r">\s*$"),
    ),
    "codex": AgentDef(
        key="codex",
        name="Codex CLI",
        command="codex",
        env_override="AGENT_COMMANDER_CODEX_CMD",
        prompt_patterns=(r"❯\s*$", r">\s*$", r"›\s*$", r"^\s*›\s"),
    ),
}


def get_agent_def(agent_type: str) -> AgentDef:
    """Get an agent definition by key."""
    key = (agent_type or "").strip().lower()
    if key not in AGENT_DEFS:
        choices = ", ".join(sorted(AGENT_DEFS))
        raise ValueError(f"Unknown agent type '{agent_type}'. Expected one of: {choices}")
    return AGENT_DEFS[key]
