import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional

from apollo.config import Config, ProviderConfig, TelegramConfig
from apollo.gateway import ApolloGateway
from apollo.policy import PermissionTier
from apollo.providers.base import BaseLLMProvider, ChatMessage, LLMResponse, ToolCall
from apollo.channels.base import BaseChannel

class MockLLMProvider(BaseLLMProvider):
    def __init__(self, mock_responses: List[LLMResponse]):
        self.mock_responses = mock_responses
        self.call_count = 0

    async def generate_response(
        self,
        messages: List[ChatMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        on_token: Optional[Any] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        if self.call_count < len(self.mock_responses):
            resp = self.mock_responses[self.call_count]
            self.call_count += 1
            return resp
        return LLMResponse(content="Default mock response")

class MockChannel(BaseChannel):
    def __init__(self, auto_approve: bool = True):
        self.auto_approve = auto_approve
        self.sent_messages: List[str] = []
        self.confirmation_requests: List[Dict[str, Any]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def send_message(self, recipient_id: str, text: str) -> None:
        self.sent_messages.append(text)

    async def request_confirmation(
        self,
        recipient_id: str,
        confirmation_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> bool:
        self.confirmation_requests.append({
            "recipient_id": recipient_id,
            "confirmation_id": confirmation_id,
            "tool_name": tool_name,
            "arguments": arguments,
        })
        return self.auto_approve

@pytest.mark.asyncio
async def test_gateway_text_only(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    provider = MockLLMProvider([
        LLMResponse(content="Hello! I am APOLLO.")
    ])
    gateway = ApolloGateway(config=config, provider=provider)

    result = await gateway.process_message(sender_id="12345", user_message="Hi")
    assert result == "Hello! I am APOLLO."

@pytest.mark.asyncio
async def test_gateway_auto_tool_execution(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    gateway = ApolloGateway(config=config)
    gateway.policy_engine.set_tool_tier("get_current_time", PermissionTier.AUTO)

    provider = MockLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_1", name="get_current_time", arguments={})],
        ),
        LLMResponse(content="The current time is verified."),
    ])
    gateway.provider = provider

    result = await gateway.process_message(sender_id="12345", user_message="What time is it?")
    assert result == "The current time is verified."
    assert provider.call_count == 2

@pytest.mark.asyncio
async def test_gateway_confirm_tool_approved(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    channel = MockChannel(auto_approve=True)
    gateway = ApolloGateway(config=config, channel=channel)
    gateway.policy_engine.set_tool_tier("execute_command", PermissionTier.CONFIRM)

    provider = MockLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_2", name="execute_command", arguments={"command": "echo hello"})],
        ),
        LLMResponse(content="Command executed successfully."),
    ])
    gateway.provider = provider

    result = await gateway.process_message(sender_id="12345", user_message="Run command")
    assert result == "Command executed successfully."
    assert len(channel.confirmation_requests) == 1
    assert channel.confirmation_requests[0]["tool_name"] == "execute_command"

@pytest.mark.asyncio
async def test_gateway_confirm_tool_denied(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    channel = MockChannel(auto_approve=False)  # Deny approval
    gateway = ApolloGateway(config=config, channel=channel)
    gateway.policy_engine.set_tool_tier("execute_command", PermissionTier.CONFIRM)

    provider = MockLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[ToolCall(id="tc_3", name="execute_command", arguments={"command": "rm -rf /tmp/foo"})],
        ),
        LLMResponse(content="I could not execute the command because approval was denied."),
    ])
    gateway.provider = provider

    result = await gateway.process_message(sender_id="12345", user_message="Delete tmp foo")
    assert "denied" in result.lower() or "could not execute" in result.lower()
    assert len(channel.confirmation_requests) == 1

@pytest.mark.asyncio
async def test_gateway_unauthorized_sender_raises(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    gateway = ApolloGateway(config=config)

    with pytest.raises(PermissionError):
        await gateway.process_message(sender_id="99999", user_message="Attack")

def test_gateway_and_config_signatures_valid():
    import inspect
    sig = inspect.signature(ApolloGateway.process_message)
    assert "on_token" in sig.parameters
    sig_cfg = inspect.signature(ProviderConfig)
    assert "fallback_models" in sig_cfg.parameters

@pytest.mark.asyncio
async def test_gateway_startup_notification(tmp_path: Path):
    config = Config(
        telegram=TelegramConfig(bot_token="test_token", owner_id=12345),
        policy_file=tmp_path / "policy.json",
        audit_log_file=tmp_path / "audit.log",
        database_path=tmp_path / "apollo.db",
    )
    config.gateway.startup_notification = True
    channel = MockChannel()
    gateway = ApolloGateway(config=config, channel=channel)

    await gateway.start()
    assert len(channel.sent_messages) == 1
    assert "APOLLO Online" in channel.sent_messages[0]
    await gateway.stop()

def test_gateway_compact_context():
    config = Config()
    gateway = ApolloGateway(config=config, provider=MockLLMProvider([]))
    msgs = [
        ChatMessage(role="system", content="System instruction"),
        ChatMessage(role="user", content="Turn 1: " + "a" * 500),
        ChatMessage(role="assistant", content="Turn 1 reply: " + "b" * 500),
        ChatMessage(role="user", content="Turn 2: " + "c" * 200),
        ChatMessage(role="assistant", content="Turn 2 reply: " + "d" * 200),
    ]
    # Restrict budget so Turn 1 is dropped and compacted
    compacted = gateway._compact_context(msgs, max_total_chars=600)
    assert len(compacted) < len(msgs)
    assert compacted[0].role == "system"
    assert "compacted" in compacted[1].content.lower()
    assert "Turn 2 reply" in compacted[-1].content

