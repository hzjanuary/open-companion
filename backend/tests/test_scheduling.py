from datetime import UTC, date, datetime

import pytest

from app.application.scheduling import (
    ScheduleValidationError,
    build_definition,
    due_window,
    in_quiet_hours,
    next_recurring_at,
    parse_local_time,
    quiet_hours_end,
    resolve_local,
    validate_timezone,
    weekday_mask,
)
from app.domain.scheduling import (
    ALL_WEEKDAYS,
    RecurrenceKind,
    ScheduleKind,
    SchedulePreferences,
)


def test_timezone_and_clock_validation_fail_closed() -> None:
    assert validate_timezone("Asia/Ho_Chi_Minh") == "Asia/Ho_Chi_Minh"
    assert parse_local_time("23:59") == 1439
    assert weekday_mask("mon,wed,sun") == 69
    for value in ("", "../UTC", "/UTC", "Not/AZone"):
        with pytest.raises(ScheduleValidationError):
            validate_timezone(value)
    for value in ("24:00", "1:00", "12:60", "１２:００"):
        with pytest.raises(ScheduleValidationError):
            parse_local_time(value)
    with pytest.raises(ScheduleValidationError):
        weekday_mask("mon,mon")


def test_dst_gap_moves_forward_and_fold_uses_earlier_instant() -> None:
    # Europe/London skips 01:00 on 2026-03-29.
    assert resolve_local("Europe/London", date(2026, 3, 29), 90) == datetime(
        2026, 3, 29, 1, 0, tzinfo=UTC
    )
    # 01:30 occurs twice on 2026-10-25; the first instant is 00:30 UTC.
    assert resolve_local("Europe/London", date(2026, 10, 25), 90) == datetime(
        2026, 10, 25, 0, 30, tzinfo=UTC
    )


def test_recurring_time_advances_and_due_window_collapses_missed_runs() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    next_run = next_recurring_at(
        after=now,
        zone_name="UTC",
        local_time_minute=9 * 60,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2027, 9, 11, 12, tzinfo=UTC),
    )
    assert next_run == datetime(2026, 9, 12, 9, tzinfo=UTC)
    window = due_window(
        now=datetime(2026, 9, 21, 12, tzinfo=UTC),
        zone_name="UTC",
        local_time_minute=9 * 60,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2027, 9, 11, 12, tzinfo=UTC),
    )
    assert window is not None
    assert window.latest_due_at == datetime(2026, 9, 21, 9, tzinfo=UTC)
    assert window.next_run_at == datetime(2026, 9, 22, 9, tzinfo=UTC)

    terminal = due_window(
        now=datetime(2026, 9, 22, 10, tzinfo=UTC),
        zone_name="UTC",
        local_time_minute=9 * 60,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2026, 9, 21, 12, tzinfo=UTC),
    )
    assert terminal is not None
    assert terminal.latest_due_at == datetime(2026, 9, 21, 9, tzinfo=UTC)
    assert terminal.next_run_at is None


def test_due_window_exact_occurrence_local_date_identity() -> None:
    # Occurrence identity is (schedule_id, latest_local_date) in the schedule
    # zone. The local date is exact, not a due-date tolerance window.
    daily = dict(
        local_time_minute=9 * 60,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2027, 9, 30, 12, tzinfo=UTC),
    )
    # UTC local date equals the UTC due date.
    utc_window = due_window(
        now=datetime(2026, 9, 11, 12, tzinfo=UTC),
        zone_name="UTC",
        **daily,
    )
    assert utc_window is not None
    assert utc_window.latest_local_date == date(2026, 9, 11)
    assert utc_window.latest_due_at == datetime(2026, 9, 11, 9, tzinfo=UTC)
    # A fixed+7 zone: the local calendar date is one day ahead of the UTC due
    # date, so the identity contract must use the exact local date.
    ho_chi_minh = dict(
        local_time_minute=2 * 60,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2027, 9, 30, 12, tzinfo=UTC),
    )
    ahead = due_window(
        now=datetime(2026, 9, 11, 20, tzinfo=UTC),
        zone_name="Asia/Ho_Chi_Minh",
        **ho_chi_minh,
    )
    assert ahead is not None
    assert ahead.latest_local_date == date(2026, 9, 12)
    assert ahead.latest_due_at == datetime(2026, 9, 11, 19, tzinfo=UTC)
    # Local midnight boundary just after midnight still belongs to the new
    # local day even when the UTC due date is the previous calendar day.
    midnight = dict(
        local_time_minute=0,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 9, 1),
        ends_at=datetime(2027, 9, 30, 12, tzinfo=UTC),
    )
    after_midnight = due_window(
        now=datetime(2026, 9, 11, 17, 20, tzinfo=UTC),
        zone_name="Asia/Ho_Chi_Minh",
        **midnight,
    )
    assert after_midnight is not None
    assert after_midnight.latest_local_date == date(2026, 9, 12)
    assert after_midnight.latest_due_at == datetime(2026, 9, 11, 17, tzinfo=UTC)
    # Spring-forward gap (Europe/London 2026-03-29): 01:30 is pushed to 01:00
    # UTC, which is still in the future of 00:30 UTC, so the exact local date
    # steps back to the previous eligible day.
    gap = due_window(
        now=datetime(2026, 3, 29, 0, 30, tzinfo=UTC),
        zone_name="Europe/London",
        local_time_minute=90,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 3, 1),
        ends_at=datetime(2026, 4, 30, 12, tzinfo=UTC),
    )
    assert gap is not None
    assert gap.latest_local_date == date(2026, 3, 28)
    assert gap.latest_due_at == datetime(2026, 3, 28, 1, 30, tzinfo=UTC)
    # Fall-back fold (Europe/London 2026-10-25): 01:30 uses the earlier fold
    # instant 00:30 UTC and keeps the same local date.
    fold = due_window(
        now=datetime(2026, 10, 25, 0, 35, tzinfo=UTC),
        zone_name="Europe/London",
        local_time_minute=90,
        weekday_mask_value=ALL_WEEKDAYS,
        starts_on=date(2026, 10, 1),
        ends_at=datetime(2026, 11, 30, 12, tzinfo=UTC),
    )
    assert fold is not None
    assert fold.latest_local_date == date(2026, 10, 25)
    assert fold.latest_due_at == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)


def test_quiet_hours_support_cross_midnight_and_dst_resolution() -> None:
    preferences = SchedulePreferences("UTC", True, 22 * 60, 8 * 60, 1)
    moment = datetime(2026, 9, 11, 23, tzinfo=UTC)
    assert in_quiet_hours(moment, preferences)
    assert quiet_hours_end(moment, preferences) == datetime(2026, 9, 12, 8, tzinfo=UTC)
    assert not in_quiet_hours(datetime(2026, 9, 11, 12, tzinfo=UTC), preferences)


def test_definition_enforces_lead_horizon_and_content_bounds() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    definition = build_definition(
        kind=ScheduleKind.REMINDER,
        recurrence=RecurrenceKind.ONCE,
        timezone_name="UTC",
        local_date=date(2026, 9, 12),
        local_time_minute=13 * 60,
        weekday_mask_value=0,
        reminder_text="Call Mum",
        now=now,
        minimum_lead_seconds=60,
        horizon_days=365,
        text_limit=100,
    )
    assert definition.first_run_at == datetime(2026, 9, 12, 13, tzinfo=UTC)
    assert definition.reminder_text == "Call Mum"
    exact_lead = build_definition(
        kind=ScheduleKind.REMINDER,
        recurrence=RecurrenceKind.ONCE,
        timezone_name="UTC",
        local_date=date(2026, 9, 11),
        local_time_minute=12 * 60 + 1,
        weekday_mask_value=0,
        reminder_text="One minute",
        now=now,
        minimum_lead_seconds=60,
        horizon_days=365,
        text_limit=100,
    )
    assert exact_lead.first_run_at == datetime(2026, 9, 11, 12, 1, tzinfo=UTC)
    with pytest.raises(ScheduleValidationError):
        build_definition(
            kind=ScheduleKind.REMINDER,
            recurrence=RecurrenceKind.ONCE,
            timezone_name="UTC",
            local_date=date(2026, 9, 11),
            local_time_minute=12 * 60,
            weekday_mask_value=0,
            reminder_text="too soon",
            now=now,
            minimum_lead_seconds=60,
            horizon_days=365,
            text_limit=100,
        )
    with pytest.raises(ScheduleValidationError):
        build_definition(
            kind=ScheduleKind.REMINDER,
            recurrence=RecurrenceKind.ONCE,
            timezone_name="UTC",
            local_date=date(2026, 9, 12),
            local_time_minute=13 * 60,
            weekday_mask_value=0,
            reminder_text="hidden\u0085control",
            now=now,
            minimum_lead_seconds=60,
            horizon_days=365,
            text_limit=100,
        )
