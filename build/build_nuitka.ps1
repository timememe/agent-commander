# Nuitka build script for Agent Commander (Qt GUI)
# Run from project root: .\build\build_nuitka.ps1

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$EntryPoint = Join-Path $ProjectRoot "agent_commander\gui\launcher.py"
$OutputDir = Join-Path $ProjectRoot "dist_nuitka"
$IconPath = Join-Path $ProjectRoot "logo_w.ico"

Push-Location $ProjectRoot

python -m nuitka `
    --standalone `
    --windows-console-mode=disable `
    --output-dir="$OutputDir" `
    --output-filename="AgentCommander" `
    --enable-plugin=pyside6 `
    --include-package=agent_commander `
    --include-package=pyte `
    --include-package=loguru `
    --include-package=croniter `
    --include-package=rich `
    --include-package=prompt_toolkit `
    --include-package=pydantic `
    --include-package=pydantic_settings `
    --include-package=typer `
    --include-package=click `
    --include-package=python_docx `
    --include-package=openpyxl `
    --include-package=plyer `
    --noinclude-default-mode=nofollow `
    --windows-icon-from-ico="$IconPath" `
    --assume-yes-for-downloads `
    "$EntryPoint"

Pop-Location
