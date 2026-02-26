"""Context builder for assembling agent prompts."""

import platform
from pathlib import Path
from typing import Any

from agent_commander.agent.memory import MemoryStore
from agent_commander.agent.skills import SkillsLoader


class ContextBuilder:
    """
    Builds the context (system prompt + messages) for the agent.
    
    Assembles bootstrap files, memory, skills, and conversation history
    into a coherent prompt for the LLM.
    """
    
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]
    
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)
    
    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        Build the system prompt from bootstrap files, memory, and skills.
        
        Args:
            skill_names: Optional list of skills to include.
        
        Returns:
            Complete system prompt.
        """
        parts = []
        
        # Core identity
        parts.append(self._get_identity())
        
        # Bootstrap files
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)
        
        # Memory context
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")
        
        # Skills - progressive loading
        # 1. Always-loaded skills: include full content
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")
        
        # 2. Available skills: only show summary (agent uses read_file to load)
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")
        
        return "\n\n---\n\n".join(parts)

    def build_cli_turn_prompt(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        cwd: str | None = None,
        max_history_messages: int = 30,
    ) -> str:
        """
        Build a plain-text prompt for CLI-agent pass-through mode.

        The prompt carries:
        - system context (bootstrap/memory/skills)
        - compact recent chat history
        - current user message
        """
        sections: list[str] = []

        system_prompt = self.build_system_prompt(skill_names)
        sections.append(f"# System Context\n{system_prompt}")

        session_rows: list[str] = []
        if channel and chat_id:
            session_rows.append(f"Channel: {channel}")
            session_rows.append(f"Chat ID: {chat_id}")
        if cwd:
            session_rows.append(f"Working Directory: {cwd}")
            session_rows.append(
                "Tooling note: default all filesystem/shell operations to this directory. "
                "Do not set tool `cwd` explicitly unless the user asks for another path."
            )
        if session_rows:
            sections.append(f"# Session\n" + "\n".join(session_rows))

        history_text = self._format_history(history, max_history_messages=max_history_messages)
        if history_text:
            sections.append(f"# Conversation History\n{history_text}")

        sections.append(f"# Current User Message\n{current_message}")
        sections.append("Respond only with your assistant answer.")

        return "\n\n".join(sections)
    
    def _get_identity(self) -> str:
        """Get the core identity section."""
        from datetime import datetime
        import time as _time
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = _time.strftime("%Z") or "UTC"
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"
        
        return f"""# agent-commander-gui 🐈

You are Agent Commander running in desktop GUI mode.
You interact through a CLI coding agent session (Claude Code, Gemini CLI, or Codex CLI).
The CLI agent controls its own tool usage and reasoning loop.

## Current Time
{now} ({tz})

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Memory files: {workspace_path}/memory/MEMORY.md
- Daily notes: {workspace_path}/memory/YYYY-MM-DD.md
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md
The workspace is your project root, but the active chat working directory can differ.
When `# Session` includes `Working Directory`, treat that as the default location for tool calls.

When responding, return the direct final assistant text.
Do not output internal transport wrappers, channel commands, or tool schema blocks unless the user asks.

Always be helpful, accurate, and concise.
When remembering something, write to {workspace_path}/memory/MEMORY.md"""

    def _format_history(self, history: list[dict[str, Any]], max_history_messages: int) -> str:
        if not history:
            return ""
        trimmed = history[-max_history_messages:]
        rows: list[str] = []
        for item in trimmed:
            role = str(item.get("role", "user")).strip().lower()
            content = item.get("content", "")
            if isinstance(content, list):
                content = str(content)
            content_text = str(content).strip()
            if not content_text:
                continue
            rows.append(f"{role.upper()}: {content_text}")
        return "\n\n".join(rows)
    
    def _load_bootstrap_files(self) -> str:
        """Load all bootstrap files from workspace."""
        parts = []
        
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")
        
        return "\n\n".join(parts) if parts else ""
    
