"""Tests for transparent execution progress and <think> reasoning extraction."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from apollo.providers.nvidia import _extract_thinking, _has_visual_content
from apollo.providers.base import LLMResponse
from apollo.channels.telegram import (
    _split_thinking,
    _render_thinking_spoiler,
    _build_status_block,
    _format_arg_preview,
    _tool_emoji,
    _THINK_START,
    _THINK_END,
)
from apollo.gateway import ApolloGateway
from apollo.config import Config


# ─────────────────────────────────────────────
# 1.  _extract_thinking  (provider layer)
# ─────────────────────────────────────────────

def test_extract_thinking_simple():
    text = "<think>I should consider this carefully.</think>Sure, here is the answer."
    clean, thinking = _extract_thinking(text)
    assert "I should consider this carefully." in thinking
    assert "<think>" not in clean
    assert "Sure, here is the answer." in clean


def test_extract_thinking_multi_block():
    text = "<think>Step 1</think>Intermediate.<think>Step 2</think>Final."
    clean, thinking = _extract_thinking(text)
    assert "Step 1" in thinking
    assert "Step 2" in thinking
    assert "Intermediate." in clean
    assert "Final." in clean


def test_extract_thinking_no_block():
    text = "Plain response without any thinking."
    clean, thinking = _extract_thinking(text)
    assert clean == text
    assert thinking is None


def test_extract_thinking_empty_string():
    clean, thinking = _extract_thinking("")
    assert clean == ""
    assert thinking is None


def test_extract_thinking_case_insensitive():
    text = "<THINK>uppercase block</THINK>reply"
    clean, thinking = _extract_thinking(text)
    assert "uppercase block" in thinking
    assert "reply" in clean


# ─────────────────────────────────────────────
# 2.  Sentinel split / spoiler render  (Telegram layer)
# ─────────────────────────────────────────────

def test_split_thinking_with_sentinel():
    thinking_content = "I need to think about this"
    reply_content = "Here is my answer."
    raw = f"{_THINK_START}{thinking_content}{_THINK_END}{reply_content}"
    thinking, reply = _split_thinking(raw)
    assert thinking == thinking_content
    assert reply == reply_content


def test_split_thinking_no_sentinel():
    raw = "Normal response without thinking."
    thinking, reply = _split_thinking(raw)
    assert thinking is None
    assert reply == raw


def test_render_thinking_spoiler_contains_content():
    spoiler = _render_thinking_spoiler("My reasoning here.")
    assert "My reasoning here." in spoiler
    assert "blockquote" in spoiler
    assert "Reasoning" in spoiler


def test_render_thinking_spoiler_escapes_html():
    spoiler = _render_thinking_spoiler("<script>alert(1)</script>")
    assert "<script>" not in spoiler
    assert "&lt;script&gt;" in spoiler


# ─────────────────────────────────────────────
# 3.  Status block builder
# ─────────────────────────────────────────────

def test_build_status_block_running():
    lines = [{"name": "web_search", "status": "running", "args": {"query": "vencord plugins"}}]
    block = _build_status_block(lines)
    assert "Running" in block
    assert "Web Search" in block
    assert "vencord plugins" in block


def test_build_status_block_done():
    lines = [{"name": "read_file", "status": "done", "args": {"file_path": "/etc/hosts"}}]
    block = _build_status_block(lines)
    assert "✅" in block
    assert "/etc/hosts" in block


def test_build_status_block_failed():
    lines = [{"name": "execute_command", "status": "failed", "args": {"command": "rm -rf /"}}]
    block = _build_status_block(lines)
    assert "❌" in block


def test_tool_emoji_known_tools():
    assert _tool_emoji("web_search") == "🌐"
    assert _tool_emoji("execute_command") == "⚙️"
    assert _tool_emoji("read_file") == "📄"
    assert _tool_emoji("analyze_image") == "🔍"


def test_tool_emoji_unknown():
    assert _tool_emoji("some_custom_tool") == "🔧"


def test_format_arg_preview_truncates():
    args = {"query": "x" * 100}
    preview = _format_arg_preview("web_search", args)
    assert len(preview) < 120
    assert "…" in preview


# ─────────────────────────────────────────────
# 4.  Gateway on_tool_status integration
# ─────────────────────────────────────────────

class SimpleProvider:
    """Minimal provider: returns a fixed response with one tool call then a final reply."""
    def __init__(self):
        self.call_count = 0

    async def generate_response(self, messages, tools=None, temperature=0.7, max_tokens=None, on_token=None, model=None):
        from apollo.providers.base import LLMResponse, ToolCall
        self.call_count += 1
        if self.call_count == 1:
            # First turn: request a tool call
            return LLMResponse(
                content=None,
                tool_calls=[ToolCall(id="tc1", name="get_current_time", arguments={})],
            )
        # Second turn: final answer
        return LLMResponse(content="It is currently some time.", tool_calls=[])


@pytest.mark.asyncio
async def test_gateway_on_tool_status_called(tmp_path):
    config = Config()
    config.database_path = tmp_path / "test.db"
    config.audit_log_file = tmp_path / "audit.log"
    config.chat_log_file = tmp_path / "chat.log"
    config.policy_file = tmp_path / "policy.json"
    config.telegram.owner_id = 99

    # Write a minimal policy file
    import json
    config.policy_file.write_text(json.dumps({"version":"1.0","default_tier":"auto","tools":{}}))

    provider = SimpleProvider()
    gateway = ApolloGateway(config=config, provider=provider)

    calls: list = []

    async def capture_status(tool_name: str, status: str, args: dict) -> None:
        calls.append((tool_name, status))

    result = await gateway.process_message(
        sender_id="99",
        user_message="What time is it?",
        on_tool_status=capture_status,
    )

    assert "some time" in result
    # Should have gotten "running" then "done" for get_current_time
    names = [c[0] for c in calls]
    statuses = [c[1] for c in calls]
    assert "get_current_time" in names
    assert "running" in statuses
    assert "done" in statuses


@pytest.mark.asyncio
async def test_gateway_thinking_in_response(tmp_path):
    """Verify that <think> content in LLM output is stripped from final content
    and returned via the sentinel prefix."""
    import json
    from apollo.providers.base import LLMResponse

    class ThinkingProvider:
        async def generate_response(self, messages, tools=None, **kw):
            return LLMResponse(
                content="The answer is 42.",
                thinking="I need to think about what 42 means.",
                tool_calls=[],
            )

    config = Config()
    config.database_path = tmp_path / "test.db"
    config.audit_log_file = tmp_path / "audit.log"
    config.chat_log_file = tmp_path / "chat.log"
    config.policy_file = tmp_path / "policy.json"
    config.telegram.owner_id = 99
    config.policy_file.write_text(json.dumps({"version":"1.0","default_tier":"auto","tools":{}}))

    gateway = ApolloGateway(config=config, provider=ThinkingProvider())
    raw = await gateway.process_message(sender_id="99", user_message="What is the answer?")

    thinking, reply = _split_thinking(raw)
    assert thinking is not None
    assert "I need to think about what 42 means." in thinking
    assert "The answer is 42." in reply


# ─────────────────────────────────────────────
# 5.  _format_streaming_display (Real-time live thinking)
# ─────────────────────────────────────────────

def test_format_streaming_active_thinking():
    """Test real-time thinking formatting while <think> is still generating (unclosed)."""
    from apollo.channels.telegram import _format_streaming_display

    raw_stream = "<think>\nAnalyzing the user's question about quantum physics..."
    html = _format_streaming_display(raw_stream)

    assert "Thinking…" in html
    assert "blockquote" in html
    assert "quantum physics" in html
    assert "▌" in html


def test_format_streaming_completed_thinking_with_answer():
    """Test formatting when thinking has finished and response is streaming."""
    from apollo.channels.telegram import _format_streaming_display

    raw_stream = "<think>Calculated the velocity</think>The velocity is 45 m/s."
    html = _format_streaming_display(raw_stream)

    assert "Reasoning" in html
    assert "Calculated the velocity" in html
    assert "The velocity is 45 m/s." in html
    assert "▌" in html


def test_format_streaming_with_tool_status_and_thinking():
    """Test tool status lines combined with live thinking preview."""
    from apollo.channels.telegram import _format_streaming_display

    tool_lines = [{"name": "web_search", "status": "running", "args": {"query": "weather Tokyo"}}]
    raw_stream = "<think>Searching the live weather feed"
    html = _format_streaming_display(raw_stream, tool_status_lines=tool_lines)

    assert "Web Search" in html
    assert "weather Tokyo" in html
    assert "Thinking…" in html
    assert "live weather feed" in html
