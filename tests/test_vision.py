import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import base64

from apollo.providers.base import ChatMessage, ToolCall, LLMResponse, BaseLLMProvider
from apollo.providers.nvidia import NvidiaNIMProvider
from apollo.tools.vision import AnalyzeImageTool
from apollo.config import Config, ProviderConfig
from apollo.gateway import ApolloGateway
from apollo.channels.telegram import TelegramChannel
from apollo.auth import SingleOwnerAuthGuard

class DummyProvider(BaseLLMProvider):
    def __init__(self, reply_text: str = "Test vision analysis"):
        self.reply_text = reply_text
        self.last_messages = []

    async def generate_response(self, messages, tools=None, temperature=0.7, max_tokens=None, on_token=None):
        self.last_messages = messages
        return LLMResponse(content=self.reply_text)

def test_chat_message_multimodal_dict():
    """Verify ChatMessage formats multimodal parts properly for OpenAI/NIM API."""
    msg = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "What is in this image?"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo="}},
        ],
    )
    d = msg.to_dict()
    assert d["role"] == "user"
    assert isinstance(d["content"], list)
    assert len(d["content"]) == 2
    assert d["content"][0]["type"] == "text"
    assert d["content"][1]["type"] == "image_url"

@pytest.mark.asyncio
async def test_analyze_image_tool_local_file(tmp_path):
    """Test AnalyzeImageTool reading a real image from disk and calling provider."""
    # Create a small dummy png
    test_img = tmp_path / "test_screenshot.png"
    test_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4")

    provider = DummyProvider(reply_text="Screenshot shows a terminal window.")
    tool = AnalyzeImageTool(provider=provider)

    result = await tool.execute(image_path=str(test_img), prompt="What is on the screen?")
    assert "Screenshot shows a terminal window." in result
    assert len(provider.last_messages) == 1
    content = provider.last_messages[0].content
    assert isinstance(content, list)
    assert content[0]["text"] == "What is on the screen?"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

@pytest.mark.asyncio
async def test_analyze_image_tool_missing_file():
    """Test AnalyzeImageTool with non-existent file."""
    provider = DummyProvider()
    tool = AnalyzeImageTool(provider=provider)
    result = await tool.execute(image_path="/non/existent/path/screenshot.png")
    assert "Error: Image file does not exist" in result

@pytest.mark.asyncio
async def test_nvidia_provider_vision_routing():
    """Test that NvidiaNIMProvider routes requests containing image_url to vision_model."""
    provider = NvidiaNIMProvider(
        api_key="mock_key",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        vision_model="meta/llama-3.2-11b-vision-instruct",
        fallback_models=["nvidia/nemotron-3-super-120b-a12b"],
    )

    mock_client = MagicMock()
    mock_completions = AsyncMock()
    
    mock_choice = MagicMock()
    mock_choice.message.content = "Vision response"
    mock_choice.message.tool_calls = None
    mock_choice.finish_reason = "stop"
    
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_completions.create = AsyncMock(return_value=mock_response)
    mock_client.chat.completions = mock_completions
    provider._client = mock_client

    # Send multimodal message
    msg = ChatMessage(
        role="user",
        content=[
            {"type": "text", "text": "Describe image"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
        ],
    )

    resp = await provider.generate_response(messages=[msg])
    assert resp.content == "Vision response"
    
    # Check that model passed in kwargs was the vision_model
    call_args, call_kwargs = mock_completions.create.call_args
    assert call_kwargs["model"] == "meta/llama-3.2-11b-vision-instruct"

@pytest.mark.asyncio
async def test_gateway_process_message_with_image(tmp_path):
    """Test ApolloGateway process_message with image attachment."""
    config = Config()
    config.paths_json = {}
    config.database_path = tmp_path / "test.db"
    config.audit_log_file = tmp_path / "test_audit.log"
    config.chat_log_file = tmp_path / "test_chat.log"
    config.policy_file = tmp_path / "test_policy.json"
    config.telegram.owner_id = 12345

    provider = DummyProvider(reply_text="Analysis: This is a test diagram.")
    gateway = ApolloGateway(config=config, provider=provider)

    data_uri = "data:image/png;base64,iVBORw0KGgo="
    result = await gateway.process_message(
        sender_id="12345",
        user_message="Analyze this architecture diagram",
        images=[data_uri],
    )

    assert "Analysis: This is a test diagram." in result
    # Check that last turn message to provider included the image
    last_user_msg = [m for m in provider.last_messages if m.role == "user"][-1]
    assert isinstance(last_user_msg.content, list)
    assert last_user_msg.content[1]["image_url"]["url"] == data_uri
