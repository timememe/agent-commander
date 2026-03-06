#!/usr/bin/env bash
# Nuitka build script for Agent Commander (Qt GUI) — macOS
# Run from project root: bash build/build_macos.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENTRY_POINT="$PROJECT_ROOT/agent_commander/gui/launcher.py"
OUTPUT_DIR="$PROJECT_ROOT/dist_nuitka"

cd "$PROJECT_ROOT"

python -m nuitka \
    --standalone \
    --macos-create-app-bundle \
    --macos-app-name="AgentCommander" \
    --output-dir="$OUTPUT_DIR" \
    --output-filename="AgentCommander" \
    --enable-plugin=pyside6 \
    --include-package=agent_commander \
    --include-package=pyte \
    --include-package=loguru \
    --include-package=croniter \
    --include-package=rich \
    --include-package=prompt_toolkit \
    --include-package=pydantic \
    --include-package=pydantic_settings \
    --include-package=typer \
    --include-package=click \
    --include-package=docx \
    --include-package=openpyxl \
    --include-package=plyer \
    --include-package=pexpect \
    --noinclude-default-mode=nofollow \
    --nofollow-import-to=contourpy \
    --nofollow-import-to=matplotlib \
    --nofollow-import-to=numpy \
    --nofollow-import-to=PIL \
    --nofollow-import-to=lxml \
    --nofollow-import-to=pandas \
    --nofollow-import-to=customtkinter \
    --nofollow-import-to=tkinterdnd2 \
    --nofollow-import-to=winpty \
    --assume-yes-for-downloads \
    "$ENTRY_POINT"
