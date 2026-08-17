from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.core.config import WebArticlesSourceConfig
from app.domain.models import Candidate
from app.pipeline.normalize import canonicalize_url

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ArticleIndexItem:
    title: str
    url: str
    published_at: datetime | None
    summary: str = ""


def _parse_date(value: str) -> datetime | None:
    normalized = " ".join(value.replace(",", " ").split())
    for pattern in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_the_batch(html: str, base_url: str) -> list[ArticleIndexItem]:
    """Parse only explicit article cards from The Batch index."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for article in soup.select("article"):
        heading = article.find(["h2", "h3"])
        links = article.select('a[href*="/the-batch/"]')
        link = next((item for item in reversed(links) if "/tag/" not in item["href"]), None)
        if heading is None or link is None:
            continue
        title = heading.get_text(" ", strip=True)
        if not title:
            continue
        text = article.get_text(" ", strip=True)
        date_match = re.search(
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)\s+\d{1,2},\s+20\d{2}",
            text,
        )
        summary_tag = article.find("p")
        items.append(
            ArticleIndexItem(
                title=title,
                url=canonicalize_url(urljoin(base_url, link["href"])),
                published_at=_parse_date(date_match.group()) if date_match else None,
                summary=summary_tag.get_text(" ", strip=True) if summary_tag else "",
            )
        )
    return items


def parse_kimi(html: str, base_url: str) -> list[ArticleIndexItem]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.post-item"):
        link = card.select_one('h3 a[href^="/blog/posts/"]')
        time_tag = card.find("time", datetime=True)
        if link is None or time_tag is None:
            continue
        try:
            published = datetime.fromisoformat(time_tag["datetime"].replace("Z", "+00:00"))
        except ValueError:
            published = None
        items.append(
            ArticleIndexItem(
                title=link.get_text(" ", strip=True),
                url=canonicalize_url(urljoin(base_url, link["href"])),
                published_at=published,
            )
        )
    return items


PARSERS: dict[str, Callable[[str, str], list[ArticleIndexItem]]] = {
    "the_batch": parse_the_batch,
    "kimi": parse_kimi,
}


class WebArticlesCollector:
    def __init__(
        self,
        sources: list[WebArticlesSourceConfig],
        client: httpx.AsyncClient,
        max_concurrency: int = 3,
    ):
        self.sources = [source for source in sources if source.enabled]
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.errors: list[str] = []
        self.health: list[dict] = []
        self.metrics = {"sources_fetched": 0, "items_found": 0}

    async def collect(self) -> list[Candidate]:
        groups = await asyncio.gather(*(self._collect_source(source) for source in self.sources))
        return [candidate for group in groups for candidate in group]

    async def _collect_source(self, source: WebArticlesSourceConfig) -> list[Candidate]:
        status = None
        try:
            async with self.semaphore:
                response = await self.client.get(str(source.url), follow_redirects=True)
            status = response.status_code
            response.raise_for_status()
            self.metrics["sources_fetched"] += 1
            parser = PARSERS.get(source.parser)
            if parser is None:
                raise ValueError(f"unknown web_articles parser: {source.parser}")
            entries = parser(response.text, str(source.url))
            entries = list({entry.url: entry for entry in entries}.values())
            if not entries:
                logger.warning(
                    "source_parse_empty", extra={"source": source.name, "http_status": status}
                )
                self._record_health(source.name, status, [], "EMPTY")
                self.errors.append(f"{source.name}: source_parse_empty")
                return []
            self.metrics["items_found"] += len(entries)
            self._record_health(source.name, status, entries, "OK")
            return [
                Candidate(
                    source_name=source.name,
                    source_url=str(source.url),
                    source_trust=source.trust_level,
                    source_is_primary=source.is_primary,
                    title=entry.title,
                    url=entry.url,
                    summary=entry.summary,
                    published_at=entry.published_at,
                    source_type="web_articles",
                    source_requires_primary_verification=source.requires_primary_verification,
                    external_id=entry.url,
                )
                for entry in entries
            ]
        except httpx.HTTPError as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._record_health(source.name, status, [], "HTTP_ERROR")
            return []
        except (KeyError, TypeError, ValueError) as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self._record_health(source.name, status, [], "PARSE_ERROR")
            return []

    def _record_health(self, name, status, entries, state) -> None:
        latest = max((entry.published_at for entry in entries if entry.published_at), default=None)
        self.health.append(
            {
                "source": name,
                "http_status": status,
                "items": len(entries),
                "latest": latest,
                "status": state,
            }
        )
