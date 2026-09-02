import json
import logging
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger("apollo.policy")

class PermissionTier(str, Enum):
    AUTO = "auto"
    LOGGED = "logged"
    CONFIRM = "confirm"

class PolicyEngine:
    """Evaluates tool permission tiers based on policy.json configuration."""

    def __init__(self, policy_path: Path = Path("policy.json")):
        self.policy_path = policy_path
        self.default_tier = PermissionTier.CONFIRM
        self.tool_tiers: Dict[str, PermissionTier] = {}
        self.load_policy()

    def load_policy(self) -> None:
        """Load policy configuration from JSON file."""
        if not self.policy_path.exists():
            logger.warning(f"Policy file '{self.policy_path}' not found. Using default tier '{self.default_tier.value}'.")
            return

        try:
            with open(self.policy_path, "r", encoding="utf-8") as f:
                data: Dict[str, Any] = json.load(f)

            default_tier_str = data.get("default_tier", "confirm").lower()
            try:
                self.default_tier = PermissionTier(default_tier_str)
            except ValueError:
                self.default_tier = PermissionTier.CONFIRM

            raw_tools = data.get("tools", {})
            self.tool_tiers = {}
            for tool_name, tier_str in raw_tools.items():
                try:
                    self.tool_tiers[tool_name] = PermissionTier(tier_str.lower())
                except ValueError:
                    logger.warning(f"Invalid tier '{tier_str}' for tool '{tool_name}'. Defaulting to 'confirm'.")
                    self.tool_tiers[tool_name] = PermissionTier.CONFIRM

            logger.info(f"Loaded policy from '{self.policy_path}' with {len(self.tool_tiers)} rules.")

        except Exception as e:
            logger.error(f"Error reading policy file '{self.policy_path}': {e}. Using default fallback policy.")

    def get_tier(self, tool_name: str) -> PermissionTier:
        """Return the permission tier assigned to a given tool name."""
        return self.tool_tiers.get(tool_name, self.default_tier)

    def set_tool_tier(self, tool_name: str, tier: PermissionTier) -> None:
        """Dynamically set or override a tool's permission tier."""
        self.tool_tiers[tool_name] = tier
