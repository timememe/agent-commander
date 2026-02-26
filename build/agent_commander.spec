# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Agent Commander GUI."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# Project root (one level up from build/)
PROJECT_ROOT = Path(SPECPATH).parent.resolve()

# ---------------------------------------------------------------------------
# Collect customtkinter assets (themes, json, images)
# ---------------------------------------------------------------------------
ctk_datas, ctk_binaries, ctk_hiddenimports = collect_all("customtkinter")

# ---------------------------------------------------------------------------
# Collect tkinterdnd2 (native libtkdnd DLL + Python wrapper)
# ---------------------------------------------------------------------------
tkdnd_datas, tkdnd_binaries, tkdnd_hiddenimports = collect_all("tkinterdnd2")

# ---------------------------------------------------------------------------
# Skill markdown/shell files (agent_commander/skills/**/*)
# ---------------------------------------------------------------------------
skills_datas = []
skills_root = PROJECT_ROOT / "agent_commander" / "skills"
if skills_root.exists():
    for path in skills_root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(PROJECT_ROOT)
            dest = str(rel.parent)
            skills_datas.append((str(path), dest))

# ---------------------------------------------------------------------------
# Workspace templates (workspace/**/*)
# ---------------------------------------------------------------------------
workspace_datas = []
workspace_root = PROJECT_ROOT / "workspace"
if workspace_root.exists():
    for path in workspace_root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(PROJECT_ROOT)
            dest = str(rel.parent)
            workspace_datas.append((str(path), dest))

# ---------------------------------------------------------------------------
# Application icon
# ---------------------------------------------------------------------------
icon_path = PROJECT_ROOT / "logo_w.ico"
if not icon_path.exists():
    icon_path = None
else:
    icon_path = str(icon_path)

# Bundle logo_w.ico at the dist root so the GUI can call iconbitmap() at runtime
logo_ico = PROJECT_ROOT / "logo_w.ico"
logo_datas = [(str(logo_ico), ".")] if logo_ico.exists() else []

# ---------------------------------------------------------------------------
# Hidden imports that PyInstaller may not detect
# ---------------------------------------------------------------------------
hidden_imports = [
    "pyte",
    "pyte.screens",
    "pyte.streams",
    "loguru",
    "croniter",
    "rich",
    "rich.console",
    "prompt_toolkit",
    "plyer",
    "plyer.platforms",
    "plyer.platforms.win",
    "plyer.platforms.win.notification",
    "pydantic",
    "pydantic_settings",
    "typer",
    "click",
    "agent_commander",
    "agent_commander.cli.commands",
    "agent_commander.gui",
    "agent_commander.gui.app",
    "agent_commander.gui.launcher",
    "agent_commander.gui.channel",
    "agent_commander.gui.chat_panel",
    "agent_commander.gui.input_bar",
    "agent_commander.gui.sidebar",
    "agent_commander.gui.session_list",
    "agent_commander.gui.agent_selector",
    "agent_commander.gui.terminal_panel",
    "agent_commander.gui.file_tray",
    "agent_commander.gui.settings_dialog",
    "agent_commander.gui.skill_bar",
    "agent_commander.gui.team_dialog",
    "agent_commander.gui.notifications",
    "agent_commander.gui.events",
    "agent_commander.gui.state_store",
    "agent_commander.gui.theme",
    "agent_commander.gui.widgets",
    "agent_commander.gui.widgets.chat_bubble",
    "agent_commander.gui.widgets.markdown_view",
    "agent_commander.gui.widgets.status_bar",
    "agent_commander.agent.loop",
    "agent_commander.agent.context",
    "agent_commander.agent.memory",
    "agent_commander.agent.skills",
    "agent_commander.bus.queue",
    "agent_commander.bus.events",
    "agent_commander.config.loader",
    "agent_commander.config.schema",
    "agent_commander.cron.service",
    "agent_commander.cron.types",
    "agent_commander.heartbeat.service",
    "agent_commander.providers.base",
    "agent_commander.providers.proxy_api",
    "agent_commander.providers.proxy_server",
    "agent_commander.providers.tools",
    "agent_commander.providers.agent_registry",
    "agent_commander.providers.agent_session",
    "agent_commander.providers.pty_backend",
    "agent_commander.providers.signal_filter",
    "agent_commander.providers.marker_parser",
    "agent_commander.providers.capabilities",
    "agent_commander.session.manager",
    "agent_commander.session.gui_store",
    "agent_commander.session.skill_store",
    "agent_commander.utils.helpers",
]

# Win-specific hidden imports
if sys.platform == "win32":
    hidden_imports += [
        "win10toast",
        "winpty",
        "winpty._winpty",
    ]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT_ROOT / "agent_commander" / "gui" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=ctk_binaries + tkdnd_binaries,
    datas=ctk_datas + tkdnd_datas + skills_datas + workspace_datas + logo_datas,
    hiddenimports=hidden_imports + ctk_hiddenimports + tkdnd_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "cv2",
        "torch",
        "tensorflow",
        "jupyter",
        "notebook",
        "IPython",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ (compressed Python bytecode archive)
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentCommander",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app — no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

# ---------------------------------------------------------------------------
# COLLECT (directory mode — faster startup than onefile)
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AgentCommander",
)
