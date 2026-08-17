from __future__ import annotations

import asyncio
import calendar
from datetime import UTC, datetime

import feedparser
import httpx

from app.core.config import RSSSourceConfig
from app.domain.models import Candidate


class RSSCollector:
    def __init__(
        self,
        sources: list[RSSSourceConfig],
        client: httpx.AsyncClient,
        max_concurrency: int = 5,
    ):
        self.sources = [source for source in sources if source.enabled]
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.errors: list[str] = []

    async def collect(self) -> list[Candidate]:
        results = await asyncio.gather(*(self._collect_source(source) for source in self.sources))
        return [candidate for group in results for candidate in group]

    async def _collect_source(self, source: RSSSourceConfig) -> list[Candidate]:
        try:
            async with self.semaphore:
                response = await self.client.get(str(source.url), follow_redirects=True)
                response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError("invalid RSS/Atom response")
            return [self._entry_to_candidate(source, entry) for entry in parsed.entries]
        except (httpx.HTTPError, ValueError) as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            return []

    @staticmethod
    def _entry_to_candidate(source: RSSSourceConfig, entry: object) -> Candidate:
        published = getattr(entry, "published_parsed", None) or getattr(
            entry, "updated_parsed", None
        )
        published_at = (
            datetime.fromtimestamp(calendar.timegm(published), tz=UTC) if published else None
        )
        return Candidate(
            source_name=source.name,
            source_url=str(source.url),
            source_trust=source.trust_level,
            source_is_primary=source.is_primary,
            title=str(getattr(entry, "title", "")).strip(),
            url=str(getattr(entry, "link", "")).strip(),
            summary=str(getattr(entry, "summary", "")).strip(),
            published_at=published_at,
            source_type="rss",
            source_requires_primary_verification=source.requires_primary_verification,
            external_id=getattr(entry, "id", None),
        )
