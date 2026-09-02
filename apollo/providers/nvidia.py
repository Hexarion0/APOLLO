import json
import logging
from typing import Any, Dict, List, Optional
from openai import AsyncOpenAI

from apollo.providers.base import BaseLLMProvider, ChatMessage, LLMResponse, ToolCall

logger = logging.getLogger("apollo.providers.nvidia")

class NvidiaNIMProvider(BaseLLMProvider):
    """NVIDIA NIM API Provider implementation using OpenAI-compatible interface."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        model: str = "nvidia/nemotron-3-ultra-550b-a55b",
        fallback_models: Optional[List[str]] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.fallback_models = fallback_models if fallback_models is not None else ["nvidia/nemotron-3-super-120b-a12b", "meta/llama-3.2-11b-vision-instruct"]
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                logger.warning("NVIDIA_API_KEY is not set. NIM requests will fail if unauthenticated.")
            self._client = AsyncOpenAI(
                api_key=self.api_key or "dummy_key",
                base_url=self.base_url,
                timeout=60.0,
                max_retries=1,
            )
        return self._client

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 1024,
    ) -> LLMResponse:
        formatted_messages = [msg.to_dict() for msg in messages]

        candidate_models = [self.model] + [m for m in self.fallback_models if m != self.model]
        last_exception = None

        for model_name in candidate_models:
            kwargs: Dict[str, Any] = {
                "model": model_name,
                "messages": formatted_messages,
                "temperature": temperature,
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            logger.info(f"Sending LLM request using model '{model_name}'...")
            try:
                response = None
                for retry_attempt in range(2):
                    try:
                        response = await self.client.chat.completions.create(**kwargs, timeout=25.0)
                        break
                    except Exception as err:
                        err_str = str(err).lower()
                        if ("503" in err_str or "resourceexhausted" in err_str or "429" in err_str) and retry_attempt == 0:
                            logger.warning(f"Model '{model_name}' hit worker limit (503/429). Retrying in 0.5s...")
                            await asyncio.sleep(0.5)
                        else:
                            raise err

                if response is None:
                    raise RuntimeError(f"Failed to get response from model '{model_name}'.")

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
                    model_used=model_name,
                    was_fallback=(model_name != self.model),
                )

            except Exception as e:
                logger.warning(f"Model '{model_name}' failed or timed out: {e}. Trying fallback models if available...")
                last_exception = e

        raise RuntimeError(f"All attempted NIM models failed. Last error: {last_exception}") from last_exception
