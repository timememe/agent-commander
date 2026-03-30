# Agent Commander

**Desktop AI agent workspace — Claude, Gemini, and Codex in one GUI.**

Agent Commander is a desktop application that wraps CLI-based AI agents (Claude Code, Gemini CLI, OpenAI Codex) in a rich PySide6 interface with multi-session management, scheduled automation, skill injection, project workspaces, and external service integrations.

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
| ⇄ **Cycle** | Round-robin across a team of agents |

### Skill Library
Create reusable context blocks injected into agent sessions before the first message. Perfect for personas, coding standards, domain knowledge, or system-level instructions.

### Schedule Agent
Configure agents to run on any schedule — every 15 minutes, daily at a specific time, weekly on selected days, or a custom cron expression. Stop, restart, and edit schedules inline.

### Projects
Group sessions under projects with a shared architecture document. Agents reference the project context to maintain consistency across conversations. The agent store (store_set / store_get / store_list) provides per-project persistent key-value memory.

### Extensions
Connect external services to give agents real capabilities via built-in tools:

| Extension | Tools |
|-----------|-------|
| **Google Drive** | `gdrive_list_files`, `gdrive_get_file_info`, `gdrive_create_folder`, `gdrive_delete_file` |
| **Google Docs** | `gdocs_create`, `gdocs_get`, `gdocs_append` |
| **Google Sheets** | `gsheets_create`, `gsheets_read`, `gsheets_write`, `gsheets_append` |
| **Google Calendar** | `gcal_list_events`, `gcal_create_event` |
| **Gmail** | `gmail_list`, `gmail_read`, `gmail_send` |
| **Yandex Mail** | IMAP/SMTP via app password |
| **Worksection** | `ws_get_projects`, `ws_get_tasks`, `ws_create_task`, `ws_add_comment`, and more |

Google Workspace auth uses your own OAuth2 Desktop App client (`client_secrets.json`) from GCP Console — no gcloud or gws required.

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

For Google Workspace tools, also install:
```bash
pip install google-auth-oauthlib google-api-python-client
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
├── gui_qt/         # All UI components (PySide6)
│   ├── app.py      # Main window
│   ├── chat_panel.py
│   ├── sidebar.py
│   ├── input_bar.py
│   ├── settings_dialog.py
│   ├── extensions_panel.py  # Extension connect dialogs
│   └── ...
├── agent/          # AgentLoop — message dispatch and loop logic
├── providers/      # PTY backend, ProxyAPI client, tool definitions
│   └── tools/      # Tool definitions + Google Workspace / Worksection executors
├── session/        # Persistent stores (sessions, skills, projects, extensions)
├── cron/           # CronService — schedule execution
└── bus/            # Internal message bus
```

---

## Building

```bat
build\build.bat
```

Output: `dist\AgentCommander\AgentCommander.exe`

Requires Python 3.11+ in PATH. PyInstaller is installed automatically by the build script.

---

## License

MIT — see [LICENSE](LICENSE)
