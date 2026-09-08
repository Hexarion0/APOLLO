from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional, Awaitable

class BaseChannel(ABC):
    """Abstract base class for messaging channels (Telegram, CLI, Webhook, etc.)."""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming channel messages."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop channel service cleanly."""
        pass

    @abstractmethod
    async def send_message(self, recipient_id: str, text: str) -> None:
        """Send a text message to a user or chat ID."""
        pass

    @abstractmethod
    async def request_confirmation(
        self,
        recipient_id: str,
        confirmation_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Request explicit owner approval for a confirmation-tier tool action."""
        pass

    def cancel_active_task(self, recipient_id: str) -> bool:
        """Cancel any active processing task for recipient_id if supported."""
        return False


