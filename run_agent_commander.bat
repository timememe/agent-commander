@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "STAMP_FILE=%VENV_DIR%\.deps_installed"
set "STAMP_LOCK_FILE=%VENV_DIR%\.pyproject.lock"
set "PROJECT_FILE=pyproject.toml"
set "SETUP_ONLY=0"
set "USE_CONSOLE=0"
set "FORWARD_ARGS="

:parse_args
if "%~1"=="" goto args_done
if /I "%~1"=="--setup-only" (
    set "SETUP_ONLY=1"
    shift
    goto parse_args
)
if /I "%~1"=="--console" (
    set "USE_CONSOLE=1"
    shift
    goto parse_args
)
set "FORWARD_ARGS=%FORWARD_ARGS% %~1"
shift
goto parse_args

:args_done

if not exist "agent_commander\__main__.py" (
    echo [ERROR] agent_commander project files not found in:
    echo %CD%
    pause
    exit /b 1
)

set "PY_BOOTSTRAP="
where py >nul 2>&1 && set "PY_BOOTSTRAP=py -3"
if not defined PY_BOOTSTRAP (
    where python >nul 2>&1 && set "PY_BOOTSTRAP=python"
)
if not defined PY_BOOTSTRAP (
    echo [ERROR] Python 3.10+ was not found.
    echo Install Python and re-run this launcher.
    echo https://www.python.org/downloads/windows/
    pause
    exit /b 1
)

if not exist "%VENV_PY%" (
    echo [SETUP] Creating local virtual environment in %VENV_DIR% ...
    %PY_BOOTSTRAP% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

if not exist "%VENV_PY%" (
    echo [ERROR] Virtual environment python not found: %VENV_PY%
    pause
    exit /b 1
)

set "NEED_INSTALL=0"
if not exist "%STAMP_FILE%" set "NEED_INSTALL=1"
if exist "%PROJECT_FILE%" (
    if not exist "%STAMP_LOCK_FILE%" (
        set "NEED_INSTALL=1"
    ) else (
        fc /b "%PROJECT_FILE%" "%STAMP_LOCK_FILE%" >nul 2>&1
        if errorlevel 1 set "NEED_INSTALL=1"
    )
)

if "%NEED_INSTALL%"=="0" (
    "%VENV_PY%" -c "import importlib.util; mods=('typer','pydantic','customtkinter','pyte','winpty','plyer'); raise SystemExit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" (
    echo [SETUP] Installing Python dependencies...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] Failed to upgrade pip.
        pause
        exit /b 1
    )

    "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
    if errorlevel 1 (
        echo [WARN] Python is below 3.11. Installing runtime dependencies without editable package.
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
            "tkinterdnd2>=0.4.3" ^
            "plyer>=2.1.0" ^
            "win10toast>=0.9" ^
            "pywinpty>=2.0.13"
        if errorlevel 1 (
            echo [ERROR] Failed to install runtime dependencies.
            pause
            exit /b 1
        )
    ) else (
        "%VENV_PY%" -m pip install -e .
        if errorlevel 1 (
            echo [ERROR] Failed to install project dependencies.
            pause
            exit /b 1
        )
    )

    >"%STAMP_FILE%" echo %DATE% %TIME%
    if exist "%PROJECT_FILE%" copy /Y "%PROJECT_FILE%" "%STAMP_LOCK_FILE%" >nul
)

if "%SETUP_ONLY%"=="1" (
    echo [OK] Setup completed.
    exit /b 0
)

set "CONFIG_FILE=%USERPROFILE%\.agent_commander\config.json"
if not exist "%CONFIG_FILE%" (
    echo [SETUP] No config found, running initial onboarding...
    "%VENV_PY%" -m agent-commander onboard
    if errorlevel 1 (
        echo [ERROR] Onboarding failed.
        pause
        exit /b 1
    )
)

if "%USE_CONSOLE%"=="1" (
    "%VENV_PY%" -m agent-commander gui %FORWARD_ARGS%
    exit /b %errorlevel%
)

if exist "%VENV_PYW%" (
    "%VENV_PYW%" -m agent-commander gui %FORWARD_ARGS%
    exit /b %errorlevel%
)

"%VENV_PY%" -m agent-commander gui %FORWARD_ARGS%
exit /b %errorlevel%
