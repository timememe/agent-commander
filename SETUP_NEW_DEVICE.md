# New Device Setup (Windows)

This project includes a one-command bootstrap script for a clean machine.

## Fastest way (no Python/manual setup)

Double-click:

`Install_Agent_Commander.bat`

or run:

```bat
.\Install_Agent_Commander.bat
```

This installer will:
- install Python 3.11+ automatically via `winget` (if missing)
- download `CLIProxyAPI` automatically (if missing)
- create `.venv` and install project dependencies
- initialize `~/.agent-commander/config.json`
- start GUI

Installer flags:

```bat
.\Install_Agent_Commander.bat -SetupOnly
.\Install_Agent_Commander.bat -SkipLaunch
.\Install_Agent_Commander.bat -ForceOnboard
```

## 1. Open PowerShell in project root

```powershell
cd <path-to>\agent-commander-gui
```

## 2. Run bootstrap

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1
```

What it does:
- creates `.venv`
- installs Python dependencies (`pip install -e .`)
- runs `agent-commander onboard --non-interactive`
- detects and writes paths for `claude` / `gemini` / `codex` CLIs into `~/.agent-commander/config.json` (if found)
- detects `CLIProxyAPI` binary/config and writes them into `~/.agent-commander/config.json` (if found)
- runs `agent-commander status`

## Optional flags

```powershell
# include dev dependencies
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -InstallDev

# do setup only, do not launch anything
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -SetupOnly

# force re-create config during onboarding
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -ForceOnboard

# skip onboarding
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_windows.ps1 -SkipOnboard
```

## 3. Start app

```powershell
.\.venv\Scripts\python.exe -m agent-commander gui
```

## Requirements

- For the fastest path: `winget` available on Windows
- For manual bootstrap path: Python 3.11+
- Windows with Tk available (standard Python installer includes it)
- Optional but recommended:
  - `claude` CLI in `PATH`
  - `gemini` CLI in `PATH`
  - `codex` CLI in `PATH`
  - `CLIProxyAPI` binary + config
