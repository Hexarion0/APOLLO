import asyncio
import json
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional

from apollo.audit import AuditLogger
from apollo.auth import SingleOwnerAuthGuard
from apollo.channels.base import BaseChannel
from apollo.chat_log import ChatFileLogger
from apollo.config import Config
from apollo.memory.store import SQLiteMemoryStore
from apollo.policy import PermissionTier, PolicyEngine
from apollo.providers.base import BaseLLMProvider, ChatMessage, ToolCall
from apollo.providers.nvidia import NvidiaNIMProvider
from apollo.providers.router import ComplexityRouter
from apollo.scheduler.cron import BackgroundScheduler
from apollo.tools.builtins import (
    CancelTaskTool,
    ExecuteCommandTool,
    GetCurrentTimeTool,
    GetSystemInfoTool,
    GitDiffTool,
    GitStatusTool,
    ImportMemoryTool,
    ListDirectoryTool,
    ListTasksTool,
    ReadFileTool,
    RecallMemoryTool,
    ScheduleTaskTool,
    StoreMemoryTool,
    WriteFileTool,
)
from apollo.tools.internet import DownloadFileTool, FetchURLTool, GetWeatherTool, WebSearchTool
from apollo.tools.vision import AnalyzeImageTool
from apollo.tools.desktop import TakeScreenshotTool, MediaControlTool, SystemPowerTool
from apollo.tools.reminders import SetReminderTool, ListRemindersTool, CancelReminderTool
from apollo.tools.registry import ToolRegistry

from apollo.persona import DEFAULT_PERSONA_PROMPT, get_proactive_prompt_for_time

logger = logging.getLogger("apollo.gateway")

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
        self.chat_logger = ChatFileLogger(log_path=config.chat_log_file)
        self.memory_store = SQLiteMemoryStore(db_path=config.database_path)

        # Provider initialization (defaults to NVIDIA NIM if not supplied)
        if provider:
            self.provider = provider
        else:
            self.provider = NvidiaNIMProvider(
                api_key=config.provider.api_key,
                base_url=config.provider.base_url,
                model=config.provider.model,
                fallback_models=config.provider.fallback_models,
                vision_model=config.provider.vision_model,
            )

        self.channel = channel

        # Adaptive model router (zero-overhead heuristic tier classifier)
        self.router = ComplexityRouter(config=self.config.provider)

        # Scheduler
        self.scheduler = BackgroundScheduler(
            task_callback=self._handle_scheduled_task,
            memory_store=self.memory_store,
        )

        # Tool Registry
        self.tools = ToolRegistry()
        self._register_default_tools()

    def get_system_prompt(self) -> str:
        """Load personality prompt from persona file if available."""
        if self.config.persona_file and self.config.persona_file.exists():
            try:
                content = self.config.persona_file.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception as e:
                logger.warning(f"Error reading persona file '{self.config.persona_file}': {e}")
        return DEFAULT_PERSONA_PROMPT

    def _register_default_tools(self) -> None:
        """Register built-in system tools."""
        self.tools.register(GetSystemInfoTool())
        self.tools.register(GetCurrentTimeTool())
        self.tools.register(ListDirectoryTool())
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(ExecuteCommandTool())
        self.tools.register(GitStatusTool())
        self.tools.register(GitDiffTool())
        self.tools.register(StoreMemoryTool(memory_store=self.memory_store))
        self.tools.register(RecallMemoryTool(memory_store=self.memory_store))
        self.tools.register(ImportMemoryTool(memory_store=self.memory_store))
        # Scheduler tools
        self.tools.register(ScheduleTaskTool(scheduler=self.scheduler))
        self.tools.register(ListTasksTool(scheduler=self.scheduler))
        self.tools.register(CancelTaskTool(scheduler=self.scheduler))
        # Internet tools
        self.tools.register(WebSearchTool())
        self.tools.register(FetchURLTool())
        self.tools.register(DownloadFileTool())
        self.tools.register(GetWeatherTool())
        # Vision tool
        self.tools.register(AnalyzeImageTool(provider=self.provider))
        # Desktop control tools
        self.tools.register(
            TakeScreenshotTool(
                channel=self.channel,
                owner_id=str(self.config.telegram.owner_id) if self.config.telegram.owner_id else None,
            )
        )
        self.tools.register(MediaControlTool())
        self.tools.register(SystemPowerTool())
        # Reminder tools
        self.tools.register(SetReminderTool(scheduler=self.scheduler))
        self.tools.register(ListRemindersTool(scheduler=self.scheduler))
        self.tools.register(CancelReminderTool(scheduler=self.scheduler))

    async def start(self) -> None:
        """Start APOLLO Gateway engine, channel, and scheduler."""
        logger.info("Initializing APOLLO Gateway...")
        self.scheduler.start()

        # Register proactive persona check-in if enabled
        if self.config.proactive_enabled:
            interval_sec = max(60, self.config.proactive_interval_hours * 3600)
            self.scheduler.add_task(
                task_id="proactive_persona_checkin",
                name="Proactive Persona Check-in",
                prompt="Trigger spontaneous persona check-in",
                interval_seconds=interval_sec,
            )
            logger.info(f"Registered Proactive Persona engine (interval={self.config.proactive_interval_hours}h).")

        if self.channel:
            await self.channel.start()
            if self.config.gateway.startup_notification and self.config.telegram.owner_id:
                try:
                    await self.channel.send_message(
                        recipient_id=str(self.config.telegram.owner_id),
                        text=self.config.gateway.startup_message,
                    )
                    logger.info("Sent startup notification to owner.")
                except Exception as e:
                    logger.warning(f"Failed to send startup notification: {e}")
        logger.info("APOLLO Gateway is online and ready.")

    async def stop(self) -> None:
        """Cleanly shut down APOLLO Gateway services."""
        logger.info("Shutting down APOLLO Gateway...")
        self.scheduler.stop()
        if self.channel:
            await self.channel.stop()
        self.chat_logger.log_session_end()
        logger.info("APOLLO Gateway offline.")

    async def _handle_scheduled_task(self, task_id: str, prompt: str) -> None:
        """Execute autonomous background scheduled task and notify owner."""
        logger.info(f"Executing scheduled task [{task_id}]: {prompt}")
        owner_id = str(self.config.telegram.owner_id)

        if task_id.startswith("reminder_"):
            # One-shot precision timer / reminder
            if self.channel and owner_id != "0":
                await self.channel.send_message(
                    recipient_id=owner_id,
                    text=f"🔔 <b>REMINDER ALERT</b> 🔔\n\n📌 <b>{prompt}</b>",
                )
            # Remove one-shot task so it doesn't repeat
            self.scheduler.remove_task(task_id)
        elif task_id == "proactive_persona_checkin":
            proactive_prompt = get_proactive_prompt_for_time()
            response = await self.process_message(
                sender_id=owner_id,
                user_message=f"[System Event: Initiating spontaneous check-in. Instructions: {proactive_prompt}]",
            )
            if self.channel and owner_id != "0":
                await self.channel.send_message(recipient_id=owner_id, text=response)
        else:
            response = await self.process_message(sender_id=owner_id, user_message=f"[Scheduled Task: {prompt}]")
            if self.channel and owner_id != "0":
                await self.channel.send_message(
                    recipient_id=owner_id,
                    text=f"⏰ *Autonomous Action Result* (`{task_id}`):\n\n{response}",
                )

    def _sanitize_chat_history(self, history: List[Dict[str, Any]]) -> List[ChatMessage]:
        """Sanitize conversation history to merge consecutive same-role messages for LLM API compatibility."""
        sanitized: List[ChatMessage] = []
        for h in history:
            role = h.get("role")
            content = h.get("content")
            if not role or not content:
                continue
            if (
                sanitized
                and sanitized[-1].role == role
                and isinstance(sanitized[-1].content, str)
                and isinstance(content, str)
            ):
                sanitized[-1].content = f"{sanitized[-1].content}\n{content}"
            else:
                sanitized.append(ChatMessage(role=role, content=content))
        return sanitized

    def _compact_context(
        self,
        messages: List[ChatMessage],
        max_total_chars: int = 40000,
    ) -> List[ChatMessage]:
        """Ensure context messages do not exceed maximum character budget,
        preserving the system prompt and the most recent user/assistant turns."""
        if not messages or len(messages) <= 2:
            return messages

        system_msg = messages[0] if messages[0].role == "system" else None
        chat_msgs = messages[1:] if system_msg else messages[:]

        def _msg_chars(msg: ChatMessage) -> int:
            if isinstance(msg.content, str):
                return len(msg.content)
            elif isinstance(msg.content, list):
                total = 0
                for part in msg.content:
                    if isinstance(part, dict) and "text" in part:
                        total += len(part["text"])
                    else:
                        total += 200
                return total
            return 0

        system_len = _msg_chars(system_msg) if system_msg else 0
        budget_for_history = max(100, max_total_chars - system_len)

        total_chat_chars = sum(_msg_chars(m) for m in chat_msgs)
        if total_chat_chars <= budget_for_history:
            return messages

        retained: List[ChatMessage] = []
        accumulated = 0
        for msg in reversed(chat_msgs):
            char_count = _msg_chars(msg)
            if accumulated + char_count > budget_for_history and retained:
                break
            retained.append(msg)
            accumulated += char_count

        retained.reverse()

        result = [system_msg] if system_msg else []
        if len(retained) < len(chat_msgs):
            dropped_count = len(chat_msgs) - len(retained)
            result.append(ChatMessage(role="system", content=f"[Context budget managed: {dropped_count} earlier turns compacted]"))
        result.extend(retained)
        return result

    def cancel_task(self, sender_id: str) -> bool:
        """Cancel an active response/task for sender_id if supported by the channel."""
        if self.channel and hasattr(self.channel, "cancel_active_task"):
            return self.channel.cancel_active_task(sender_id)
        return False

    def _select_model(self, user_message: str):
        """Use ComplexityRouter to pick the best model tier for this message.

        Returns:
            (model_name: str, cleaned_prompt: str)  — prompt is stripped of tier override prefixes.
        """
        from apollo.providers.router import ModelTier
        tier, cleaned = self.router.classify(user_message)
        model = self.router.get_model_for_prompt(user_message)
        return model, cleaned

    async def process_message(
        self,
        sender_id: str,
        user_message: str,
        images: Optional[List[str]] = None,
        max_turns: Optional[int] = None,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
        on_tool_status: Optional[Callable[[str, str, Dict[str, Any]], Awaitable[None]]] = None,
    ) -> str:
        """Process an incoming text or multimodal message from the owner through the LLM tool execution loop.

        Args:
            sender_id: Owner's ID string.
            user_message: The user's text prompt.
            images: Optional list of base64 data URIs for multimodal content.
            max_turns: Maximum agentic loop iterations.
            on_token: Streaming token callback.
            on_tool_status: Called with (tool_name, status, args) where status is
                            "running", "done", "failed", or "denied".
        """
        if max_turns is None:
            max_turns = self.config.gateway.max_turns

        self.auth_guard.validate_or_raise(sender_id)

        channel_name = "telegram" if self.channel else "local"
        log_content = f"[Image Attached]\n{user_message}" if images else user_message
        self.memory_store.add_chat_message(channel=channel_name, sender_id=sender_id, role="user", content=log_content)
        self.chat_logger.log_user(log_content, sender_id=sender_id)

        # Load recent context
        history = self.memory_store.get_recent_chat_history(
            channel=channel_name,
            sender_id=sender_id,
            limit=self.config.gateway.chat_history_limit,
        )

        system_prompt = self.get_system_prompt()
        messages: List[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]
        messages.extend(self._sanitize_chat_history(history))

        # If images are provided in the current turn, format the latest user message with multimodal parts
        if images and messages and messages[-1].role == "user":
            content_parts: List[Dict[str, Any]] = [{"type": "text", "text": user_message}]
            for img_uri in images:
                content_parts.append({"type": "image_url", "image_url": {"url": img_uri}})
            messages[-1].content = content_parts

        # Compact context to protect against token overflow
        messages = self._compact_context(messages)

        tool_schemas = self.tools.get_openai_schemas()

        # Classify prompt complexity and select appropriate model tier
        selected_model, cleaned_user_message = self._select_model(user_message)
        logger.debug(f"Model router selected: {selected_model} for prompt (len={len(user_message)})")

        # Accumulate all thinking blocks across turns
        all_thinking: List[str] = []

        async def _fire_tool_status(tool_name: str, status: str, args: Dict[str, Any]) -> None:
            if on_tool_status:
                try:
                    await on_tool_status(tool_name, status, args)
                except Exception as e:
                    logger.debug(f"on_tool_status callback error: {e}")

        try:
            for turn in range(max_turns):
                logger.debug(f"LLM Loop Turn {turn + 1}/{max_turns}")
                try:
                    response = await self.provider.generate_response(
                        messages=messages,
                        tools=tool_schemas,
                        on_token=on_token,
                        model=selected_model,
                    )
                except TypeError as te:
                    if "on_token" in str(te):
                        response = await self.provider.generate_response(
                            messages=messages,
                            tools=tool_schemas,
                            model=selected_model,
                        )
                    else:
                        raise te

                # Capture any thinking content from this turn
                if response.thinking:
                    all_thinking.append(response.thinking)

                if not response.tool_calls:
                    final_content = response.content or "No response generated."
                    if response.was_fallback and response.model_used:
                        logger.info(f"Primary model unavailable. Response delivered via fallback model '{response.model_used}'.")
                        final_content += f"\n\n_(ℹ️ Responded via fallback model: `{response.model_used}`)_"

                    messages.append(ChatMessage(role="assistant", content=final_content))
                    self.memory_store.add_chat_message(channel=channel_name, sender_id=sender_id, role="assistant", content=final_content)
                    self.chat_logger.log_assistant(final_content)

                    # Prepend aggregated thinking as a sentinel so Telegram layer can render it
                    if all_thinking:
                        combined_thinking = "\n\n---\n\n".join(all_thinking)
                        return f"\x00THINK\x00{combined_thinking}\x00ENDTHINK\x00{final_content}"
                    return final_content

                # LLM requested tool calls
                messages.append(ChatMessage(role="assistant", content=response.content, tool_calls=response.tool_calls))

                for tc in response.tool_calls:
                    tool_name = tc.name
                    arguments = tc.arguments
                    tier = self.policy_engine.get_tier(tool_name)

                    logger.info(f"Tool call requested: {tool_name} (tier: {tier.value}) args={arguments}")
                    self.chat_logger.log_tool_call(tool_name, arguments)

                    # Notify channel: tool is starting
                    await _fire_tool_status(tool_name, "running", arguments)

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
                            await _fire_tool_status(tool_name, "done", arguments)
                        except Exception as e:
                            logger.error(f"Error executing tool '{tool_name}': {e}")
                            result_data = {"error": str(e)}
                            error_msg = str(e)
                            action_status = "FAILED"
                            await _fire_tool_status(tool_name, "failed", arguments)
                    else:
                        await _fire_tool_status(tool_name, "denied", arguments)

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

                    # Log tool execution to chat log
                    self.chat_logger.log_tool_result(
                        tool_name=tool_name,
                        result=result_data or {"status": action_status, "error": error_msg},
                        status=action_status,
                    )

                    # Format tool output for message history
                    tool_output_str = json.dumps(result_data or {"status": action_status, "error": error_msg}, ensure_ascii=False)
                    if len(tool_output_str) > 2500:
                        tool_output_str = tool_output_str[:2500] + "... [truncated for length]"

                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=tool_output_str,
                            tool_call_id=tc.id,
                            name=tool_name,
                        )
                    )

            # If all turns completed with tool executions, perform a final synthesis pass
            try:
                synth_messages = messages + [
                    ChatMessage(
                        role="system",
                        content="Synthesize all tool outputs above and provide your complete, final response to the owner. Do not request any further tools.",
                    )
                ]
                final_synth = await self.provider.generate_response(
                    messages=synth_messages,
                    tools=None,
                    on_token=on_token,
                )
                if final_synth.thinking:
                    all_thinking.append(final_synth.thinking)
                final_content = final_synth.content or "Completed requested actions."
            except Exception as synth_err:
                logger.warning(f"Final synthesis pass encountered error: {synth_err}")
                final_content = "Completed requested actions."

            messages.append(ChatMessage(role="assistant", content=final_content))
            self.memory_store.add_chat_message(channel=channel_name, sender_id=sender_id, role="assistant", content=final_content)
            self.chat_logger.log_assistant(final_content)

            if all_thinking:
                combined_thinking = "\n\n---\n\n".join(all_thinking)
                return f"\x00THINK\x00{combined_thinking}\x00ENDTHINK\x00{final_content}"
            return final_content
        except asyncio.CancelledError:
            logger.info(f"Task processing cancelled for sender {sender_id}")
            self.chat_logger.log_assistant("[Interrupted by user]")
            raise

