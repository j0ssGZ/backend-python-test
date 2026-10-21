import asyncio
import time
from collections.abc import Awaitable, Callable

from notification_service.repository import SQLiteRepository


class GlobalRateLimiter:
    """SQLite coordinates sliding-window admission and cooldown across all workers."""

    def __init__(
        self,
        repository: SQLiteRepository,
        limit: int,
        window: float,
        spacing: float,
        *,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.repository = repository
        self.limit = limit
        self.window = window
        self.spacing = spacing
        self.clock = clock
        self.sleep = sleep

    async def start(self, attempt_timeout: float) -> None:
        # Previous in-flight attempts may arrive after this process starts.
        await self.repository.defer_rate_limit_until(self.clock() + self.window + attempt_timeout)

    async def acquire(self) -> None:
        while True:
            delay = await self.repository.reserve_rate_slot(
                self.clock(),
                self.limit,
                self.window,
                self.spacing,
            )
            if delay == 0:
                return
            await self.sleep(delay)

    async def cooldown(self, delay: float) -> None:
        await self.repository.defer_rate_limit_until(self.clock() + delay)
