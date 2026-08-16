import httpx


class TelegramDeliveryError(RuntimeError):
    pass


class TelegramAlertChannel:
    def __init__(
        self, token: str, chat_id: str, client: httpx.AsyncClient | None = None, timeout: float = 20
    ):
        self.token = token
        self.chat_id = chat_id
        self.client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def send(self, text: str) -> str:
        response = await self.client.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"},
        )
        if response.is_error:
            raise TelegramDeliveryError(f"telegram_http_{response.status_code}")
        payload = response.json()
        if not payload.get("ok"):
            raise TelegramDeliveryError("telegram_api_error")
        return str(payload["result"]["message_id"])

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()
