import json
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

logger = logging.getLogger("apollo.config")

@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "meta/llama-3.3-70b-instruct"
    temperature: float = 0.7
    max_tokens: int = 2048

@dataclass
class TelegramConfig:
    bot_token: str = ""
    owner_id: int = 0

@dataclass
class GatewayConfig:
    max_turns: int = 12
    persona_file: Path = Path("persona.txt")

@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    policy_file: Path = Path("policy.json")
    audit_log_file: Path = Path("audit.log")
    database_path: Path = Path("apollo.db")
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
                with open(c_path, "r", encoding="utf-8") as f:
                    json_data = json.load(f)
                logger.info(f"Loaded master configuration from '{c_path}'.")
            except Exception as e:
                logger.warning(f"Error reading configuration file '{c_path}': {e}")

        provider_json = json_data.get("provider", {})
        telegram_json = json_data.get("telegram", {})
        gateway_json = json_data.get("gateway", {})
        proactive_json = json_data.get("proactive", {})
        paths_json = json_data.get("paths", {})

        # Environment variable overrides take precedence if non-empty
        api_key = os.getenv("NVIDIA_API_KEY") or provider_json.get("api_key", "")
        base_url = os.getenv("NVIDIA_BASE_URL") or provider_json.get("base_url", "https://integrate.api.nvidia.com/v1")
        model = os.getenv("NVIDIA_MODEL") or provider_json.get("model", "meta/llama-3.3-70b-instruct")
        temperature = float(provider_json.get("temperature", 0.7))
        max_tokens = int(provider_json.get("max_tokens", 2048))

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or telegram_json.get("bot_token", "")
        owner_id_env = os.getenv("TELEGRAM_OWNER_ID")
        if owner_id_env:
            try:
                owner_id = int(owner_id_env)
            except ValueError:
                owner_id = 0
        else:
            owner_id = int(telegram_json.get("owner_id", 0))

        max_turns = int(gateway_json.get("max_turns", 12))
        persona_file = Path(os.getenv("PERSONA_FILE") or gateway_json.get("persona_file") or "persona.txt")

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

        policy_file = Path(os.getenv("POLICY_FILE") or paths_json.get("policy_file") or "policy.json")
        audit_log_file = Path(os.getenv("AUDIT_LOG_FILE") or paths_json.get("audit_log_file") or "audit.log")
        database_path = Path(os.getenv("DATABASE_PATH") or paths_json.get("database_path") or "apollo.db")

        return cls(
            provider=ProviderConfig(
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            ),
            telegram=TelegramConfig(
                bot_token=bot_token,
                owner_id=owner_id,
            ),
            gateway=GatewayConfig(
                max_turns=max_turns,
                persona_file=persona_file,
            ),
            policy_file=policy_file,
            audit_log_file=audit_log_file,
            database_path=database_path,
            persona_file=persona_file,
            proactive_enabled=proactive_enabled,
            proactive_interval_hours=proactive_interval,
        )

    @classmethod
    def load_from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Backward compatible load method."""
        return cls.load(env_file=env_file)
