import httpx
import pytest

from app.alerts.telegram import TelegramAlertChannel, TelegramDeliveryError


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
