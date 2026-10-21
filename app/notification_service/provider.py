import math
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from notification_service.domain import Notification


class DeliveryError(Exception):
    def __init__(self, category: str, *, retryable: bool, retry_after: float | None = None):
        super().__init__(category)
        self.category = category
        self.retryable = retryable
        self.retry_after = retry_after


class NotificationProvider(Protocol):
    async def send(self, notification: Notification) -> str: ...


class ProviderResponse(BaseModel):
    status: Literal["delivered"]
    provider_id: str = Field(min_length=1)


class HTTPNotificationProvider:
    def __init__(self, client: httpx.AsyncClient, clock: Callable[[], float] = time.time):
        self.client = client
        self.clock = clock

    def _retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        try:
            seconds = float(value)
        except ValueError:
            try:
                seconds = parsedate_to_datetime(value).timestamp() - self.clock()
            except (ValueError, TypeError, OverflowError):
                return None
        return max(0, seconds) if math.isfinite(seconds) else None

    async def send(self, notification: Notification) -> str:
        try:
            response = await self.client.post(
                "/v1/notify",
                params={"trace_id": notification.id},
                json={
                    "to": notification.to,
                    "message": notification.message,
                    "type": notification.channel.value,
                },
            )
        except httpx.RequestError as exc:
            raise DeliveryError("transport_error", retryable=True) from exc
        if response.status_code != 200:
            raise DeliveryError(
                f"http_{response.status_code}",
                retryable=response.status_code == 429 or response.status_code >= 500,
                retry_after=self._retry_after(response.headers.get("Retry-After")),
            )
        try:
            return ProviderResponse.model_validate(response.json()).provider_id
        except (ValueError, ValidationError) as exc:
            raise DeliveryError("invalid_response", retryable=False) from exc
