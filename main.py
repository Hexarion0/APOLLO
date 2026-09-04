import asyncio
import logging
import signal
import sys
from pathlib import Path

from apollo.channels.telegram import TelegramChannel
from apollo.config import Config
from apollo.gateway import ApolloGateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("apollo.main")

async def main() -> None:
    print(r"""
    █████╗ ██████╗ ██████╗ ██╗     ██╗      ██████╗ 
   ██╔══██╗██╔══██╗██╔══██╗██║     ██║     ██╔═══██╗
   ███████║██████╔╝██║  ██║██║     ██║     ██║   ██║
   ██╔══██║██╔═══╝ ██║  ██║██║     ██║     ██║   ██║
   ██║  ██║██║     ██████╔╝███████╗███████╗╚██████╔╝
   ╚═╝  ╚═╝╚═╝     ╚═════╝ ╚══════╝╚══════╝ ╚═════╝ 
    Adaptive Personal Operator for Learning, Life & Optimization
    """)

    config = Config.load_from_env()

    # Apply logging level from configuration
    log_level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.getLogger().setLevel(log_level)
    logger.info(f"Log level set to {config.logging.level.upper()}.")

    if not config.telegram.owner_id:
        logger.warning("TELEGRAM_OWNER_ID is not configured in .env! Single-owner validation will reject requests until set.")

    if not config.provider.api_key:
        logger.warning("NVIDIA_API_KEY is not configured in .env! LLM API calls may fail.")

    gateway = ApolloGateway(config=config)

    # Initialize Telegram channel if token is provided
    if config.telegram.bot_token:
        telegram_channel = TelegramChannel(
            bot_token=config.telegram.bot_token,
            auth_guard=gateway.auth_guard,
            message_handler_callback=gateway.process_message,
        )
        gateway.channel = telegram_channel

    await gateway.start()

    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Received termination signal. Shutting down APOLLO...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Signal handlers not implemented on some OS/platforms
            pass

    try:
        await stop_event.wait()
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Termination signal received in main loop.")
    finally:
        try:
            await asyncio.wait_for(gateway.stop(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("Gateway shutdown timed out after 10 seconds. Forcing exit.")
        except Exception as e:
            logger.error(f"Error during Gateway shutdown: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("APOLLO Gateway stopped.")
