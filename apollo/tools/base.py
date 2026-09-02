from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseTool(ABC):
    """Abstract base class for all APOLLO agentic tools."""

    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for function arguments

    def to_openai_schema(self) -> Dict[str, Any]:
        """Format tool definition for OpenAI/NIM tool specification."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute tool action with keyword arguments."""
        pass
