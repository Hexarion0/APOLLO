#!/usr/bin/env python3
"""
APOLLO Unified Command Line Interface (CLI).
Supports Linux & Windows seamless management.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# Root directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config.json"
PERSONA_FILE = BASE_DIR / "persona.txt"
POLICY_FILE = BASE_DIR / "policy.json"
ENV_FILE = BASE_DIR / ".env"
LOG_FILE = BASE_DIR / "logs" / "chat.log"
AUDIT_FILE = BASE_DIR / "logs" / "audit.log"
DB_FILE = BASE_DIR / "data" / "apollo.db"

# Virtualenv Python paths
if sys.platform == "win32":
    VENV_PYTHON = BASE_DIR / ".venv_win" / "Scripts" / "python.exe"
    if not VENV_PYTHON.exists():
        VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
else:
    VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"

# ANSI Colors
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
MAGENTA = "\033[1;35m"
BLUE = "\033[1;34m"
RESET = "\033[0m"


def _header(text: str) -> None:
    print(f"\n{CYAN}{BOLD}=== {text} ==={RESET}\n")


def cmd_status(args: argparse.Namespace) -> None:
    """Check running status, database statistics, and health."""
    _header("APOLLO System Status")
    is_win = sys.platform == "win32"
    print(f"{BOLD}Operating System:{RESET} {sys.platform.capitalize()} ({'Windows' if is_win else 'Linux'})")
    print(f"{BOLD}Project Root:{RESET}     {BASE_DIR}")

    # Process / Service status
    if not is_win:
        try:
            res = subprocess.run(
                ["systemctl", "--user", "is-active", "apollo.service"],
                capture_output=True,
                text=True,
            )
            status_text = res.stdout.strip()
            if status_text == "active":
                print(f"{BOLD}Service Status:{RESET}   {GREEN}● Active (Running via systemd){RESET}")
            else:
                print(f"{BOLD}Service Status:{RESET}   {YELLOW}○ Inactive ({status_text}){RESET}")
        except Exception as e:
            print(f"{BOLD}Service Status:{RESET}   {RED}Error checking systemd: {e}{RESET}")
    else:
        # Check running python main.py process on Windows
        try:
            res = subprocess.run(
                ["powershell", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*main.py*' } | Select-Object -ExpandProperty Id"],
                capture_output=True,
                text=True,
            )
            pids = res.stdout.strip().split()
            if pids and pids[0]:
                print(f"{BOLD}Process Status:{RESET}   {GREEN}● Active (PID: {', '.join(pids)}){RESET}")
            else:
                print(f"{BOLD}Process Status:{RESET}   {YELLOW}○ Inactive (Not running){RESET}")
        except Exception:
            print(f"{BOLD}Process Status:{RESET}   {YELLOW}Status unknown (PowerShell query failed){RESET}")

    # Database Statistics
    if DB_FILE.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(DB_FILE))
            c = conn.cursor()
            c.execute("SELECT count(*) FROM memories;")
            mem_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM conversation_history;")
            hist_count = c.fetchone()[0]
            c.execute("SELECT count(*) FROM scheduled_tasks;")
            task_count = c.fetchone()[0]
            conn.close()
            print(f"{BOLD}Database:{RESET}         {GREEN}Connected{RESET} ({mem_count} memories, {hist_count} history rows, {task_count} scheduled tasks)")
        except Exception as e:
            print(f"{BOLD}Database:{RESET}         {YELLOW}Found ({DB_FILE.stat().st_size / 1024:.1f} KB, query err: {e}){RESET}")
    else:
        print(f"{BOLD}Database:{RESET}         {RED}Missing ({DB_FILE}){RESET}")

    # Logs
    if LOG_FILE.exists():
        size_kb = LOG_FILE.stat().st_size / 1024
        print(f"{BOLD}Chat Log:{RESET}         {size_kb:.1f} KB ({LOG_FILE})")
    if AUDIT_FILE.exists():
        size_kb = AUDIT_FILE.stat().st_size / 1024
        print(f"{BOLD}Audit Log:{RESET}        {size_kb:.1f} KB ({AUDIT_FILE})")

    print()


def cmd_start(args: argparse.Namespace) -> None:
    """Start APOLLO gateway."""
    _header("Starting APOLLO")
    if sys.platform != "win32":
        try:
            subprocess.run(["systemctl", "--user", "start", "apollo.service"], check=True)
            print(f"{GREEN}✓ apollo.service started successfully via systemd.{RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{RED}✗ Failed to start service: {e}{RESET}")
    else:
        vbs_path = BASE_DIR / "start_windows_background.vbs"
        if vbs_path.exists():
            try:
                subprocess.Popen(["wscript.exe", str(vbs_path)], cwd=str(BASE_DIR))
                print(f"{GREEN}✓ APOLLO launched in background on Windows.{RESET}")
            except Exception as e:
                print(f"{RED}✗ Failed to launch: {e}{RESET}")
        else:
            bat_path = BASE_DIR / "start_windows.bat"
            subprocess.Popen([str(bat_path)], cwd=str(BASE_DIR), shell=True)
            print(f"{GREEN}✓ APOLLO launched via start_windows.bat.{RESET}")


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop APOLLO gateway."""
    _header("Stopping APOLLO")
    if sys.platform != "win32":
        try:
            subprocess.run(["systemctl", "--user", "stop", "apollo.service"], check=True)
            print(f"{YELLOW}✓ apollo.service stopped.{RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{RED}✗ Failed to stop service: {e}{RESET}")
    else:
        try:
            subprocess.run(
                ["powershell", "-Command", "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*main.py*' } | Stop-Process -Force"],
                check=False,
            )
            print(f"{YELLOW}✓ APOLLO stopped on Windows.{RESET}")
        except Exception as e:
            print(f"{RED}✗ Error stopping process: {e}{RESET}")


def cmd_restart(args: argparse.Namespace) -> None:
    """Restart APOLLO gateway."""
    _header("Restarting APOLLO")
    if sys.platform != "win32":
        try:
            subprocess.run(["systemctl", "--user", "restart", "apollo.service"], check=True)
            print(f"{GREEN}✓ apollo.service restarted successfully.{RESET}")
        except subprocess.CalledProcessError as e:
            print(f"{RED}✗ Failed to restart: {e}{RESET}")
    else:
        cmd_stop(args)
        time.sleep(1)
        cmd_start(args)


def cmd_logs(args: argparse.Namespace) -> None:
    """View live or recent logs."""
    lines = args.lines or 30
    if sys.platform != "win32" and not args.file:
        cmd = ["journalctl", "--user", "-u", "apollo.service", f"-n{lines}"]
        if args.follow:
            cmd.append("-f")
        try:
            subprocess.run(cmd)
        except KeyboardInterrupt:
            pass
    else:
        target_file = AUDIT_FILE if args.audit else LOG_FILE
        if not target_file.exists():
            print(f"{RED}Log file not found at {target_file}{RESET}")
            return
        
        if not args.follow:
            with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    print(line, end="")
        else:
            try:
                with open(target_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(0, os.SEEK_END)
                    while True:
                        line = f.readline()
                        if line:
                            print(line, end="", flush=True)
                        else:
                            time.sleep(0.5)
            except KeyboardInterrupt:
                pass


def cmd_config(args: argparse.Namespace) -> None:
    """View or edit configuration."""
    if args.action == "edit":
        editor = os.environ.get("EDITOR", "notepad" if sys.platform == "win32" else "nano")
        subprocess.run([editor, str(CONFIG_FILE)])
        return

    _header("APOLLO Configuration")
    if not CONFIG_FILE.exists():
        print(f"{RED}config.json not found!{RESET}")
        return

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        
        provider = cfg.get("provider", {})
        print(f"{BOLD}LLM Base URL:{RESET}       {provider.get('base_url')}")
        print(f"{BOLD}Fast Model:{RESET}         {CYAN}{provider.get('model_fast')}{RESET}")
        print(f"{BOLD}Balanced Model:{RESET}     {GREEN}{provider.get('model_balanced')}{RESET}")
        print(f"{BOLD}Complex Model:{RESET}      {MAGENTA}{provider.get('model_complex')}{RESET}")
        print(f"{BOLD}Vision Model:{RESET}       {provider.get('vision_model')}")
        print(f"{BOLD}Temperature:{RESET}        {provider.get('temperature')}")
        print(f"{BOLD}Max Tokens:{RESET}         {provider.get('max_tokens')}")
        
        tg = cfg.get("telegram", {})
        print(f"{BOLD}Telegram Owner ID:{RESET}  {tg.get('owner_id')}")
        
        proactive = cfg.get("proactive", {})
        print(f"{BOLD}Proactive Engine:{RESET}   {'Enabled (' + str(proactive.get('interval_hours', 4)) + 'h)' if proactive.get('enabled') else 'Disabled'}")
        
        print(f"\n{DIM}To edit full JSON, run: apollo config edit{RESET}\n")
    except Exception as e:
        print(f"{RED}Error reading config.json: {e}{RESET}")


def cmd_persona(args: argparse.Namespace) -> None:
    """View or edit persona.txt."""
    if args.action == "edit":
        editor = os.environ.get("EDITOR", "notepad" if sys.platform == "win32" else "nano")
        subprocess.run([editor, str(PERSONA_FILE)])
        return

    _header("APOLLO Persona (System Prompt)")
    if PERSONA_FILE.exists():
        with open(PERSONA_FILE, "r", encoding="utf-8") as f:
            print(f.read())
        print(f"\n{DIM}To edit persona, run: apollo persona edit{RESET}\n")
    else:
        print(f"{RED}persona.txt not found!{RESET}")


def cmd_test(args: argparse.Namespace) -> None:
    """Run pytest suite."""
    _header("Running Automated Tests")
    pytest_bin = None
    if sys.platform == "win32":
        pytest_bin = BASE_DIR / ".venv_win" / "Scripts" / "pytest.exe"
        if not pytest_bin.exists():
            pytest_bin = BASE_DIR / ".venv" / "Scripts" / "pytest.exe"
    else:
        pytest_bin = BASE_DIR / ".venv" / "bin" / "pytest"

    if pytest_bin and pytest_bin.exists():
        cmd = [str(pytest_bin)]
    else:
        cmd = ["pytest"]

    if args.filter:
        cmd.extend(["-k", args.filter])

    subprocess.run(cmd, cwd=str(BASE_DIR))


def cmd_autostart(args: argparse.Namespace) -> None:
    """Manage autostart settings."""
    _header("APOLLO Auto-Start Manager")
    is_win = sys.platform == "win32"
    action = args.action or "status"

    if not is_win:
        # Linux systemd user service
        if action in ("enable", "on"):
            subprocess.run(["systemctl", "--user", "enable", "--now", "apollo.service"])
            print(f"{GREEN}✓ apollo.service enabled for auto-start on boot.{RESET}")
        elif action in ("disable", "off"):
            subprocess.run(["systemctl", "--user", "disable", "apollo.service"])
            print(f"{YELLOW}✓ apollo.service disabled from auto-start.{RESET}")
        else:
            res = subprocess.run(["systemctl", "--user", "is-enabled", "apollo.service"], capture_output=True, text=True)
            enabled = res.stdout.strip() == "enabled"
            print(f"Auto-start on Linux: {GREEN if enabled else YELLOW}{res.stdout.strip().upper()}{RESET}")
    else:
        # Windows Startup folder
        if action in ("enable", "on"):
            bat = BASE_DIR / "install_autostart_windows.bat"
            subprocess.run([str(bat)], shell=True)
        elif action in ("disable", "off"):
            bat = BASE_DIR / "uninstall_autostart_windows.bat"
            subprocess.run([str(bat)], shell=True)
        else:
            startup_lnk = Path(os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\APOLLO.lnk"))
            if startup_lnk.exists():
                print(f"Auto-start on Windows: {GREEN}ENABLED (in Startup Folder){RESET}")
            else:
                print(f"Auto-start on Windows: {YELLOW}DISABLED{RESET}")


def cmd_wizard(args: argparse.Namespace) -> None:
    """Run interactive setup wizard."""
    wizard_path = BASE_DIR / "wizard.py"
    py_bin = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    subprocess.run([py_bin, str(wizard_path)])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="apollo",
        description=f"{BOLD}APOLLO{RESET} — Unified Management CLI (Linux & Windows)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # status
    p_status = subparsers.add_parser("status", help="Show system status, service health, and database metrics")
    p_status.set_defaults(func=cmd_status)

    # start / stop / restart
    p_start = subparsers.add_parser("start", help="Start APOLLO gateway service/process")
    p_start.set_defaults(func=cmd_start)

    p_stop = subparsers.add_parser("stop", help="Stop APOLLO gateway service/process")
    p_stop.set_defaults(func=cmd_stop)

    p_restart = subparsers.add_parser("restart", help="Restart APOLLO gateway service/process")
    p_restart.set_defaults(func=cmd_restart)

    # logs
    p_logs = subparsers.add_parser("logs", help="View recent or live journal/chat logs")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output in real time")
    p_logs.add_argument("-n", "--lines", type=int, default=30, help="Number of lines to show (default: 30)")
    p_logs.add_argument("--audit", action="store_true", help="View audit.log instead of chat.log")
    p_logs.add_argument("--file", action="store_true", help="Read directly from file rather than journalctl")
    p_logs.set_defaults(func=cmd_logs)

    # config
    p_config = subparsers.add_parser("config", help="View or edit config.json")
    p_config.add_argument("action", nargs="?", choices=["show", "edit"], default="show", help="Action (show or edit)")
    p_config.set_defaults(func=cmd_config)

    # persona
    p_persona = subparsers.add_parser("persona", help="View or edit persona.txt")
    p_persona.add_argument("action", nargs="?", choices=["show", "edit"], default="show", help="Action (show or edit)")
    p_persona.set_defaults(func=cmd_persona)

    # test
    p_test = subparsers.add_parser("test", help="Run automated test suite (pytest)")
    p_test.add_argument("-k", "--filter", help="Filter tests by keyword expression")
    p_test.set_defaults(func=cmd_test)

    # autostart
    p_autostart = subparsers.add_parser("autostart", help="Manage autostart on system boot/login")
    p_autostart.add_argument("action", nargs="?", choices=["status", "enable", "disable"], default="status", help="Autostart action")
    p_autostart.set_defaults(func=cmd_autostart)

    # wizard
    p_wizard = subparsers.add_parser("wizard", help="Run the interactive configuration wizard")
    p_wizard.set_defaults(func=cmd_wizard)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
