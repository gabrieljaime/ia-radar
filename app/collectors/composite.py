import asyncio

from app.collectors.base import Collector
from app.domain.models import Candidate


class CompositeCollector:
    def __init__(self, collectors: list[Collector]):
        self.collectors = collectors
        self.errors: list[str] = []

    async def collect(self) -> list[Candidate]:
        groups = await asyncio.gather(*(collector.collect() for collector in self.collectors))
        self.errors = [
            error for collector in self.collectors for error in getattr(collector, "errors", [])
        ]
        return [candidate for group in groups for candidate in group]
