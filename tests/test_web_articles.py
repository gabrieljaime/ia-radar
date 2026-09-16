from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.collectors.web_articles import (
    WebArticlesCollector,
    parse_dario_amodei_sitemap,
    parse_international_ai_safety_report,
    parse_mustafa_suleyman_sitemap,
    parse_nist_ai_news,
    parse_the_batch,
    parse_yoshua_bengio_blog,
)
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


def test_international_ai_safety_report_parser():
    html = """
    <div class="c-card__content">
      <p class="c-card__meta"><time datetime="3 February 2026">3 February 2026</time></p>
      <h3><a class="c-card__link" href="/publication/report-2026">Report 2026</a></h3>
      <p class="c-card__description">A comprehensive safety review.</p>
    </div>
    """
    items = parse_international_ai_safety_report(
        html, "https://internationalaisafetyreport.org/publications"
    )
    assert len(items) == 1
    assert items[0].title == "Report 2026"
    assert items[0].url == "https://internationalaisafetyreport.org/publication/report-2026"
    assert items[0].published_at == datetime(2026, 2, 3, tzinfo=UTC)
    assert items[0].summary == "A comprehensive safety review."


def test_nist_ai_news_parser():
    html = """
    <article class="nist-teaser">
      <h3 class="nist-teaser__title">
        <a href="/news-events/news/2026/08/ai-guidelines">AI Guidelines</a>
      </h3>
      <time datetime="2026-08-19T12:00:00Z">August 19, 2026</time>
      <div class="nist-teaser__content">NIST released a new draft.</div>
    </article>
    """
    items = parse_nist_ai_news(html, "https://www.nist.gov/news-events/news-updates")
    assert len(items) == 1
    assert items[0].title == "AI Guidelines"
    assert items[0].url == "https://www.nist.gov/news-events/news/2026/08/ai-guidelines"
    assert items[0].published_at == datetime(2026, 8, 19, tzinfo=UTC)
    assert items[0].summary == "NIST released a new draft."


def test_dario_amodei_sitemap_parser():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://darioamodei.com/post/we-must-pace-the-frontier</loc>
        <lastmod>2026-09-14T13:28:15.874Z</lastmod>
      </url>
      <url>
        <loc>https://darioamodei.com/privacy-policy</loc>
        <lastmod>2026-09-12T14:28:44.666Z</lastmod>
      </url>
    </urlset>"""
    items = parse_dario_amodei_sitemap(xml, "https://darioamodei.com/sitemap.xml")
    assert len(items) == 1
    assert items[0].title == "We Must Pace The Frontier"
    assert items[0].url == "https://darioamodei.com/post/we-must-pace-the-frontier"
    assert items[0].published_at == datetime(2026, 9, 14, 13, 28, 15, 874000, tzinfo=UTC)
    assert "AI strategy" in items[0].summary


def test_mustafa_suleyman_sitemap_parser():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://mustafa-suleyman.ai</loc><lastmod>2026-09-15T14:25:36Z</lastmod></url>
      <url>
        <loc>https://mustafa-suleyman.ai/the-humanist-ai-code-of-conduct</loc>
        <lastmod>2026-09-15T00:00:00Z</lastmod>
      </url>
    </urlset>"""
    items = parse_mustafa_suleyman_sitemap(xml, "https://mustafa-suleyman.ai/sitemap.xml")
    assert len(items) == 1
    assert items[0].title == "The Humanist AI Code Of Conduct"
    assert items[0].published_at == datetime(2026, 9, 15, tzinfo=UTC)
    assert "Mustafa Suleyman" in items[0].summary


def test_yoshua_bengio_blog_parser():
    html = """
    <div class="node node--type-post node--view-mode-teaser">
      <a class="link-wrapper" href="/en/blog/why-are-ai-agents-lying">
        <h3>Why are AI agents lying?</h3>
        <div class="field--name-body"><div class="field-item">A safety analysis.</div></div>
        <div class="field--name-node-post-date">
          <div class="field-item">11 September 2026</div>
        </div>
      </a>
    </div>
    """
    items = parse_yoshua_bengio_blog(html, "https://yoshuabengio.org/en/blog")
    assert len(items) == 1
    assert items[0].title == "Why are AI agents lying?"
    assert items[0].url == "https://yoshuabengio.org/en/blog/why-are-ai-agents-lying"
    assert items[0].published_at == datetime(2026, 9, 11, tzinfo=UTC)
    assert items[0].summary == "A safety analysis."


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
