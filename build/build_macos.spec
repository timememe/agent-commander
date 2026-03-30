# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Agent Commander GUI — macOS .app bundle.

Run from project root:
    pyinstaller build/build_macos.spec

Requirements:
    pip install pyinstaller
    # Place macOS cli-proxy-api binary at:
    #   cliproxyapi/cli-proxy-api   (built on Mac from CLIProxyAPI source)
    # Optionally place icon at:
    #   logo_w.icns                 (convert from logo_w.ico: sips / iconutil)
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(SPECPATH).parent.resolve()

# ---------------------------------------------------------------------------
# PySide6 — only the three modules we actually use (saves ~400MB vs full)
# ---------------------------------------------------------------------------
pyside6_datas, pyside6_binaries, pyside6_hiddenimports = [], [], []
for _mod in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets"):
    _d, _b, _h = collect_all(_mod)
    pyside6_datas += _d
    pyside6_binaries += _b
    pyside6_hiddenimports += _h

# ---------------------------------------------------------------------------
# Skill markdown/shell files
# ---------------------------------------------------------------------------
skills_datas = []
skills_root = PROJECT_ROOT / "agent_commander" / "skills"
if skills_root.exists():
    for path in skills_root.rglob("*"):
        if path.is_file():
            dest = str(path.relative_to(PROJECT_ROOT).parent)
            skills_datas.append((str(path), dest))

# ---------------------------------------------------------------------------
# Workspace templates
# ---------------------------------------------------------------------------
workspace_datas = []
workspace_root = PROJECT_ROOT / "workspace"
if workspace_root.exists():
    for path in workspace_root.rglob("*"):
        if path.is_file():
            dest = str(path.relative_to(PROJECT_ROOT).parent)
            workspace_datas.append((str(path), dest))

# ---------------------------------------------------------------------------
# Logo (data — shown in About etc.)
# ---------------------------------------------------------------------------
logo_datas = []
for logo_name in ("logo_w.icns", "logo_w.ico", "logo_w.png"):
    logo = PROJECT_ROOT / logo_name
    if logo.exists():
        logo_datas.append((str(logo), "."))

# ---------------------------------------------------------------------------
# Icon for the .app bundle
# ---------------------------------------------------------------------------
icon_path = None
for icon_name in ("logo_w.icns", "logo_w.ico"):
    candidate = PROJECT_ROOT / icon_name
    if candidate.exists():
        icon_path = str(candidate)
        break

# ---------------------------------------------------------------------------
# CLIProxyAPI binary (macOS, built separately on Mac)
# Must be placed at:  {project_root}/cliproxyapi/cli-proxy-api
# ---------------------------------------------------------------------------
cliproxy_binaries = []
proxy_bin = PROJECT_ROOT / "cliproxyapi" / "cli-proxy-api"
proxy_cfg = PROJECT_ROOT / "cliproxyapi" / "config.yaml"
if proxy_bin.exists():
    # Add as binary so PyInstaller preserves execute bit
    cliproxy_binaries.append((str(proxy_bin), "cliproxyapi"))
if proxy_cfg.exists():
    cliproxy_datas = [(str(proxy_cfg), "cliproxyapi")]
else:
    cliproxy_datas = []

# ---------------------------------------------------------------------------
# Hidden imports
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
    "plyer.platforms.macosx",
    "plyer.platforms.macosx.notification",
    "pexpect",
    "pexpect.popen_spawn",
    "pydantic",
    "pydantic_settings",
    "typer",
    "click",
    "docx",
    "openpyxl",
    "agent_commander",
    "agent_commander.cli.commands",
    "agent_commander.gui.launcher",
    # Qt GUI
    "agent_commander.gui_qt",
    "agent_commander.gui_qt.app",
    "agent_commander.gui_qt.channel",
    "agent_commander.gui_qt.chat_panel",
    "agent_commander.gui_qt.input_bar",
    "agent_commander.gui_qt.session_list",
    "agent_commander.gui_qt.file_tray",
    "agent_commander.gui_qt.settings_panel",
    "agent_commander.gui_qt.extensions_panel",
    "agent_commander.gui_qt.new_session_dialog",
    "agent_commander.gui_qt.projects_panel",
    "agent_commander.gui_qt.team_panel",
    "agent_commander.gui_qt.cycle_bar",
    "agent_commander.gui_qt.theme",
    # Agent core
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
    "agent_commander.providers.provider",
    "agent_commander.providers.transport.proxy_session",
    "agent_commander.providers.transport.proxy_server",
    "agent_commander.providers.tools",
    "agent_commander.providers.runtime.registry",
    "agent_commander.providers.runtime.session",
    "agent_commander.session.manager",
    "agent_commander.session.gui_store",
    "agent_commander.session.skill_store",
    "agent_commander.session.extension_store",
    "agent_commander.session.project_store",
    "agent_commander.utils.helpers",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(PROJECT_ROOT / "agent_commander" / "gui" / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=pyside6_binaries + cliproxy_binaries,
    datas=pyside6_datas + skills_datas + workspace_datas + logo_datas + cliproxy_datas,
    hiddenimports=hidden_imports + pyside6_hiddenimports,
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
        "customtkinter",
        "tkinterdnd2",
        "win10toast",
        "winpty",
        # Unused PySide6 submodules
        "PySide6.QtSvg",
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQml",
        "PySide6.QtLocation",
        "PySide6.QtPositioning",
        "PySide6.QtSensors",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtWebSockets",
        "PySide6.QtWebChannel",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtStateMachine",
        "PySide6.QtTextToSpeech",
    ],
    noarchive=False,
)

# ---------------------------------------------------------------------------
# PYZ
# ---------------------------------------------------------------------------
pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE — no console window, argv_emulation for macOS dock drag-drop
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AgentCommander",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,         # strip debug symbols → smaller binary on Mac
    upx=False,          # UPX breaks code signing on macOS — keep OFF
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,   # handle Apple events (file open, dock drop)
    target_arch=None,      # None = current arch; use "universal2" for fat binary
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

# ---------------------------------------------------------------------------
# COLLECT — directory bundle (used by BUNDLE below)
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,          # UPX + macOS code signing = broken → keep OFF
    upx_exclude=[],
    name="AgentCommander",
)

# ---------------------------------------------------------------------------
# BUNDLE — creates AgentCommander.app
# ---------------------------------------------------------------------------
app = BUNDLE(
    coll,
    name="AgentCommander.app",
    icon=icon_path,
    bundle_identifier="com.agentcommander.app",
    version="1.0.0",
    info_plist={
        # Allow high-resolution Retina rendering
        "NSHighResolutionCapable": True,
        # Required for webbrowser.open() to work in sandboxed contexts
        "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
        # Allow access to user Downloads/Documents for workspace
        "NSDocumentsFolderUsageDescription": "Agent Commander uses this folder as workspace.",
        "NSDownloadsFolderUsageDescription": "Agent Commander may save files here.",
        # Minimum macOS version
        "LSMinimumSystemVersion": "12.0",
        # App display name in menu bar / About
        "CFBundleDisplayName": "Agent Commander",
        "CFBundleShortVersionString": "1.0.0",
    },
)
