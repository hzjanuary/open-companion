"""Optional durable worker for Qdrant explicit-memory derived state."""

import argparse
import asyncio
import logging
import socket

from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingProvider,
    SemanticMemoryIndex,
    collection_name,
    embedding_version,
)
from app.core.config import Settings
from app.domain.persistence import (
    SemanticMemoryIndexJobStatus,
    SemanticMemoryIndexOperation,
)
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderOperation,
    WorkloadClass,
)
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.database.database import Database
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)
from app.infrastructure.governed_provider import GovernedEmbeddingProvider
from app.infrastructure.rate_limit import RedisRateLimiter
from app.infrastructure.semantic_memory import (
    create_embedding_provider,
    create_semantic_index,
    embed_with_controls,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder, MetricsHttpExporter
from app.runtime.lifecycle import RuntimeLifecycle

logger = logging.getLogger(__name__)


def worker_name() -> str:
    return f"semantic-memory-{socket.gethostname()}"


async def consume_once(
    settings: Settings,
    database: Database,
    owner: str | None = None,
    provider: EmbeddingProvider | None = None,
    index: SemanticMemoryIndex | None = None,
    telemetry: MetricsRecorder | None = None,
    force: bool = False,
) -> int:
    if not (
        (force or settings.semantic_memory_enabled)
        and (force or settings.semantic_memory_worker_enabled)
        and settings.embedding_provider
        and settings.embedding_model
    ):
        return 0
    version = embedding_version(
        settings.embedding_provider,
        settings.embedding_model,
        settings.embedding_dimension,
    )
    repository = SqlAlchemySemanticMemoryRepository(database.session_factory)
    recorder = telemetry or NoOpMetricsRecorder()
    owns_index = index is None
    owns_provider = provider is None
    active_index = index or create_semantic_index(settings)
    active_provider = provider or create_embedding_provider(settings)
    governance_mode = GovernanceMode(settings.provider_governance_mode)
    governance_limiter = (
        RedisRateLimiter(settings)
        if governance_mode != GovernanceMode.LEGACY and settings.rate_limit_enabled
        else None
    )
    governance_concurrency = (
        RedisConcurrencyLimiter(settings)
        if governance_mode != GovernanceMode.LEGACY
        and settings.provider_concurrency_enabled
        else None
    )
    lease_owner = owner or worker_name()
    processed = 0
    try:
        for job in await repository.claim(
            lease_owner,
            settings.semantic_memory_job_batch_size,
            settings.semantic_memory_job_lease_seconds,
        ):
            recorder.increment(
                "january_semantic_memory_index_jobs_total",
                operation=job.operation.value,
                outcome="claimed",
            )
            try:
                if job.target_collection is None:
                    target_collection = await repository.active_collection(
                        job.embedding_version,
                        collection_name(
                            settings.qdrant_collection_prefix,
                            job.embedding_version,
                        ),
                    )
                else:
                    target_collection = job.target_collection
                if job.operation == SemanticMemoryIndexOperation.DELETE:
                    await active_index.delete(target_collection, job.memory_id)
                else:
                    await active_index.ensure_collection(
                        target_collection, settings.embedding_dimension
                    )
                    canonical = await repository.point_for_upsert(
                        job.memory_id, job.embedding_version
                    )
                    if canonical is None or job.embedding_version != version:
                        await repository.complete(job.id, lease_owner)
                        recorder.increment(
                            "january_semantic_memory_index_jobs_total",
                            operation=job.operation.value,
                            outcome="no_op",
                        )
                        recorder.increment(
                            "january_semantic_memory_index_operations_total",
                            operation=job.operation.value,
                            outcome="no_op",
                            embedding_version=job.embedding_version,
                        )
                        continue
                    point, content = canonical
                    provider_for_job = active_provider
                    if governance_mode != GovernanceMode.LEGACY:
                        governance = SqlAlchemyProviderGovernanceRepository(
                            database.session_factory,
                            mode=governance_mode,
                            reservation_lease_seconds=(
                                settings.provider_reservation_lease_seconds
                            ),
                        )
                        governed_source = await governance.semantic_source(job.id)
                        routes = await governance.resolve_routes(
                            governed_source,
                            WorkloadClass.EMBEDDING,
                            {
                                "embedding_dimension": settings.embedding_dimension,
                                "embedding_version": version,
                                "allowed_data_classes": ["local"],
                                "require_current_health": True,
                            },
                        )
                        if not routes:
                            recorder.increment(
                                "january_provider_routing_decisions_total",
                                workload="embedding",
                                operation=(
                                    "semantic_rebuild"
                                    if "_rebuild_" in target_collection
                                    else "semantic_index"
                                ),
                                route_role="primary",
                                outcome="denied",
                                reason="no_route",
                            )
                            raise ProviderGovernanceUnavailable(
                                "no eligible embedding route"
                            )
                        route = routes[0]
                        if (
                            route.provider_id.value != active_provider.provider_id
                            or route.model != active_provider.model
                        ):
                            raise ProviderGovernanceUnavailable(
                                "embedding route does not match configured adapter"
                            )
                        operation = (
                            ProviderOperation.SEMANTIC_REBUILD
                            if "_rebuild_" in target_collection
                            else ProviderOperation.SEMANTIC_INDEX
                        )
                        provider_for_job = GovernedEmbeddingProvider(
                            active_provider,
                            route,
                            governed_source,
                            operation,
                            governance,
                            settings,
                            governance_limiter,
                            governance_concurrency,
                            recorder,
                        )
                    vector = await embed_with_controls(
                        settings, provider_for_job, content, recorder
                    )
                    # A privacy/delete transaction can commit during embedding I/O.
                    fresh = await repository.point_for_upsert(
                        job.memory_id, job.embedding_version
                    )
                    if fresh is None:
                        await active_index.delete(target_collection, job.memory_id)
                    elif fresh[1] == content:
                        await active_index.upsert(target_collection, fresh[0], vector)
                    # An explicit correction may commit during embedding I/O.
                    # Its reopened job owns the refreshed vector; never attach
                    # this old vector to the newly corrected canonical text.
                if await repository.complete(job.id, lease_owner):
                    processed += 1
                    recorder.increment(
                        "january_semantic_memory_index_jobs_total",
                        operation=job.operation.value,
                        outcome="completed",
                    )
                    recorder.increment(
                        "january_semantic_memory_index_operations_total",
                        operation=job.operation.value,
                        outcome="success",
                        embedding_version=job.embedding_version,
                    )
            except Exception as exc:
                category = _error_category(exc)
                status = await repository.release(
                    job.id,
                    lease_owner,
                    category,
                    _retry_delay(settings, job.attempt_count),
                    settings.semantic_memory_max_attempts,
                    _retryable(exc),
                )
                outcome = (
                    "failed"
                    if status == SemanticMemoryIndexJobStatus.FAILED
                    else "released"
                )
                recorder.increment(
                    "january_semantic_memory_index_jobs_total",
                    operation=job.operation.value,
                    outcome=outcome,
                )
                recorder.increment(
                    "january_semantic_memory_index_operations_total",
                    operation=job.operation.value,
                    outcome=category,
                    embedding_version=job.embedding_version,
                )
        return processed
    finally:
        if owns_provider:
            await active_provider.aclose()
        if owns_index:
            await active_index.aclose()
        if governance_limiter is not None:
            await governance_limiter.aclose()
        if governance_concurrency is not None:
            await governance_concurrency.aclose()


def _error_category(exc: Exception) -> str:
    """Persist only closed, content-free failure categories in durable jobs."""
    if isinstance(exc, EmbeddingError):
        return exc.category.value
    if isinstance(exc, ProviderGovernanceUnavailable):
        return "governance_unavailable"
    return "qdrant_unavailable" if isinstance(exc, RuntimeError) else "unexpected_error"


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, ProviderGovernanceUnavailable):
        return False
    return exc.retryable if isinstance(exc, EmbeddingError) else True


def _retry_delay(settings: Settings, attempt_count: int) -> float:
    return float(
        min(
            settings.semantic_memory_retry_max_delay_seconds,
            settings.semantic_memory_retry_min_delay_seconds * 2 ** (attempt_count - 1),
        )
    )


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.semantic_memory_worker_enabled:
        return
    database = Database(settings)
    telemetry = (
        InMemoryMetricsRecorder() if settings.metrics_enabled else NoOpMetricsRecorder()
    )
    exporter = (
        MetricsHttpExporter(
            telemetry,
            settings.metrics_bind_host,
            settings.semantic_memory_metrics_port,
        )
        if settings.metrics_export_enabled
        else None
    )
    await database.start()
    if GovernanceMode(settings.provider_governance_mode) == GovernanceMode.ENFORCE:
        governance = SqlAlchemyProviderGovernanceRepository(
            database.session_factory,
            mode=GovernanceMode.ENFORCE,
            reservation_lease_seconds=settings.provider_reservation_lease_seconds,
        )
        await governance.validate_prerequisites(WorkloadClass.EMBEDDING)
    if exporter is not None:
        await exporter.start()
    lifecycle = RuntimeLifecycle("semantic_memory_index_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database, telemetry=telemetry)
            if once:
                return
            if not processed:
                await lifecycle.wait(settings.planning_job_poll_interval_seconds)
    finally:
        lifecycle.close()
        if exporter is not None:
            await exporter.close()
        await database.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
