from pathlib import Path

import httpx
import pytest

from app.collectors.web_changelog import (
    WebChangelogCollector,
    parse_anthropic,
    parse_gemini,
    parse_meta,
    parse_mistral,
    parse_xai,
)
from app.core.config import WebChangelogSourceConfig

FIXTURES = Path("tests/fixtures")


@pytest.mark.parametrize(
    ("parser", "fixture", "expected"),
    [
        (parse_gemini, "gemini_changelog.html", "Gemini 3.7 released"),
        (parse_mistral, "mistral_changelog.html", "Mistral Large 4"),
        (parse_xai, "xai_changelog.html", "Grok 5"),
        (parse_meta, "meta_changelog.html", "Introducing Llama 5"),
        (parse_anthropic, "anthropic_changelog.html", "Introducing Claude 5"),
    ],
)
def test_web_changelog_parsers(parser, fixture, expected):
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    entries = parser(html, "https://example.com/changelog")
    assert len(entries) == 1
    assert expected in entries[0]["title"]
    assert entries[0]["published_at"] is not None


async def test_web_changelog_empty_and_malformed_html_are_isolated():
    async def handler(request):
        return httpx.Response(200, text="<html><broken>")

    source = WebChangelogSourceConfig(
        name="Broken",
        url="https://example.com/changelog",
        parser="gemini",
        category="official",
        trust_level=100,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebChangelogCollector([source], client)
        assert await collector.collect() == []
    assert collector.health[0]["status"] == "PARSE_ERROR"


async def test_web_changelog_http_error_is_isolated():
    async def handler(request):
        return httpx.Response(503)

    source = WebChangelogSourceConfig(
        name="Unavailable",
        url="https://example.com/changelog",
        parser="gemini",
        category="official",
        trust_level=100,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebChangelogCollector([source], client)
        assert await collector.collect() == []
    assert collector.health[0]["status"] == "HTTP_ERROR"


def test_parser_preserves_missing_date_explicitly():
    entries = parse_anthropic(
        '<a href="/news/x"><h3>Claude update</h3><time>unknown</time></a>',
        "https://anthropic.com/news",
    )
    assert entries[0]["published_at"] is None


async def test_collector_deduplicates_repeated_entry_url_without_calling_llm():
    html = (FIXTURES / "anthropic_changelog.html").read_text(encoding="utf-8")

    async def handler(request):
        return httpx.Response(200, text=html + html)

    source = WebChangelogSourceConfig(
        name="Anthropic",
        url="https://example.com/news",
        parser="anthropic",
        category="official",
        trust_level=100,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebChangelogCollector([source], client)
        candidates = await collector.collect()
    assert len(candidates) == 1
    assert collector.health[0]["items"] == 1
