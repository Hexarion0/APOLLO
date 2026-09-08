import asyncio
import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

from apollo.auth import SingleOwnerAuthGuard
from apollo.channels.telegram import (
    TelegramChannel,
    _is_pure_interrupt_text,
    _is_continue_text,
)
from apollo.config import Config, TelegramConfig
from apollo.gateway import ApolloGateway
from apollo.providers.base import BaseLLMProvider, ChatMessage, LLMResponse


class SlowMockLLMProvider(BaseLLMProvider):
    def __init__(self, delay: float = 5.0, tokens_to_stream: Optional[List[str]] = None):
        self.delay = delay
        self.tokens_to_stream = tokens_to_stream or []

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if on_token and self.tokens_to_stream:
            for token in self.tokens_to_stream:
                await on_token(token)
                await asyncio.sleep(0.01)

        await asyncio.sleep(self.delay)
        return LLMResponse(content="Slow response completed")


def test_is_pure_interrupt_text():
    # True cases
    assert _is_pure_interrupt_text("wait") is True
    assert _is_pure_interrupt_text("Wait") is True
    assert _is_pure_interrupt_text("WAIT!") is True
    assert _is_pure_interrupt_text("wait...") is True
    assert _is_pure_interrupt_text("wait please") is True
    assert _is_pure_interrupt_text("please wait") is True
    assert _is_pure_interrupt_text("stop") is True
    assert _is_pure_interrupt_text("STOP!") is True
    assert _is_pure_interrupt_text("/stop") is True
    assert _is_pure_interrupt_text("/wait") is True
    assert _is_pure_interrupt_text("/cancel") is True
    assert _is_pure_interrupt_text("hold on") is True
    assert _is_pure_interrupt_text("pause") is True

    # False cases (Steer-in-flight / not pure interrupt)
    assert _is_pure_interrupt_text("wait, make it in python") is False
    assert _is_pure_interrupt_text("stop and check weather") is False
    assert _is_pure_interrupt_text("waiting for the bus") is False
    assert _is_pure_interrupt_text("hello world") is False
    assert _is_pure_interrupt_text("") is False


def test_is_continue_text():
    # True cases
    assert _is_continue_text("continue") is True
    assert _is_continue_text("Continue") is True
    assert _is_continue_text("continue please") is True
    assert _is_continue_text("please continue") is True
    assert _is_continue_text("/continue") is True
    assert _is_continue_text("/resume") is True
    assert _is_continue_text("resume") is True
    assert _is_continue_text("go on") is True
    assert _is_continue_text("keep going") is True

    # False cases
    assert _is_continue_text("continuous integration") is False
    assert _is_continue_text("hello world") is False
    assert _is_continue_text("wait") is False
    assert _is_continue_text("") is False


@pytest.mark.asyncio
async def test_telegram_channel_cancel_active_task():
    auth_guard = SingleOwnerAuthGuard(owner_id=12345)
    channel = TelegramChannel(bot_token="dummy_token", auth_guard=auth_guard)

    async def _dummy_coro():
        await asyncio.sleep(10.0)

    task = asyncio.create_task(_dummy_coro())
    channel.active_tasks["12345"] = task

    assert not task.done()
    cancelled = channel.cancel_active_task("12345")
    assert cancelled is True
    assert task.cancelling() > 0
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_gateway_cancellation(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    provider = SlowMockLLMProvider(delay=10.0)
    gateway = ApolloGateway(config=config, provider=provider)

    task = asyncio.create_task(gateway.process_message(sender_id="12345", user_message="Sleep task"))
    await asyncio.sleep(0.05)

    assert not task.done()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_draft_preservation_and_continuation():
    auth_guard = SingleOwnerAuthGuard(owner_id=12345)
    channel = TelegramChannel(bot_token="dummy_token", auth_guard=auth_guard)

    # Simulate a stream being cancelled and draft preserved
    streamed = ["Hello, ", "this is a partial ", "sentence"]
    draft_text = "".join(streamed)
    channel.last_interrupted_drafts["12345"] = draft_text

    assert channel.last_interrupted_drafts["12345"] == "Hello, this is a partial sentence"

