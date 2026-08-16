#!/usr/bin/env python3
import asyncio
import calendar
import time
from datetime import UTC, datetime

import feedparser
import httpx

from app.core.config import get_settings, load_sources


def latest_entry_date(entries: list[object]) -> str:
    dates = []
    for entry in entries:
        parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if parsed:
            dates.append(datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC))
    return max(dates).isoformat() if dates else "unknown"


async def check_feed(client: httpx.AsyncClient, name: str, url: str) -> dict[str, object]:
    started = time.perf_counter()
    result: dict[str, object] = {
        "name": name,
        "url": url,
        "http_status": "error",
        "valid_feed": False,
        "entries": 0,
        "latest_entry": "unknown",
        "latency_ms": 0,
        "error": None,
    }
    try:
        response = await client.get(url, follow_redirects=True)
        result["http_status"] = response.status_code
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        result["entries"] = len(parsed.entries)
        result["valid_feed"] = bool(parsed.entries) and not bool(parsed.bozo)
        result["latest_entry"] = latest_entry_date(parsed.entries)
        if parsed.bozo:
            result["error"] = f"feed_parse_error: {type(parsed.bozo_exception).__name__}"
        elif not parsed.entries:
            result["error"] = "feed_has_no_entries"
    except httpx.HTTPError as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        result["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return result


async def main() -> int:
    settings = get_settings()
    sources = load_sources(settings.config_dir / "sources.yaml")
    async with httpx.AsyncClient(
        timeout=settings.request_timeout_seconds,
        headers={"User-Agent": "AI-Radar/0.1 feed-validation"},
    ) as client:
        results = await asyncio.gather(
            *(
                check_feed(client, source.name, str(source.url))
                for source in sources.rss
                if source.enabled
            )
        )
    print("NAME\tHTTP\tVALID\tENTRIES\tLATEST\tLATENCY_MS\tURL\tERROR")
    for result in results:
        print(
            "{name}\t{http_status}\t{valid_feed}\t{entries}\t{latest_entry}\t"
            "{latency_ms}\t{url}\t{error}".format(**result)
        )
    return 0 if all(result["valid_feed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
