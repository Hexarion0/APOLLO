import asyncio
import html as html_lib
import json
import logging
import re
from typing import Any, Callable, Dict, Optional, Awaitable
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
# Markdown → Telegram HTML converter
# ---------------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """
    Convert a standard Markdown string to Telegram HTML (parse_mode=HTML).

    Handles:
      - Fenced code blocks  ```lang\\ncode```  →  <pre><code class="...">
      - Inline code         `code`             →  <code>
      - Bold                **text** / __text__ →  <b>
      - Italic              *text*             →  <i>
      - Strikethrough       ~~text~~           →  <s>
      - ATX headers         # / ## / ###       →  <b> (Telegram has no headings)
      - Remaining text has HTML-unsafe chars escaped (<, >, &)

    Tables are left as-is (Telegram doesn't support them; the text is still
    readable as plain ASCII art).
    """

    # Step 1 — pull out fenced code blocks so their content isn't touched.
    code_blocks: list[str] = []

    def _replace_fenced(m: re.Match) -> str:
        lang = (m.group(1) or "").strip()
        code = html_lib.escape(m.group(2))
        if lang:
            rendered = f'<pre><code class="language-{html_lib.escape(lang)}">{code}</code></pre>'
        else:
            rendered = f"<pre>{code}</pre>"
        placeholder = f"\x00CB{len(code_blocks)}\x00"
        code_blocks.append(rendered)
        return placeholder

    text = re.sub(r"```(\w*)\n?(.*?)```", _replace_fenced, text, flags=re.DOTALL)

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

    # Step 4 — apply inline formatting (order matters: bold before italic).
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text, flags=re.DOTALL)

    # Italic: *text* (single asterisk only — underscore italic skipped to
    # avoid mangling file names and variable names like my_var).
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


async def _reply_html(message: Any, text: str) -> None:
    """Send a reply with HTML formatting, falling back to plain text on error."""
    try:
        await message.reply_text(_md_to_html(text), parse_mode=ParseMode.HTML)
    except Exception as html_err:
        logger.warning(f"HTML send failed ({html_err}), retrying as plain text.")
        await message.reply_text(text)


async def _send_html(bot: Any, chat_id: int, text: str, **kwargs: Any) -> None:
    """Send a new message with HTML formatting, falling back to plain text."""
    try:
        await bot.send_message(chat_id=chat_id, text=_md_to_html(text), parse_mode=ParseMode.HTML, **kwargs)
    except Exception as html_err:
        logger.warning(f"HTML send failed ({html_err}), retrying as plain text.")
        await bot.send_message(chat_id=chat_id, text=text, **kwargs)


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

    async def start(self) -> None:
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN is missing. Telegram channel will not start.")
            return

        self.app = Application.builder().token(self.bot_token).build()

        self.app.add_handler(CommandHandler("start", self._handle_start))
        self.app.add_handler(CommandHandler("help", self._handle_help))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_incoming_text))
        self.app.add_handler(CallbackQueryHandler(self._handle_callback_query))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        logger.info("Telegram channel started and polling.")

    async def stop(self) -> None:
        if self.app:
            try:
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
            "• Permission policy strictly enforces `auto`, `logged`, and `confirm` tiers.\n"
            "• Destructive actions will present interactive approval buttons.\n"
        )
        await _reply_html(update.message, help_text)

    async def _handle_incoming_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or not update.message or not update.message.text:
            return

        sender_id = update.effective_user.id
        if not self.auth_guard.is_authorized(sender_id):
            logger.warning(f"Access denied: rejected message from unauthorized user ID {sender_id}")
            await update.message.reply_text("⛔ Unauthorized user identity. Access denied.")
            return

        user_text = update.message.text.strip()
        logger.info(f"Received message from owner ({sender_id}): '{user_text}'")

        if self.message_handler_callback:
            # Telegram's typing indicator expires after ~5s, so we keep
            # re-sending it every 4s in a background task for the full duration.
            chat_id = update.effective_chat.id

            async def _keep_typing() -> None:
                try:
                    while True:
                        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
                        await asyncio.sleep(4)
                except asyncio.CancelledError:
                    pass

            typing_task = asyncio.create_task(_keep_typing())
            try:
                response = await self.message_handler_callback(str(sender_id), user_text)
                if response:
                    await _reply_html(update.message, response)
            except Exception as e:
                logger.error(f"Error handling Telegram message: {e}")
                await update.message.reply_text(f"⚠️ Error executing request: {e}")
            finally:
                typing_task.cancel()

    async def send_message(self, recipient_id: str, text: str) -> None:
        if not self.app or not self.app.bot:
            logger.error("Cannot send Telegram message: Bot not initialized.")
            return

        await _send_html(self.app.bot, int(recipient_id), text)

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
