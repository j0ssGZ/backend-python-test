import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import aiosqlite

from notification_service.domain import BacklogFull, Channel, NotFound, Notification, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    recipient TEXT NOT NULL,
    message TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'sms', 'push')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'processing', 'sent', 'failed')),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    process_requested_at REAL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_expires_at REAL,
    last_error TEXT,
    provider_id TEXT
);
CREATE INDEX IF NOT EXISTS pending_jobs
    ON notifications (next_attempt_at, created_at)
    WHERE process_requested_at IS NOT NULL AND status IN ('queued', 'processing');
CREATE INDEX IF NOT EXISTS active_notifications
    ON notifications (status) WHERE status IN ('queued', 'processing');
CREATE TABLE IF NOT EXISTS rate_admissions (admitted_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS admission_time ON rate_admissions (admitted_at);
CREATE TABLE IF NOT EXISTS rate_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    not_before REAL NOT NULL
);
INSERT OR IGNORE INTO rate_state VALUES (1, 0);
"""


class SQLiteRepository:
    """Serialize transactions on one connection; never hold them during HTTP calls."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Repository is not open")
        return self._db

    async def __aenter__(self) -> "SQLiteRepository":
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path, isolation_level=None, timeout=1)
        self._db.row_factory = aiosqlite.Row
        try:
            await self._db.execute("PRAGMA journal_mode=WAL")
            await self._db.execute("PRAGMA synchronous=FULL")
            await self._db.execute("PRAGMA busy_timeout=1000")
            await self._db.executescript(SCHEMA)
        except BaseException:
            await self._db.close()
            self._db = None
            raise
        return self

    async def __aexit__(self, *exc_info) -> None:
        async with self._lock:
            await self.db.close()
            self._db = None

    @asynccontextmanager
    async def _transaction(self):
        async with self._lock:
            try:
                # aiosqlite may execute BEGIN even if its awaiting task is cancelled.
                # Keep it inside the rollback boundary to leave the connection reusable.
                await self.db.execute("BEGIN IMMEDIATE")
                yield self.db
                await self.db.commit()
            except BaseException:
                await self.db.rollback()
                raise

    @staticmethod
    def _notification(row: aiosqlite.Row) -> Notification:
        return Notification(
            id=row["id"],
            to=row["recipient"],
            message=row["message"],
            channel=Channel(row["channel"]),
            status=Status(row["status"]),
            created_at=row["created_at"],
            process_requested_at=row["process_requested_at"],
            attempts=row["attempts"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
        )

    async def create(self, notification: Notification, capacity: int) -> None:
        async with self._transaction() as db:
            async with db.execute(
                "SELECT count(*) FROM notifications WHERE status IN ('queued', 'processing')"
            ) as cursor:
                row = await cursor.fetchone()
            if row[0] >= capacity:
                raise BacklogFull
            await db.execute(
                """INSERT INTO notifications
                   (id, recipient, message, channel, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    notification.id,
                    notification.to,
                    notification.message,
                    notification.channel,
                    notification.status,
                    notification.created_at,
                    notification.created_at,
                ),
            )

    async def get(self, request_id: str) -> Notification:
        async with self._lock:
            async with self.db.execute(
                "SELECT * FROM notifications WHERE id = ?", (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            raise NotFound(request_id)
        return self._notification(row)

    async def request_processing(self, request_id: str, now: float) -> Notification:
        async with self._transaction() as db:
            async with db.execute(
                """UPDATE notifications
                   SET next_attempt_at = CASE WHEN process_requested_at IS NULL
                                             THEN ? ELSE next_attempt_at END,
                       process_requested_at = COALESCE(process_requested_at, ?), updated_at = ?
                   WHERE id = ? RETURNING *""",
                (now, now, now, request_id),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise NotFound(request_id)
        return self._notification(row)

    async def ping(self) -> None:
        async with self._lock:
            async with self.db.execute("SELECT 1") as cursor:
                await cursor.fetchone()

    async def has_due(self, now: float) -> bool:
        async with self._lock:
            async with self.db.execute(
                """SELECT 1 FROM notifications WHERE process_requested_at IS NOT NULL
                   AND status IN ('queued', 'processing') AND next_attempt_at <= ?
                   AND (lease_expires_at IS NULL OR lease_expires_at <= ?) LIMIT 1""",
                (now, now),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def claim(
        self, now: float, lease_seconds: float, max_attempts: int
    ) -> Notification | None:
        async with self._transaction() as db:
            await db.execute(
                """UPDATE notifications SET status = 'failed', updated_at = ?,
                   last_error = 'attempts_exhausted_after_lease', lease_token = NULL,
                   lease_expires_at = NULL
                   WHERE status = 'processing' AND attempts >= ?
                   AND (lease_expires_at IS NULL OR lease_expires_at <= ?)""",
                (now, max_attempts, now),
            )
            async with db.execute(
                """UPDATE notifications SET status = 'processing', attempts = attempts + 1,
                   lease_token = ?, lease_expires_at = ?, updated_at = ?
                   WHERE id = (
                       SELECT id FROM notifications WHERE process_requested_at IS NOT NULL
                       AND status IN ('queued', 'processing') AND next_attempt_at <= ?
                       AND attempts < ?
                       AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                       ORDER BY next_attempt_at, created_at, id LIMIT 1
                   ) RETURNING *""",
                (str(uuid4()), now + lease_seconds, now, now, max_attempts, now),
            ) as cursor:
                row = await cursor.fetchone()
        return self._notification(row) if row else None

    async def finish(
        self,
        item: Notification,
        now: float,
        *,
        provider_id: str | None = None,
        error: str | None = None,
        next_attempt_at: float | None = None,
    ) -> bool:
        status = (
            Status.SENT
            if provider_id
            else (Status.PROCESSING if next_attempt_at is not None else Status.FAILED)
        )
        async with self._transaction() as db:
            async with db.execute(
                """UPDATE notifications SET status = ?, provider_id = ?, last_error = ?,
                   next_attempt_at = ?, updated_at = ?, lease_token = NULL, lease_expires_at = NULL
                   WHERE id = ? AND status = 'processing' AND lease_token = ?
                   AND lease_expires_at > ?""",
                (
                    status,
                    provider_id,
                    error,
                    next_attempt_at or 0,
                    now,
                    item.id,
                    item.lease_token,
                    now,
                ),
            ) as cursor:
                return cursor.rowcount == 1

    async def reserve_rate_slot(
        self,
        now: float,
        limit: int,
        window: float,
        spacing: float,
    ) -> float:
        """Return zero for a durable permit, or the delay until another attempt is possible."""
        async with self._transaction() as db:
            await db.execute(
                "DELETE FROM rate_admissions WHERE admitted_at <= ?", (now - window - 0.001,)
            )
            async with db.execute("SELECT not_before FROM rate_state WHERE singleton = 1") as cur:
                not_before = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT count(*), min(admitted_at), max(admitted_at) FROM rate_admissions"
            ) as cur:
                count, oldest, latest = await cur.fetchone()
            deadline = max(now, not_before)
            if count >= limit:
                deadline = max(deadline, oldest + window + 0.001)
            if latest is not None:
                deadline = max(deadline, latest + spacing)
            if deadline > now:
                return deadline - now
            await db.execute("INSERT INTO rate_admissions VALUES (?)", (now,))
            return 0

    async def defer_rate_limit_until(self, deadline: float) -> None:
        async with self._transaction() as db:
            await db.execute(
                "UPDATE rate_state SET not_before = max(not_before, ?) WHERE singleton = 1",
                (deadline,),
            )
