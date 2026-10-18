"""Closed, platform-independent values for bounded proactive scheduling."""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID


class ScheduleKind(StrEnum):
    REMINDER = "reminder"
    CHECK_IN = "check_in"


class RecurrenceKind(StrEnum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


class ScheduleStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERASED = "erased"


class OccurrenceStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    ENQUEUED = "enqueued"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    PERMANENTLY_FAILED = "permanently_failed"
    DELIVERY_UNKNOWN = "delivery_unknown"
    HISTORY_REDACTED = "history_redacted"


class MaterializationOutcome(StrEnum):
    MATERIALIZED = "materialized"
    STALE = "stale"


class ScheduleReason(StrEnum):
    NONE = "none"
    STALE = "stale"
    QUIET_HOURS = "quiet_hours"
    RECENT_ACTIVITY = "recent_activity"
    CANCELLED = "cancelled"
    PRIVACY = "privacy"
    MEMBERSHIP = "membership"
    PAUSED = "paused"
    EXPIRED = "expired"
    DELIVERY_REJECTED = "delivery_rejected"
    DELIVERY_UNKNOWN = "delivery_unknown"


class ScheduleOperation(StrEnum):
    TIMEZONE_SET = "timezone_set"
    QUIET_HOURS_SET = "quiet_hours_set"
    REMINDER_CREATE = "reminder_create"
    REMINDER_CANCEL = "reminder_cancel"
    CHECKINS_ENABLE = "checkins_enable"
    CHECKINS_DISABLE = "checkins_disable"


class ScheduleCommandOutcome(StrEnum):
    CREATED = "created"
    UPDATED = "updated"
    CANCELLED = "cancelled"
    UNCHANGED = "unchanged"
    NOT_FOUND = "not_found"
    LIMIT_REACHED = "limit_reached"
    TOO_LATE = "too_late"
    INVALID = "invalid"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class ScheduleDefinition:
    kind: ScheduleKind
    recurrence: RecurrenceKind
    timezone_name: str
    local_time_minute: int
    weekday_mask: int
    starts_on: date
    first_run_at: datetime
    ends_at: datetime
    reminder_text: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class ScheduleView:
    public_id: str
    kind: ScheduleKind
    recurrence: RecurrenceKind
    timezone_name: str
    local_time_minute: int
    weekday_mask: int
    next_run_at: datetime | None
    ends_at: datetime
    reminder_text: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class SchedulePreferences:
    timezone_name: str | None
    quiet_hours_enabled: bool
    quiet_start_minute: int
    quiet_end_minute: int
    revision: int


@dataclass(frozen=True, slots=True)
class OccurrenceClaim:
    occurrence_id: UUID
    schedule_id: UUID
    conversation_id: UUID
    participant_id: UUID
    kind: ScheduleKind
    reminder_text: str | None = field(repr=False)
    scheduled_for: datetime
    local_date: date
    attempt_count: int
    lease_token: UUID
    schedule_version: int
    privacy_revision: int
    language: str


@dataclass(frozen=True, slots=True)
class MaterializationResult:
    count: int
    events: tuple[tuple[ScheduleKind, MaterializationOutcome], ...]


WEEKDAY_BITS: dict[str, int] = {
    "mon": 1 << 0,
    "tue": 1 << 1,
    "wed": 1 << 2,
    "thu": 1 << 3,
    "fri": 1 << 4,
    "sat": 1 << 5,
    "sun": 1 << 6,
}
ALL_WEEKDAYS = (1 << 7) - 1
