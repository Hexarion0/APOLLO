"""
apollo/providers/router.py — Adaptive Complexity-Based Model Router.

Routes incoming prompts dynamically across Fast, Balanced, and Complex model tiers
in < 0.1ms with zero API overhead.
"""

import enum
import logging
import re
from typing import Optional, Tuple

from apollo.config import ProviderConfig

logger = logging.getLogger("apollo.providers.router")


class ModelTier(enum.Enum):
    FAST = "fast"
    BALANCED = "balanced"
    COMPLEX = "complex"


# Fast tier pattern matches (case-insensitive)
FAST_PATTERNS = [
    # Time / Date
    r"^(what('?s| is)? (the )?(time|date|day)|current time|time now|clock|what day is it)",
    # Media & volume
    r"^(play|pause|stop|resume|next( song| track)?|prev(ious)?( song| track)?|skip|mute|unmute|volume|shuffle|loop)",
    # Quick greetings / casual chat
    r"^(hi|hello|hey|yo|sup|good (morning|afternoon|evening|night)|how are you|what'?s up)[.!?]?$",
    # Weather
    r"^(what('?s| is)? the weather|weather in|weather today|forecast)",
    # Reminders & timers
    r"^(remind me|set (a )?reminder|set (a )?timer|cancel reminder|list reminders)",
    # Power & screen
    r"^(lock( pc| session| workstation)?|screen (off|on)|sleep( pc)?|suspend( pc)?)$",
    # Status / ping
    r"^(ping|status|uptime|system info)$",
]

# Complex tier pattern matches (case-insensitive)
COMPLEX_PATTERNS = [
    r"(deep(ly)? think|think hard|step[- ]by[- ]step tradeoff|trade[- ]off matrix)",
    r"(architectural (design|review|overhaul)|design (a |an )?(architecture|system)|distributed system)",
    r"(refactor (the |all |every |entire )|complete (rewrite|refactor))",
    r"(complex (bug|issue|race condition|deadlock|memory leak|segfault))",
    r"(formulate (a |an )?(algorithm|mathematical proof|formal specification))",
    r"(full implementation plan|comprehensive audit of every file)",
]


class ComplexityRouter:
    """Zero-overhead heuristic prompt classifier and model router."""

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig()

    def classify(self, prompt: str) -> Tuple[ModelTier, str]:
        """
        Classify prompt into a ModelTier in < 0.1ms.
        Returns (ModelTier, cleaned_prompt).
        """
        text = prompt.strip()
        lower_text = text.lower()

        # 1. Check for manual prefix overrides
        if lower_text.startswith(("/fast", "[fast]", "!fast")):
            cleaned = re.sub(r"^(\/fast|\[fast\]|!fast)\s*", "", text, flags=re.IGNORECASE).strip()
            return ModelTier.FAST, cleaned or text

        if lower_text.startswith(("/deep", "[deep]", "!deep", "/ultra", "[ultra]", "!ultra", "/complex")):
            cleaned = re.sub(r"^(\/deep|\[deep\]|!deep|\/ultra|\[ultra\]|!ultra|\/complex)\s*", "", text, flags=re.IGNORECASE).strip()
            return ModelTier.COMPLEX, cleaned or text

        if lower_text.startswith(("/balanced", "[balanced]", "!balanced", "/mid")):
            cleaned = re.sub(r"^(\/balanced|\[balanced\]|!balanced|\/mid)\s*", "", text, flags=re.IGNORECASE).strip()
            return ModelTier.BALANCED, cleaned or text

        # 2. Check for Fast Tier patterns
        for pattern in FAST_PATTERNS:
            if re.search(pattern, lower_text):
                return ModelTier.FAST, text

        # 3. Check for Complex Tier patterns or long multi-requirement prompts
        for pattern in COMPLEX_PATTERNS:
            if re.search(pattern, lower_text):
                return ModelTier.COMPLEX, text

        # High token / char heuristic (e.g. > 1500 chars with multiple code blocks)
        if len(text) > 1500 and text.count("```") >= 2:
            return ModelTier.COMPLEX, text

        # 4. Default: Balanced Tier (coding, tool usage, general technical queries)
        return ModelTier.BALANCED, text

    def get_model_for_prompt(self, prompt: str) -> str:
        """Get the model string identifier for the given prompt based on complexity."""
        tier, _ = self.classify(prompt)
        if tier == ModelTier.FAST:
            model = getattr(self.config, "model_fast", None) or "nvidia/nemotron-3-super-120b-a12b"
            logger.info(f"Prompt classified as FAST tier -> selected model '{model}'")
            return model
        elif tier == ModelTier.COMPLEX:
            model = getattr(self.config, "model_complex", None) or "nvidia/nemotron-3-ultra-550b-a55b"
            logger.info(f"Prompt classified as COMPLEX tier -> selected model '{model}'")
            return model
        else:
            model = getattr(self.config, "model_balanced", None) or getattr(self.config, "model", "nvidia/nemotron-4-340b-instruct")
            logger.info(f"Prompt classified as BALANCED tier -> selected model '{model}'")
            return model
