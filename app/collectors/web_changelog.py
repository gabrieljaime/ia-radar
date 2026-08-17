from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.core.config import WebChangelogSourceConfig
from app.domain.models import Candidate

logger = logging.getLogger(__name__)


def _date(value: str) -> datetime | None:
    normalized = " ".join(value.replace(",", " ").split())
    for pattern in ("%B %d %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _title(text: str, limit: int = 180) -> str:
    first = re.split(r"(?<=[.!?])\s+", " ".join(text.split()), maxsplit=1)[0]
    return first[:limit].strip(" :-")


def parse_gemini(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for heading in soup.select("h2[id]"):
        published = _date(heading.get_text(" ", strip=True))
        node = heading.find_next_sibling()
        entry_index = 0
        while node and not (isinstance(node, Tag) and node.name == "h2"):
            if isinstance(node, Tag) and node.name == "ul":
                for entry in node.find_all("li", recursive=False):
                    entry_index += 1
                    summary = entry.get_text(" ", strip=True)
                    strong = entry.find("strong")
                    title = strong.get_text(" ", strip=True) if strong else _title(summary)
                    link = entry.find("a", href=True)
                    url = (
                        urljoin(base_url, link["href"])
                        if link
                        else f"{base_url}#{heading['id']}-{entry_index}"
                    )
                    items.append(
                        {"title": title, "url": url, "summary": summary, "published_at": published}
                    )
            node = node.find_next_sibling() if isinstance(node, Tag) else None
    return items


def parse_mistral(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for article in soup.select("article"):
        # The live page wraps the whole changelog in one outer <article> and places each
        # dated entry in a nested <article> immediately after its heading.
        if article.find("article") is not None:
            continue
        heading = article.find_previous("h2")
        if heading is None:
            continue
        year_heading = heading.find_previous("h3")
        year_match = re.search(
            r"\b(\d{2})\b", year_heading.get_text(" ", strip=True) if year_heading else ""
        )
        year = 2000 + int(year_match.group(1)) if year_match else datetime.now(UTC).year
        published = _date(f"{heading.get_text(' ', strip=True)} {year}")
        summary = article.get_text(" ", strip=True)
        if not summary:
            continue
        identifier = published.strftime("%Y-%m-%d") if published else str(len(items) + 1)
        items.append(
            {
                "title": _title(summary),
                "url": f"{base_url}#{identifier}",
                "summary": summary,
                "published_at": published,
            }
        )
    return items


def parse_xai(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    page_date_match = re.search(r'"dateModified":"(20\d{2}-\d{2}-\d{2})', html)
    page_date = _date(page_date_match.group(1)) if page_date_match else None
    items = []
    for heading in soup.select("h3[id]"):
        month_heading = heading.find_previous("h2")
        month_text = month_heading.get_text(" ", strip=True) if month_heading else ""
        year_match = re.search(r"20\d{2}", month_text)
        year = (
            int(year_match.group())
            if year_match
            else (page_date.year if page_date else datetime.now(UTC).year)
        )
        month = re.sub(r"\s+20\d{2}", "", month_text)
        published = (
            page_date
            if page_date and month == page_date.strftime("%B")
            else _date(f"{month} 1 {year}")
        )
        container = heading.parent
        description = container.find_next_sibling() if isinstance(container, Tag) else None
        summary = description.get_text(" ", strip=True) if isinstance(description, Tag) else ""
        if not summary:
            continue
        items.append(
            {
                "title": heading.get_text(" ", strip=True),
                "url": f"{base_url}#{heading['id']}",
                "summary": summary,
                "published_at": published,
            }
        )
    return items


def parse_meta(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    for link in soup.select('a[href*="/blog/"]'):
        url = urljoin(base_url, link.get("href"))
        title = link.get_text(" ", strip=True)
        if url in seen or len(title) < 10:
            continue
        card = link.find_parent(
            lambda tag: tag.name == "div" and re.search(r"20\d{2}", tag.get_text(" ", strip=True))
        )
        text = card.get_text(" ", strip=True) if card else title
        date_match = re.search(
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+20\d{2}", text
        )
        if not date_match:
            continue
        seen.add(url)
        items.append(
            {"title": title, "url": url, "summary": text, "published_at": _date(date_match.group())}
        )
    return items


def parse_anthropic(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    for time_tag in soup.select("time"):
        link = time_tag.find_parent("a", href=True)
        if link is None:
            continue
        url = urljoin(base_url, link["href"])
        if url in seen:
            continue
        seen.add(url)
        text = link.get_text(" ", strip=True)
        title_tag = link.find(["h2", "h3", "h4"])
        title = title_tag.get_text(" ", strip=True) if title_tag else _title(text)
        items.append(
            {
                "title": title,
                "url": url,
                "summary": text,
                "published_at": _date(time_tag.get_text(" ", strip=True)),
            }
        )
    return items


PARSERS: dict[str, Callable[[str, str], list[dict]]] = {
    "gemini": parse_gemini,
    "mistral": parse_mistral,
    "xai": parse_xai,
    "meta": parse_meta,
    "anthropic": parse_anthropic,
}


class WebChangelogCollector:
    def __init__(
        self,
        sources: list[WebChangelogSourceConfig],
        client: httpx.AsyncClient,
        max_concurrency: int = 3,
    ):
        self.sources = [source for source in sources if source.enabled]
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.errors: list[str] = []
        self.health: list[dict] = []

    async def collect(self) -> list[Candidate]:
        groups = await asyncio.gather(*(self._collect_source(source) for source in self.sources))
        return [candidate for group in groups for candidate in group]

    async def _collect_source(self, source: WebChangelogSourceConfig) -> list[Candidate]:
        status = None
        try:
            async with self.semaphore:
                response = await self.client.get(str(source.url), follow_redirects=True)
            status = response.status_code
            response.raise_for_status()
            entries = PARSERS[source.parser](response.text, str(source.url))
            # A page may repeat a card in desktop/mobile markup. Emit one Candidate per
            # canonical entry; database URL uniqueness remains the cross-run state.
            entries = list({entry["url"]: entry for entry in entries}.values())
            if not entries:
                logger.warning(
                    "source_parse_empty", extra={"source": source.name, "http_status": status}
                )
                raise ValueError("web changelog contained no entries")
            latest = max(
                (entry["published_at"] for entry in entries if entry["published_at"]), default=None
            )
            self.health.append(
                {
                    "source": source.name,
                    "http_status": status,
                    "items": len(entries),
                    "latest": latest,
                    "status": "OK",
                }
            )
            logger.info(
                "source_fetch_successful",
                extra={
                    "source": source.name,
                    "http_status": status,
                    "items_parsed": len(entries),
                    "latest_published_at": latest.isoformat() if latest else None,
                },
            )
            return [
                Candidate(
                    source_name=source.name,
                    source_url=str(source.url),
                    source_trust=source.trust_level,
                    source_is_primary=source.is_primary,
                    title=entry["title"],
                    url=entry["url"],
                    summary=entry["summary"],
                    published_at=entry["published_at"],
                    source_type="web_changelog",
                    source_requires_primary_verification=source.requires_primary_verification,
                    external_id=entry["url"],
                )
                for entry in entries
            ]
        except (httpx.HTTPError, KeyError, ValueError) as error:
            self.errors.append(f"{source.name}: {type(error).__name__}")
            self.health.append(
                {
                    "source": source.name,
                    "http_status": status,
                    "items": 0,
                    "latest": None,
                    "status": "HTTP_ERROR" if isinstance(error, httpx.HTTPError) else "PARSE_ERROR",
                }
            )
            return []
