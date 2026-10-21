import asyncio
import os
import signal
import sys
from pathlib import Path

from notification_service.config import Settings
from notification_service.domain import Status
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository
from notification_service.worker import WorkerPool
from test_rate_limiter import Clock
from test_worker import FakeProvider, prepare


async def test_expired_lease_is_reclaimed_and_old_owner_cannot_commit(tmp_path):
    clock = Clock()
    path = str(tmp_path / "jobs.db")
    async with SQLiteRepository(path) as first, SQLiteRepository(path) as second:
        item = await prepare(first, clock)
        old = await first.claim(100, 30, 5)
        assert old.id == item.id
        assert await second.claim(129, 30, 5) is None
        recovered = await second.claim(130, 30, 5)
        assert recovered.id == item.id
        assert recovered.attempts == 2
        assert recovered.lease_token != old.lease_token
        assert not await first.finish(old, 131, provider_id="old-response")
        assert await second.finish(recovered, 131, provider_id="new-response")
        assert (await first.get(item.id)).status == Status.SENT


async def test_expired_owner_cannot_commit_even_before_reclamation(tmp_path):
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, Clock())
        claimed = await repository.claim(100, 30, 5)
        assert not await repository.finish(claimed, 130, provider_id="late")
        assert (await repository.get(item.id)).status == Status.PROCESSING
        assert await repository.claim(130, 30, 5) is not None


async def test_crash_during_final_attempt_eventually_becomes_failed(tmp_path):
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, Clock())
        await repository.claim(100, 30, max_attempts=1)
        assert await repository.claim(129, 30, max_attempts=1) is None
        assert await repository.claim(130, 30, max_attempts=1) is None
        assert (await repository.get(item.id)).status == Status.FAILED


async def test_atomic_claim_across_competing_connections(tmp_path):
    path = str(tmp_path / "jobs.db")
    async with SQLiteRepository(path) as first, SQLiteRepository(path) as second:
        await prepare(first, Clock())
        claims = await asyncio.gather(
            *[(first if index % 2 else second).claim(100, 30, 5) for index in range(100)]
        )
        assert sum(claim is not None for claim in claims) == 1


async def test_sigkill_leaves_a_recoverable_durable_lease(tmp_path):
    path = str(tmp_path / "jobs.db")
    async with SQLiteRepository(path) as repository:
        item = await prepare(repository, Clock())
    script = """
import asyncio, os, signal, sys
from notification_service.repository import SQLiteRepository
async def main():
    async with SQLiteRepository(sys.argv[1]) as repository:
        assert await repository.claim(100, 30, 5) is not None
        os.kill(os.getpid(), signal.SIGKILL)
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    )
    assert await process.wait() == -signal.SIGKILL
    async with SQLiteRepository(path) as repository:
        assert (await repository.get(item.id)).status == Status.PROCESSING
        assert await repository.claim(129, 30, 5) is None
        recovered = await repository.claim(130, 30, 5)
        assert recovered.id == item.id
        assert recovered.attempts == 2


async def test_repeated_process_calls_and_bounded_workers_send_each_job_once(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        items = [await prepare(repository, clock) for _ in range(8)]
        await asyncio.gather(
            *[repository.request_processing(items[0].id, now=100) for _ in range(100)]
        )
        entered = asyncio.Event()
        release = asyncio.Event()
        completed = asyncio.Event()

        class BlockingProvider:
            def __init__(self):
                self.active = 0
                self.peak = 0
                self.calls = []

            async def send(self, item):
                self.active += 1
                self.peak = max(self.peak, self.active)
                if self.active == 4:
                    entered.set()
                await release.wait()
                self.calls.append(item.id)
                self.active -= 1
                if len(self.calls) == 8:
                    completed.set()
                return "p-1"

        provider = BlockingProvider()
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(repository, provider, limiter, Settings(), clock=clock)
        pool.start()
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert provider.peak == 4
            release.set()
            await asyncio.wait_for(completed.wait(), timeout=5)
        finally:
            release.set()
            await pool.stop()
        assert sorted(provider.calls) == sorted(item.id for item in items)
        for item in items:
            assert (await repository.get(item.id)).status == Status.SENT


async def test_retry_schedule_survives_repository_reopening(tmp_path):
    clock = Clock()
    path = str(tmp_path / "jobs.db")
    from notification_service.provider import DeliveryError

    async with SQLiteRepository(path) as repository:
        item = await prepare(repository, clock)
        provider = FakeProvider([DeliveryError("http_500", retryable=True)])
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(repository, provider, limiter, Settings(), clock=clock, random=lambda: 1)
        await pool.run_once()
    async with SQLiteRepository(path) as repository:
        assert await repository.claim(100.5, 30, 5) is None
        recovered = await repository.claim(101, 30, 5)
        assert recovered.id == item.id
        assert recovered.attempts == 2
