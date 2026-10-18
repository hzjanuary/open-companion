"""Task-local operational correlation distinct from HTTP request IDs."""

from contextvars import ContextVar, Token
from uuid import uuid4

correlation_id_context: ContextVar[str | None] = ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(correlation_id: str) -> Token[str | None]:
    return correlation_id_context.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    correlation_id_context.reset(token)


def get_correlation_id() -> str | None:
    return correlation_id_context.get()


def new_operation_correlation_id() -> str:
    """Generate an opaque root only when no durable root is available."""

    return str(uuid4())
