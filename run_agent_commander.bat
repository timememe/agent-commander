@echo off
setlocal

cd /d "%~dp0"
set "APP_FILE=app_gui.py"
set "PREFLIGHT_FILE=launcher_preflight.py"
set "REQ_FILE=requirements.txt"
set "VENV_DIR=.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "VENV_PYW=%VENV_DIR%\Scripts\pythonw.exe"
set "STAMP_FILE=%VENV_DIR%\.deps_installed"
set "STAMP_REQ_FILE=%VENV_DIR%\.requirements.lock"
set "SETUP_ONLY=0"

if /I "%~1"=="--setup-only" (
    set "SETUP_ONLY=1"
)

if not exist "%APP_FILE%" (
    echo [ERROR] %APP_FILE% not found in:
    echo %CD%
    pause
    exit /b 1
)

call :resolve_python_bootstrap
if errorlevel 1 (
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
if exist "%REQ_FILE%" (
    if not exist "%STAMP_REQ_FILE%" (
        set "NEED_INSTALL=1"
    ) else (
        fc /b "%REQ_FILE%" "%STAMP_REQ_FILE%" >nul 2>&1
        if errorlevel 1 set "NEED_INSTALL=1"
    )
)

if "%NEED_INSTALL%"=="1" (
    echo [SETUP] Installing Python dependencies...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] Failed to upgrade pip.
        pause
        exit /b 1
    )

    if exist "%REQ_FILE%" (
        "%VENV_PY%" -m pip install -r "%REQ_FILE%"
        if errorlevel 1 (
            echo [ERROR] Failed to install dependencies from %REQ_FILE%.
            pause
            exit /b 1
        )
    ) else (
        echo [WARN] %REQ_FILE% not found. Skipping dependency installation.
    )

    >"%STAMP_FILE%" echo %DATE% %TIME%
    if exist "%REQ_FILE%" copy /Y "%REQ_FILE%" "%STAMP_REQ_FILE%" >nul
)

if exist "%PREFLIGHT_FILE%" (
    "%VENV_PY%" "%PREFLIGHT_FILE%" >nul 2>&1
)

if "%SETUP_ONLY%"=="1" (
    echo [OK] Setup completed.
    exit /b 0
)

if exist "%VENV_PYW%" (
    "%VENV_PYW%" "%APP_FILE%"
    exit /b %errorlevel%
)

"%VENV_PY%" "%APP_FILE%"
exit /b %errorlevel%

:resolve_python_bootstrap
where py >nul 2>&1
if %errorlevel%==0 (
    set "PY_BOOTSTRAP=py -3"
    exit /b 0
)

where python >nul 2>&1
if %errorlevel%==0 (
    set "PY_BOOTSTRAP=python"
    exit /b 0
)

exit /b 1
