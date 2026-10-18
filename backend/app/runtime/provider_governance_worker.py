"""Bounded SPEC-026 reservation and ambiguous-I/O recovery runtime."""

import argparse
import asyncio
import socket
from time import perf_counter

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.domain.provider_governance import GovernanceMode
from app.infrastructure.database.database import Database
from app.infrastructure.database.provider_governance import (
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder, MetricsHttpExporter
from app.runtime.lifecycle import RuntimeLifecycle


def worker_name(settings: Settings) -> str:
    return f"{settings.provider_governance_owner_name}-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    *,
    telemetry: MetricsRecorder | None = None,
) -> int:
    if (
        not settings.provider_governance_worker_enabled
        or GovernanceMode(settings.provider_governance_mode) == GovernanceMode.LEGACY
    ):
        return 0
    recorder = telemetry or NoOpMetricsRecorder()
    repository = SqlAlchemyProviderGovernanceRepository(
        database.session_factory,
        mode=GovernanceMode(settings.provider_governance_mode),
        reservation_lease_seconds=settings.provider_reservation_lease_seconds,
    )
    started = perf_counter()
    try:
        result = await repository.recover_stale(settings.provider_governance_batch_size)
    except Exception:
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="reservation",
            outcome="failed",
        )
        recorder.observe(
            "january_worker_operation_duration_seconds",
            perf_counter() - started,
            runtime="provider_governance",
            operation="provider_recovery_batch",
            outcome="failed",
        )
        recorder.increment(
            "january_worker_operations_total",
            runtime="provider_governance",
            operation="provider_recovery_batch",
            outcome="failed",
        )
        raise
    for _ in range(result.released):
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="reservation",
            outcome="completed",
        )
    for _ in range(result.ambiguous):
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="io_possible",
            outcome="completed",
        )
    for transition in result.health_transitions:
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="health_evaluation",
            outcome="completed",
        )
        recorder.increment(
            "january_provider_health_transitions_total",
            provider=transition.provider_id.value,
            from_state=(
                transition.from_state.value
                if transition.from_state is not None
                else "unknown"
            ),
            to_state=(
                transition.to_state.value
                if transition.to_state is not None
                else "unknown"
            ),
            reason=transition.reason,
        )
    if not result.released:
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="reservation",
            outcome="no_op",
        )
    if not result.ambiguous:
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="io_possible",
            outcome="no_op",
        )
    if not result.health_transitions:
        recorder.increment(
            "january_provider_governance_recovery_total",
            operation="health_evaluation",
            outcome="no_op",
        )
    outcome = (
        "completed"
        if result.released or result.ambiguous or result.health_transitions
        else "no_op"
    )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        perf_counter() - started,
        runtime="provider_governance",
        operation="provider_recovery_batch",
        outcome=outcome,
    )
    recorder.increment(
        "january_worker_operations_total",
        runtime="provider_governance",
        operation="provider_recovery_batch",
        outcome=outcome,
    )
    return result.released + result.ambiguous + len(result.health_transitions)


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.provider_governance_worker_enabled:
        return
    database = Database(settings)
    await database.start()
    recorder = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    exporter = (
        MetricsHttpExporter(
            recorder,
            settings.metrics_bind_host,
            settings.provider_governance_metrics_port,
        )
        if settings.metrics_export_enabled
        else None
    )
    if exporter is not None:
        await exporter.start()
    lifecycle = RuntimeLifecycle("provider_governance_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database, telemetry=recorder)
            if once:
                return
            if processed == 0:
                await lifecycle.wait(settings.provider_governance_poll_interval_seconds)
    finally:
        lifecycle.close()
        if exporter is not None:
            await exporter.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
