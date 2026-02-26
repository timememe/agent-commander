"""CLI commands for agent-commander-gui."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import typer
from loguru import logger
from rich.console import Console

from agent_commander import __version__

app = typer.Typer(
    name="agent_commander",
    help="agent-commander-gui - Desktop CLI-agent workspace",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"agent-commander v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None,
        "--version",
        "-v",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """agent-commander-gui entrypoint."""
    del version


@app.command()
def onboard(
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing config without prompt.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Do not ask interactive questions during setup.",
    ),
) -> None:
    """Initialize agent-commander-gui configuration and workspace."""
    from agent_commander.config.loader import get_config_path, save_config
    from agent_commander.config.schema import Config
    from agent_commander.utils.helpers import get_workspace_path

    config_path = get_config_path()
    if config_path.exists():
        if not force and non_interactive:
            console.print(f"[yellow]Config already exists at {config_path} (skip).[/yellow]")
            raise typer.Exit()
        if not force:
            console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
            if not typer.confirm("Overwrite?"):
                raise typer.Exit()

    config = Config()
    _run_setup_wizard(config, interactive=not non_interactive)
    save_config(config)
    console.print(f"[green]OK[/green] Created config at {config_path}")

    workspace = get_workspace_path()
    console.print(f"[green]OK[/green] Created workspace at {workspace}")
    _create_workspace_templates(workspace)

    console.print("\nagent-commander-gui is ready!")
    console.print("\nNext steps:")
    console.print("  1. (Optional) edit [cyan]~/.agent-commander/config.json[/cyan] and set CLI commands per agent")
    console.print("  2. Start desktop app: [cyan]agent-commander gui[/cyan]")


def _create_workspace_templates(workspace: Path) -> None:
    templates = {
        "AGENTS.md": """# Agent Instructions

You are a helpful AI assistant. Be concise, accurate, and friendly.

## Guidelines

- Explain what you are doing before taking actions
- Ask for clarification when request intent is ambiguous
- Prefer practical and verifiable solutions
""",
        "SOUL.md": """# Soul

I am agent-commander-gui, a desktop assistant focused on coding and project execution.
""",
        "USER.md": """# User

User preferences and long-term constraints.
""",
    }

    for filename, content in templates.items():
        file_path = workspace / filename
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")
            console.print(f"  [dim]Created {filename}[/dim]")

    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(
            "# Long-term Memory\n\nStore durable context and user preferences here.\n",
            encoding="utf-8",
        )
        console.print("  [dim]Created memory/MEMORY.md[/dim]")

    skills_dir = workspace / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)


def _resolve_workdir(raw: str, workspace: Path) -> str:
    value = (raw or "").strip()
    if not value:
        return str(workspace)
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = (workspace / candidate).resolve()
    return str(candidate)


def _apply_agent_overrides(config: "Config", workspace: Path) -> dict[str, str]:
    from agent_commander.providers.agent_registry import AGENT_DEFS

    workdirs: dict[str, str] = {}
    for key, agent_def in AGENT_DEFS.items():
        agent_cfg = config.get_agent_config(key)
        if not agent_cfg:
            workdirs[key] = str(workspace)
            continue

        command = (agent_cfg.command or "").strip()
        if command:
            os.environ[agent_def.env_override] = command

        workdirs[key] = _resolve_workdir(agent_cfg.working_dir, workspace)
    return workdirs


def _enabled_agents(config: "Config") -> list[str]:
    from agent_commander.providers.agent_registry import AGENT_DEFS

    enabled: list[str] = []
    for key in AGENT_DEFS:
        cfg = config.get_agent_config(key)
        if cfg and cfg.enabled:
            enabled.append(key)
    return enabled


def _detect_available_agents() -> dict[str, str]:
    """Detect installed CLI agents from PATH."""
    from agent_commander.providers.agent_registry import AGENT_DEFS

    detected: dict[str, str] = {}
    for key, agent_def in AGENT_DEFS.items():
        configured = os.getenv(agent_def.env_override, "").strip()
        command = configured or agent_def.command
        binary = command.split()[0] if command else ""
        if not binary:
            continue
        resolved = shutil.which(binary)
        if resolved:
            detected[key] = resolved
    return detected


def _apply_detected_agents(config: "Config", detected: dict[str, str]) -> None:
    for key, path in detected.items():
        cfg = config.get_agent_config(key)
        if cfg is None:
            continue
        cfg.enabled = True
        if not (cfg.command or "").strip():
            cfg.command = path

    if config.agents.defaults.active not in detected:
        for preferred in ("codex", "claude", "gemini"):
            if preferred in detected:
                config.agents.defaults.active = preferred
                break


def _run_setup_wizard(config: "Config", *, interactive: bool) -> bool:
    """
    First-launch setup wizard for CLI agent detection.

    Returns True if configuration was modified.
    """
    if _enabled_agents(config):
        return False

    detected = _detect_available_agents()
    if not detected:
        console.print("[yellow]No installed CLI agents detected in PATH.[/yellow]")
        console.print("Install at least one of: claude, gemini, codex")
        return False

    console.print("\nDetected CLI agents:")
    for key, path in detected.items():
        console.print(f"  - {key}: [cyan]{path}[/cyan]")

    if interactive and not typer.confirm("Apply detected agents to config?", default=True):
        return False

    _apply_detected_agents(config, detected)

    if interactive and len(detected) > 1:
        selected = typer.prompt(
            f"Default agent ({', '.join(detected.keys())})",
            default=config.agents.defaults.active,
        ).strip().lower()
        if selected in detected:
            config.agents.defaults.active = selected

    return True


def _project_root() -> Path:
    app_dir = os.environ.get("AGENT_COMMANDER_APP_DIR", "")
    if app_dir:
        return Path(app_dir)
    return Path(__file__).resolve().parents[2]


def _build_proxy_server_manager(config: "Config"):
    if not config.proxy_api.enabled:
        return None
    from agent_commander.providers.proxy_server import ProxyServerManager

    return ProxyServerManager(
        binary_path=config.proxy_api.binary_path,
        config_path=config.proxy_api.config_path,
        base_url=config.proxy_api.base_url,
        api_key=config.proxy_api.api_key,
        project_root=str(_project_root()),
    )


@app.command()
def gui(
    agent: str = typer.Option("", "--agent", help="Default agent (claude|gemini|codex)"),
) -> None:
    """Start Agent Commander desktop GUI."""
    from agent_commander.agent.loop import AgentLoop
    from agent_commander.bus.queue import MessageBus
    from agent_commander.config.loader import load_config, save_config
    from agent_commander.gui import theme as gui_theme
    from agent_commander.gui.channel import GUIChannel
    from agent_commander.providers.agent_registry import AGENT_DEFS
    from agent_commander.providers.base import CLIAgentProvider
    from agent_commander.providers.proxy_api import ProxyAPIProvider
    from agent_commander.session.gui_store import GUIStore
    from agent_commander.session.extension_store import ExtensionStore
    from agent_commander.session.skill_store import SkillStore, seed_starter_skills

    config = load_config()
    if _run_setup_wizard(config, interactive=False):
        save_config(config)

    # In frozen builds, always ensure proxy_api points to the bundled binary.
    if os.environ.get("AGENT_COMMANDER_FROZEN"):
        root = _project_root()
        name = "cli-proxy-api.exe" if os.name == "nt" else "cli-proxy-api"
        proxy_bin = root / "cliproxyapi" / name
        if proxy_bin.is_file():
            changed = False
            if not config.proxy_api.enabled:
                config.proxy_api.enabled = True
                changed = True
            bundled_bin = str(proxy_bin)
            if config.proxy_api.binary_path != bundled_bin:
                config.proxy_api.binary_path = bundled_bin
                changed = True
            cfg_yaml = proxy_bin.parent / "config.yaml"
            if cfg_yaml.is_file() and config.proxy_api.config_path != str(cfg_yaml):
                config.proxy_api.config_path = str(cfg_yaml)
                changed = True
            if not config.proxy_api.api_key:
                config.proxy_api.api_key = "agent-commander-local"
                changed = True
            if not config.proxy_api.auto_start:
                config.proxy_api.auto_start = True
                changed = True
            if changed:
                save_config(config)

    workspace = config.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)

    selected_agent = (agent or config.agents.defaults.active or "codex").strip().lower()
    if selected_agent not in AGENT_DEFS:
        choices = ", ".join(sorted(AGENT_DEFS))
        console.print(f"[red]Unknown agent '{selected_agent}'. Expected: {choices}[/red]")
        raise typer.Exit(1)

    if config.gui.font_size > 0:
        gui_theme.FONT_SIZE = config.gui.font_size

    agent_workdirs = _apply_agent_overrides(config, workspace)
    default_cwd = agent_workdirs.get(selected_agent, str(workspace))

    # CLIProxyAPI server manager (core lifecycle).
    server_manager = _build_proxy_server_manager(config)
    if server_manager is not None and config.proxy_api.auto_start:
        console.print("Starting CLIProxyAPI server...")
        if server_manager.start(
            timeout_s=8.0,
            take_over_existing=config.proxy_api.take_over_existing,
        ):
            console.print("[green]CLIProxyAPI server is running[/green]")
        else:
            console.print("[yellow]CLIProxyAPI server failed to start - chat may not work[/yellow]")

    from agent_commander.cron.service import CronService
    from agent_commander.session.project_store import ProjectStore

    session_store = GUIStore()
    skill_store = SkillStore()
    seed_starter_skills(skill_store)  # no-op if skills already exist
    project_store = ProjectStore()
    extension_store = ExtensionStore()

    cron_store_path = Path.home() / ".agent-commander" / "cron.json"
    cron_service = CronService(store_path=cron_store_path)

    bus = MessageBus()
    gui_channel = GUIChannel(
        bus=bus,
        default_cwd=default_cwd,
        default_agent=selected_agent,
        window_width=config.gui.width,
        window_height=config.gui.height,
        agent_workdirs=agent_workdirs,
        notify_on_long_tasks=config.gui.notify_on_long_tasks,
        long_task_notify_s=config.gui.long_task_notify_s,
        server_manager=server_manager,
        session_store=session_store,
        skill_store=skill_store,
        cron_service=cron_service,
        project_store=project_store,
        extension_store=extension_store,
    )
    if config.proxy_api.enabled:
        cli_provider = ProxyAPIProvider(
            base_url=config.proxy_api.base_url,
            api_key=config.proxy_api.api_key,
            endpoint=config.proxy_api.endpoint,
            request_timeout_s=config.proxy_api.request_timeout_s,
            model_claude=config.proxy_api.model_claude,
            model_gemini=config.proxy_api.model_gemini,
            model_codex=config.proxy_api.model_codex,
            extension_store=extension_store,
        )
    else:
        cli_provider = CLIAgentProvider(
            poll_interval_s=config.agents.defaults.poll_interval_s,
            idle_settle_s=config.agents.defaults.idle_settle_s,
            turn_timeout_s=config.agents.defaults.turn_timeout_s,
        )

    async def stream_callback(msg: "InboundMessage", chunk: str, final: bool) -> None:
        await gui_channel.emit_stream_chunk(session_id=msg.chat_id, chunk=chunk, final=final)

    async def terminal_callback(msg: "InboundMessage", chunk: str, final: bool) -> None:
        await gui_channel.emit_terminal_chunk(session_id=msg.chat_id, chunk=chunk, final=final)

    async def tool_callback(msg: "InboundMessage", chunk: str, final: bool) -> None:
        await gui_channel.emit_tool_chunk(session_id=msg.chat_id, chunk=chunk, final=final)

    agent_loop = AgentLoop(
        bus=bus,
        workspace=workspace,
        default_agent=selected_agent,
        cli_provider=cli_provider,
        stream_callback=stream_callback,
        terminal_callback=terminal_callback,
        tool_callback=tool_callback,
    )

    bus.subscribe_outbound("gui", gui_channel.send)

    console.print("Starting Agent Commander GUI")
    console.print(f"Workspace: [cyan]{workspace}[/cyan]")
    console.print(f"Default agent: [cyan]{selected_agent}[/cyan]")
    transport = "proxy_api" if config.proxy_api.enabled else "pty"
    console.print(f"Transport: [cyan]{transport}[/cyan]")

    async def run_stack() -> None:
        # Reconcile: remove cron jobs for sessions that no longer exist.
        schedule_channels = {
            s.session_id for s in session_store.list_sessions()
            if s.mode == "schedule"
        }
        purged = cron_service.purge_orphan_jobs(schedule_channels)
        if purged:
            logger.info(f"Startup: purged {purged} orphan cron job(s)")

        await cron_service.start()
        dispatch_task = asyncio.create_task(bus.dispatch_outbound())
        loop_task = asyncio.create_task(agent_loop.run())
        gui_task = asyncio.create_task(gui_channel.start())
        try:
            await gui_task
        finally:
            await gui_channel.stop()
            cron_service.stop()
            agent_loop.stop()
            bus.stop()
            for task in (dispatch_task, loop_task):
                task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.gather(dispatch_task, loop_task, return_exceptions=True),
                    timeout=3.0,
                )
            except asyncio.TimeoutError:
                pass
            if server_manager is not None:
                server_manager.stop(force=server_manager.is_managed())

    try:
        asyncio.run(run_stack())
    except KeyboardInterrupt:
        if server_manager is not None:
            server_manager.stop(force=server_manager.is_managed())
    finally:
        # Force-exit so no daemon threads or asyncio internals keep python.exe alive.
        os._exit(0)


@app.command()
def agent() -> None:
    """Deprecated legacy command."""
    console.print("[yellow]`agent-commander agent` is deprecated in agent-commander-gui.[/yellow]")
    console.print("Use [cyan]agent-commander gui[/cyan].")
    raise typer.Exit(1)


@app.command()
def gateway() -> None:
    """Deprecated legacy command."""
    console.print("[yellow]`agent-commander gateway` is deprecated in agent-commander-gui.[/yellow]")
    console.print("Use [cyan]agent-commander gui[/cyan].")
    raise typer.Exit(1)


@app.command()
def status() -> None:
    """Show agent-commander-gui status."""
    from agent_commander.config.loader import get_config_path, load_config
    from agent_commander.providers.agent_registry import AGENT_DEFS

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print("agent-commander-gui Status\n")
    console.print(f"Config: {config_path} {'[green]OK[/green]' if config_path.exists() else '[red]NO[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]OK[/green]' if workspace.exists() else '[red]NO[/red]'}")
    console.print(f"Default agent: [cyan]{config.agents.defaults.active}[/cyan]")
    console.print(
        f"GUI: {config.gui.width}x{config.gui.height}, font {config.gui.font_size}, theme {config.gui.theme}"
    )
    transport = "proxy_api" if config.proxy_api.enabled else "pty"
    console.print(f"Transport: [cyan]{transport}[/cyan]")
    if config.proxy_api.enabled:
        console.print(f"Proxy API: [cyan]{config.proxy_api.base_url}{config.proxy_api.endpoint}[/cyan]")
        server_manager = _build_proxy_server_manager(config)
        if server_manager is not None:
            state = server_manager.runtime_state()
            mode = "managed" if state["managed"] else "attached" if state["running"] else "stopped"
            console.print(f"Proxy Server: [cyan]{mode}[/cyan]")
            if state["binary_path"]:
                console.print(f"Proxy Binary: [dim]{state['binary_path']}[/dim]")
            else:
                console.print("[yellow]Proxy Binary: not found (set proxyApi.binaryPath)[/yellow]")
            if state["config_path"]:
                console.print(f"Proxy Config: [dim]{state['config_path']}[/dim]")
            provider_status = server_manager.get_provider_status()
            console.print(
                "Proxy Providers: "
                f"claude={'yes' if provider_status.get('claude') else 'no'}, "
                f"gemini={'yes' if provider_status.get('gemini') else 'no'}, "
                f"codex={'yes' if provider_status.get('codex') else 'no'}"
            )

    console.print("\nCLI agents:")
    for key, agent_def in AGENT_DEFS.items():
        agent_cfg = config.get_agent_config(key)
        command = agent_def.resolve_command()
        workdir = _resolve_workdir(agent_cfg.working_dir if agent_cfg else "", workspace)
        enabled = bool(agent_cfg.enabled) if agent_cfg else False
        state = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        console.print(f"  - {key}: {state} | cmd={command} | cwd={workdir}")


@app.command()
def heartbeat(
    agent: str = typer.Option("", "--agent", help="Agent for heartbeat turn (claude|gemini|codex)"),
) -> None:
    """Trigger one heartbeat check (optional scheduled-task flow)."""
    from agent_commander.agent.loop import AgentLoop
    from agent_commander.bus.queue import MessageBus
    from agent_commander.config.loader import load_config
    from agent_commander.heartbeat.service import HEARTBEAT_OK_TOKEN, HEARTBEAT_PROMPT, HeartbeatService
    from agent_commander.providers.agent_registry import AGENT_DEFS
    from agent_commander.providers.base import CLIAgentProvider
    from agent_commander.providers.proxy_api import ProxyAPIProvider

    config = load_config()
    if _run_setup_wizard(config, interactive=False):
        from agent_commander.config.loader import save_config

        save_config(config)

    workspace = config.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)

    selected_agent = (agent or config.agents.defaults.active or "codex").strip().lower()
    if selected_agent not in AGENT_DEFS:
        choices = ", ".join(sorted(AGENT_DEFS))
        console.print(f"[red]Unknown agent '{selected_agent}'. Expected: {choices}[/red]")
        raise typer.Exit(1)

    agent_workdirs = _apply_agent_overrides(config, workspace)
    selected_cwd = agent_workdirs.get(selected_agent, str(workspace))

    server_manager = None
    if config.proxy_api.enabled:
        server_manager = _build_proxy_server_manager(config)
        if server_manager is not None and config.proxy_api.auto_start:
            server_manager.start(
                timeout_s=8.0,
                take_over_existing=config.proxy_api.take_over_existing,
            )
        provider = ProxyAPIProvider(
            base_url=config.proxy_api.base_url,
            api_key=config.proxy_api.api_key,
            endpoint=config.proxy_api.endpoint,
            request_timeout_s=config.proxy_api.request_timeout_s,
            model_claude=config.proxy_api.model_claude,
            model_gemini=config.proxy_api.model_gemini,
            model_codex=config.proxy_api.model_codex,
        )
    else:
        provider = CLIAgentProvider(
            poll_interval_s=config.agents.defaults.poll_interval_s,
            idle_settle_s=config.agents.defaults.idle_settle_s,
            turn_timeout_s=config.agents.defaults.turn_timeout_s,
        )

    agent_loop = AgentLoop(
        bus=MessageBus(),
        workspace=workspace,
        default_agent=selected_agent,
        cli_provider=provider,
    )

    async def on_heartbeat(prompt: str) -> str:
        return await agent_loop.process_direct(
            content=prompt,
            session_key="system:heartbeat",
            channel="system",
            chat_id="gui:heartbeat",
            agent=selected_agent,
            cwd=selected_cwd,
        )

    async def run_once() -> str | None:
        service = HeartbeatService(workspace=workspace, on_heartbeat=on_heartbeat, enabled=True)
        try:
            return await service.trigger_now()
        finally:
            agent_loop.stop()
            if server_manager is not None:
                server_manager.stop(force=server_manager.is_managed())

    console.print(f"Heartbeat -> agent [cyan]{selected_agent}[/cyan]")
    result = asyncio.run(run_once())
    content = (result or "").strip()
    console.print(content if content else HEARTBEAT_OK_TOKEN)


if __name__ == "__main__":
    app()
