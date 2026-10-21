import asyncio

import pytest
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository


class Clock:
    def __init__(self, now=100):
        self.now = float(now)

    def __call__(self):
        return self.now

    async def sleep(self, delay):
        assert delay > 0
        self.now += delay


async def test_every_sliding_window_respects_quota_without_real_sleep(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        admissions = []
        for _ in range(160):
            await limiter.acquire()
            admissions.append(clock.now)
        for end in admissions:
            assert sum(end - 10 < timestamp <= end for timestamp in admissions) <= 50
        assert admissions[50] >= 110
        assert admissions[100] >= 120


async def test_quota_is_shared_between_connections_and_survives_reopen(tmp_path):
    path = str(tmp_path / "jobs.db")
    async with SQLiteRepository(path) as first, SQLiteRepository(path) as second:
        assert await first.reserve_rate_slot(100, 2, 10, 0) == 0
        assert await second.reserve_rate_slot(100, 2, 10, 0) == 0
        assert await first.reserve_rate_slot(100, 2, 10, 0) == pytest.approx(10.001)
    async with SQLiteRepository(path) as repository:
        assert await repository.reserve_rate_slot(105, 2, 10, 0) > 5


async def test_restart_waits_for_inflight_requests_and_provider_window(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        await limiter.start(attempt_timeout=5)
        await limiter.acquire()
        assert clock.now == pytest.approx(115)


async def test_shared_cooldown_and_spacing(tmp_path):
    clock = Clock()
    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        limiter = GlobalRateLimiter(repository, 50, 10, 0.25, clock=clock, sleep=clock.sleep)
        await limiter.acquire()
        await limiter.acquire()
        assert clock.now == pytest.approx(100.25)
        await limiter.cooldown(12)
        await limiter.acquire()
        assert clock.now == pytest.approx(112.25)


async def test_simultaneous_admission_cannot_overbook_window(tmp_path):
    path = str(tmp_path / "jobs.db")
    async with SQLiteRepository(path) as first, SQLiteRepository(path) as second:
        permits = await asyncio.gather(
            *[
                (first if index % 2 else second).reserve_rate_slot(100, 50, 10, 0)
                for index in range(100)
            ]
        )
        assert sum(delay == 0 for delay in permits) == 50
        assert sum(delay >= 10 for delay in permits) == 50
