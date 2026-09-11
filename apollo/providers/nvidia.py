import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
from openai import AsyncOpenAI

from apollo.providers.base import BaseLLMProvider, ChatMessage, LLMResponse, ToolCall

logger = logging.getLogger("apollo.providers.nvidia")

import re as _re

def _extract_thinking(text: str) -> tuple[str, Optional[str]]:
    """Strip <think>…</think> blocks from text, returning (clean_text, thinking_content).

    Handles:
    - <think>…</think> (DeepSeek-R1, Qwen3, Nemotron reasoning models)
    - Multiple think blocks are concatenated with newlines.
    - Remaining text is stripped of leading/trailing whitespace.
    """
    if not text or not _re.search(r"<think>", text, flags=_re.IGNORECASE):
        return text, None

    thinking_parts: List[str] = []

    def _replace(m: _re.Match) -> str:
        thinking_parts.append(m.group(1).strip())
        return ""

    clean = _re.sub(r"<think>(.*?)</think>", _replace, text, flags=_re.DOTALL | _re.IGNORECASE)
    clean = clean.strip()
    thinking = "\n\n".join(thinking_parts) if thinking_parts else None
    return clean, thinking

def _has_visual_content(messages: List[Dict[str, Any]]) -> bool:
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and (part.get("type") == "image_url" or "image_url" in part):
                    return True
    return False

class NvidiaNIMProvider(BaseLLMProvider):
    """NVIDIA NIM API Provider implementation using OpenAI-compatible interface."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        model: str = "nvidia/nemotron-3-ultra-550b-a55b",
        fallback_models: Optional[List[str]] = None,
        vision_model: str = "meta/llama-3.2-11b-vision-instruct",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.fallback_models = fallback_models if fallback_models is not None else ["nvidia/nemotron-3-super-120b-a12b", "meta/llama-3.2-11b-vision-instruct"]
        self.vision_model = vision_model
        self._client: Optional[AsyncOpenAI] = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            if not self.api_key:
                logger.warning("NVIDIA_API_KEY is not set. NIM requests will fail if unauthenticated.")
            self._client = AsyncOpenAI(
                api_key=self.api_key or "dummy_key",
                base_url=self.base_url,
                timeout=120.0,
                max_retries=1,
            )
        return self._client

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 1024,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        formatted_messages = [msg.to_dict() for msg in messages]

        has_vision = _has_visual_content(formatted_messages)
        if has_vision:
            # Build list of vision-capable candidate models
            candidate_models = [self.vision_model]
            all_known = [self.model] + self.fallback_models
            for m in all_known:
                if m not in candidate_models and any(tag in m.lower() for tag in ("vision", "neva", "llava", "multimodal", "vl")):
                    candidate_models.append(m)
        else:
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

            logger.info(f"Sending LLM request using model '{model_name}' (streaming={bool(on_token)})...")
            try:
                for retry_attempt in range(2):
                    try:
                        if on_token is not None:
                            stream = await self.client.chat.completions.create(
                                **kwargs,
                                stream=True,
                                timeout=90.0,
                            )
                            accumulated_content: List[str] = []
                            tool_call_chunks: Dict[int, Dict[str, str]] = {}
                            finish_reason = None

                            async for chunk in stream:
                                if not chunk.choices:
                                    continue
                                choice = chunk.choices[0]
                                if choice.finish_reason:
                                    finish_reason = choice.finish_reason
                                delta = choice.delta
                                if delta.content:
                                    accumulated_content.append(delta.content)
                                    try:
                                        await on_token(delta.content)
                                    except Exception as token_err:
                                        logger.debug(f"on_token handler exception: {token_err}")

                                if delta.tool_calls:
                                    for tc_chunk in delta.tool_calls:
                                        idx = tc_chunk.index
                                        if idx not in tool_call_chunks:
                                            tool_call_chunks[idx] = {
                                                "id": tc_chunk.id or "",
                                                "name": (tc_chunk.function.name if tc_chunk.function else "") or "",
                                                "arguments": (tc_chunk.function.arguments if tc_chunk.function else "") or "",
                                            }
                                        else:
                                            if tc_chunk.id:
                                                tool_call_chunks[idx]["id"] += tc_chunk.id
                                            if tc_chunk.function and tc_chunk.function.name:
                                                tool_call_chunks[idx]["name"] += tc_chunk.function.name
                                            if tc_chunk.function and tc_chunk.function.arguments:
                                                tool_call_chunks[idx]["arguments"] += tc_chunk.function.arguments

                            parsed_tool_calls: List[ToolCall] = []
                            for idx in sorted(tool_call_chunks.keys()):
                                tc_data = tool_call_chunks[idx]
                                raw_args = tc_data["arguments"]
                                args_dict = {}
                                if raw_args:
                                    try:
                                        args_dict = json.loads(raw_args)
                                    except json.JSONDecodeError:
                                        args_dict = {"raw": raw_args}
                                parsed_tool_calls.append(
                                    ToolCall(
                                        id=tc_data["id"] or f"tc_{idx}",
                                        name=tc_data["name"],
                                        arguments=args_dict,
                                    )
                                )

                            full_content = "".join(accumulated_content) if accumulated_content else None
                            clean_content, thinking = _extract_thinking(full_content or "")
                            return LLMResponse(
                                content=clean_content or None,
                                tool_calls=parsed_tool_calls,
                                finish_reason=finish_reason,
                                model_used=model_name,
                                was_fallback=(model_name != self.model),
                                thinking=thinking,
                            )
                        else:
                            response = await self.client.chat.completions.create(**kwargs, timeout=90.0)
                            choice = response.choices[0]
                            message = choice.message

                            parsed_tool_calls = []
                            if message.tool_calls:
                                for tc in message.tool_calls:
                                    arguments_dict = {}
                                    if tc.function.arguments:
                                        try:
                                            arguments_dict = json.loads(tc.function.arguments)
                                        except json.JSONDecodeError:
                                            arguments_dict = {"raw": tc.function.arguments}
                                    parsed_tool_calls.append(
                                        ToolCall(
                                            id=tc.id,
                                            name=tc.function.name,
                                            arguments=arguments_dict,
                                        )
                                    )

                            clean_content, thinking = _extract_thinking(message.content or "")
                            return LLMResponse(
                                content=clean_content or None,
                                tool_calls=parsed_tool_calls,
                                finish_reason=choice.finish_reason,
                                raw_response=response,
                                model_used=model_name,
                                was_fallback=(model_name != self.model),
                                thinking=thinking,
                            )

                    except Exception as err:
                        err_str = str(err).lower()
                        if ("503" in err_str or "resourceexhausted" in err_str or "429" in err_str) and retry_attempt == 0:
                            logger.warning(f"Model '{model_name}' hit worker limit (503/429). Retrying in 0.5s...")
                            await asyncio.sleep(0.5)
                        else:
                            raise err

            except Exception as e:
                logger.warning(f"Model '{model_name}' failed or timed out: {e}. Trying fallback models if available...")
                last_exception = e

        raise RuntimeError(f"All attempted NIM models failed. Last error: {last_exception}") from last_exception
