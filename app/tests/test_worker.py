import pytest
from notification_service.config import Settings
from notification_service.domain import Channel, Notification, Status
from notification_service.provider import DeliveryError
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository
from notification_service.worker import WorkerPool
from test_rate_limiter import Clock


class FakeProvider:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []

    async def send(self, notification):
        self.calls.append(notification.id)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def prepare(repository, clock):
    item = Notification.create("recipient", "Hello", Channel.SMS, now=clock())
    await repository.create(item, capacity=100)
    await repository.request_processing(item.id, now=clock())
    return item


@pytest.mark.parametrize(
    "outcome,expected",
    [("p-1234", Status.SENT), (DeliveryError("http_401", retryable=False), Status.FAILED)],
)
async def test_worker_records_real_outcome(tmp_path, outcome, expected):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, clock)
        provider = FakeProvider([outcome])
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(
            repository, provider, limiter, Settings(), clock=clock, random=lambda: 0.5
        )
        assert await pool.run_once()
        assert (await repository.get(item.id)).status == expected
        assert not await pool.run_once()
        assert provider.calls == [item.id]


async def test_retry_is_scheduled_durably_and_exhaustion_is_terminal(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, clock)
        provider = FakeProvider([DeliveryError("http_500", retryable=True)] * 2)
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(
            repository, provider, limiter, Settings(max_attempts=2), clock=clock, random=lambda: 1
        )
        assert await pool.run_once()
        assert (await repository.get(item.id)).status == Status.PROCESSING
        assert not await pool.run_once()
        clock.now += 1
        assert await pool.run_once()
        stored = await repository.get(item.id)
        assert stored.status == Status.FAILED
        assert stored.attempts == 2


async def test_429_pauses_other_workers_and_honors_retry_after(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, clock)
        provider = FakeProvider([DeliveryError("http_429", retryable=True, retry_after=12), "p-1"])
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(repository, provider, limiter, Settings(), clock=clock, random=lambda: 0)
        assert await pool.run_once()
        clock.now += 12
        assert await pool.run_once()
        assert (await repository.get(item.id)).status == Status.SENT


async def test_registered_request_is_not_sent_until_activated(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        await repository.create(
            Notification.create("recipient", "Hello", Channel.EMAIL, now=clock()), capacity=100
        )
        provider = FakeProvider([])
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(repository, provider, limiter, Settings(), clock=clock)
        assert not await pool.run_once()
        assert provider.calls == []


async def test_attempt_timeout_and_final_429_are_not_hidden(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        first = await prepare(repository, clock)
        second = await prepare(repository, clock)
        provider = FakeProvider([TimeoutError(), DeliveryError("http_429", retryable=True)])
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(repository, provider, limiter, Settings(max_attempts=1), clock=clock)
        assert await pool.run_once()
        assert await pool.run_once()
        assert (await repository.get(first.id)).status == Status.FAILED
        assert (await repository.get(second.id)).status == Status.FAILED
        assert await repository.reserve_rate_slot(clock(), 50, 10, 0) >= 10


async def test_shutdown_during_quota_wait_does_not_start_delivery(tmp_path):
    import asyncio

    waiting = asyncio.Event()
    release = asyncio.Event()
    clock = Clock()

    class PausedLimiter:
        async def acquire(self):
            waiting.set()
            await release.wait()

    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, clock)
        provider = FakeProvider(["p-unexpected"])
        pool = WorkerPool(repository, provider, PausedLimiter(), Settings(), clock=clock)
        attempt = asyncio.create_task(pool.run_once())
        await asyncio.wait_for(waiting.wait(), timeout=5)
        await pool.stop()
        release.set()
        assert not await attempt
        assert provider.calls == []
        stored = await repository.get(item.id)
        assert stored.status == Status.QUEUED
        assert stored.attempts == 0
