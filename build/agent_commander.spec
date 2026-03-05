# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Agent Commander GUI (Qt backend)."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# Project root (one level up from build/)
PROJECT_ROOT = Path(SPECPATH).parent.resolve()

# ---------------------------------------------------------------------------
# Collect only the PySide6 modules we actually use
# (QtCore, QtGui, QtWidgets — skip WebEngine, Multimedia, 3D, etc.)
# ---------------------------------------------------------------------------
pyside6_datas, pyside6_binaries, pyside6_hiddenimports = [], [], []
for _mod in ("PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets", "PySide6.QtSvg"):
    _d, _b, _h = collect_all(_mod)
    pyside6_datas += _d
    pyside6_binaries += _b
    pyside6_hiddenimports += _h

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
    binaries=pyside6_binaries,
    datas=pyside6_datas + skills_datas + workspace_datas + logo_datas,
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
        # Unused PySide6 submodules (saves ~500MB)
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
