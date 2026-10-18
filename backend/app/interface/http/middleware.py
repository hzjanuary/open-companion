"""HTTP middleware for request correlation."""

import re
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.application.ports.telemetry import NoOpMetricsRecorder
from app.core.request_context import reset_request_id, set_request_id

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def resolve_request_id(value: str | None) -> str:
    """Accept bounded correlation IDs and replace malformed input."""

    if value is not None and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return str(uuid4())


class RequestIdMiddleware:
    """Attach a request ID to context and every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        request_id = resolve_request_id(headers.get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        token = set_request_id(request_id)
        started = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
                nonlocal status_code
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            telemetry = getattr(scope["app"].state, "telemetry", NoOpMetricsRecorder())
            route = scope.get("route")
            path = getattr(route, "path", None) or "unmatched"
            labels = {
                "route": path,
                "method": scope["method"],
                "status": f"{status_code // 100}xx",
            }
            try:
                telemetry.increment("january_http_requests_total", **labels)
                telemetry.observe(
                    "january_http_request_duration_seconds",
                    perf_counter() - started,
                    **labels,
                )
            except Exception:
                pass
            reset_request_id(token)
