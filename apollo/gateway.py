import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from apollo.audit import AuditLogger
from apollo.auth import SingleOwnerAuthGuard
from apollo.channels.base import BaseChannel
from apollo.config import Config
from apollo.memory.store import SQLiteMemoryStore
from apollo.policy import PermissionTier, PolicyEngine
from apollo.providers.base import BaseLLMProvider, ChatMessage, ToolCall
from apollo.providers.nvidia import NvidiaNIMProvider
from apollo.scheduler.cron import BackgroundScheduler
from apollo.tools.builtins import (
    ExecuteCommandTool,
    GetCurrentTimeTool,
    GetSystemInfoTool,
    ReadFileTool,
    RecallMemoryTool,
    StoreMemoryTool,
    WriteFileTool,
)
from apollo.tools.registry import ToolRegistry

logger = logging.getLogger("apollo.gateway")

SYSTEM_PROMPT = """You are APOLLO ("Adaptive Personal Operator for Learning, Life & Optimization"), a self-hosted personal AI assistant gateway for a single operator.

You are equipped with tools to interact with the host system, manage files, store persistent memories, and schedule background tasks.
When calling tools:
- Always use precise parameters.
- If a tool action is sensitive or destructive, explain your intent clearly.
- Always be helpful, concise, and direct in your responses to your owner.
"""

class ApolloGateway:
    """Core APOLLO Gateway orchestrator."""

    def __init__(
        self,
        config: Config,
        provider: Optional[BaseLLMProvider] = None,
        channel: Optional[BaseChannel] = None,
    ):
        self.config = config
        self.auth_guard = SingleOwnerAuthGuard(owner_id=config.telegram.owner_id)
        self.policy_engine = PolicyEngine(policy_path=config.policy_file)
        self.audit_logger = AuditLogger(log_path=config.audit_log_file)
        self.memory_store = SQLiteMemoryStore(db_path=config.database_path)

        # Provider initialization (defaults to NVIDIA NIM if not supplied)
        if provider:
            self.provider = provider
        else:
            self.provider = NvidiaNIMProvider(
                api_key=config.provider.api_key,
                base_url=config.provider.base_url,
                model=config.provider.model,
            )

        self.channel = channel

        # Tool Registry
        self.tools = ToolRegistry()
        self._register_default_tools()

        # Scheduler
        self.scheduler = BackgroundScheduler(task_callback=self._handle_scheduled_task)

    def _register_default_tools(self) -> None:
        """Register built-in system tools."""
        self.tools.register(GetSystemInfoTool())
        self.tools.register(GetCurrentTimeTool())
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(ExecuteCommandTool())
        self.tools.register(StoreMemoryTool(memory_store=self.memory_store))
        self.tools.register(RecallMemoryTool(memory_store=self.memory_store))

    async def start(self) -> None:
        """Start APOLLO Gateway engine, channel, and scheduler."""
        logger.info("Initializing APOLLO Gateway...")
        self.scheduler.start()
        if self.channel:
            await self.channel.start()
        logger.info("APOLLO Gateway is online and ready.")

    async def stop(self) -> None:
        """Cleanly shut down APOLLO Gateway services."""
        logger.info("Shutting down APOLLO Gateway...")
        self.scheduler.stop()
        if self.channel:
            await self.channel.stop()
        logger.info("APOLLO Gateway offline.")

    async def _handle_scheduled_task(self, task_id: str, prompt: str) -> None:
        """Execute autonomous background scheduled task and notify owner."""
        logger.info(f"Executing scheduled task [{task_id}]: {prompt}")
        owner_id = str(self.config.telegram.owner_id)
        response = await self.process_message(sender_id=owner_id, user_message=f"[Scheduled Task: {prompt}]")
        if self.channel and owner_id != "0":
            await self.channel.send_message(
                recipient_id=owner_id,
                text=f"⏰ *Autonomous Action Result* (`{task_id}`):\n\n{response}",
            )

    async def process_message(self, sender_id: str, user_message: str, max_turns: int = 5) -> str:
        """Process an incoming text message from the owner through the LLM tool execution loop."""
        self.auth_guard.validate_or_raise(sender_id)

        channel_name = "telegram" if self.channel else "local"
        self.memory_store.add_chat_message(channel=channel_name, sender_id=sender_id, role="user", content=user_message)

        # Load recent context
        history = self.memory_store.get_recent_chat_history(channel=channel_name, sender_id=sender_id, limit=10)

        messages: List[ChatMessage] = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
        for h in history:
            messages.append(ChatMessage(role=h["role"], content=h["content"]))

        tool_schemas = self.tools.get_openai_schemas()

        for turn in range(max_turns):
            logger.debug(f"LLM Loop Turn {turn + 1}/{max_turns}")
            response = await self.provider.generate_response(messages=messages, tools=tool_schemas)

            if not response.tool_calls:
                final_content = response.content or "No response generated."
                messages.append(ChatMessage(role="assistant", content=final_content))
                self.memory_store.add_chat_message(channel=channel_name, sender_id=sender_id, role="assistant", content=final_content)
                return final_content

            # LLM requested tool calls
            messages.append(ChatMessage(role="assistant", content=response.content, tool_calls=response.tool_calls))

            for tc in response.tool_calls:
                tool_name = tc.name
                arguments = tc.arguments
                tier = self.policy_engine.get_tier(tool_name)

                logger.info(f"Tool call requested: {tool_name} (tier: {tier.value}) args={arguments}")

                # Evaluate Policy Tier
                should_execute = False
                action_status = "PENDING"
                error_msg = None
                result_data = None

                if tier == PermissionTier.AUTO:
                    should_execute = True
                    action_status = "EXECUTED"
                elif tier == PermissionTier.LOGGED:
                    should_execute = True
                    action_status = "EXECUTED"
                elif tier == PermissionTier.CONFIRM:
                    if self.channel:
                        conf_id = str(uuid.uuid4())[:8]
                        approved = await self.channel.request_confirmation(
                            recipient_id=sender_id,
                            confirmation_id=conf_id,
                            tool_name=tool_name,
                            arguments=arguments,
                        )
                        if approved:
                            should_execute = True
                            action_status = "CONFIRMED"
                        else:
                            should_execute = False
                            action_status = "DENIED"
                            error_msg = "Tool execution rejected by owner approval dialog."
                    else:
                        logger.warning(f"No interactive channel available to confirm tool '{tool_name}'. Rejecting execution.")
                        should_execute = False
                        action_status = "DENIED"
                        error_msg = "No interactive channel available for confirmation."

                # Execute or Reject
                if should_execute:
                    try:
                        result_data = await self.tools.execute_tool(tool_name, **arguments)
                    except Exception as e:
                        logger.error(f"Error executing tool '{tool_name}': {e}")
                        result_data = {"error": str(e)}
                        error_msg = str(e)
                        action_status = "FAILED"

                # Log to audit file if tier is logged or confirm
                if tier in (PermissionTier.LOGGED, PermissionTier.CONFIRM):
                    self.audit_logger.log_action(
                        tool_name=tool_name,
                        arguments=arguments,
                        tier=tier.value,
                        status=action_status,
                        result=result_data,
                        error=error_msg,
                    )

                # Format tool output for message history
                tool_output_str = json.dumps(result_data or {"status": action_status, "error": error_msg}, ensure_ascii=False)
                messages.append(
                    ChatMessage(
                        role="tool",
                        content=tool_output_str,
                        tool_call_id=tc.id,
                        name=tool_name,
                    )
                )

        return "Maximum conversation turns reached without final response."
