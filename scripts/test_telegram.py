#!/usr/bin/env python3
import asyncio
import logging

from app.alerts.telegram import TelegramAlertChannel
from app.core.config import get_settings
from app.core.logging import configure_logging


async def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("test_telegram")
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.error(
            "missing_required_configuration",
            extra={"variables": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]},
        )
        return 2
    channel = TelegramAlertChannel(
        settings.telegram_bot_token,
        settings.telegram_chat_id,
        timeout=settings.request_timeout_seconds,
    )
    try:
        message_id = await channel.send("<b>AI Radar — mensaje de prueba</b>")
    finally:
        await channel.close()
    logger.info("telegram_test_sent", extra={"message_id": message_id})
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
