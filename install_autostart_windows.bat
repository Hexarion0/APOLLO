@echo off
title Install APOLLO Auto-Start (Windows)
cd /d "%~dp0"

echo ====================================================
echo        Installing APOLLO Auto-Start on Windows
echo ====================================================
echo.

set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\APOLLO.lnk"
set "TARGET_PATH=%~dp0start_windows_background.vbs"
set "WORKING_DIR=%~dp0"

echo Target: %TARGET_PATH%
echo Startup Folder: %STARTUP_FOLDER%
echo.

:: Use PowerShell to create the shortcut in the Startup folder
powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut('%SHORTCUT_PATH%'); $s.TargetPath = '%TARGET_PATH%'; $s.WorkingDirectory = '%WORKING_DIR%'; $s.Save()"

if %errorlevel% equ 0 (
    echo [SUCCESS] APOLLO has been added to your Windows Startup folder!
    echo It will now automatically launch in the background whenever you log into Windows.
) else (
    echo [ERROR] Failed to create startup shortcut.
)

echo.
pause
