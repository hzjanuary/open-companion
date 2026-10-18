"""Transactional outbox dispatcher for Redis ingress-reference events."""

import asyncio
from time import perf_counter

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
from app.infrastructure.queue.redis_streams import RedisIngressQueue
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.lifecycle import RuntimeLifecycle


async def dispatch_once(
    settings: Settings,
    repository: SqlAlchemyDurableIngressRepository,
    queue: RedisIngressQueue,
    telemetry: MetricsRecorder | None = None,
) -> int:
    recorder = telemetry or NoOpMetricsRecorder()
    started = perf_counter()
    events = await repository.pending_events(settings.ingress_outbox_batch_size)
    for event in events:
        queue_event = await repository.event_for(event.id)
        if queue_event is None:
            continue
        try:
            await queue.publish(queue_event)
        except Exception:
            await repository.mark_publish_failed(
                event.id, settings.ingress_outbox_poll_interval_seconds
            )
            continue
        await repository.mark_published(event.id)
    recorder.increment(
        "january_worker_operations_total",
        runtime="ingress_dispatcher",
        operation="publish_batch",
        outcome="completed",
    )
    recorder.observe(
        "january_worker_operation_duration_seconds",
        perf_counter() - started,
        runtime="ingress_dispatcher",
        operation="publish_batch",
        outcome="completed",
    )
    return len(events)


async def run() -> None:
    settings = Settings()
    database = Database(settings)
    queue = RedisIngressQueue(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    await database.start()
    repository = SqlAlchemyDurableIngressRepository(
        database.session_factory, settings.ingress_event_schema_version
    )
    lifecycle = RuntimeLifecycle("ingress_dispatcher")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await dispatch_once(settings, repository, queue, telemetry)
            if processed == 0:
                await lifecycle.wait(settings.ingress_outbox_poll_interval_seconds)
    except asyncio.CancelledError:
        raise
    finally:
        lifecycle.close()
        await queue.aclose()
        await database.stop()


if __name__ == "__main__":
    asyncio.run(run())
