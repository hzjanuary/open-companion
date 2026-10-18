"""Dedicated no-network raw-content retention runtime."""

import argparse
import asyncio
import logging
from time import perf_counter

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.semantic_memory import embedding_version
from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


async def consume_once(
    settings: Settings, database: Database, telemetry: MetricsRecorder | None = None
) -> int:
    recorder = telemetry or NoOpMetricsRecorder()
    started = perf_counter()
    try:
        index_version = (
            embedding_version(
                settings.embedding_provider,
                settings.embedding_model,
                settings.embedding_dimension,
            )
            if settings.embedding_provider is not None
            and settings.embedding_model is not None
            else None
        )
        counts = await SqlAlchemyRetentionRepository(
            database.session_factory, index_version
        ).redact_once(
            retention_days=settings.raw_content_retention_days,
            governance_audit_retention_days=settings.governance_audit_retention_days,
            schedule_history_retention_days=settings.scheduler_history_retention_days,
            batch_size=settings.retention_batch_size,
        )
    except Exception:  # noqa: BLE001 - record bounded outcome, then fail the batch
        recorder.increment(
            "january_worker_operations_total",
            runtime="retention",
            operation="redaction_batch",
            outcome="failed",
        )
        recorder.observe(
            "january_worker_operation_duration_seconds",
            perf_counter() - started,
            runtime="retention",
            operation="redaction_batch",
            outcome="failed",
        )
        raise
    total = sum(
        (
            counts.incoming_updates,
            counts.messages,
            counts.response_plans,
            counts.outbound_actions,
            counts.command_arguments,
            counts.summaries,
            counts.audit_events,
            counts.control_audit_events,
            counts.memories,
            counts.schedules,
            counts.schedule_occurrences,
            counts.voice_artifacts,
        )
    )
    logger.info("retention_redaction_complete counts=%s", counts)
    recorder.increment(
        "january_worker_operations_total",
        runtime="retention",
        operation="redaction_batch",
        outcome="completed",
    )
    if counts.summaries:
        recorder.increment(
            "january_summary_retention_events_total",
            counts.summaries,
            outcome="expired",
        )
    if counts.audit_events or counts.control_audit_events:
        recorder.increment(
            "january_governance_audit_retention_total",
            counts.audit_events + counts.control_audit_events,
            outcome="purged",
        )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        perf_counter() - started,
        runtime="retention",
        operation="redaction_batch",
        outcome="completed",
    )
    return total


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.retention_worker_enabled:
        return
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    lifecycle = RuntimeLifecycle("retention_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database, telemetry)
            if once:
                return
            if processed == 0:
                await lifecycle.wait(settings.retention_worker_poll_interval_seconds)
    finally:
        lifecycle.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
