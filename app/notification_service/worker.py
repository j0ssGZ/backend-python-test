import asyncio
import logging
import random
import time
from collections.abc import Callable

from notification_service.config import Settings
from notification_service.provider import DeliveryError, NotificationProvider
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository

logger = logging.getLogger(__name__)


class WorkerPool:
    def __init__(
        self,
        repository: SQLiteRepository,
        provider: NotificationProvider,
        limiter: GlobalRateLimiter,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.time,
        random: Callable[[], float] = random.random,
    ):
        self.repository = repository
        self.provider = provider
        self.limiter = limiter
        self.settings = settings
        self.clock = clock
        self.random = random
        self.tasks: list[asyncio.Task] = []
        self.stopping = asyncio.Event()

    async def run_once(self) -> bool:
        if self.stopping.is_set():
            return False
        if not await self.repository.has_due(self.clock()):
            return False
        # Waiting for provider quota must never consume a job's lease.
        await self.limiter.acquire()
        if self.stopping.is_set():
            return False
        item = await self.repository.claim(
            self.clock(), self.settings.lease_seconds, self.settings.max_attempts
        )
        if item is None:
            return False
        try:
            async with asyncio.timeout(self.settings.attempt_timeout):
                provider_id = await self.provider.send(item)
        except (DeliveryError, TimeoutError) as exc:
            error = (
                exc
                if isinstance(exc, DeliveryError)
                else DeliveryError("attempt_timeout", retryable=True)
            )
            delay = None
            if error.category == "http_429":
                await self.limiter.cooldown(error.retry_after or self.settings.rate_window)
            if error.retryable and item.attempts < self.settings.max_attempts:
                ceiling = min(
                    self.settings.retry_cap, self.settings.retry_base * 2 ** (item.attempts - 1)
                )
                delay = self.random() * ceiling
                if error.category == "http_429":
                    delay = max(delay, error.retry_after or self.settings.rate_window)
                    await self.limiter.cooldown(delay)
                elif error.retry_after is not None:
                    delay = max(delay, error.retry_after)
            saved = await self.repository.finish(
                item,
                self.clock(),
                error=error.category,
                next_attempt_at=self.clock() + delay if delay is not None else None,
            )
            logger.warning(
                "delivery_attempt_failed",
                extra={
                    "request_id": item.id,
                    "attempt": item.attempts,
                    "error_category": error.category,
                    "retry_delay": delay,
                    "state_saved": saved,
                },
            )
        else:
            saved = await self.repository.finish(item, self.clock(), provider_id=provider_id)
            logger.info(
                "delivery_sent" if saved else "delivery_lease_lost",
                extra={
                    "request_id": item.id,
                    "attempt": item.attempts,
                    "state_saved": saved,
                },
            )
        return True

    def start(self) -> None:
        self.tasks = [
            asyncio.create_task(self._run(), name=f"notification-worker-{index}")
            for index in range(self.settings.worker_count)
        ]

    @property
    def healthy(self) -> bool:
        return bool(self.tasks) and all(not task.done() for task in self.tasks)

    async def _run(self) -> None:
        while not self.stopping.is_set():
            try:
                if await self.run_once():
                    continue
            except Exception:
                logger.exception("worker_iteration_failed")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=self.settings.poll_interval)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self.stopping.set()
        if not self.tasks:
            return
        _, pending = await asyncio.wait(self.tasks, timeout=self.settings.shutdown_timeout)
        for task in pending:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
