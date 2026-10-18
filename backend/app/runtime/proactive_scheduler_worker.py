"""Bounded, no-network materializer for private proactive schedules."""

import argparse
import asyncio
import logging
import socket
from datetime import UTC, datetime
from time import perf_counter

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.scheduling import SqlAlchemySchedulingRepository
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def worker_name(settings: Settings) -> str:
    return f"{settings.scheduler_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    *,
    owner: str | None = None,
    telemetry: MetricsRecorder | None = None,
    now: datetime | None = None,
) -> int:
    if not (
        settings.proactive_scheduling_enabled and settings.scheduler_worker_enabled
    ):
        return 0
    recorder = telemetry or NoOpMetricsRecorder()
    started = perf_counter()
    moment = now or datetime.now(UTC)
    repository = SqlAlchemySchedulingRepository(database.session_factory)
    try:
        materialization = await repository.materialize_due(
            moment, settings.scheduler_batch_size
        )
        for materialized_kind, materialized_outcome in materialization.events:
            recorder.increment(
                "january_schedule_occurrences_total",
                kind=materialized_kind.value,
                outcome=materialized_outcome.value,
            )
        claims = await repository.claim(
            owner or worker_name(settings),
            moment,
            settings.scheduler_batch_size,
            settings.scheduler_lease_seconds,
        )
        outcomes: dict[tuple[str, str], int] = {}
        for claim in claims:
            claim_outcome = "reclaimed" if claim.attempt_count > 1 else "claimed"
            recorder.increment(
                "january_schedule_occurrences_total",
                kind=claim.kind.value,
                outcome=claim_outcome,
            )
            enqueue_outcome = await repository.enqueue_claim(
                claim, owner or worker_name(settings), moment
            )
            key = (claim.kind.value, enqueue_outcome)
            outcomes[key] = outcomes.get(key, 0) + 1
        for (claimed_kind, claimed_outcome), count in outcomes.items():
            recorder.increment(
                "january_schedule_occurrences_total",
                count,
                kind=claimed_kind,
                outcome=claimed_outcome,
            )
        backlog = await repository.backlog_counts(settings.scheduler_batch_size)
        for (backlog_kind, backlog_status), backlog_count in backlog.items():
            recorder.set_gauge(
                "january_schedule_backlog",
                backlog_count,
                kind=backlog_kind,
                status=backlog_status,
            )
        count = materialization.count + len(claims)
        batch_outcome = "completed" if count else "no_op"
    except Exception:  # noqa: BLE001 - bounded result, lease remains recoverable
        recorder.increment(
            "january_worker_operations_total",
            runtime="scheduler",
            operation="schedule_batch",
            outcome="failed",
        )
        recorder.observe(
            "january_worker_operation_duration_seconds",
            perf_counter() - started,
            runtime="scheduler",
            operation="schedule_batch",
            outcome="failed",
        )
        raise
    recorder.increment(
        "january_worker_operations_total",
        runtime="scheduler",
        operation="schedule_batch",
        outcome=batch_outcome,
    )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        perf_counter() - started,
        runtime="scheduler",
        operation="schedule_batch",
        outcome=batch_outcome,
    )
    logger.info(
        "schedule_batch_complete materialized=%s claimed=%s",
        materialization.count,
        len(claims),
    )
    return count


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.scheduler_worker_enabled:
        return
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    lifecycle = RuntimeLifecycle("proactive_scheduler_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database, telemetry=telemetry)
            if once:
                return
            if processed == 0:
                await lifecycle.wait(settings.scheduler_poll_interval_seconds)
    finally:
        lifecycle.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
