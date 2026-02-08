@echo off
setlocal

cd /d "%~dp0"
set "APP_FILE=app_gui.py"
set "EXE_NAME=AgentCommander"
set "ICON_FILE=logo_w.ico"

if not exist "%APP_FILE%" (
    echo [ERROR] %APP_FILE% not found in:
    echo %CD%
    pause
    exit /b 1
)

if not exist "%ICON_FILE%" (
    if exist "logo_w.png" (
        where py >nul 2>&1
        if %errorlevel%==0 (
            py -3 -c "from PIL import Image; img=Image.open('logo_w.png').convert('RGBA'); img.save('logo_w.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" >nul 2>&1
        ) else (
            where python >nul 2>&1
            if %errorlevel%==0 (
                python -c "from PIL import Image; img=Image.open('logo_w.png').convert('RGBA'); img.save('logo_w.ico', format='ICO', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])" >nul 2>&1
            )
        )
    )
)

set "ICON_SWITCH="
if exist "%ICON_FILE%" set "ICON_SWITCH=--icon \"%ICON_FILE%\""

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -m pip install --upgrade pyinstaller
    py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name "%EXE_NAME%" %ICON_SWITCH% --collect-all customtkinter "%APP_FILE%"
    goto :done
)

where python >nul 2>&1
if %errorlevel%==0 (
    python -m pip install --upgrade pyinstaller
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name "%EXE_NAME%" %ICON_SWITCH% --collect-all customtkinter "%APP_FILE%"
    goto :done
)

echo [ERROR] Python was not found.
echo Install Python 3.10+ and try again.
pause
exit /b 1

:done
if %errorlevel% neq 0 (
    echo [ERROR] Build failed.
    pause
    exit /b %errorlevel%
)

echo [OK] Build complete.
echo EXE path: %CD%\dist\%EXE_NAME%.exe
pause
exit /b 0
