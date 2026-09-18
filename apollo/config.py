import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

logger = logging.getLogger("apollo.config")

DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b"

@dataclass
class LoggingConfig:
    level: str = "INFO"

@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "nvidia/nemotron-4-340b-instruct"
    model_fast: str = "nvidia/nemotron-3-super-120b-a12b"
    model_balanced: str = "nvidia/nemotron-4-340b-instruct"
    model_complex: str = "nvidia/nemotron-3-ultra-550b-a55b"
    fallback_models: List[str] = field(default_factory=lambda: ["nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-4-340b-instruct", "nvidia/neva-22b"])
    vision_model: str = "nvidia/neva-22b"
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 2048
    timeout_seconds: float = 90.0

@dataclass
class TelegramConfig:
    bot_token: str = ""
    owner_id: int = 0
    typing_indicator: bool = True

@dataclass
class GatewayConfig:
    max_turns: int = 25
    persona_file: Path = Path("persona.txt")
    startup_notification: bool = True
    startup_message: str = "🚀 **APOLLO Online**: System booted and services are operational."
    chat_history_limit: int = 10

@dataclass
class ProactiveConfig:
    enabled: bool = True
    interval_hours: int = 4

@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    policy_file: Path = Path("policy.json")
    audit_log_file: Path = Path("logs/audit.log")
    chat_log_file: Path = Path("logs/chat.log")
    database_path: Path = Path("data/apollo.db")
    persona_file: Path = Path("persona.txt")
    proactive_enabled: bool = True
    proactive_interval_hours: int = 4

    @classmethod
    def load(cls, config_path: str = "config.json", env_file: Optional[str] = None) -> "Config":
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=True)

        json_data: Dict[str, Any] = {}
        c_path = Path(config_path)
        if c_path.exists():
            try:
                raw_text = c_path.read_text(encoding="utf-8")
                # Strip single line comments starting with // or #
                lines = []
                for line in raw_text.splitlines():
                    s = line.strip()
                    if s.startswith("//") or s.startswith("#"):
                        continue
                    lines.append(line)
                json_data = json.loads("\n".join(lines))
                logger.info(f"Loaded master configuration from '{c_path}'.")
            except Exception as e:
                logger.warning(f"Error reading configuration file '{c_path}': {e}")

        provider_json = json_data.get("provider", {})
        telegram_json = json_data.get("telegram", {})
        gateway_json = json_data.get("gateway", {})
        proactive_json = json_data.get("proactive", {})
        paths_json = json_data.get("paths", {})
        logging_json = json_data.get("logging", {})

        # Logging
        log_level = os.getenv("LOG_LEVEL") or logging_json.get("level", "INFO").upper()

        # Provider
        api_key = os.getenv("NVIDIA_API_KEY") or provider_json.get("api_key", "")
        base_url = os.getenv("NVIDIA_BASE_URL") or provider_json.get("base_url", "https://integrate.api.nvidia.com/v1")
        model = os.getenv("NVIDIA_MODEL") or provider_json.get("model", "nvidia/nemotron-3-ultra-550b-a55b")
        fallback_models_env = os.getenv("FALLBACK_MODELS")
        if fallback_models_env:
            fallback_models = [m.strip() for m in fallback_models_env.split(",") if m.strip()]
        else:
            fallback_models = provider_json.get("fallback_models", ["nvidia/nemotron-3-super-120b-a12b", "meta/llama-3.2-11b-vision-instruct"])

        vision_model = os.getenv("NVIDIA_VISION_MODEL") or provider_json.get("vision_model", "meta/llama-3.2-11b-vision-instruct")
        temperature = float(os.getenv("NVIDIA_TEMPERATURE") or provider_json.get("temperature", 0.7))
        top_p = float(os.getenv("NVIDIA_TOP_P") or provider_json.get("top_p", 1.0))
        max_tokens = int(os.getenv("NVIDIA_MAX_TOKENS") or provider_json.get("max_tokens", 2048))
        timeout_seconds = float(os.getenv("NVIDIA_TIMEOUT") or provider_json.get("timeout_seconds", 90.0))

        # Telegram
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or telegram_json.get("bot_token", "")
        owner_id_env = os.getenv("TELEGRAM_OWNER_ID")
        if owner_id_env:
            try:
                owner_id = int(owner_id_env)
            except ValueError:
                owner_id = 0
        else:
            owner_id = int(telegram_json.get("owner_id", 0))

        typing_env = os.getenv("TELEGRAM_TYPING_INDICATOR")
        if typing_env:
            typing_indicator = typing_env.lower() in ("true", "1", "yes")
        else:
            typing_indicator = bool(telegram_json.get("typing_indicator", True))

        # Gateway
        max_turns = int(os.getenv("GATEWAY_MAX_TURNS") or gateway_json.get("max_turns", 12))
        persona_file = Path(os.getenv("PERSONA_FILE") or gateway_json.get("persona_file") or "persona.txt")
        startup_notif_env = os.getenv("STARTUP_NOTIFICATION")
        if startup_notif_env:
            startup_notification = startup_notif_env.lower() in ("true", "1", "yes")
        else:
            startup_notification = bool(gateway_json.get("startup_notification", True))

        startup_message = os.getenv("STARTUP_MESSAGE") or gateway_json.get(
            "startup_message", "🚀 **APOLLO Online**: System booted and services are operational."
        )
        chat_history_limit = int(os.getenv("CHAT_HISTORY_LIMIT") or gateway_json.get("chat_history_limit", 10))

        # Proactive
        proactive_env = os.getenv("PROACTIVE_ENABLED")
        if proactive_env:
            proactive_enabled = proactive_env.lower() in ("true", "1", "yes")
        else:
            proactive_enabled = bool(proactive_json.get("enabled", True))

        proactive_interval_env = os.getenv("PROACTIVE_INTERVAL_HOURS")
        if proactive_interval_env:
            try:
                proactive_interval = int(proactive_interval_env)
            except ValueError:
                proactive_interval = 4
        else:
            proactive_interval = int(proactive_json.get("interval_hours", 4))

        # Paths
        policy_file = Path(os.getenv("POLICY_FILE") or paths_json.get("policy_file") or "policy.json")
        audit_log_file = Path(os.getenv("AUDIT_LOG_FILE") or paths_json.get("audit_log_file") or "logs/audit.log")
        chat_log_file = Path(os.getenv("CHAT_LOG_FILE") or paths_json.get("chat_log_file") or "logs/chat.log")
        database_path = Path(os.getenv("DATABASE_PATH") or paths_json.get("database_path") or "data/apollo.db")

        return cls(
            provider=ProviderConfig(
                api_key=api_key,
                base_url=base_url,
                model=model,
                fallback_models=fallback_models,
                vision_model=vision_model,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
            ),
            telegram=TelegramConfig(
                bot_token=bot_token,
                owner_id=owner_id,
                typing_indicator=typing_indicator,
            ),
            gateway=GatewayConfig(
                max_turns=max_turns,
                persona_file=persona_file,
                startup_notification=startup_notification,
                startup_message=startup_message,
                chat_history_limit=chat_history_limit,
            ),
            proactive=ProactiveConfig(
                enabled=proactive_enabled,
                interval_hours=proactive_interval,
            ),
            logging=LoggingConfig(
                level=log_level,
            ),
            policy_file=policy_file,
            audit_log_file=audit_log_file,
            chat_log_file=chat_log_file,
            database_path=database_path,
            persona_file=persona_file,
            proactive_enabled=proactive_enabled,
            proactive_interval_hours=proactive_interval,
        )

    @classmethod
    def load_from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Backward compatible load method."""
        return cls.load(env_file=env_file)
