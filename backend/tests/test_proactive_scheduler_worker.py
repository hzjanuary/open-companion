import asyncio
from typing import cast
from uuid import UUID

import pytest

from app.core.config import Settings
from app.domain.scheduling import (
    MaterializationOutcome,
    MaterializationResult,
    ScheduleKind,
)
from app.infrastructure.database.database import Database
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime import proactive_scheduler_worker
from app.runtime.proactive_scheduler_worker import consume_once


def _enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        proactive_scheduling_enabled=True,
        scheduler_worker_enabled=True,
        outbound_delivery_enabled=True,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_platform_connection_id=UUID(int=1),
    )


def test_disabled_scheduler_performs_no_database_work() -> None:
    class DatabaseThatMustNotBeUsed:
        @property
        def session_factory(self) -> object:
            raise AssertionError("disabled scheduler touched the database")

    assert (
        asyncio.run(
            consume_once(
                Settings(_env_file=None),
                cast(Database, DatabaseThatMustNotBeUsed()),
            )
        )
        == 0
    )


def test_scheduler_emits_closed_materialization_and_worker_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repository:
        def __init__(self, _: object) -> None:
            pass

        async def materialize_due(self, _: object, __: int) -> MaterializationResult:
            return MaterializationResult(
                2,
                (
                    (ScheduleKind.REMINDER, MaterializationOutcome.MATERIALIZED),
                    (ScheduleKind.CHECK_IN, MaterializationOutcome.STALE),
                ),
            )

        async def claim(self, _: str, __: object, ___: int, ____: int) -> list[object]:
            return []

        async def backlog_counts(self, _: int) -> dict[tuple[str, str], int]:
            return {
                ("reminder", "pending"): 3,
                ("reminder", "leased"): 1,
                ("check_in", "pending"): 0,
                ("check_in", "leased"): 0,
            }

    class DatabaseStub:
        session_factory = object()

    monkeypatch.setattr(
        proactive_scheduler_worker, "SqlAlchemySchedulingRepository", Repository
    )
    metrics = InMemoryMetricsRecorder()
    settings = _enabled_settings()
    assert (
        asyncio.run(
            consume_once(
                settings,
                cast(Database, DatabaseStub()),
                owner="scheduler-test",
                telemetry=metrics,
            )
        )
        == 2
    )
    assert (
        metrics.counter_value(
            "january_schedule_occurrences_total",
            kind="reminder",
            outcome="materialized",
        )
        == 1
    )
    assert (
        metrics.gauge_value(
            "january_schedule_backlog", kind="reminder", status="pending"
        )
        == 3
    )
    assert (
        metrics.counter_value(
            "january_schedule_occurrences_total", kind="check_in", outcome="stale"
        )
        == 1
    )
    assert (
        metrics.counter_value(
            "january_worker_operations_total",
            runtime="scheduler",
            operation="schedule_batch",
            outcome="completed",
        )
        == 1
    )


def test_scheduler_failure_is_reported_and_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingRepository:
        def __init__(self, _: object) -> None:
            pass

        async def materialize_due(self, _: object, __: int) -> MaterializationResult:
            raise RuntimeError("synthetic database failure")

    class DatabaseStub:
        session_factory = object()

    monkeypatch.setattr(
        proactive_scheduler_worker,
        "SqlAlchemySchedulingRepository",
        FailingRepository,
    )
    metrics = InMemoryMetricsRecorder()
    settings = _enabled_settings()
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        asyncio.run(
            consume_once(
                settings,
                cast(Database, DatabaseStub()),
                telemetry=metrics,
            )
        )
    assert (
        metrics.counter_value(
            "january_worker_operations_total",
            runtime="scheduler",
            operation="schedule_batch",
            outcome="failed",
        )
        == 1
    )
