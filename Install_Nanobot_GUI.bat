@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\install_windows_easy.ps1" %*
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Installer failed with code %EXIT_CODE%.
    echo Check logs in .\logs\installer\
    pause
)
exit /b %EXIT_CODE%
