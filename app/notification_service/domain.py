from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class Status(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class NotFound(Exception):
    pass


class BacklogFull(Exception):
    pass


@dataclass(frozen=True)
class Notification:
    id: str
    to: str
    message: str
    channel: Channel
    status: Status
    created_at: float
    process_requested_at: float | None = None
    attempts: int = 0
    lease_token: str | None = None
    lease_expires_at: float | None = None

    @classmethod
    def create(cls, to: str, message: str, channel: Channel, now: float) -> "Notification":
        return cls(str(uuid4()), to, message, channel, Status.QUEUED, now)
