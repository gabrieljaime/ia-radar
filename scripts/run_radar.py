#!/usr/bin/env python3
import argparse
import asyncio
import json
import logging

import httpx

from app.alerts.dry_run import DryRunAlertChannel
from app.alerts.telegram import TelegramAlertChannel
from app.application.radar_service import RadarService
from app.collectors.rss import RSSCollector
from app.core.config import get_settings, load_sources
from app.core.logging import configure_logging
from app.db.repository import RadarRepository
from app.db.session import create_session_factory
from app.llm.provider import OpenAICompatibleLLMProvider
from app.profiles.loader import load_profiles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI Radar RSS pipeline")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print eligible alerts without sending Telegram"
    )
    return parser.parse_args()


async def main(dry_run: bool = False) -> int:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("run_radar")
    if not settings.llm_api_key and not dry_run:
        logger.error("missing_required_configuration", extra={"variable": "LLM_API_KEY"})
        return 2

    sources = load_sources(settings.config_dir / "sources.yaml")
    profiles = load_profiles(settings.config_dir / "profiles")
    session_factory = create_session_factory(settings.database_url)
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as http_client:
        collector = RSSCollector(sources.rss, http_client)
        llm = None
        if settings.llm_api_key:
            llm = OpenAICompatibleLLMProvider(
                settings.llm_api_key,
                settings.llm_model,
                settings.llm_base_url,
                settings.request_timeout_seconds,
                settings.llm_input_cost_per_million_usd,
                settings.llm_output_cost_per_million_usd,
            )
        else:
            logger.warning("llm_disabled_missing_configuration")
        alert_channel = DryRunAlertChannel() if dry_run else None
        if not dry_run and settings.telegram_bot_token and settings.telegram_chat_id:
            alert_channel = TelegramAlertChannel(
                settings.telegram_bot_token, settings.telegram_chat_id, http_client
            )
        elif not dry_run:
            logger.warning("telegram_disabled_missing_configuration")
        try:
            with session_factory() as session:
                service = RadarService(
                    collector=collector,
                    llm=llm,
                    repository=RadarRepository(session, settings.dedupe_title_threshold),
                    profiles=profiles,
                    alert_channel=alert_channel,
                    max_age_days=settings.max_article_age_days,
                    prefilter_min_score=settings.prefilter_min_score,
                    alert_score_threshold=settings.alert_score_threshold,
                    alert_confidence_threshold=settings.alert_confidence_threshold,
                )
                result = await service.run()
        finally:
            if llm is not None:
                await llm.close()
    print(
        json.dumps(
            {
                "run_id": str(result.run_id),
                "events_analyzed": result.analyzed,
                "llm_calls": result.llm_calls,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated_cost_usd": round(result.estimated_cost_usd, 6),
                "cost_rates_configured": bool(
                    settings.llm_input_cost_per_million_usd
                    or settings.llm_output_cost_per_million_usd
                ),
                "errors": result.errors,
                "dry_run": dry_run,
            }
        )
    )
    return 1 if result.errors else 0


if __name__ == "__main__":
    arguments = parse_args()
    raise SystemExit(asyncio.run(main(arguments.dry_run)))
