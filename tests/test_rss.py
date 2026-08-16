from pathlib import Path

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
