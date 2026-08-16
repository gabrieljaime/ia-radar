from typing import Protocol

from app.domain.models import Candidate


class Collector(Protocol):
    async def collect(self) -> list[Candidate]: ...
