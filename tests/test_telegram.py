from datetime import UTC, datetime

import httpx
import pytest

from app.alerts.formatting import format_telegram_alert
from app.alerts.telegram import TelegramAlertChannel, TelegramDeliveryError
from app.domain.models import Candidate
from app.pipeline.score import calculate_scores


async def test_telegram_request_can_be_mocked():
    async def handler(request):
        assert request.url.path.endswith("/sendMessage")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = TelegramAlertChannel("fake-test-token", "123", client)
        assert await channel.send("hello") == "42"


async def test_telegram_error_has_no_secret_in_message():
    async def handler(request):
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        channel = TelegramAlertChannel("secret-token", "123", client)
        with pytest.raises(TelegramDeliveryError, match="telegram_http_500"):
            await channel.send("hello")


def test_alert_format_separates_relevance_and_alert(analysis, profiles):
    item = Candidate(
        "Official",
        "https://example.com/feed",
        100,
        True,
        "Model X",
        "https://example.com/model-x",
        "Summary",
        datetime.now(UTC),
        canonical_url="https://example.com/model-x",
    )
    text = format_telegram_alert(item, analysis, calculate_scores(analysis, 100, True), profiles)
    assert "Relevancia: 99" in text
    assert "Alerta:" in text
    assert "Hype: 0.05" in text
    assert "Fuente primaria: sí" in text
