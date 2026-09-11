import asyncio
import base64
import html as html_lib
import inspect
import json
import logging
import re
from typing import Any, Callable, Dict, Optional, Awaitable, List
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from apollo.auth import SingleOwnerAuthGuard
from apollo.channels.base import BaseChannel

logger = logging.getLogger("apollo.channels.telegram")


# ---------------------------------------------------------------------------
# Tool status display: emoji map and live-progress helpers
# ---------------------------------------------------------------------------

# Per-tool emoji shown in the live status block
_TOOL_EMOJI: Dict[str, str] = {
    "execute_command":   "⚙️",
    "read_file":         "📄",
    "write_file":        "✏️",
    "list_directory":    "📁",
    "web_search":        "🌐",
    "fetch_url":         "🌐",
    "download_file":     "⬇️",
    "get_weather":       "🌤️",
    "git_status":        "🔀",
    "git_diff":          "🔀",
    "store_memory":      "🧠",
    "recall_memory":     "🧠",
    "import_memory":     "🧠",
    "analyze_image":     "🔍",
    "schedule_task":     "⏰",
    "list_tasks":        "⏰",
    "cancel_task":       "⏰",
    "get_system_info":   "💻",
    "get_current_time":  "🕐",
    "take_screenshot":   "📸",
    "media_control":     "🎵",
    "system_power":      "⚡",
    "set_reminder":      "🔔",
    "list_reminders":    "🔔",
    "cancel_reminder":   "🔔",
}
_DEFAULT_TOOL_EMOJI = "🔧"

def _tool_emoji(tool_name: str) -> str:
    return _TOOL_EMOJI.get(tool_name, _DEFAULT_TOOL_EMOJI)

def _tool_label(tool_name: str) -> str:
    """Human-readable tool label for display."""
    return tool_name.replace("_", " ").title()

def _format_arg_preview(tool_name: str, args: Dict[str, Any]) -> str:
    """Short single-line preview of the most relevant argument for a tool call."""
    preview_keys = {
        "execute_command": "command",
        "read_file": "file_path",
        "write_file": "file_path",
        "list_directory": "path",
        "web_search": "query",
        "fetch_url": "url",
        "download_file": "url",
        "get_weather": "location",
        "git_diff": "path",
        "store_memory": "key",
        "recall_memory": "query",
        "analyze_image": "image_path",
        "schedule_task": "name",
        "cancel_task": "task_id",
        "take_screenshot": "region",
        "media_control": "action",
        "system_power": "action",
        "set_reminder": "text",
        "cancel_reminder": "reminder_id",
    }
    key = preview_keys.get(tool_name)
    if key and key in args:
        val = str(args[key])
        # Trim long values
        if len(val) > 60:
            val = val[:57] + "…"
        return f" — <code>{html_lib.escape(val)}</code>"
    return ""

def _build_status_block(
    tool_lines: List[Dict[str, Any]],
    header: str = "🤔 <i>Processing your request…</i>",
) -> str:
    """Build a formatted HTML status block for the Telegram placeholder."""
    parts = [header]
    for entry in tool_lines:
        status = entry["status"]
        name = entry["name"]
        args = entry["args"]
        emoji = _tool_emoji(name)
        label = _tool_label(name)
        preview = _format_arg_preview(name, args)
        if status == "running":
            line = f"{emoji} <b>Running:</b> {html_lib.escape(label)}{preview}"
        elif status == "done":
            line = f"✅ {html_lib.escape(label)}{preview}"
        elif status == "failed":
            line = f"❌ {html_lib.escape(label)}{preview}"
        elif status == "denied":
            line = f"🚫 {html_lib.escape(label)} <i>(denied)</i>"
        else:
            line = f"{emoji} {html_lib.escape(label)}{preview}"
        parts.append(line)
    return "\n".join(parts)

# Sentinel delimiters used by gateway to carry thinking content
_THINK_START = "\x00THINK\x00"
_THINK_END   = "\x00ENDTHINK\x00"

def _split_thinking(response: str) -> tuple[Optional[str], str]:
    """Extract thinking content and clean reply from a gateway response string."""
    if response.startswith(_THINK_START) and _THINK_END in response:
        end_idx = response.index(_THINK_END)
        thinking = response[len(_THINK_START):end_idx]
        reply = response[end_idx + len(_THINK_END):]
        return thinking.strip() or None, reply
    return None, response

def _render_thinking_spoiler(thinking: str) -> str:
    """Wrap thinking content in a collapsed Telegram spoiler block."""
    escaped = html_lib.escape(thinking)
    return f'<blockquote expandable>💭 <b>Reasoning</b>\n\n{escaped}</blockquote>'


def _format_streaming_display(
    streamed_text: str,
    tool_status_lines: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Format currently streamed content (including live real-time thinking and tool status) for Telegram preview."""
    parts: list[str] = []

    # 1. Tool status progress block
    if tool_status_lines:
        status_block = _build_status_block(tool_status_lines)
        if status_block:
            parts.append(status_block)

    text = streamed_text.strip()
    if not text:
        if not parts:
            return "💭 <i>Thinking…</i> ▌"
        return "\n\n".join(parts) + "\n\n💭 <i>Thinking…</i> ▌"

    # Check if there is a <think> block
    has_think_open = bool(re.search(r"<think>", text, flags=re.IGNORECASE))
    has_think_close = bool(re.search(r"</think>", text, flags=re.IGNORECASE))

    if has_think_open:
        if not has_think_close:
            # Currently actively generating thoughts in real-time
            think_match = re.search(r"<think>(.*)$", text, flags=re.DOTALL | re.IGNORECASE)
            thinking_body = think_match.group(1).strip() if think_match else ""
            escaped_think = html_lib.escape(thinking_body)
            if len(escaped_think) > 3400:
                escaped_think = "…" + escaped_think[-3300:]

            think_html = f"💭 <b>Thinking…</b>\n<blockquote expandable><i>{escaped_think} ▌</i></blockquote>"
            parts.append(think_html)
            return "\n\n".join(parts)
        else:
            # Thinking block finished, now streaming answer
            think_match = re.search(r"<think>(.*?)</think>", text, flags=re.DOTALL | re.IGNORECASE)
            thinking_body = think_match.group(1).strip() if think_match else ""
            after_think = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

            if thinking_body:
                escaped_think = html_lib.escape(thinking_body)
                if len(escaped_think) > 2000:
                    escaped_think = escaped_think[:1900] + "…"
                parts.append(f"<blockquote expandable>💭 <b>Reasoning</b>\n\n<i>{escaped_think}</i></blockquote>")

            if after_think:
                first_chunk = _chunk_text(after_think, max_chunk_size=3000)[0]
                parts.append(_md_to_html(first_chunk) + " ▌")
            else:
                parts.append("<i>Formulating response…</i> ▌")

            return "\n\n".join(parts)
    else:
        # Standard streaming without <think> tag
        first_chunk = _chunk_text(text, max_chunk_size=3000)[0]
        parts.append(_md_to_html(first_chunk) + " ▌")
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Markdown → Telegram HTML converter
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """
    Convert a standard Markdown string to Telegram HTML (parse_mode=HTML).

    Handles:
      - Fenced code blocks  ```lang\\ncode```  →  <pre><code class="language-lang">
      - Inline code         `code`             →  <code>
      - Blockquotes         > quote            →  <blockquote>
      - Spoilers            ||spoiler||        →  <tg-spoiler>
      - Bold                **text** / __text__ →  <b>
      - Italic              *text*             →  <i>
      - Strikethrough       ~~text~~           →  <s>
      - ATX headers         # / ## / ###       →  <b>
      - Remaining text has HTML-unsafe chars escaped (<, >, &)
    """

    # Step 1 — pull out fenced code blocks so their content isn't touched.
    code_blocks: list[str] = []

    def _replace_fenced(m: re.Match) -> str:
        lang = (m.group(1) or "").strip().lower()
        code = html_lib.escape(m.group(2).strip("\r\n"))
        if lang:
            rendered = f'<pre><code class="language-{html_lib.escape(lang)}">{code}</code></pre>'
        else:
            rendered = f"<pre>{code}</pre>"
        placeholder = f"\x00CB{len(code_blocks)}\x00"
        code_blocks.append(rendered)
        return placeholder

    text = re.sub(r"```([a-zA-Z0-9_\+\#-]*)[^\n\r]*\r?\n?(.*?)\r?```", _replace_fenced, text, flags=re.DOTALL)

    # Step 2 — pull out inline code.
    inline_codes: list[str] = []

    def _replace_inline(m: re.Match) -> str:
        code = html_lib.escape(m.group(1))
        placeholder = f"\x00IC{len(inline_codes)}\x00"
        inline_codes.append(f"<code>{code}</code>")
        return placeholder

    text = re.sub(r"`([^`\n]+)`", _replace_inline, text)

    # Step 3 — HTML-escape everything that remains (outside placeholders).
    parts = re.split(r"(\x00(?:CB|IC)\d+\x00)", text)
    escaped: list[str] = []
    for part in parts:
        if re.fullmatch(r"\x00(?:CB|IC)\d+\x00", part):
            escaped.append(part)
        else:
            escaped.append(html_lib.escape(part))
    text = "".join(escaped)

    # Step 4 — apply block and inline formatting.
    # Blockquotes: consecutive lines starting with >
    def _replace_blockquote(m: re.Match) -> str:
        block_content = m.group(0)
        cleaned_lines = [re.sub(r"^>\s?", "", line) for line in block_content.splitlines()]
        return f"<blockquote>{chr(10).join(cleaned_lines)}</blockquote>"

    text = re.sub(r"(?:^>[^\n]*(?:\n|$))+", _replace_blockquote, text, flags=re.MULTILINE)

    # Spoilers: ||spoiler||
    text = re.sub(r"\|\|(.+?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text, flags=re.DOTALL)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # Italic: *text* (single asterisk only)
    text = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text, flags=re.DOTALL)

    # Headers → bold line
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Step 5 — restore placeholders.
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CB{i}\x00", block)
    for i, block in enumerate(inline_codes):
        text = text.replace(f"\x00IC{i}\x00", block)

    return text


def _chunk_text(text: str, max_chunk_size: int = 3500) -> list[str]:
    """
    Split text into chunks that fit within Telegram limits (~3500 chars).
    Maintains balanced code blocks across chunk boundaries.
    """
    if len(text) <= max_chunk_size:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    in_code_block = False
    code_lang = ""

    for line in text.splitlines(keepends=True):
        line_len = len(line)
        if current_len + line_len > max_chunk_size and current:
            if in_code_block:
                current.append("```\n")
            chunks.append("".join(current))
            current = []
            current_len = 0
            if in_code_block:
                current.append(f"```{code_lang}\n")
                current_len += len(current[-1])

        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                in_code_block = False
                code_lang = ""
            else:
                in_code_block = True
                code_lang = stripped[3:].strip()

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("".join(current))

    return chunks


async def _reply_html(message: Any, text: str) -> None:
    """Send a reply with HTML formatting, auto-chunking long messages."""
    chunks = _chunk_text(text)
    for idx, chunk in enumerate(chunks):
        html_chunk = _md_to_html(chunk)
        try:
            if idx == 0:
                await message.reply_text(html_chunk, parse_mode=ParseMode.HTML)
            else:
                await message.chat.send_message(html_chunk, parse_mode=ParseMode.HTML)
        except Exception as html_err:
            logger.warning(f"HTML send failed ({html_err}), retrying chunk as plain text.")
            if idx == 0:
                await message.reply_text(chunk)
            else:
                await message.chat.send_message(chunk)


async def _send_html(bot: Any, chat_id: int, text: str, **kwargs: Any) -> None:
    """Send a new message with HTML formatting, auto-chunking long messages."""
    chunks = _chunk_text(text)
    for chunk in chunks:
        html_chunk = _md_to_html(chunk)
        try:
            await bot.send_message(chat_id=chat_id, text=html_chunk, parse_mode=ParseMode.HTML, **kwargs)
        except Exception as html_err:
            logger.warning(f"HTML send failed ({html_err}), retrying chunk as plain text.")
            await bot.send_message(chat_id=chat_id, text=chunk, **kwargs)


# ---------------------------------------------------------------------------
def _is_pure_interrupt_text(text: str) -> bool:
    """
    Check if a text message is purely an interruption trigger (e.g. 'wait', 'stop', '/stop', '/wait').
    """
    if not text:
        return False
    raw = text.strip().lower()
    if raw in ("/stop", "/wait", "/cancel", "/pause", "/interrupt"):
        return True

    cleaned = re.sub(r"^[^\w/]+|[^\w]+$", "", raw)
    exact_triggers = {
        "wait", "stop", "pause", "halt", "hold on", "cancel",
        "wait please", "please wait", "stop please", "please stop",
        "wait a sec", "wait a second", "wait a minute", "hold on a sec",
        "stop now", "stop it", "cancel that", "hold up", "hold on a moment"
    }
    if cleaned in exact_triggers:
        return True

    if re.fullmatch(r"/?(wait|stop|pause|halt|hold\s+on|cancel)[!.,?\s]*", raw):
        return True

    return False


def _is_continue_text(text: str) -> bool:
    """
    Check if a text message is a continuation request (e.g. '/continue', 'continue', 'resume').
    """
    if not text:
        return False
    raw = text.strip().lower()
    if raw in ("/continue", "/resume", "/proceed", "/go"):
        return True

    cleaned = re.sub(r"^[^\w/]+|[^\w]+$", "", raw)
    continue_triggers = {
        "continue", "resume", "proceed", "go on", "keep going",
        "continue please", "please continue", "resume please", "please resume",
        "carry on", "go ahead"
    }
    if cleaned in continue_triggers:
        return True

    if re.fullmatch(r"/?(continue|resume|proceed|go\s+on|keep\s+going)[!.,?\s]*", raw):
        return True

    return False


# ---------------------------------------------------------------------------
# TelegramChannel
# ---------------------------------------------------------------------------

class TelegramChannel(BaseChannel):
    """Telegram Bot Channel implementation with single-owner verification and inline confirmation dialogs."""

    def __init__(
        self,
        bot_token: str,
        auth_guard: SingleOwnerAuthGuard,
        message_handler_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
    ):
        self.bot_token = bot_token
        self.auth_guard = auth_guard
        self.message_handler_callback = message_handler_callback
        self.app: Optional[Application] = None
        self.pending_confirmations: Dict[str, asyncio.Future[bool]] = {}
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.active_placeholders: Dict[str, Any] = {}
        self.active_typing_tasks: Dict[str, asyncio.Task] = {}
        self.last_interrupted_drafts: Dict[str, str] = {}

    def cancel_active_task(self, sender_id: str | int) -> bool:
        """Cancel any ongoing processing task for the given sender ID."""
        sender_key = str(sender_id)
        task = self.active_tasks.get(sender_key)
        cancelled = False
        if task and not task.done():
            task.cancel()
            cancelled = True

        typing_task = self.active_typing_tasks.pop(sender_key, None)
        if typing_task and not typing_task.done():
            typing_task.cancel()

        for conf_id, fut in list(self.pending_confirmations.items()):
            if not fut.done():
                fut.cancel()

        return cancelled

    async def start(self) -> None:
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN is missing. Telegram channel will not start.")
            return

        self.app = Application.builder().token(self.bot_token).build()

        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(CommandHandler("stop", self._handle_interrupt_command))
        self.app.add_handler(CommandHandler("wait", self._handle_interrupt_command))
        self.app.add_handler(CommandHandler("cancel", self._handle_interrupt_command))
        self.app.add_handler(CommandHandler("pause", self._handle_interrupt_command))
        self.app.add_handler(CommandHandler("continue", self._handle_continue_command))
        self.app.add_handler(CommandHandler("resume", self._handle_continue_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_incoming_text))
        self.app.add_handler(MessageHandler(filters.PHOTO, self._handle_incoming_photo))
        self.app.add_handler(MessageHandler(filters.Document.IMAGE, self._handle_incoming_document_image))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram channel started and polling.")

    async def stop(self) -> None:
        if self.app:
            try:
                for sender_key in list(self.active_tasks.keys()):
                    self.cancel_active_task(sender_key)

                if self.app.updater and self.app.updater.running:
                    logger.info("Stopping Telegram updater...")
                    try:
                        await asyncio.wait_for(self.app.updater.stop(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.warning("Telegram updater stop timed out. Forcing shutdown.")

                if self.app.running:
                    logger.info("Stopping Telegram application...")
                    try:
                        await asyncio.wait_for(self.app.stop(), timeout=3.0)
                    except asyncio.TimeoutError:
                        logger.warning("Telegram application stop timed out.")

                logger.info("Shutting down Telegram application...")
                try:
                    await asyncio.wait_for(self.app.shutdown(), timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning("Telegram application shutdown timed out.")
            except Exception as e:
                logger.error(f"Error during Telegram channel stop: {e}")
            finally:
                self.app = None
                logger.info("Telegram channel stopped.")

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        sender_id = update.effective_user.id if update.effective_user else 0
        if not self.auth_guard.is_authorized(sender_id):
            logger.warning(f"Rejecting unauthorized /start from user ID {sender_id}")
            return

        await update.message.reply_text(
            "🚀 APOLLO Gateway online. Ready for single-owner operations."
        )

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        sender_id = update.effective_user.id if update.effective_user else 0
        if not self.auth_guard.is_authorized(sender_id):
            return

        help_text = (
            "🤖 **APOLLO Commands & Capabilities**\n\n"
            "Just chat naturally to ask questions or trigger actions.\n"
            "• `/stop` or `/wait` (or say **wait** / **stop**): Interrupt active responses.\n"
            "• `/continue` or `/resume` (or say **continue**): Resume an interrupted response.\n"
            "• **Steer-in-Flight**: Send a revised instruction while APOLLO is responding to immediately pivot!\n"
            "• Permission policy strictly enforces `auto`, `logged`, and `confirm` tiers.\n"
            "• Destructive actions will present interactive approval buttons.\n"
        )
        await _reply_html(update.message, help_text)

    async def _handle_interrupt_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            return

        was_active = self.cancel_active_task(sender_id)
        if was_active:
            logger.info(f"Interrupted active task for sender {sender_id} via command")
            await update.message.reply_text("🛑 <b>Interrupted.</b> Active response stopped.", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("ℹ️ No active task or generation is currently running.")

    async def _handle_continue_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message:
            return
        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            return

        sender_key = str(sender_id)
        active_task = self.active_tasks.get(sender_key)
        if active_task and not active_task.done():
            await update.message.reply_text("⏳ Already generating a response. Send /stop or **wait** to interrupt.")
            return

        last_draft = self.last_interrupted_drafts.get(sender_key)
        if last_draft:
            continuation_prompt = (
                f"Please continue and complete your previous response right where you were interrupted. "
                f"Here is what you had generated so far before being stopped:\n\n{last_draft}"
            )
        else:
            continuation_prompt = "Please continue your previous response from where you left off."

        if self.message_handler_callback:
            task = asyncio.create_task(
                self._execute_message_flow(update=update, context=context, sender_id=sender_id, user_text=continuation_prompt)
            )
            self.active_tasks[sender_key] = task

    async def _handle_incoming_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message or not update.message.text:
            return

        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            logger.warning(f"Access denied: rejected message from unauthorized user ID {sender_id}")
            await update.message.reply_text("⛔ Unauthorized user identity. Access denied.")
            return

        user_text = update.message.text.strip()
        sender_key = str(sender_id)
        logger.info(f"Received message from owner ({sender_id}): '{user_text}'")

        existing_task = self.active_tasks.get(sender_key)
        has_active = existing_task is not None and not existing_task.done()

        # 1. Pure Interrupt check (e.g. "wait", "stop", "/stop", "hold on")
        if _is_pure_interrupt_text(user_text):
            if has_active:
                logger.info(f"Interrupted active task for sender {sender_id} upon pure interrupt '{user_text}'")
                self.cancel_active_task(sender_id)
                await update.message.reply_text("🛑 <b>Interrupted.</b> Response generation stopped.", parse_mode=ParseMode.HTML)
                return
            else:
                if user_text.startswith("/") or user_text.lower() in ("stop", "cancel"):
                    await update.message.reply_text("ℹ️ No active task or generation is currently running.")
                    return
                elif user_text.lower() in ("wait", "hold on", "pause", "please wait"):
                    await update.message.reply_text("⏸️ Standing by. Let me know what you need!")
                    return

        # 2. Continuation check (e.g. "continue", "resume", "/continue")
        if _is_continue_text(user_text):
            if has_active:
                await update.message.reply_text("⏳ Already generating a response. Send /stop or **wait** to interrupt.")
                return

            last_draft = self.last_interrupted_drafts.get(sender_key)
            if last_draft:
                continuation_prompt = (
                    f"Please continue and complete your previous response right where you were interrupted. "
                    f"Here is what you had generated so far before being stopped:\n\n{last_draft}"
                )
            else:
                continuation_prompt = "Please continue your previous response from where you left off."

            if self.message_handler_callback:
                task = asyncio.create_task(
                    self._execute_message_flow(update=update, context=context, sender_id=sender_id, user_text=continuation_prompt)
                )
                self.active_tasks[sender_key] = task
            return

        # 3. Steer-in-Flight check: If a new prompt/revision is sent while generation is active
        if has_active:
            logger.info(f"Steer-in-flight: Cancelling active task for sender {sender_id} to pivot to: '{user_text}'")
            self.cancel_active_task(sender_id)
            await asyncio.sleep(0.05)

        # 4. Launch message processing
        if self.message_handler_callback:
            task = asyncio.create_task(
                self._execute_message_flow(update=update, context=context, sender_id=sender_id, user_text=user_text)
            )
            self.active_tasks[sender_key] = task

    async def _handle_incoming_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message or not update.message.photo:
            return

        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            logger.warning(f"Access denied: rejected photo from unauthorized user ID {sender_id}")
            await update.message.reply_text("⛔ Unauthorized user identity. Access denied.")
            return

        sender_key = str(sender_id)
        caption = (update.message.caption or "").strip()
        user_prompt = caption if caption else "Please analyze and describe this image in detail. Extract any visible text/code, explain diagrams/UI elements, and highlight key details."
        logger.info(f"Received photo from owner ({sender_id}) with caption: '{caption}'")

        existing_task = self.active_tasks.get(sender_key)
        has_active = existing_task is not None and not existing_task.done()
        if has_active:
            logger.info(f"Steer-in-flight: Cancelling active task for sender {sender_id} to pivot to photo")
            self.cancel_active_task(sender_id)
            await asyncio.sleep(0.05)

        try:
            # Get largest resolution photo
            photo = update.message.photo[-1]
            tg_file = await context.bot.get_file(photo.file_id)
            photo_bytes = await tg_file.download_as_bytearray()
            b64_str = base64.b64encode(photo_bytes).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{b64_str}"

            if self.message_handler_callback:
                task = asyncio.create_task(
                    self._execute_message_flow(
                        update=update,
                        context=context,
                        sender_id=sender_id,
                        user_text=user_prompt,
                        images=[data_uri],
                    )
                )
                self.active_tasks[sender_key] = task
        except Exception as e:
            logger.error(f"Failed to process incoming photo: {e}")
            await update.message.reply_text(f"⚠️ Error downloading/processing image: {e}")

    async def _handle_incoming_document_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message or not update.message.document:
            return

        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            logger.warning(f"Access denied: rejected document image from unauthorized user ID {sender_id}")
            await update.message.reply_text("⛔ Unauthorized user identity. Access denied.")
            return

        doc = update.message.document
        mime_type = doc.mime_type or "image/png"
        if not mime_type.startswith("image/"):
            return

        sender_key = str(sender_id)
        caption = (update.message.caption or "").strip()
        user_prompt = caption if caption else "Please analyze and describe this image in detail. Extract any visible text/code, explain diagrams/UI elements, and highlight key details."
        logger.info(f"Received document image ({mime_type}) from owner ({sender_id}) with caption: '{caption}'")

        existing_task = self.active_tasks.get(sender_key)
        has_active = existing_task is not None and not existing_task.done()
        if has_active:
            logger.info(f"Steer-in-flight: Cancelling active task for sender {sender_id} to pivot to document image")
            self.cancel_active_task(sender_id)
            await asyncio.sleep(0.05)

        try:
            tg_file = await context.bot.get_file(doc.file_id)
            file_bytes = await tg_file.download_as_bytearray()
            b64_str = base64.b64encode(file_bytes).decode("utf-8")
            data_uri = f"data:{mime_type};base64,{b64_str}"

            if self.message_handler_callback:
                task = asyncio.create_task(
                    self._execute_message_flow(
                        update=update,
                        context=context,
                        sender_id=sender_id,
                        user_text=user_prompt,
                        images=[data_uri],
                    )
                )
                self.active_tasks[sender_key] = task
        except Exception as e:
            logger.error(f"Failed to process incoming document image: {e}")
            await update.message.reply_text(f"⚠️ Error downloading/processing image document: {e}")

    async def _execute_message_flow(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        sender_id: int,
        user_text: str,
        images: Optional[List[str]] = None,
    ) -> None:
        sender_key = str(sender_id)
        chat_id = update.effective_chat.id

        async def _keep_typing() -> None:
            try:
                while True:
                    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                    await asyncio.sleep(4)
            except asyncio.CancelledError:
                pass

        typing_task = asyncio.create_task(_keep_typing())
        self.active_typing_tasks[sender_key] = typing_task

        placeholder = None
        try:
            placeholder = await update.message.reply_text("<i>Thinking...</i>", parse_mode=ParseMode.HTML)
        except Exception:
            try:
                placeholder = await update.message.reply_text("Thinking...")
            except Exception:
                pass
        self.active_placeholders[sender_key] = placeholder

        streamed_tokens: list[str] = []
        last_edit_time = 0.0

        async def _on_token(token: str) -> None:
            nonlocal last_edit_time
            streamed_tokens.append(token)
            if not placeholder:
                return
            now = asyncio.get_event_loop().time()
            if now - last_edit_time >= 0.9:
                current_text = "".join(streamed_tokens).strip()
                if current_text:
                    last_edit_time = now
                    display_html = _format_streaming_display(current_text, tool_status_lines)
                    try:
                        await placeholder.edit_text(display_html, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass

        # Live-progress tracking: list of {name, status, args} dicts
        tool_status_lines: List[Dict[str, Any]] = []
        last_status_edit: float = 0.0

        async def _on_tool_status(tool_name: str, status: str, args: Dict[str, Any]) -> None:
            nonlocal last_status_edit
            # Update or append status line for this tool
            found = False
            for entry in tool_status_lines:
                if entry["name"] == tool_name and entry["status"] == "running":
                    entry["status"] = status
                    found = True
                    break
            if not found:
                tool_status_lines.append({"name": tool_name, "status": status, "args": args})

            if not placeholder:
                return
            # Throttle edits to avoid Telegram rate limits (max every 0.8s)
            now = asyncio.get_event_loop().time()
            if now - last_status_edit >= 0.8:
                last_status_edit = now
                current_text = "".join(streamed_tokens).strip()
                display_html = _format_streaming_display(current_text, tool_status_lines)
                try:
                    await placeholder.edit_text(display_html, parse_mode=ParseMode.HTML)
                except Exception:
                    pass

        try:
            sig = inspect.signature(self.message_handler_callback)
            call_kwargs: Dict[str, Any] = {}
            if "on_token" in sig.parameters:
                call_kwargs["on_token"] = _on_token
            if "images" in sig.parameters and images:
                call_kwargs["images"] = images
            if "on_tool_status" in sig.parameters:
                call_kwargs["on_tool_status"] = _on_tool_status

            raw_response = await self.message_handler_callback(str(sender_id), user_text, **call_kwargs)

            # --- Parse thinking sentinel and build final message ---
            thinking, response = _split_thinking(raw_response or "")
            spoiler_html = _render_thinking_spoiler(thinking) if thinking else None

            if response and placeholder:
                chunks = _chunk_text(response)
                first_chunk_html = _md_to_html(chunks[0]) if chunks else ""

                if spoiler_html:
                    combined_html = f"{spoiler_html}\n\n{first_chunk_html}".strip()
                    if len(combined_html) <= 4000:
                        # Unified single-bubble rendering with expandable reasoning blockquote
                        try:
                            await placeholder.edit_text(combined_html, parse_mode=ParseMode.HTML)
                        except Exception:
                            try:
                                await placeholder.edit_text(chunks[0])
                            except Exception:
                                pass
                    else:
                        # Exceeds single message limit: send thinking first, then reply
                        try:
                            await update.message.chat.send_message(spoiler_html, parse_mode=ParseMode.HTML)
                        except Exception:
                            pass
                        try:
                            await placeholder.edit_text(first_chunk_html, parse_mode=ParseMode.HTML)
                        except Exception:
                            try:
                                await placeholder.edit_text(chunks[0])
                            except Exception:
                                pass
                else:
                    try:
                        await placeholder.edit_text(first_chunk_html, parse_mode=ParseMode.HTML)
                    except Exception:
                        try:
                            await placeholder.edit_text(chunks[0])
                        except Exception:
                            pass

                for follow_up in chunks[1:]:
                    html_chunk = _md_to_html(follow_up)
                    try:
                        await update.message.chat.send_message(html_chunk, parse_mode=ParseMode.HTML)
                    except Exception:
                        await update.message.chat.send_message(follow_up)

            elif response:
                if spoiler_html:
                    combined_html = f"{spoiler_html}\n\n{_md_to_html(response)}".strip()
                    if len(combined_html) <= 4000:
                        await update.message.reply_text(combined_html, parse_mode=ParseMode.HTML)
                    else:
                        await update.message.reply_text(spoiler_html, parse_mode=ParseMode.HTML)
                        await _reply_html(update.message, response)
                else:
                    await _reply_html(update.message, response)

            elif placeholder:
                if spoiler_html:
                    try:
                        await placeholder.edit_text(spoiler_html, parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                else:
                    try:
                        await placeholder.delete()
                    except Exception:
                        pass

        except asyncio.CancelledError:
            logger.info(f"Task for sender {sender_id} cancelled.")
            typing_task.cancel()
            draft = "".join(streamed_tokens).strip()
            if draft:
                self.last_interrupted_drafts[sender_key] = draft
                if placeholder:
                    first_chunk = _chunk_text(draft)[0]
                    try:
                        await placeholder.edit_text(
                            _md_to_html(first_chunk) + "\n\n⏸️ <i>[Interrupted draft saved • Send /continue to resume]</i>",
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        try:
                            await placeholder.edit_text(
                                first_chunk + "\n\n[Interrupted draft saved • Send /continue to resume]"
                            )
                        except Exception:
                            pass
            else:
                if placeholder:
                    try:
                        await placeholder.edit_text("⏸️ <i>Generation interrupted.</i>", parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
            raise
        except Exception as e:
            logger.error(f"Error handling Telegram message: {e}")
            error_text = f"⚠️ Error executing request: {e}"
            if placeholder:
                try:
                    await placeholder.edit_text(error_text)
                except Exception:
                    await update.message.reply_text(error_text)
            else:
                await update.message.reply_text(error_text)
        finally:
            typing_task.cancel()
            self.active_typing_tasks.pop(sender_key, None)
            self.active_placeholders.pop(sender_key, None)
            self.active_tasks.pop(sender_key, None)


    async def send_message(self, recipient_id: str, text: str) -> None:
        if not self.app or not self.app.bot:
            logger.error("Cannot send Telegram message: Bot not initialized.")
            return

        await _send_html(self.app.bot, int(recipient_id), text)

    async def send_photo(self, recipient_id: str, photo_path: str, caption: Optional[str] = None) -> None:
        """Send a photo to the Telegram owner directly."""
        if not self.app or not self.app.bot:
            logger.error("Cannot send Telegram photo: Bot not initialized.")
            return

        try:
            path_obj = Path(photo_path).expanduser().resolve()
            if not path_obj.exists() or not path_obj.is_file():
                logger.error(f"Cannot send photo: File does not exist at {path_obj}")
                return

            with open(path_obj, "rb") as photo_file:
                await self.app.bot.send_photo(
                    chat_id=int(recipient_id),
                    photo=photo_file,
                    caption=caption or "",
                )
            logger.info(f"Sent photo {path_obj} to owner {recipient_id}")
        except Exception as e:
            logger.error(f"Failed to send Telegram photo: {e}")

    async def request_confirmation(
        self,
        recipient_id: str,
        confirmation_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> bool:
        """Send interactive Telegram buttons for explicit owner approval."""
        if not self.app or not self.app.bot:
            logger.error("Cannot request confirmation: Bot not initialized.")
            return False

        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self.pending_confirmations[confirmation_id] = future

        args_str = html_lib.escape(json.dumps(arguments, indent=2, ensure_ascii=False))
        message_text = (
            f"⚠️ <b>APPROVAL REQUIRED</b>\n\n"
            f"Tool: <code>{html_lib.escape(tool_name)}</code>\n"
            f"Tier: <code>confirm</code>\n"
            f"Arguments:\n<pre>{args_str}</pre>\n\n"
            f"Do you authorize execution of this action?"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"confirm:{confirmation_id}:approve"),
                InlineKeyboardButton("❌ Deny", callback_data=f"confirm:{confirmation_id}:deny"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await self.app.bot.send_message(
                chat_id=int(recipient_id),
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram confirmation request: {e}")
            self.pending_confirmations.pop(confirmation_id, None)
            return False

        try:
            # Wait for user approval click or timeout (5 minutes)
            approved = await asyncio.wait_for(future, timeout=300.0)
            return approved
        except asyncio.TimeoutError:
            logger.warning(f"Confirmation request {confirmation_id} timed out after 300s.")
            return False
        finally:
            self.pending_confirmations.pop(confirmation_id, None)

    async def _handle_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not update.effective_user:
            return

        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            await query.answer("Unauthorized identity.", show_alert=True)
            return

        data = query.data or ""
        parts = data.split(":")
        if len(parts) == 3 and parts[0] == "confirm":
            conf_id = parts[1]
            action = parts[2]

            try:
                await query.answer()
            except Exception:
                pass

            future = self.pending_confirmations.get(conf_id)
            if future and not future.done():
                approved = (action == "approve")
                future.set_result(approved)
                status_str = "✅ APPROVED BY OWNER" if approved else "❌ DENIED BY OWNER"
                logger.info(f"Confirmation {conf_id} set result: {approved}")

                try:
                    orig_text = query.message.text if query.message else ""
                    escaped_orig = html_lib.escape(orig_text)
                    await query.edit_message_text(
                        text=f"{escaped_orig}\n\n<b>STATUS: {status_str}</b>",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e:
                    logger.warning(f"Could not update confirmation message UI: {e}")
            else:
                try:
                    await query.answer("Confirmation request expired or already processed.", show_alert=True)
                except Exception:
                    pass
