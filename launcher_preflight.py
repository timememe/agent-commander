import json
import os
import shlex
import shutil
from datetime import datetime, timezone

COMMON_CACHE_DIRNAME = "main_cache"
SETUP_STATE_FILENAME = "agent_setup.json"
LAUNCHER_CHECK_FILENAME = "launcher_agent_check.json"

SETUP_AGENT_DEFS = [
    ("claude", "TRIPTYCH_CLAUDE_CMD", "claude"),
    ("gemini", "TRIPTYCH_GEMINI_CMD", "gemini"),
    ("codex", "TRIPTYCH_CODEX_CMD", "codex"),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_read_json(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def safe_write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def resolve_command(env_var: str, default_cmd: str) -> str:
    value = os.getenv(env_var, default_cmd)
    return value.strip() if isinstance(value, str) else default_cmd


def command_exists(command: str) -> bool:
    try:
        token = shlex.split(command)[0] if command else ""
    except Exception:
        token = command.strip().split(" ")[0] if command else ""
    return bool(token and shutil.which(token))


def main() -> int:
    project_root = os.path.dirname(os.path.abspath(__file__))
    cache_dir = os.path.join(project_root, COMMON_CACHE_DIRNAME)
    os.makedirs(cache_dir, exist_ok=True)

    setup_path = os.path.join(cache_dir, SETUP_STATE_FILENAME)
    launcher_check_path = os.path.join(cache_dir, LAUNCHER_CHECK_FILENAME)

    detected_agents: dict[str, bool] = {}
    resolved_commands: dict[str, str] = {}
    for agent_id, env_var, default_cmd in SETUP_AGENT_DEFS:
        cmd = resolve_command(env_var, default_cmd)
        resolved_commands[agent_id] = cmd
        detected_agents[agent_id] = command_exists(cmd)

    safe_write_json(
        launcher_check_path,
        {
            "version": 1,
            "checked_at": utc_now_iso(),
            "detected_agents": detected_agents,
            "resolved_commands": resolved_commands,
        },
    )

    all_detected = all(detected_agents.values())
    if not all_detected:
        return 0

    setup_state = safe_read_json(setup_path)
    if setup_state.get("setup_complete"):
        return 0

    selected_agents = [agent_id for agent_id, _, _ in SETUP_AGENT_DEFS]
    safe_write_json(
        setup_path,
        {
            "version": 1,
            "setup_complete": True,
            "selected_agents": selected_agents,
            "detected_agents": detected_agents,
            "auto_completed": True,
            "updated_at": utc_now_iso(),
            "source": "launcher_preflight",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

