"""Structured operational logging without product audit persistence."""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.core.request_context import get_request_id
from app.core.telemetry_context import get_correlation_id

_OPERATIONAL_FIELDS = frozenset(
    {
        "runtime",
        "operation",
        "outcome",
        "status",
        "duration_ms",
        "error_class",
        "provider",
        "model",
        "retry_count",
        "retry_after_ms",
        "conversation_id",
        "message_id",
        "planning_job_id",
        "response_plan_id",
        "outbound_action_id",
        "command_job_id",
        "policy_version",
        "schema_version",
    }
)


def operational_event(
    logger: logging.Logger,
    event: str,
    /,
    *,
    level: int = logging.INFO,
    **fields: object,
) -> None:
    """Emit an allowlisted content-free event; unknown fields are rejected."""

    invalid = set(fields) - _OPERATIONAL_FIELDS
    if invalid:
        raise ValueError("operational event contains unsupported fields")
    logger.log(
        level, event, extra={"operational_event": event, "operational_fields": fields}
    )


class JsonFormatter(logging.Formatter):
    """Emit compact JSON records suitable for container log collection."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = get_request_id()
        if request_id is not None:
            payload["request_id"] = request_id
        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id
        event = getattr(record, "operational_event", None)
        if event is not None:
            payload["event"] = event
            payload.update(getattr(record, "operational_fields", {}))
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configure the application logger once without altering root handlers."""

    logger = logging.getLogger("january")
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
