import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

@dataclass
class ProviderConfig:
    api_key: str = ""
    base_url: str = "https://integrate.api.nvidia.com/v1"
    model: str = "meta/llama-3.3-70b-instruct"

@dataclass
class TelegramConfig:
    bot_token: str = ""
    owner_id: int = 0

@dataclass
class Config:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    policy_file: Path = Path("policy.json")
    audit_log_file: Path = Path("audit.log")
    database_path: Path = Path("apollo.db")
    persona_file: Path = Path("persona.txt")
    proactive_enabled: bool = True
    proactive_interval_hours: int = 4

    @classmethod
    def load_from_env(cls, env_file: Optional[str] = None) -> "Config":
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=True)

        owner_id_str = os.getenv("TELEGRAM_OWNER_ID", "0")
        try:
            owner_id = int(owner_id_str)
        except ValueError:
            owner_id = 0

        proactive_enabled_str = os.getenv("PROACTIVE_ENABLED", "true").lower()
        proactive_enabled = proactive_enabled_str in ("true", "1", "yes")

        try:
            proactive_interval = int(os.getenv("PROACTIVE_INTERVAL_HOURS", "4"))
        except ValueError:
            proactive_interval = 4

        return cls(
            provider=ProviderConfig(
                api_key=os.getenv("NVIDIA_API_KEY", ""),
                base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
                model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            ),
            telegram=TelegramConfig(
                bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
                owner_id=owner_id,
            ),
            policy_file=Path(os.getenv("POLICY_FILE", "policy.json")),
            audit_log_file=Path(os.getenv("AUDIT_LOG_FILE", "audit.log")),
            database_path=Path(os.getenv("DATABASE_PATH", "apollo.db")),
            persona_file=Path(os.getenv("PERSONA_FILE", "persona.txt")),
            proactive_enabled=proactive_enabled,
            proactive_interval_hours=proactive_interval,
        )
