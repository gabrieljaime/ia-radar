from pathlib import Path
from types import SimpleNamespace

import httpx

from app.collectors.rss import RSSCollector
from app.core.config import RSSSourceConfig


async def test_rss_parsing_uses_fixture():
    content = Path("tests/fixtures/rss_ai_news.xml").read_bytes()

    async def handler(request):
        return httpx.Response(200, content=content)

    source = RSSSourceConfig(
        name="Fixture", url="https://example.com/feed", category="official", trust_level=95
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await RSSCollector([source], client).collect()
    assert len(items) == 2
    assert items[0].external_id == "release-model-x"
    assert items[0].published_at is not None


async def test_rss_source_failure_is_isolated():
    async def handler(request):
        return httpx.Response(503)

    source = RSSSourceConfig(
        name="Broken", url="https://example.com/feed", category="official", trust_level=95
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = RSSCollector([source], client)
        assert await collector.collect() == []
    assert collector.errors == ["Broken: HTTPStatusError"]


async def test_rss_source_limit_bounds_each_run():
    content = Path("tests/fixtures/rss_ai_news.xml").read_bytes()

    async def handler(request):
        return httpx.Response(200, content=content)

    source = RSSSourceConfig(
        name="Fixture",
        url="https://example.com/feed",
        category="official",
        trust_level=95,
        limit=1,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await RSSCollector([source], client).collect()
    assert len(items) == 1
    assert items[0].external_id == "release-model-x"


async def test_rss_publisher_allowlist_filters_aggregated_feed():
    content = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Aggregator</title>
      <item><title>Trusted AI safety report</title><link>https://news.test/1</link>
        <guid>1</guid><pubDate>Tue, 15 Sep 2026 12:00:00 GMT</pubDate>
        <source url="https://trusted.test">Trusted News</source></item>
      <item><title>Untrusted AI rumor</title><link>https://news.test/2</link>
        <guid>2</guid><pubDate>Tue, 15 Sep 2026 12:00:00 GMT</pubDate>
        <source url="https://rumor.test">Rumor Blog</source></item>
    </channel></rss>"""

    async def handler(request):
        return httpx.Response(200, content=content)

    source = RSSSourceConfig(
        name="Aggregator",
        url="https://example.com/feed",
        category="media",
        trust_level=75,
        publisher_allowlist=["Trusted News"],
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await RSSCollector([source], client).collect()
    assert [item.title for item in items] == ["Trusted AI safety report"]


def test_rss_replaces_missing_or_placeholder_title():
    source = RSSSourceConfig(
        name="Sam Altman Blog",
        url="https://blog.samaltman.com/posts.atom",
        category="primary_executive_essays",
        trust_level=100,
    )
    entry = SimpleNamespace(
        title="-",
        link="https://blog.samaltman.com/post",
        summary="An essay about AI safety.",
        id="post-1",
    )
    item = RSSCollector._entry_to_candidate(source, entry)
    assert item.title == "New post from Sam Altman Blog"
