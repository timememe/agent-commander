# Agent Commander

**Desktop AI agent workspace — Claude, Gemini, and Codex in one GUI.**

Agent Commander is a desktop application that wraps CLI-based AI agents (Claude Code, Gemini CLI, OpenAI Codex) in a rich interface with multi-session management, scheduled automation, skill injection, and extension support.

![Agent Commander](agent_commander_logo.png)

---

## Features

### Multi-Agent, Multi-Session
- Run **Claude**, **Gemini**, and **Codex** simultaneously in separate sessions
- Switch agents per session without restarting
- Two transport modes: **PTY** (direct CLI subprocess) and **ProxyAPI** (OpenAI-compatible HTTP streaming)

### Session Modes
| Mode | Description |
|------|-------------|
| 💬 **Chat** | Standard interactive conversation |
| ↺ **Loop** | Agent auto-continues until it outputs `[TASK_COMPLETE]` |
| ◷ **Schedule** | Agent runs automatically on a cron schedule |

### Skill Library
Create reusable context blocks that are injected into agent sessions before the first message. Perfect for personas, coding standards, domain knowledge, or any system-level instructions.

### Schedule Agent
Configure agents to run on any schedule — every 15 minutes, daily at a specific time, weekly on selected days, or a custom interval. Stop, restart, and edit schedules inline without creating a new session.

### Extensions
Connect external services to give agents real capabilities:
- **Yandex Mail / Gmail** — agents can list, read, and send emails via IMAP/SMTP tool calling

### Projects
Group sessions under projects with a shared architecture document. Agents can reference the project context to maintain consistency across conversations.

### File Tray & Drag-and-Drop
A built-in file browser on the right side lets you drag files directly into the chat input.

---

## Installation

### Windows (recommended)

1. Download the latest release from [Releases](https://github.com/timememe/agent-commander/releases)
2. Extract and run `AgentCommander.exe`

Or run the setup script:
```bat
bootstrap_windows.bat
```

### From source

**Requirements:** Python 3.11+, one or more CLI agents installed (`claude`, `gemini`, `codex`)

```bash
git clone https://github.com/timememe/agent-commander.git
cd agent-commander
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -e .
agent-commander gui
```

---

## Configuration

Config file is created automatically at `~/.agent-commander/config.json` on first run.

To use **ProxyAPI mode** (recommended for Claude), point it at a running [CLIProxyAPI](https://github.com/timememe/CLIProxyAPI) instance:

```json
{
  "proxy_api": {
    "enabled": true,
    "base_url": "http://localhost:8080",
    "model_claude": "claude-opus-4-6"
  }
}
```

The included `cliproxyapi/cli-proxy-api.exe` can be started from the Settings panel inside the app.

---

## Project Structure

```
agent_commander/
├── cli/            # Entry point (typer commands)
├── gui/            # All UI components (customtkinter)
│   ├── app.py      # Main TriptychApp window
│   ├── chat_panel.py
│   ├── sidebar.py
│   ├── input_bar.py
│   ├── settings_dialog.py
│   ├── team_dialog.py   # Skill Library panel
│   └── ...
├── agent/          # AgentLoop — message dispatch and loop logic
├── providers/      # PTY backend, ProxyAPI client, tool definitions
├── session/        # Persistent stores (sessions, skills, projects, extensions)
├── cron/           # CronService — schedule execution
└── bus/            # Internal message bus
```

---

## Building

Requires [Inno Setup](https://jrsoftware.org/isdl.php) for the installer (optional).

```bat
build\build.bat
```

Output: `dist\AgentCommander\AgentCommander.exe`

---

## License

MIT — see [LICENSE](LICENSE)
