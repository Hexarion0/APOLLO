@echo off
setlocal
cd /d "%~dp0"

if exist ".venv_win\Scripts\python.exe" (
    set "PYTHON_EXEC=.venv_win\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXEC=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXEC=python"
)

"%PYTHON_EXEC%" -m apollo.cli %*
endlocal
