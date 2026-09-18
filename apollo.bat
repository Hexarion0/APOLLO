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

set "PYTHONPATH=%~dp0;%PYTHONPATH%"
"%PYTHON_EXEC%" "%~dp0apollo\cli.py" %*
endlocal
