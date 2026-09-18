@echo off
title APOLLO - Windows Launcher
cd /d "%~dp0..\.."

echo ====================================================
echo             APOLLO Launcher for Windows
echo ====================================================

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

:: Check or create Windows virtual environment (.venv_win)
if not exist ".venv_win\Scripts\activate.bat" (
    echo [*] Creating Windows virtual environment in .venv_win...
    python -m venv .venv_win
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [*] Installing dependencies from requirements.txt...
    call .venv_win\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install requirements.
        pause
        exit /b 1
    )
) else (
    call .venv_win\Scripts\activate.bat
)

:: Check if .env exists
if not exist ".env" (
    echo [WARNING] .env file not found!
    echo Copying .env.example to .env...
    copy .env.example .env
    echo Please edit .env with your TELEGRAM_BOT_TOKEN and NVIDIA_API_KEY.
)

echo [*] Starting APOLLO Gateway...
python main.py

if %errorlevel% neq 0 (
    echo.
    echo [APOLLO Exited with error code %errorlevel%]
    pause
)
