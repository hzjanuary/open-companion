"""Pure schedule validation and timezone/DST calculation."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from unicodedata import category
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.scheduling import (
    ALL_WEEKDAYS,
    WEEKDAY_BITS,
    RecurrenceKind,
    ScheduleDefinition,
    ScheduleKind,
    SchedulePreferences,
)


class ScheduleValidationError(ValueError):
    """A user schedule cannot satisfy the bounded product contract."""


@dataclass(frozen=True, slots=True)
class DueWindow:
    latest_due_at: datetime
    latest_local_date: date
    next_run_at: datetime | None


def validate_timezone(value: str) -> str:
    if not value or len(value) > 64 or value.startswith(("/", ".")):
        raise ScheduleValidationError("timezone is invalid")
    try:
        zone = ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ScheduleValidationError("timezone is invalid") from None
    if zone.key != value:
        raise ScheduleValidationError("timezone must be canonical")
    return value


def parse_local_time(value: str) -> int:
    if len(value) != 5 or value[2] != ":":
        raise ScheduleValidationError("local time is invalid")
    hour, minute = value[:2], value[3:]
    if (
        not hour.isascii()
        or not minute.isascii()
        or not hour.isdigit()
        or not minute.isdigit()
    ):
        raise ScheduleValidationError("local time is invalid")
    result = int(hour) * 60 + int(minute)
    if int(hour) > 23 or int(minute) > 59:
        raise ScheduleValidationError("local time is invalid")
    return result


def parse_local_date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ScheduleValidationError("local date is invalid") from None
    if parsed.isoformat() != value:
        raise ScheduleValidationError("local date is invalid")
    return parsed


def weekday_mask(value: str) -> int:
    values = value.split(",")
    if not values or any(item not in WEEKDAY_BITS for item in values):
        raise ScheduleValidationError("weekdays are invalid")
    if len(set(values)) != len(values):
        raise ScheduleValidationError("weekdays must be unique")
    return sum(WEEKDAY_BITS[item] for item in values)


def format_local_time(minutes: int) -> str:
    if not 0 <= minutes < 1440:
        raise ValueError("local time minute is outside one day")
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def resolve_local(zone_name: str, local_date: date, minute: int) -> datetime:
    """Resolve one local minute, first fold or first valid minute after a gap."""

    zone = ZoneInfo(validate_timezone(zone_name))
    start = datetime.combine(local_date, time(minute // 60, minute % 60))
    for offset in range(181):
        naive = start + timedelta(minutes=offset)
        candidates: list[datetime] = []
        for fold in (0, 1):
            aware = naive.replace(tzinfo=zone, fold=fold)
            candidate = aware.astimezone(UTC)
            back = candidate.astimezone(zone)
            if back.replace(tzinfo=None) == naive:
                candidates.append(candidate)
        if candidates:
            return min(set(candidates))
    raise ScheduleValidationError("timezone gap exceeds supported bound")


def _allowed(mask: int, value: date) -> bool:
    return bool(mask & (1 << value.weekday()))


def _next_date(start: date, mask: int, *, include: bool) -> date:
    for offset in range(0 if include else 1, 8):
        candidate = start + timedelta(days=offset)
        if _allowed(mask, candidate):
            return candidate
    raise AssertionError("valid weekday mask has a next date")


def _previous_date(start: date, mask: int, *, include: bool) -> date:
    for offset in range(0 if include else 1, 8):
        candidate = start - timedelta(days=offset)
        if _allowed(mask, candidate):
            return candidate
    raise AssertionError("valid weekday mask has a previous date")


def next_recurring_at(
    *,
    after: datetime,
    zone_name: str,
    local_time_minute: int,
    weekday_mask_value: int,
    starts_on: date,
    ends_at: datetime,
) -> datetime | None:
    if after.tzinfo is None or not 1 <= weekday_mask_value <= ALL_WEEKDAYS:
        raise ValueError("recurrence inputs are invalid")
    local = after.astimezone(ZoneInfo(validate_timezone(zone_name)))
    candidate_date = max(local.date(), starts_on)
    for _ in range(2):
        candidate_date = _next_date(candidate_date, weekday_mask_value, include=True)
        candidate = resolve_local(zone_name, candidate_date, local_time_minute)
        if candidate > after:
            return candidate if candidate <= ends_at else None
        candidate_date = _next_date(candidate_date, weekday_mask_value, include=False)
    raise AssertionError("bounded recurrence did not advance")


def due_window(
    *,
    now: datetime,
    zone_name: str,
    local_time_minute: int,
    weekday_mask_value: int,
    starts_on: date,
    ends_at: datetime,
) -> DueWindow | None:
    if now.tzinfo is None or not 1 <= weekday_mask_value <= ALL_WEEKDAYS:
        raise ValueError("due inputs are invalid")
    zone = ZoneInfo(validate_timezone(zone_name))
    reference = min(now, ends_at)
    local_today = reference.astimezone(zone).date()
    latest_date = _previous_date(local_today, weekday_mask_value, include=True)
    latest = resolve_local(zone_name, latest_date, local_time_minute)
    if latest > reference:
        latest_date = _previous_date(latest_date, weekday_mask_value, include=False)
        latest = resolve_local(zone_name, latest_date, local_time_minute)
    if latest_date < starts_on or latest > ends_at:
        return None
    following = next_recurring_at(
        after=now,
        zone_name=zone_name,
        local_time_minute=local_time_minute,
        weekday_mask_value=weekday_mask_value,
        starts_on=starts_on,
        ends_at=ends_at,
    )
    return DueWindow(latest, latest_date, following)


def in_quiet_hours(moment: datetime, preferences: SchedulePreferences) -> bool:
    if not preferences.quiet_hours_enabled or preferences.timezone_name is None:
        return False
    local = moment.astimezone(ZoneInfo(preferences.timezone_name))
    minute = local.hour * 60 + local.minute
    start, end = preferences.quiet_start_minute, preferences.quiet_end_minute
    return start <= minute < end if start < end else minute >= start or minute < end


def quiet_hours_end(moment: datetime, preferences: SchedulePreferences) -> datetime:
    if not in_quiet_hours(moment, preferences) or preferences.timezone_name is None:
        return moment
    zone = ZoneInfo(preferences.timezone_name)
    local = moment.astimezone(zone)
    end_date = local.date()
    if preferences.quiet_start_minute > preferences.quiet_end_minute and (
        local.hour * 60 + local.minute >= preferences.quiet_start_minute
    ):
        end_date += timedelta(days=1)
    return resolve_local(
        preferences.timezone_name, end_date, preferences.quiet_end_minute
    )


def build_definition(
    *,
    kind: ScheduleKind,
    recurrence: RecurrenceKind,
    timezone_name: str,
    local_date: date | None,
    local_time_minute: int,
    weekday_mask_value: int,
    reminder_text: str | None,
    now: datetime,
    minimum_lead_seconds: int,
    horizon_days: int,
    text_limit: int,
) -> ScheduleDefinition:
    zone_name = validate_timezone(timezone_name)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if kind == ScheduleKind.REMINDER:
        text_value = (reminder_text or "").strip()
        if (
            not text_value
            or len(text_value) > text_limit
            or any(category(character) == "Cc" for character in text_value)
        ):
            raise ScheduleValidationError("reminder text is invalid")
    elif reminder_text is not None:
        raise ScheduleValidationError("check-in cannot contain reminder text")
    else:
        text_value = ""
    ends_at = now + timedelta(days=horizon_days)
    if recurrence == RecurrenceKind.ONCE:
        if local_date is None or weekday_mask_value != 0:
            raise ScheduleValidationError("one-time schedule shape is invalid")
        first = resolve_local(zone_name, local_date, local_time_minute)
        starts_on = local_date
    else:
        if local_date is not None:
            raise ScheduleValidationError("recurring schedule date is invalid")
        mask = (
            ALL_WEEKDAYS if recurrence == RecurrenceKind.DAILY else weekday_mask_value
        )
        if not 1 <= mask <= ALL_WEEKDAYS:
            raise ScheduleValidationError("recurrence weekdays are invalid")
        starts_on = now.astimezone(ZoneInfo(zone_name)).date()
        recurring_first = next_recurring_at(
            after=now,
            zone_name=zone_name,
            local_time_minute=local_time_minute,
            weekday_mask_value=mask,
            starts_on=starts_on,
            ends_at=ends_at,
        )
        if recurring_first is None:
            raise ScheduleValidationError("schedule has no occurrence in horizon")
        first = recurring_first
        weekday_mask_value = mask
    if first < now + timedelta(seconds=minimum_lead_seconds) or first > ends_at:
        raise ScheduleValidationError("schedule is outside the allowed horizon")
    return ScheduleDefinition(
        kind=kind,
        recurrence=recurrence,
        timezone_name=zone_name,
        local_time_minute=local_time_minute,
        weekday_mask=weekday_mask_value,
        starts_on=starts_on,
        first_run_at=first,
        ends_at=ends_at,
        reminder_text=text_value or None,
    )
