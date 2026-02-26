"""Configuration schema for agent-commander-gui."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
try:
    from pydantic_settings import BaseSettings
except ImportError:  # pragma: no cover - local fallback when optional dep is absent
    from pydantic import BaseModel as BaseSettings


class CLIAgentConfig(BaseModel):
    """Configuration for one CLI agent binary."""

    enabled: bool = False
    command: str = ""
    working_dir: str = ""


class AgentDefaults(BaseModel):
    """Global defaults for CLI-agent runtime."""

    workspace: str = "~/.agent-commander/workspace"
    active: str = "codex"
    poll_interval_s: float = 0.05
    idle_settle_s: float = 0.20
    turn_timeout_s: float = 300.0


class AgentsConfig(BaseModel):
    """CLI agents configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)
    claude: CLIAgentConfig = Field(default_factory=CLIAgentConfig)
    gemini: CLIAgentConfig = Field(default_factory=CLIAgentConfig)
    codex: CLIAgentConfig = Field(default_factory=CLIAgentConfig)


class GUIConfig(BaseModel):
    """Desktop GUI configuration."""

    theme: str = "dark"
    width: int = 1400
    height: int = 800
    font_size: int = 14
    notify_on_long_tasks: bool = True
    long_task_notify_s: float = 12.0


class ProxyAPIConfig(BaseModel):
    """Configuration for CLIProxyAPI transport mode."""

    enabled: bool = False
    base_url: str = "http://127.0.0.1:8317"
    api_key: str = "agent-commander-local"
    endpoint: str = "/v1/chat/completions"
    request_timeout_s: float = 300.0
    model_claude: str = "claude-sonnet-4-5-20250929"
    model_gemini: str = "gemini-2.5-pro"
    model_codex: str = "gpt-5.1-codex"
    binary_path: str = ""
    config_path: str = ""
    auto_start: bool = True
    take_over_existing: bool = True


class Config(BaseSettings):
    """Root configuration for agent-commander-gui."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    gui: GUIConfig = Field(default_factory=GUIConfig)
    proxy_api: ProxyAPIConfig = Field(default_factory=ProxyAPIConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def get_agent_config(self, name: str) -> CLIAgentConfig | None:
        """Get agent-specific configuration by key."""
        key = (name or "").strip().lower()
        value = getattr(self.agents, key, None)
        return value if isinstance(value, CLIAgentConfig) else None

    model_config = ConfigDict(
        env_prefix="AGENT_COMMANDER_",
        env_nested_delimiter="__",
        extra="ignore",
    )
