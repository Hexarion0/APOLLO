from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class ChatMessage:
    role: str  # 'system', 'user', 'assistant', 'tool'
    content: Optional[Union[str, List[Dict[str, Any]]]] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

@dataclass
class LLMResponse:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None
    raw_response: Optional[Any] = None
    model_used: Optional[str] = None
    was_fallback: bool = False
    thinking: Optional[str] = None  # Extracted <think>…</think> reasoning content

class BaseLLMProvider(ABC):
    """Abstract interface for LLM providers (NVIDIA NIM, Anthropic, OpenAI, Ollama, etc.)."""

    @abstractmethod
    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        """Generate a response from the LLM provider given conversation history and tools."""
        pass

    async def analyze_image(
        self,
        image_data_uri: str,
        prompt: str = "Describe and analyze this image in detail, including any text, code, or UI elements.",
    ) -> str:
        """Analyze an image using a vision-capable model."""
        messages = [
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            )
        ]
        response = await self.generate_response(messages=messages)
        return response.content or "No analysis generated."
