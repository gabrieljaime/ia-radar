#!/usr/bin/env python3
import asyncio
from datetime import UTC, datetime, timedelta

import httpx

from app.collectors.github_releases import GitHubReleasesCollector
from app.collectors.huggingface_models import HuggingFaceModelsCollector
from app.collectors.web_articles import WebArticlesCollector
from app.collectors.web_changelog import WebChangelogCollector
from app.core.config import get_settings, load_sources
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
    return 0 if all(row["status"] in {"OK", "STALE"} for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
