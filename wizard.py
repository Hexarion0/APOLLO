#!/usr/bin/env python3
"""APOLLO Setup & Management Wizard.

Provides an interactive CLI wizard to configure credentials, test Telegram
connectivity, install/manage systemd auto-boot services, and edit policies.
"""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Base directories
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
CONFIG_FILE = BASE_DIR / "config.json"
POLICY_FILE = BASE_DIR / "policy.json"
VENV_PYTHON = BASE_DIR / ".venv" / "bin" / "python"

# ANSI Colors
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
MAGENTA = "\033[1;35m"
RESET = "\033[0m"


def clear_screen() -> None:
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_banner() -> None:
    print(f"""{CYAN}
 ╔══════════════════════════════════════════════════════════════════╗
 ║                     APOLLO SETUP WIZARD                          ║
 ║    Auto-Boot (systemd), Telegram Ping & System Configuration     ║
 ╚══════════════════════════════════════════════════════════════════╝{RESET}
""")


def get_input(prompt: str, default: Optional[str] = None) -> str:
    """Helper to prompt user input with optional default value."""
    if default:
        p = f"{BOLD}{prompt}{RESET} [{CYAN}{default}{RESET}]: "
    else:
        p = f"{BOLD}{prompt}{RESET}: "
    val = input(p).strip()
    return val if val else (default or "")


def read_env_file() -> Dict[str, str]:
    """Read .env file into key-value dictionary."""
    env_dict = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_dict[k.strip()] = v.strip()
    return env_dict


def write_env_file(env_dict: Dict[str, str]) -> None:
    """Write dictionary back to .env file cleanly."""
    lines = [
        "# APOLLO Master Environment Configuration",
        "",
        "# NVIDIA NIM / LLM Provider Configuration",
        f"NVIDIA_API_KEY={env_dict.get('NVIDIA_API_KEY', '')}",
        f"NVIDIA_BASE_URL={env_dict.get('NVIDIA_BASE_URL', 'https://integrate.api.nvidia.com/v1')}",
        f"NVIDIA_MODEL={env_dict.get('NVIDIA_MODEL', 'nvidia/nemotron-3-ultra-550b-a55b')}",
        f"FALLBACK_MODELS={env_dict.get('FALLBACK_MODELS', 'nvidia/nemotron-3-super-120b-a12b,meta/llama-3.2-11b-vision-instruct')}",
        f"NVIDIA_TEMPERATURE={env_dict.get('NVIDIA_TEMPERATURE', '0.7')}",
        f"NVIDIA_TOP_P={env_dict.get('NVIDIA_TOP_P', '1.0')}",
        f"NVIDIA_MAX_TOKENS={env_dict.get('NVIDIA_MAX_TOKENS', '2048')}",
        f"NVIDIA_TIMEOUT={env_dict.get('NVIDIA_TIMEOUT', '90.0')}",
        "",
        "# Telegram Channel Configuration",
        f"TELEGRAM_BOT_TOKEN={env_dict.get('TELEGRAM_BOT_TOKEN', '')}",
        f"TELEGRAM_OWNER_ID={env_dict.get('TELEGRAM_OWNER_ID', '')}",
        f"TELEGRAM_TYPING_INDICATOR={env_dict.get('TELEGRAM_TYPING_INDICATOR', 'true')}",
        "",
        "# Gateway Execution Controls",
        f"GATEWAY_MAX_TURNS={env_dict.get('GATEWAY_MAX_TURNS', '12')}",
        f"CHAT_HISTORY_LIMIT={env_dict.get('CHAT_HISTORY_LIMIT', '10')}",
        f"PERSONA_FILE={env_dict.get('PERSONA_FILE', 'persona.txt')}",
        f"STARTUP_NOTIFICATION={env_dict.get('STARTUP_NOTIFICATION', 'true')}",
        f"STARTUP_MESSAGE={env_dict.get('STARTUP_MESSAGE', '🚀 **APOLLO Online**: System booted and services are operational.')}",
        "",
        "# Autonomous Proactive Check-ins",
        f"PROACTIVE_ENABLED={env_dict.get('PROACTIVE_ENABLED', 'true')}",
        f"PROACTIVE_INTERVAL_HOURS={env_dict.get('PROACTIVE_INTERVAL_HOURS', '4')}",
        "",
        "# Logging Level (DEBUG, INFO, WARNING, ERROR)",
        f"LOG_LEVEL={env_dict.get('LOG_LEVEL', 'INFO')}",
        "",
        "# Security & Data Paths",
        f"POLICY_FILE={env_dict.get('POLICY_FILE', 'policy.json')}",
        f"AUDIT_LOG_FILE={env_dict.get('AUDIT_LOG_FILE', 'audit.log')}",
        f"CHAT_LOG_FILE={env_dict.get('CHAT_LOG_FILE', 'chat.log')}",
        f"DATABASE_PATH={env_dict.get('DATABASE_PATH', 'apollo.db')}",
        "",
    ]
    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    """Execute shell command and return returncode, stdout, stderr."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return res.returncode, res.stdout, res.stderr
    except Exception as e:
        return 1, "", str(e)


# ---------------------------------------------------------------------------
# Wizard Steps
# ---------------------------------------------------------------------------

def step_configure_credentials() -> None:
    """Step: Configure API keys, Telegram Bot, and Owner ID."""
    print(f"\n{MAGENTA}━━━ [1/3] Configure Credentials & Settings ━━━{RESET}\n")
    env_data = read_env_file()

    cur_nv = env_data.get("NVIDIA_API_KEY", "")
    cur_tg = env_data.get("TELEGRAM_BOT_TOKEN", "")
    cur_owner = env_data.get("TELEGRAM_OWNER_ID", "")

    print(f"1. {BOLD}NVIDIA API Key{RESET} (from build.nvidia.com)")
    nv_val = get_input("   Enter NVIDIA_API_KEY", cur_nv or "nvapi-...")
    if nv_val:
        env_data["NVIDIA_API_KEY"] = nv_val

    print(f"\n2. {BOLD}Telegram Bot Token{RESET} (from @BotFather)")
    tg_val = get_input("   Enter TELEGRAM_BOT_TOKEN", cur_tg or "123456789:ABC...")
    if tg_val:
        env_data["TELEGRAM_BOT_TOKEN"] = tg_val

    print(f"\n3. {BOLD}Telegram Owner ID{RESET} (Your personal Telegram User ID, e.g. from @userinfobot)")
    owner_val = get_input("   Enter TELEGRAM_OWNER_ID", cur_owner or "6579740425")
    if owner_val:
        env_data["TELEGRAM_OWNER_ID"] = owner_val

    print(f"\n4. {BOLD}Startup Notification Message{RESET}")
    cur_msg = env_data.get("STARTUP_MESSAGE", "🚀 **APOLLO Online**: System booted and services are operational.")
    msg_val = get_input("   Enter boot notification text", cur_msg)
    env_data["STARTUP_MESSAGE"] = msg_val
    env_data["STARTUP_NOTIFICATION"] = "true"

    write_env_file(env_data)
    print(f"\n{GREEN}✓ Settings saved to .env successfully!{RESET}\n")


async def async_test_telegram(bot_token: str, owner_id: str, message: str) -> bool:
    """Send a real Telegram test message to verify credentials."""
    try:
        from telegram import Bot
        bot = Bot(token=bot_token)
        async with bot:
            await bot.send_message(chat_id=int(owner_id), text=message)
        return True
    except Exception as e:
        print(f"{RED}Telegram test error: {e}{RESET}")
        return False


def step_test_telegram() -> bool:
    """Step: Test Telegram connection and boot notification ping."""
    print(f"\n{MAGENTA}━━━ [2/3] Test Telegram Notification Ping ━━━{RESET}\n")
    env_data = read_env_file()
    token = env_data.get("TELEGRAM_BOT_TOKEN", "")
    owner_id = env_data.get("TELEGRAM_OWNER_ID", "")
    boot_msg = env_data.get("STARTUP_MESSAGE", "🚀 **APOLLO Online**: System booted and services are operational.")

    if not token or not owner_id or owner_id == "0":
        print(f"{YELLOW}⚠️ Telegram Bot Token or Owner ID is missing in .env.{RESET}")
        print("Please configure credentials first.")
        return False

    print(f"Sending test notification ping to Telegram ID {CYAN}{owner_id}{RESET}...")
    test_text = f"🧪 **APOLLO Connectivity Test**\n\n{boot_msg}\n\n*Boot notification is verified and ready.*"

    success = asyncio.run(async_test_telegram(token, owner_id, test_text))
    if success:
        print(f"{GREEN}✓ Test message successfully delivered to your Telegram!{RESET}\n")
        return True
    else:
        print(f"{RED}✗ Could not deliver message to Telegram. Please verify your Bot Token & Owner ID.{RESET}\n")
        return False


def step_install_systemd() -> None:
    """Step: Install and enable systemd user service."""
    print(f"\n{MAGENTA}━━━ [3/3] Configure & Enable systemd Auto-Boot ━━━{RESET}\n")

    user = os.getenv("USER", "hexarion")
    user_systemd_dir = Path.home() / ".config" / "systemd" / "user"
    service_file = user_systemd_dir / "apollo.service"

    python_exec = str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable)
    work_dir = str(BASE_DIR)

    service_content = f"""[Unit]
Description=APOLLO - Adaptive Personal Operator for Learning, Life & Optimization
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={work_dir}
EnvironmentFile=-{work_dir}/.env
ExecStart={python_exec} main.py
Restart=always
RestartSec=5
KillMode=process
TimeoutStopSec=15
PassEnvironment=WAYLAND_DISPLAY XDG_RUNTIME_DIR HYPRLAND_INSTANCE_SIGNATURE DISPLAY PULSE_SERVER

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""

    print(f"Service Configuration:")
    print(f"  • Working Directory: {CYAN}{work_dir}{RESET}")
    print(f"  • Python Interpreter: {CYAN}{python_exec}{RESET}")
    print(f"  • Target Unit: {CYAN}{service_file}{RESET}")

    proceed = get_input("\nProceed with installing the systemd user service? (y/n)", "y").lower()
    if proceed not in ("y", "yes"):
        print(f"{YELLOW}Installation skipped.{RESET}")
        return

    # 1. Create directory
    user_systemd_dir.mkdir(parents=True, exist_ok=True)
    service_file.write_text(service_content, encoding="utf-8")
    print(f"{GREEN}✓ Written {service_file}{RESET}")

    # 2. Enable linger
    print("Enabling user linger (so service runs on boot without GUI login)...")
    code, out, err = run_cmd(["loginctl", "enable-linger", user])
    if code == 0:
        print(f"{GREEN}✓ Linger enabled for user '{user}'{RESET}")
    else:
        print(f"{YELLOW}⚠️ Note: Could not automatically enable linger: {err.strip()}{RESET}")
        print(f"  You can run manually: {CYAN}loginctl enable-linger {user}{RESET}")

    # 3. Reload daemon
    print("Reloading systemd user daemon...")
    run_cmd(["systemctl", "--user", "daemon-reload"])

    # 4. Enable service
    print("Enabling apollo.service on boot...")
    code, out, err = run_cmd(["systemctl", "--user", "enable", "apollo.service"])
    if code == 0:
        print(f"{GREEN}✓ apollo.service enabled on boot!{RESET}")
    else:
        print(f"{RED}✗ Failed to enable service: {err.strip()}{RESET}")

    # 5. Start now?
    start_now = get_input("\nDo you want to start the APOLLO service right now? (y/n)", "y").lower()
    if start_now in ("y", "yes"):
        code, out, err = run_cmd(["systemctl", "--user", "restart", "apollo.service"])
        if code == 0:
            print(f"{GREEN}✓ APOLLO service started! Check your Telegram for the boot ping.{RESET}")
            # Show status
            _, status_out, _ = run_cmd(["systemctl", "--user", "status", "apollo.service", "--no-pager"])
            print(f"\n{BOLD}Service Status:{RESET}\n{status_out}")
        else:
            print(f"{RED}✗ Failed to start service: {err.strip()}{RESET}")


def service_manager_menu() -> None:
    """Sub-menu to manage active systemd service."""
    while True:
        print(f"\n{MAGENTA}━━━ Systemd Service Manager ━━━{RESET}\n")
        print(f"  {BOLD}1.{RESET} Check Service Status  {DIM}(systemctl --user status apollo){RESET}")
        print(f"  {BOLD}2.{RESET} Start Service         {DIM}(systemctl --user start apollo){RESET}")
        print(f"  {BOLD}3.{RESET} Stop Service          {DIM}(systemctl --user stop apollo){RESET}")
        print(f"  {BOLD}4.{RESET} Restart Service       {DIM}(systemctl --user restart apollo){RESET}")
        print(f"  {BOLD}5.{RESET} View Live Logs        {DIM}(journalctl --user -u apollo -f){RESET}")
        print(f"  {BOLD}6.{RESET} Disable & Remove Service")
        print(f"  {BOLD}0.{RESET} Back to Main Menu")

        choice = get_input("\nSelect an option", "1")
        if choice == "0":
            break
        elif choice == "1":
            code, out, err = run_cmd(["systemctl", "--user", "status", "apollo.service", "--no-pager"])
            print(f"\n{BOLD}Output:{RESET}\n{out or err}")
        elif choice == "2":
            code, out, err = run_cmd(["systemctl", "--user", "start", "apollo.service"])
            print(f"{GREEN}✓ Service started!{RESET}" if code == 0 else f"{RED}✗ Error: {err}{RESET}")
        elif choice == "3":
            code, out, err = run_cmd(["systemctl", "--user", "stop", "apollo.service"])
            print(f"{GREEN}✓ Service stopped.{RESET}" if code == 0 else f"{RED}✗ Error: {err}{RESET}")
        elif choice == "4":
            code, out, err = run_cmd(["systemctl", "--user", "restart", "apollo.service"])
            print(f"{GREEN}✓ Service restarted.{RESET}" if code == 0 else f"{RED}✗ Error: {err}{RESET}")
        elif choice == "5":
            print(f"{CYAN}Running: journalctl --user -u apollo -n 25 --no-pager{RESET}\n")
            code, out, err = run_cmd(["journalctl", "--user", "-u", "apollo", "-n", "25", "--no-pager"])
            print(out or err)
        elif choice == "6":
            confirm = get_input("Are you sure you want to disable and remove the service? (y/n)", "n")
            if confirm.lower() in ("y", "yes"):
                run_cmd(["systemctl", "--user", "stop", "apollo.service"])
                run_cmd(["systemctl", "--user", "disable", "apollo.service"])
                service_file = Path.home() / ".config" / "systemd" / "user" / "apollo.service"
                if service_file.exists():
                    service_file.unlink()
                run_cmd(["systemctl", "--user", "daemon-reload"])
                print(f"{GREEN}✓ Service disabled and removed.{RESET}")


# ---------------------------------------------------------------------------
# Main Interactive Loop
# ---------------------------------------------------------------------------

def full_quickstart() -> None:
    """Run full step-by-step setup."""
    step_configure_credentials()
    step_test_telegram()
    step_install_systemd()


def main() -> None:
    clear_screen()
    print_banner()

    while True:
        print(f"\n{BOLD}Main Menu:{RESET}")
        print(f"  {CYAN}[1]{RESET} {BOLD}🚀 Full Guided Setup{RESET} (Configure + Test Ping + Install systemd)")
        print(f"  {CYAN}[2]{RESET} ⚙️  Configure Credentials & Settings (.env)")
        print(f"  {CYAN}[3]{RESET} 🧪 Test Telegram Bot Ping & Boot Notification")
        print(f"  {CYAN}[4]{RESET} 🔌 Install / Enable systemd Auto-Boot Service")
        print(f"  {CYAN}[5]{RESET} 📊 Manage systemd Service (Status, Start, Stop, Logs)")
        print(f"  {CYAN}[0]{RESET} 🚪 Exit Wizard")

        choice = get_input("\nSelect an option", "1")

        if choice == "1":
            full_quickstart()
        elif choice == "2":
            step_configure_credentials()
        elif choice == "3":
            step_test_telegram()
        elif choice == "4":
            step_install_systemd()
        elif choice == "5":
            service_manager_menu()
        elif choice in ("0", "q", "exit"):
            print(f"\n{GREEN}Goodbye! APOLLO is ready.{RESET}\n")
            break
        else:
            print(f"{RED}Invalid selection. Please choose a valid option.{RESET}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n{YELLOW}Wizard closed.{RESET}\n")
