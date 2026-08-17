from pathlib import Path

import httpx
import pytest

from app.collectors.web_articles import WebArticlesCollector, parse_the_batch
from app.core.config import WebArticlesSourceConfig

FIXTURE = Path("tests/fixtures/the_batch.html")


def source() -> WebArticlesSourceConfig:
    return WebArticlesSourceConfig(
        name="The Batch",
        url="https://www.deeplearning.ai/the-batch/",
        parser="the_batch",
        category="technical_newsletter",
        trust_level=85,
        is_primary=False,
        requires_primary_verification=True,
    )


def test_the_batch_parser_contract_and_edge_cases():
    items = parse_the_batch(FIXTURE.read_text(encoding="utf-8"), str(source().url))
    assert len(items) == 4
    assert items[0].title == "New reasoning model with tool calling"
    assert items[0].summary.startswith("A frontier LLM")
    assert items[0].published_at.isoformat() == "2026-08-14T00:00:00+00:00"
    assert items[0].url == "https://www.deeplearning.ai/the-batch/issue-366"
    assert items[1].summary == ""
    assert items[1].published_at is None
    assert items[2].url == "https://www.deeplearning.ai/the-batch/absolute"


@pytest.mark.parametrize("html", ["", "<html><broken>", "<article>changed</article>"])
def test_the_batch_empty_malformed_or_changed_structure_returns_no_items(html):
    assert parse_the_batch(html, str(source().url)) == []


async def test_collector_deduplicates_and_creates_secondary_candidates():
    async def handler(request):
        return httpx.Response(200, text=FIXTURE.read_text(encoding="utf-8"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebArticlesCollector([source()], client)
        candidates = await collector.collect()
    assert len(candidates) == 3
    assert all(candidate.source_type == "web_articles" for candidate in candidates)
    assert all(not candidate.source_is_primary for candidate in candidates)
    assert all(candidate.source_requires_primary_verification for candidate in candidates)
    assert collector.metrics == {"sources_fetched": 1, "items_found": 3}


@pytest.mark.parametrize("status", [404, 500])
async def test_http_errors_are_isolated(status):
    async def handler(request):
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebArticlesCollector([source()], client)
        assert await collector.collect() == []
    assert collector.health[0]["status"] == "HTTP_ERROR"


async def test_timeout_is_isolated():
    async def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebArticlesCollector([source()], client)
        assert await collector.collect() == []
    assert collector.health[0]["status"] == "HTTP_ERROR"


async def test_empty_response_reports_empty_and_warning_error():
    async def handler(request):
        return httpx.Response(200, text="<html></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        collector = WebArticlesCollector([source()], client)
        assert await collector.collect() == []
    assert collector.health[0]["status"] == "EMPTY"
    assert "source_parse_empty" in collector.errors[0]
