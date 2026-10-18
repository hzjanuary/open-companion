"""Operational HTTP endpoints."""

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from app.application.ports.concurrency import ConcurrencyLimiter
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.persistence import IngressSource
from app.infrastructure.database.database import Database
from app.infrastructure.database.governance import SqlAlchemyGovernanceRepository
from app.infrastructure.database.ingress import (
    SqlAlchemyDurableIngressRepository,
    UnknownPlatformConnectionError,
)
from app.infrastructure.queue.redis_streams import RedisIngressQueue
from app.infrastructure.telegram.updates import (
    TelegramUpdateValidationError,
    parse_telegram_update,
)
from app.interface.http.middleware import REQUEST_ID_HEADER
from app.interface.http.models import (
    DatabaseComponentResponse,
    DependencyUnavailableResponse,
    HealthResponse,
    ReadinessResponse,
    ServiceResponse,
    WebhookAcknowledgementResponse,
    WebhookErrorResponse,
)


def dependency_unavailable(
    request: Request, message: str = "Database is unavailable"
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    body = DependencyUnavailableResponse(message=message, request_id=request_id)
    response = JSONResponse(status_code=503, content=body.model_dump())
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def database_for(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def queue_for(request: Request) -> RedisIngressQueue:
    return cast(RedisIngressQueue, request.app.state.ingress_queue)


def rate_limiter_for(request: Request) -> RateLimiter | None:
    return cast(RateLimiter | None, request.app.state.rate_limiter)


def concurrency_limiter_for(request: Request) -> ConcurrencyLimiter | None:
    return cast(ConcurrencyLimiter | None, request.app.state.concurrency_limiter)


def telemetry_for(request: Request) -> MetricsRecorder:
    return cast(
        MetricsRecorder, getattr(request.app.state, "telemetry", NoOpMetricsRecorder())
    )


def webhook_error(
    request: Request,
    status: int,
    error_type: Literal["unauthorized", "invalid_request", "ingress_unavailable"],
    message: str,
) -> JSONResponse:
    telemetry_for(request).increment(
        "january_telegram_updates_total", outcome="invalid", transport="webhook"
    )
    request_id = getattr(request.state, "request_id", "unknown")
    body = WebhookErrorResponse(
        error_type=error_type, message=message, request_id=request_id
    )
    response = JSONResponse(status_code=status, content=body.model_dump())
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def create_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=ServiceResponse, tags=["operations"])
    async def root() -> ServiceResponse:
        return ServiceResponse(service=settings.app_name)

    @router.get("/health", response_model=HealthResponse, tags=["operations"])
    async def health(request: Request) -> HealthResponse | JSONResponse:
        ready = await database_for(request).is_ready()
        queue_required = settings.telegram_delivery_mode != "disabled"
        queue_ready = await queue_for(request).is_ready() if queue_required else None
        limiter = rate_limiter_for(request)
        limiter_ready = await limiter.is_ready() if limiter is not None else None
        concurrency = concurrency_limiter_for(request)
        concurrency_ready = (
            await concurrency.is_ready() if concurrency is not None else None
        )
        return HealthResponse(
            service=settings.app_name,
            status=(
                "ok"
                if (
                    ready
                    and queue_ready is not False
                    and limiter_ready is not False
                    and concurrency_ready is not False
                )
                else "degraded"
            ),
            application=DatabaseComponentResponse(status="ok"),
            database=DatabaseComponentResponse(status="ok" if ready else "unavailable"),
            redis=DatabaseComponentResponse(
                status=(
                    "disabled"
                    if (
                        queue_ready is None
                        and limiter_ready is None
                        and concurrency_ready is None
                    )
                    else "ok"
                    if (
                        queue_ready is not False
                        and limiter_ready is not False
                        and concurrency_ready is not False
                    )
                    else "unavailable"
                )
            ),
        )

    @router.get("/live", response_model=ServiceResponse, tags=["operations"])
    async def live() -> ServiceResponse:
        return ServiceResponse(service=settings.app_name)

    @router.get("/ready", response_model=ReadinessResponse, tags=["operations"])
    async def ready(request: Request) -> ReadinessResponse | JSONResponse:
        if not await database_for(request).is_ready():
            return dependency_unavailable(request)
        if (
            settings.telegram_delivery_mode != "disabled"
            and not await queue_for(request).is_ready()
        ):
            return dependency_unavailable(request, "Redis is unavailable")
        limiter = rate_limiter_for(request)
        if limiter is not None and not await limiter.is_ready():
            return dependency_unavailable(request, "Redis is unavailable")
        concurrency = concurrency_limiter_for(request)
        if concurrency is not None and not await concurrency.is_ready():
            return dependency_unavailable(request, "Redis is unavailable")
        return ReadinessResponse(
            service=settings.app_name,
            database=DatabaseComponentResponse(status="ok"),
            redis=DatabaseComponentResponse(
                status=(
                    "ok"
                    if settings.telegram_delivery_mode != "disabled"
                    or settings.rate_limit_enabled
                    or settings.provider_concurrency_enabled
                    else "disabled"
                )
            ),
        )

    @router.post(
        "/api/v1/platforms/telegram/webhook/{platform_connection_id}",
        response_model=WebhookAcknowledgementResponse,
        tags=["telegram"],
    )
    async def telegram_webhook(
        platform_connection_id: UUID, request: Request
    ) -> WebhookAcknowledgementResponse | JSONResponse:
        if (
            settings.telegram_delivery_mode != "webhook"
            or settings.telegram_platform_connection_id != platform_connection_id
        ):
            return webhook_error(
                request, 503, "ingress_unavailable", "Ingress is unavailable"
            )
        provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        expected_secret = settings.telegram_webhook_secret_token
        if (
            expected_secret is None
            or provided_secret is None
            or not hmac.compare_digest(
                provided_secret, expected_secret.get_secret_value()
            )
        ):
            return webhook_error(request, 401, "unauthorized", "Unauthorized")
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > settings.telegram_webhook_body_limit_bytes:
                    return webhook_error(
                        request, 413, "invalid_request", "Request body is too large"
                    )
            except ValueError:
                return webhook_error(request, 400, "invalid_request", "Invalid request")
        raw_body = await request.body()
        if len(raw_body) > settings.telegram_webhook_body_limit_bytes:
            return webhook_error(
                request, 413, "invalid_request", "Request body is too large"
            )
        try:
            parsed = parse_telegram_update(json.loads(raw_body))
        except (json.JSONDecodeError, TelegramUpdateValidationError):
            return webhook_error(
                request, 400, "invalid_request", "Invalid Telegram update"
            )
        repository = SqlAlchemyDurableIngressRepository(
            database_for(request).session_factory, settings.ingress_event_schema_version
        )
        try:
            accepted = await repository.accept(
                parsed.to_ingress(
                    platform_connection_id=platform_connection_id,
                    ingress_source=IngressSource.WEBHOOK,
                    received_at=datetime.now(UTC),
                )
            )
        except UnknownPlatformConnectionError:
            return webhook_error(
                request, 404, "ingress_unavailable", "Ingress is unavailable"
            )
        except Exception:
            logging.getLogger("january.ingress").exception(
                "telegram_webhook_persistence_failed"
            )
            return webhook_error(
                request, 503, "ingress_unavailable", "Ingress is unavailable"
            )
        logging.getLogger("january.ingress").info(
            "telegram_webhook_accepted",
            extra={
                "platform_connection_id": str(platform_connection_id),
                "platform_update_id": parsed.update_id,
                "update_type": parsed.update_type,
                "duplicate": accepted.duplicate,
            },
        )
        telemetry_for(request).increment(
            "january_telegram_updates_total",
            outcome="duplicate" if accepted.duplicate else "accepted",
            transport="webhook",
        )
        return WebhookAcknowledgementResponse(duplicate=accepted.duplicate)

    @router.post(
        "/api/v1/governance/exports/retrieve",
        tags=["governance"],
    )
    async def retrieve_export(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if not settings.data_governance_enabled:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        if authorization is None or not authorization.startswith("Bearer "):
            return JSONResponse(
                status_code=401, content={"detail": "Authentication required"}
            )
        token = authorization[7:].strip()
        if not token or len(token) > 128 or not token.isascii():
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        repository = SqlAlchemyGovernanceRepository(
            database_for(request).session_factory
        )
        package = await repository.retrieve_export_by_token(
            hashlib.sha256(token.encode("ascii")).hexdigest()
        )
        if package is None:
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        scope = str(package.manifest.get("scope", ""))
        telemetry_for(request).increment(
            "january_governance_export_retrievals_total",
            scope=scope,
            outcome="retrieved",
        )
        telemetry_for(request).increment(
            "january_governance_packages_cleared_total",
            outcome="retrieved",
        )
        return JSONResponse(
            content=package.package,
            headers={"Cache-Control": "no-store"},
        )

    return router
