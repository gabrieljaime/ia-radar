#!/usr/bin/env python3
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.collectors.github_releases import GitHubReleasesCollector
from app.collectors.huggingface_models import HuggingFaceModelsCollector
from app.collectors.web_articles import WebArticlesCollector
from app.collectors.web_changelog import WebChangelogCollector
from app.core.config import SourcesConfig, get_settings, load_sources
from app.db.models import Source, SourceHealth
from app.db.session import create_session_factory
from scripts.check_feeds import check_feed


def source_status(http_status, items: int, latest: datetime | str | None, valid=True) -> str:
    if http_status != 200:
        return "HTTP_ERROR"
    if not valid:
        return "PARSE_ERROR"
    if items == 0:
        return "EMPTY"
    if isinstance(latest, datetime) and latest < datetime.now(UTC) - timedelta(days=30):
        return "STALE"
    return "OK"


async def main() -> int:
    settings = get_settings()
    sources = load_sources(settings.config_dir / "sources.yaml")
    rows = []
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        headers={"User-Agent": "AI-Radar/0.1 source-validation"},
    ) as client:
        rss_results = await asyncio.gather(
            *(
                check_feed(client, source.name, str(source.url))
                for source in sources.rss
                if source.enabled
            )
        )
        for result in rss_results:
            latest = result["latest_entry"]
            latest_date = None if latest == "unknown" else datetime.fromisoformat(str(latest))
            rows.append(
                {
                    "source": result["name"],
                    "type": "rss",
                    "http": result["http_status"],
                    "items": result["entries"],
                    "latest": latest,
                    "status": source_status(
                        result["http_status"],
                        int(result["entries"]),
                        latest_date,
                        bool(result["valid_feed"]),
                    ),
                }
            )
        web = WebChangelogCollector(sources.web_changelog, client)
        await web.collect()
        rows.extend(
            {
                "source": health["source"],
                "type": "web_changelog",
                "http": health["http_status"] or "error",
                "items": health["items"],
                "latest": health["latest"].isoformat() if health["latest"] else "unknown",
                "status": source_status(
                    health["http_status"],
                    health["items"],
                    health["latest"],
                    health["status"] == "OK",
                ),
            }
            for health in web.health
        )
        articles = WebArticlesCollector(sources.web_articles, client)
        await articles.collect()
        rows.extend(
            {
                "source": health["source"],
                "type": "web_articles",
                "http": health["http_status"] or "error",
                "items": health["items"],
                "latest": health["latest"].isoformat() if health["latest"] else "unknown",
                "status": source_status(
                    health["http_status"],
                    health["items"],
                    health["latest"],
                    health["status"] in {"OK", "EMPTY"},
                ),
            }
            for health in articles.health
        )
        for source_type, collector in (
            ("github_releases", GitHubReleasesCollector(sources.github_releases, client)),
            ("huggingface_models", HuggingFaceModelsCollector(sources.huggingface_models, client)),
        ):
            await collector.collect()
            rows.extend(
                {
                    "source": health["source"],
                    "type": source_type,
                    "http": health["http_status"] or "error",
                    "items": health["items"],
                    "latest": health["latest"].isoformat() if health["latest"] else "unknown",
                    "status": health["status"]
                    if health["status"] != "OK"
                    else source_status(health["http_status"], health["items"], health["latest"]),
                }
                for health in collector.health
            )
    print("SOURCE\tTYPE\tHTTP\tITEMS\tLATEST\tSTATUS")
    for row in rows:
        print("{source}\t{type}\t{http}\t{items}\t{latest}\t{status}".format(**row))
    persist_health(settings, sources, rows)
    return 0 if all(row["status"] in {"OK", "STALE"} for row in rows) else 1


def persist_health(settings, sources: SourcesConfig, rows: list[dict[str, object]]) -> None:
    """Store the latest health snapshot per source so the dashboard can read it without
    issuing live HTTP requests on page load."""
    with create_session_factory(settings.database_url)() as session:
        for source_type in (
            "rss",
            "web_changelog",
            "web_articles",
            "github_releases",
            "huggingface_models",
        ):
            for configured in getattr(sources, source_type):
                base_url = str(configured.url)
                source = session.scalar(
                    select(Source).where(
                        Source.source_type == source_type,
                        Source.base_url == base_url,
                    )
                )
                if source is None:
                    source = Source(
                        name=configured.name,
                        source_type=source_type,
                        base_url=base_url,
                        trust_level=configured.trust_level,
                        is_primary=configured.is_primary,
                        requires_primary_verification=(configured.requires_primary_verification),
                        enabled=configured.enabled,
                    )
                    session.add(source)
                else:
                    source.name = configured.name
                    source.trust_level = configured.trust_level
                    source.is_primary = configured.is_primary
                    source.requires_primary_verification = configured.requires_primary_verification
                    source.enabled = configured.enabled
        session.flush()

        for row in rows:
            source = session.scalar(
                select(Source).where(
                    Source.source_type == row["type"], Source.name == row["source"]
                )
            )
            if source is None:
                continue
            latest_raw = row["latest"]
            latest_item_at = (
                datetime.fromisoformat(str(latest_raw))
                if latest_raw and latest_raw != "unknown"
                else None
            )
            health = session.scalar(select(SourceHealth).where(SourceHealth.source_id == source.id))
            if health is None:
                health = SourceHealth(source_id=source.id)
                session.add(health)
            health.status = str(row["status"])
            health.http_status = str(row["http"])
            health.items_found = int(row["items"])
            health.latest_item_at = latest_item_at
            health.error_message = None
            health.checked_at = datetime.now(UTC)
        session.commit()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
