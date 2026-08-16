from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class SpacedRateLimiter:
    """Serialize request starts at an even interval to avoid minute-boundary bursts."""

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self.interval = 60.0 / requests_per_minute
        self.clock = clock
        self.sleep = sleep
        self._next_start = 0.0
        self._lock = asyncio.Lock()
        self.wait_count = 0
        self.wait_seconds_total = 0.0

    async def wait(self) -> float:
        async with self._lock:
            now = self.clock()
            delay = max(0.0, self._next_start - now)
            if delay:
                self.wait_count += 1
                self.wait_seconds_total += delay
                await self.sleep(delay)
                now = self.clock()
            self._next_start = max(now, self._next_start) + self.interval
            return delay
