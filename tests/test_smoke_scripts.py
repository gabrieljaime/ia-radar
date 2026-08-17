from pathlib import Path

import httpx

from scripts.check_feeds import check_feed
from scripts.check_runtime_imports import ENTRYPOINT_MODULES, main


def test_runtime_entrypoints_import_without_external_operations(capsys):
    assert main() == 0
    assert capsys.readouterr().out == "Runtime entrypoint imports: OK\n"
    assert ENTRYPOINT_MODULES == (
        "scripts.check_sources",
        "scripts.run_radar",
        "scripts.send_digest",
        "scripts.show_latest_run",
    )


async def test_check_feed_reports_parse_metadata():
    content = Path("tests/fixtures/rss_ai_news.xml").read_bytes()

    async def handler(request):
        return httpx.Response(200, content=content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await check_feed(client, "Fixture", "https://example.com/feed")
    assert result["http_status"] == 200
    assert result["valid_feed"] is True
    assert result["entries"] == 2
    assert result["latest_entry"] == "2026-08-15T13:00:00+00:00"
    assert isinstance(result["latency_ms"], int)
