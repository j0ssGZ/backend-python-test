import time
from collections.abc import Callable
from typing import Protocol

from notification_service.domain import Channel, Notification


class NotificationRepository(Protocol):
    async def create(self, notification: Notification, capacity: int) -> None: ...
    async def get(self, request_id: str) -> Notification: ...
    async def request_processing(self, request_id: str, now: float) -> Notification: ...


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        capacity: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.repository = repository
        self.capacity = capacity
        self.clock = clock

    async def create(self, to: str, message: str, channel: Channel) -> Notification:
        notification = Notification.create(to, message, channel, self.clock())
        await self.repository.create(notification, self.capacity)
        return notification

    async def process(self, request_id: str) -> Notification:
        return await self.repository.request_processing(request_id, self.clock())

    async def get(self, request_id: str) -> Notification:
        return await self.repository.get(request_id)
