"""Strict, content-safe summary contracts and retention calculations."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.summary import SUMMARY_SCHEMA_VERSION


class ConversationSummaryCandidate(BaseModel):
    """The only structured output accepted from a summary provider."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str = Field(min_length=1, max_length=4000)
    language: str | None = Field(default=None, min_length=2, max_length=16)

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("summary must be nonblank")
        if any(
            ord(character) < 32 and character not in "\n\t" for character in normalized
        ):
            raise ValueError("summary must not contain control characters")
        return normalized


@dataclass(frozen=True, slots=True)
class SummarySourceMessage:
    id: UUID
    sent_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class SummarySourceWindow:
    conversation_id: UUID
    first_message_id: UUID
    last_message_id: UUID
    started_at: datetime
    ended_at: datetime
    source_count: int
    source_window_hash: str
    expires_at: datetime
    messages: tuple[SummarySourceMessage, ...]


def source_window_hash(messages: tuple[SummarySourceMessage, ...]) -> str:
    """Hash opaque source identity and timestamps, never message text."""
    payload = "|".join(f"{item.id}:{item.sent_at.isoformat()}" for item in messages)
    return sha256(payload.encode("ascii")).hexdigest()


def source_expiry(
    messages: tuple[SummarySourceMessage, ...], retention_days: int
) -> datetime:
    """Expire at the earliest represented source-content deadline."""
    if not messages:
        raise ValueError("summary source window must not be empty")
    return min(item.sent_at + timedelta(days=retention_days) for item in messages)


def build_source_window(
    conversation_id: UUID,
    messages: tuple[SummarySourceMessage, ...],
    retention_days: int,
) -> SummarySourceWindow:
    """Construct a deterministic chronological raw-message source window."""
    if not messages:
        raise ValueError("summary source window must not be empty")
    ordered = tuple(sorted(messages, key=lambda item: (item.sent_at, str(item.id))))
    return SummarySourceWindow(
        conversation_id=conversation_id,
        first_message_id=ordered[0].id,
        last_message_id=ordered[-1].id,
        started_at=ordered[0].sent_at,
        ended_at=ordered[-1].sent_at,
        source_count=len(ordered),
        source_window_hash=source_window_hash(ordered),
        expires_at=source_expiry(ordered, retention_days),
        messages=ordered,
    )


def summary_json_schema() -> dict[str, object]:
    """Stable schema sent to providers for versioned summary generation."""
    return ConversationSummaryCandidate.model_json_schema()


def summary_request_schema_version() -> str:
    return SUMMARY_SCHEMA_VERSION
