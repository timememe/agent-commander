@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo ============================================
echo   Agent Commander GUI - Build Installer
echo ============================================
echo.

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "PROJECT_FILE=pyproject.toml"

:: -----------------------------------------------
:: Step 1: Find Python
:: -----------------------------------------------
set "PY_BOOTSTRAP="
where py >nul 2>&1 && set "PY_BOOTSTRAP=py -3"
if not defined PY_BOOTSTRAP (
    where python >nul 2>&1 && set "PY_BOOTSTRAP=python"
)
if not defined PY_BOOTSTRAP (
    echo [ERROR] Python 3.11+ not found.
    echo Install Python from https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

echo [OK] Python found: %PY_BOOTSTRAP%

:: -----------------------------------------------
:: Step 2: Create venv if missing
:: -----------------------------------------------
if not exist "%VENV_PY%" (
    echo [SETUP] Creating virtual environment...
    %PY_BOOTSTRAP% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created
)

if not exist "%VENV_PY%" (
    echo [ERROR] venv python not found: %VENV_PY%
    pause
    exit /b 1
)

:: -----------------------------------------------
:: Step 3: Install/upgrade project dependencies
:: -----------------------------------------------
"%VENV_PY%" -c "import customtkinter" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing project dependencies...
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
    "%VENV_PY%" -m pip install -e . 2>&1
    if errorlevel 1 (
        echo [WARN] Editable install failed, installing deps directly...
        "%VENV_PY%" -m pip install ^
            "typer>=0.9.0" ^
            "pydantic>=2.0.0" ^
            "pydantic-settings>=2.0.0" ^
            "loguru>=0.7.0" ^
            "rich>=13.0.0" ^
            "croniter>=2.0.0" ^
            "prompt-toolkit>=3.0.0" ^
            "customtkinter>=5.2.0" ^
            "pyte>=0.8.2" ^
            "plyer>=2.1.0" ^
            "win10toast>=0.9" ^
            "pywinpty>=2.0.13"
        if errorlevel 1 (
            echo [ERROR] Failed to install dependencies.
            pause
            exit /b 1
        )
        "%VENV_PY%" -m pip install -e . --no-deps 2>&1
    )
    echo [OK] Dependencies installed
) else (
    echo [OK] Dependencies already installed
)

:: -----------------------------------------------
:: Step 4: Install PyInstaller if missing
:: -----------------------------------------------
"%VENV_PY%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller...
    "%VENV_PY%" -m pip install pyinstaller 2>&1
    if errorlevel 1 (
        echo [ERROR] Failed to install PyInstaller.
        pause
        exit /b 1
    )
    echo [OK] PyInstaller installed
) else (
    echo [OK] PyInstaller already installed
)

:: -----------------------------------------------
:: Step 5: Run build
:: -----------------------------------------------
echo.
echo [BUILD] Starting build...
echo.
"%VENV_PY%" build\build_installer.py %*
set "BUILD_EXIT=%errorlevel%"

if not "%BUILD_EXIT%"=="0" (
    echo.
    echo [ERROR] Build failed with code %BUILD_EXIT%.
    pause
    exit /b %BUILD_EXIT%
)

echo.
echo ============================================
echo   Build complete!
echo ============================================
echo.
echo Output: dist\AgentCommander\AgentCommander.exe
echo.
pause
