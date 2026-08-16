#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.alerts.telegram import TelegramAlertChannel
from app.core.config import get_settings
from app.db.session import create_session_factory
from app.digest.service import DigestService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a digest from persisted AI Radar analyses")
    parser.add_argument("--hours", type=int, help="Override the digest lookback window")
    parser.add_argument("--run-id", type=UUID, help="Use events from one pipeline run")
    parser.add_argument("--force", action="store_true", help="Ignore duplicate-send protection")
    parser.add_argument("--dry-run", action="store_true", help="Print without sending or reserving")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    settings = get_settings()
    channel = None
    if not args.dry_run:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            print("Telegram configuration is required to send a digest.")
            return 2
        channel = TelegramAlertChannel(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            timeout=settings.request_timeout_seconds,
        )
    try:
        with create_session_factory(settings.database_url)() as session:
            service = DigestService(
                session,
                channel,
                min_alert_score=settings.digest_min_alert_score,
                max_items=settings.digest_max_items,
                max_actions=settings.digest_max_actions,
            )
            try:
                result = await service.send_digest(
                    hours=args.hours or settings.digest_lookback_hours,
                    run_id=args.run_id,
                    dry_run=args.dry_run,
                    force=args.force,
                )
            except LookupError as error:
                print(error)
                return 1
    finally:
        if channel:
            await channel.close()

    if result.status == "empty":
        print("No relevant events found for digest.")
    elif result.status == "already_sent":
        print("Digest already sent for this period.")
    elif result.status == "dry_run":
        print("DIGEST DRY RUN\nTelegram message NOT sent.\n")
        print("\n\n--- NEXT TELEGRAM MESSAGE ---\n\n".join(result.messages))
    else:
        print(f"Digest sent in {result.telegram_calls} Telegram message(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
