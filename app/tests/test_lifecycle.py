import asyncio
from unittest.mock import AsyncMock

import aiosqlite
import httpx
import main
import pytest
from notification_service.config import Settings
from notification_service.domain import Status
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository
from notification_service.worker import WorkerPool
from test_rate_limiter import Clock
from test_worker import prepare


async def test_lifespan_wires_workers_and_terminal_process_is_safe(tmp_path, monkeypatch):
    entered = asyncio.Event()

    class Provider:
        async def send(self, item):
            entered.set()
            return "p-confirmed"

    monkeypatch.setattr(main, "HTTPNotificationProvider", lambda client: Provider())
    startup = AsyncMock()
    monkeypatch.setattr(GlobalRateLimiter, "start", startup)
    application = main.create_app(
        Settings(
            database_path=str(tmp_path / "jobs.db"),
            provider_api_key="test-secret",
            poll_interval=0.001,
        )
    )
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            assert (await client.get("/health/ready")).status_code == 200
            response = await client.post(
                "/v1/requests", json={"to": "recipient", "message": "Hello", "type": "push"}
            )
            item_id = response.json()["id"]
            assert (await client.post(f"/v1/requests/{item_id}/process")).status_code == 202
            await asyncio.wait_for(entered.wait(), timeout=5)
            await application.state.workers.stop()
            assert (await client.get(f"/v1/requests/{item_id}")).json()["status"] == "sent"
            assert (await client.post(f"/v1/requests/{item_id}/process")).status_code == 200
            assert (await client.get("/health/ready")).status_code == 503
    startup.assert_awaited_once_with(5)


async def test_workers_require_an_explicit_provider_key(tmp_path):
    application = main.create_app(Settings(database_path=str(tmp_path / "jobs.db")))
    with pytest.raises(RuntimeError, match="NOTIFY_PROVIDER_API_KEY"):
        async with application.router.lifespan_context(application):
            pytest.fail("Startup must reject missing credentials")


async def test_storage_failure_never_returns_a_successful_creation(tmp_path):
    application = main.create_app(
        Settings(database_path=str(tmp_path / "jobs.db"), workers_enabled=False)
    )
    async with application.router.lifespan_context(application):
        application.state.repository.create = AsyncMock(
            side_effect=aiosqlite.OperationalError("database or disk is full")
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/requests", json={"to": "recipient", "message": "Hello", "type": "sms"}
            )
            assert response.status_code == 503
            assert "id" not in response.json()


async def test_cancellation_preserves_lease_until_atomic_recovery(tmp_path):
    entered = asyncio.Event()
    clock = Clock()

    class BlockingProvider:
        async def send(self, item):
            entered.set()
            await asyncio.Event().wait()

    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        item = await prepare(repository, clock)
        limiter = GlobalRateLimiter(repository, 50, 10, 0, clock=clock, sleep=clock.sleep)
        pool = WorkerPool(
            repository, BlockingProvider(), limiter, Settings(worker_count=1), clock=clock
        )
        pool.start()
        await asyncio.wait_for(entered.wait(), timeout=5)
        pool.tasks[0].cancel()
        await pool.stop()
        assert (await repository.get(item.id)).status == Status.PROCESSING
        assert await repository.claim(129, 30, 5) is None
        recovered = await repository.claim(130, 30, 5)
        assert recovered.id == item.id
        assert await repository.finish(recovered, 131, provider_id="p-recovered")


def test_settings_are_loaded_and_validated_from_environment(monkeypatch):
    monkeypatch.setenv("NOTIFY_BACKLOG_CAPACITY", "20000")
    monkeypatch.setenv("NOTIFY_PROVIDER_API_KEY", "test-secret")
    settings = Settings.from_env()
    assert settings.backlog_capacity == 20000
    assert "test-secret" not in repr(settings)
    monkeypatch.setenv("NOTIFY_LEASE_SECONDS", "5")
    with pytest.raises(ValueError, match="lease_seconds"):
        Settings.from_env()
