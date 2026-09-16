@echo off
title Uninstall APOLLO Auto-Start (Windows)
set "STARTUP_FOLDER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT_PATH=%STARTUP_FOLDER%\APOLLO.lnk"

if exist "%SHORTCUT_PATH%" (
    del "%SHORTCUT_PATH%"
    echo [SUCCESS] APOLLO startup shortcut removed.
) else (
    echo [INFO] APOLLO startup shortcut not found in Startup folder.
)

pause
