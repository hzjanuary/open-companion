"""FastAPI application factory and ASGI entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.telemetry import NoOpMetricsRecorder
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.database.database import Database
from app.infrastructure.queue.redis_streams import RedisIngressQueue
from app.infrastructure.rate_limit import RedisRateLimiter
from app.infrastructure.telegram.adapter import create_telegram_adapter
from app.infrastructure.telemetry import (
    InMemoryMetricsRecorder,
    MetricsHttpExporter,
)
from app.interface.http.control_plane import (
    create_router as create_control_plane_router,
)
from app.interface.http.knowledge_control import create_knowledge_router
from app.interface.http.middleware import REQUEST_ID_HEADER, RequestIdMiddleware
from app.interface.http.models import ErrorResponse
from app.interface.http.provider_governance_control import (
    create_provider_governance_router,
)
from app.interface.http.routes import create_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construct the HTTP application without connecting during import."""

    configured_settings = settings or get_settings()
    configure_logging(configured_settings.log_level)
    database = Database(configured_settings)
    telegram = create_telegram_adapter(configured_settings)
    queue = RedisIngressQueue(configured_settings)
    rate_limiter = (
        RedisRateLimiter(configured_settings)
        if configured_settings.rate_limit_enabled
        else None
    )
    concurrency_limiter: ConcurrencyLimiter | None = (
        RedisConcurrencyLimiter(configured_settings)
        if configured_settings.provider_concurrency_enabled
        else None
    )
    telemetry = (
        InMemoryMetricsRecorder()
        if configured_settings.metrics_enabled
        else NoOpMetricsRecorder()
    )
    metrics_exporter = (
        MetricsHttpExporter(
            telemetry,
            configured_settings.metrics_bind_host,
            configured_settings.metrics_port,
        )
        if configured_settings.metrics_export_enabled
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await database.start()
        app.state.database = database
        app.state.telegram = telegram
        app.state.ingress_queue = queue
        app.state.rate_limiter = rate_limiter
        app.state.concurrency_limiter = concurrency_limiter
        app.state.telemetry = telemetry
        app.state.metrics_exporter = metrics_exporter
        app.state.settings = configured_settings
        if metrics_exporter is not None:
            await metrics_exporter.start()
        try:
            yield
        finally:
            if telegram is not None:
                await telegram.aclose()
            await queue.aclose()
            if rate_limiter is not None:
                await rate_limiter.aclose()
            if concurrency_limiter is not None:
                await concurrency_limiter.aclose()
            if metrics_exporter is not None:
                await metrics_exporter.close()
            await database.stop()

    app = FastAPI(
        title=configured_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.telegram = telegram
    app.state.ingress_queue = queue
    app.state.rate_limiter = rate_limiter
    app.state.concurrency_limiter = concurrency_limiter
    app.state.telemetry = telemetry
    app.state.metrics_exporter = metrics_exporter
    app.state.settings = configured_settings
    app.add_middleware(RequestIdMiddleware)
    app.include_router(create_router(configured_settings))
    if configured_settings.control_plane_enabled:
        app.include_router(create_control_plane_router(configured_settings))
        app.include_router(create_provider_governance_router(configured_settings))
        app.include_router(create_knowledge_router(configured_settings))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        if not request.url.path.startswith("/control/"):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )
        request_id = getattr(request.state, "request_id", "unknown")
        category = {
            401: "auth_required",
            403: "forbidden",
            404: "not_found_or_forbidden",
            409: "conflict",
            422: "validation_error",
            503: "dependency_unavailable",
        }.get(exc.status_code, "validation_error")
        response = JSONResponse(
            status_code=exc.status_code,
            content={
                "error_type": category,
                "message": str(exc.detail),
                "request_id": request_id,
            },
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        logging.getLogger("january").exception("unhandled_request_error")
        body = ErrorResponse(
            error_type="internal_error",
            message="Internal server error",
            request_id=request_id,
        )
        response = JSONResponse(status_code=500, content=body.model_dump())
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    return app


app = create_app()
