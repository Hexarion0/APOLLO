import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from apollo.providers.nvidia import NvidiaNIMProvider
from apollo.providers.base import ChatMessage

@pytest.mark.asyncio
async def test_nvidia_provider_model_fallback():
    provider = NvidiaNIMProvider(
        api_key="test_key",
        model="invalid/stalled-550b-model",
        fallback_models=["nvidia/nemotron-3-super-120b-a12b"],
    )

    mock_client = AsyncMock()

    # First call (for 550b) raises error, second call (for 120b) succeeds
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "Fallback response success!"
    mock_message.tool_calls = None
    mock_choice.message = mock_message
    mock_choice.finish_reason = "stop"
    mock_response.choices = [mock_choice]

    mock_client.chat.completions.create.side_effect = [
        RuntimeError("Primary 550b model timed out"),
        mock_response,
    ]

    with patch.object(provider, "_client", mock_client):
        resp = await provider.generate_response(messages=[ChatMessage(role="user", content="Hello")])

        assert resp.content == "Fallback response success!"
        assert mock_client.chat.completions.create.call_count == 2
