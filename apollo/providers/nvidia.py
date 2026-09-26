import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional
import httpx
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
        vision_model: str = "nvidia/neva-22b",
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.fallback_models = fallback_models if fallback_models is not None else [
            "nvidia/nemotron-3-super-120b-a12b",
            "nvidia/nemotron-4-340b-instruct",
            "nvidia/neva-22b",
        ]
        self.vision_model = vision_model
        # Persistent HTTP connection pool — reuses TLS sessions, eliminates 100-300ms handshake overhead per call
        self._http_client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(
                limits=httpx.Limits(
                    max_keepalive_connections=10,
                    max_connections=20,
                    keepalive_expiry=30.0,
                ),
            ),
            timeout=120.0,
        )
        self._client: AsyncOpenAI = AsyncOpenAI(
            api_key=self.api_key or "dummy_key",
            base_url=self.base_url,
            http_client=self._http_client,
            max_retries=1,
        )

    async def close(self) -> None:
        """Close the persistent HTTP connection pool."""
        await self._http_client.aclose()
        logger.debug("NvidiaNIMProvider HTTP connection pool closed.")

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = 1024,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        model: Optional[str] = None,
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

        # If ComplexityRouter (or caller) specified an explicit model override, promote it to first
        if model and not has_vision:
            candidate_models = [model] + [m for m in candidate_models if m != model]

        primary_model = candidate_models[0]
        failed_model_errors: List[str] = []
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
                            stream = await self._client.chat.completions.create(
                                **kwargs,
                                stream=True,
                                timeout=90.0,
                            )
                            accumulated_content: List[str] = []
                            tool_call_chunks: Dict[int, Dict[str, str]] = {}
                            finish_reason = None
                            in_think_block = False

                            async for chunk in stream:
                                if not chunk.choices:
                                    continue
                                choice = chunk.choices[0]
                                if choice.finish_reason:
                                    finish_reason = choice.finish_reason
                                delta = choice.delta

                                # Handle explicit reasoning tokens (DeepSeek-R1 / Nemotron / reasoning_content)
                                reasoning_token = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                                if reasoning_token:
                                    if not in_think_block:
                                        accumulated_content.append("<think>\n")
                                        if on_token:
                                            try:
                                                await on_token("<think>\n")
                                            except Exception:
                                                pass
                                        in_think_block = True
                                    accumulated_content.append(reasoning_token)
                                    if on_token:
                                        try:
                                            await on_token(reasoning_token)
                                        except Exception as token_err:
                                            logger.debug(f"on_token handler exception: {token_err}")

                                if delta.content:
                                    if in_think_block:
                                        accumulated_content.append("\n</think>\n")
                                        if on_token:
                                            try:
                                                await on_token("\n</think>\n")
                                            except Exception:
                                                pass
                                        in_think_block = False
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

                            if in_think_block:
                                accumulated_content.append("\n</think>\n")
                                if on_token:
                                    try:
                                        await on_token("\n</think>\n")
                                    except Exception:
                                        pass
                                in_think_block = False

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
                            is_fallback = (model_name != primary_model) or bool(failed_model_errors)
                            fallback_err_str = "; ".join(failed_model_errors) if failed_model_errors else None
                            return LLMResponse(
                                content=clean_content or None,
                                tool_calls=parsed_tool_calls,
                                finish_reason=finish_reason,
                                model_used=model_name,
                                was_fallback=is_fallback,
                                fallback_error=fallback_err_str,
                                thinking=thinking,
                            )
                        else:
                            response = await self._client.chat.completions.create(**kwargs, timeout=90.0)
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

                            raw_content = message.content or ""
                            reasoning = getattr(message, "reasoning_content", None) or getattr(message, "reasoning", None)
                            if reasoning and "<think>" not in raw_content.lower():
                                raw_content = f"<think>\n{reasoning}\n</think>\n{raw_content}"
                            clean_content, thinking = _extract_thinking(raw_content)
                            is_fallback = (model_name != primary_model) or bool(failed_model_errors)
                            fallback_err_str = "; ".join(failed_model_errors) if failed_model_errors else None
                            return LLMResponse(
                                content=clean_content or None,
                                tool_calls=parsed_tool_calls,
                                finish_reason=choice.finish_reason,
                                raw_response=response,
                                model_used=model_name,
                                was_fallback=is_fallback,
                                fallback_error=fallback_err_str,
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
                err_summary = f"{model_name} ({type(e).__name__}: {str(e).strip()[:100]})"
                failed_model_errors.append(err_summary)
                logger.warning(f"Model '{model_name}' failed or timed out: {e}. Trying fallback models if available...")
                last_exception = e

        errors_joined = "; ".join(failed_model_errors) if failed_model_errors else str(last_exception)
        raise RuntimeError(f"All attempted NIM models failed ({errors_joined}). Last error: {last_exception}") from last_exception
