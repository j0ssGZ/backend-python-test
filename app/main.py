import logging
from contextlib import asynccontextmanager

import aiosqlite
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from notification_service.api import router
from notification_service.config import Settings
from notification_service.domain import BacklogFull, NotFound
from notification_service.logging import configure_logging
from notification_service.provider import HTTPNotificationProvider
from notification_service.rate_limiter import GlobalRateLimiter
from notification_service.repository import SQLiteRepository
from notification_service.service import NotificationService
from notification_service.worker import WorkerPool

logger = logging.getLogger("notification_service.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging()
        if settings.workers_enabled and not settings.provider_api_key:
            raise RuntimeError("NOTIFY_PROVIDER_API_KEY is required when workers are enabled")
        async with SQLiteRepository(settings.database_path) as repository:
            application.state.repository = repository
            application.state.service = NotificationService(repository, settings.backlog_capacity)
            if not settings.workers_enabled:
                yield
                return
            async with httpx.AsyncClient(
                base_url=str(settings.provider_url),
                headers={"X-API-Key": settings.provider_api_key.get_secret_value()},
                limits=httpx.Limits(
                    max_connections=settings.worker_count,
                    max_keepalive_connections=settings.worker_count,
                ),
                timeout=httpx.Timeout(2, connect=1, write=1, pool=1),
                trust_env=False,
            ) as client:
                limiter = GlobalRateLimiter(
                    repository, settings.rate_limit, settings.rate_window, settings.rate_spacing
                )
                await limiter.start(settings.attempt_timeout)
                pool = WorkerPool(repository, HTTPNotificationProvider(client), limiter, settings)
                application.state.workers = pool
                pool.start()
                try:
                    yield
                finally:
                    await pool.stop()

    application = FastAPI(title="Notification Service (Technical Test)", lifespan=lifespan)
    application.include_router(router)

    @application.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Request not found"})

    @application.exception_handler(BacklogFull)
    async def backlog_full(request: Request, exc: BacklogFull) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": "Backlog capacity reached"},
            headers={"Retry-After": "10"},
        )

    @application.exception_handler(aiosqlite.Error)
    async def storage_unavailable(request: Request, exc: aiosqlite.Error) -> JSONResponse:
        logger.error("storage_unavailable", exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "Storage temporarily unavailable"})

    @application.get("/health/ready")
    async def ready(request: Request) -> dict[str, str]:
        await request.app.state.repository.ping()
        if settings.workers_enabled and not request.app.state.workers.healthy:
            return JSONResponse(status_code=503, content={"detail": "Workers unavailable"})
        return {"status": "ready"}

    return application


app = create_app()
