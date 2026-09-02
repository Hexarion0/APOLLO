import json
import logging
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from apollo.providers.base import BaseLLMProvider, ChatMessage, LLMResponse, ToolCall

logger = logging.getLogger("apollo.providers.nvidia")

class NvidiaNIMProvider(BaseLLMProvider):
    """NVIDIA NIM API Provider implementation using OpenAI-compatible interface."""

    def __init__(self, api_key: str, base_url: str = "https://integrate.api.nvidia.com/v1", model: str = "nvidia/nemotron-3-super-120b-a12b"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                logger.warning("NVIDIA_API_KEY is not set. NIM requests will fail if unauthenticated.")
            self._client = AsyncOpenAI(api_key=self.api_key or "dummy_key", base_url=self.base_url, timeout=30.0)
        return self._client

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 1024,
    ) -> LLMResponse:
        formatted_messages = []
        for msg in messages:
            formatted_messages.append(msg.to_dict())

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        logger.debug(f"Sending request to NVIDIA NIM ({self.model}) at {self.base_url}")
        
        try:
            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            parsed_tool_calls: List[ToolCall] = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    arguments_dict = {}
                    if tc.function.arguments:
                        try:
                            arguments_dict = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse tool call arguments as JSON: {tc.function.arguments}")
                            arguments_dict = {"raw": tc.function.arguments}
                    parsed_tool_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=arguments_dict,
                        )
                    )

            return LLMResponse(
                content=message.content,
                tool_calls=parsed_tool_calls,
                finish_reason=choice.finish_reason,
                raw_response=response,
            )

        except Exception as e:
            logger.error(f"NVIDIA NIM Provider error: {e}")
            raise RuntimeError(f"NVIDIA NIM Provider failed: {e}") from e
