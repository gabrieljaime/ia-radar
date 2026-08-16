from typing import Protocol


class AlertChannel(Protocol):
    async def send(self, text: str) -> str: ...
