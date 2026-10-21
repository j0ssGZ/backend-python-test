import asyncio

from notification_service.domain import Channel, Notification, Status
from notification_service.repository import SQLiteRepository


async def test_processing_intent_is_durable_and_idempotent(tmp_path):
    path = str(tmp_path / "notifications.db")
    async with SQLiteRepository(path) as repository:
        notification = Notification.create("recipient", "Hello", Channel.EMAIL, now=100)
        await repository.create(notification, capacity=100)
        results = await asyncio.gather(
            *[
                repository.request_processing(notification.id, now=101 + index)
                for index in range(100)
            ]
        )
        assert all(result.status == Status.QUEUED for result in results)
    async with SQLiteRepository(path) as repository:
        stored = await repository.get(notification.id)
        assert stored.to == "recipient"
        assert stored.message == "Hello"
        assert stored.process_requested_at == 101


async def test_capacity_check_and_insert_are_atomic(tmp_path):
    from notification_service.domain import BacklogFull

    async with SQLiteRepository(str(tmp_path / "notifications.db")) as repository:
        results = await asyncio.gather(
            *[
                repository.create(
                    Notification.create("recipient", "Hello", Channel.PUSH, now=100), capacity=5
                )
                for _ in range(20)
            ],
            return_exceptions=True,
        )
        assert sum(isinstance(result, BacklogFull) for result in results) == 15
        assert sum(result is None for result in results) == 5


async def test_cancellation_during_begin_does_not_poison_connection(tmp_path, monkeypatch):
    import pytest

    async with SQLiteRepository(str(tmp_path / "jobs.db")) as repository:
        began = asyncio.Event()
        original_execute = repository.db.execute

        async def paused_execute(sql, *args):
            result = await original_execute(sql, *args)
            if sql == "BEGIN IMMEDIATE":
                began.set()
                await asyncio.Event().wait()
            return result

        monkeypatch.setattr(repository.db, "execute", paused_execute)
        item = Notification.create("recipient", "Hello", Channel.EMAIL, now=100)
        task = asyncio.create_task(repository.create(item, capacity=10))
        await asyncio.wait_for(began.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        monkeypatch.setattr(repository.db, "execute", original_execute)
        # A later request must still be able to commit on the same connection.
        await repository.create(item, capacity=10)
        assert (await repository.get(item.id)).status == Status.QUEUED
