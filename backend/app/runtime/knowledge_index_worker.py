"""Replayable knowledge-index worker with no database scope across external I/O."""

from __future__ import annotations

import asyncio
import socket
from uuid import uuid4

from app.application.knowledge import KnowledgeVectorIndex
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingProvider,
    embedding_version,
)
from app.core.config import Settings
from app.domain.knowledge import KnowledgeIndexJobStatus, KnowledgeIndexOperation
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderOperation,
    WorkloadClass,
)
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.database.database import Database
from app.infrastructure.database.knowledge import SqlAlchemyKnowledgeRepository
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.governed_provider import GovernedEmbeddingProvider
from app.infrastructure.knowledge import QdrantKnowledgeIndex
from app.infrastructure.rate_limit import RedisRateLimiter
from app.infrastructure.semantic_memory import (
    create_embedding_provider,
    embed_with_controls,
)
from app.runtime.lifecycle import RuntimeLifecycle


async def consume_once(
    settings: Settings,
    database: Database,
    *,
    telemetry: MetricsRecorder | None = None,
    provider: EmbeddingProvider | None = None,
    index: KnowledgeVectorIndex | None = None,
    owner: str | None = None,
) -> int:
    recorder = telemetry or NoOpMetricsRecorder()
    repository = SqlAlchemyKnowledgeRepository(database.session_factory)
    lease_owner = owner or f"{socket.gethostname()}:{uuid4()}"
    jobs = await repository.claim(
        lease_owner,
        settings.knowledge_job_batch_size,
        settings.knowledge_job_lease_seconds,
    )
    if not jobs:
        return 0
    active_provider = provider
    active_index = index or QdrantKnowledgeIndex(settings.qdrant_url)
    owns_provider = provider is None
    owns_index = index is None
    limiter = RedisRateLimiter(settings) if settings.rate_limit_enabled else None
    concurrency = (
        RedisConcurrencyLimiter(settings)
        if settings.provider_concurrency_enabled
        else None
    )
    processed = 0
    version = embedding_version(
        settings.embedding_provider or "",
        settings.embedding_model or "",
        settings.embedding_dimension,
    )
    try:
        for job in jobs:
            try:
                if job.operation == KnowledgeIndexOperation.DELETE:
                    await active_index.delete(job.target_collection, job.chunk_id)
                else:
                    canonical = await repository.point_for_upsert(job.id)
                    if canonical is None or job.embedding_version != version:
                        if await repository.complete(job.id, lease_owner):
                            processed += 1
                            recorder.increment(
                                "january_knowledge_index_jobs_total",
                                operation=job.operation.value,
                                outcome="no_op",
                            )
                        continue
                    if active_provider is None:
                        active_provider = create_embedding_provider(settings)
                    point, content = canonical
                    job_provider = active_provider
                    if settings.provider_governance_mode != "legacy":
                        governance = SqlAlchemyProviderGovernanceRepository(
                            database.session_factory,
                            mode=GovernanceMode(settings.provider_governance_mode),
                            reservation_lease_seconds=settings.provider_reservation_lease_seconds,
                        )
                        source = await governance.knowledge_source(job.id)
                        routes = await governance.resolve_routes(
                            source,
                            WorkloadClass.EMBEDDING,
                            {
                                "embedding_dimension": settings.embedding_dimension,
                                "embedding_version": version,
                                "allowed_data_classes": ["local"],
                                "require_current_health": True,
                            },
                        )
                        if (
                            not routes
                            or routes[0].provider_id.value
                            != active_provider.provider_id
                            or routes[0].model != active_provider.model
                        ):
                            raise ProviderGovernanceUnavailable(
                                "no eligible knowledge embedding route"
                            )
                        operation = (
                            ProviderOperation.KNOWLEDGE_REBUILD
                            if "_rebuild_" in job.target_collection
                            else ProviderOperation.KNOWLEDGE_INDEX
                        )
                        job_provider = GovernedEmbeddingProvider(
                            active_provider,
                            routes[0],
                            source,
                            operation,
                            governance,
                            settings,
                            limiter,
                            concurrency,
                            recorder,
                        )
                    vector = await embed_with_controls(
                        settings, job_provider, content, recorder
                    )
                    fresh = await repository.point_for_upsert(job.id)
                    if fresh is None or fresh[1] != content:
                        await active_index.delete(job.target_collection, job.chunk_id)
                    else:
                        await active_index.ensure_collection(
                            job.target_collection, settings.embedding_dimension
                        )
                        await active_index.upsert(
                            job.target_collection, fresh[0], vector
                        )
                if await repository.complete(job.id, lease_owner):
                    processed += 1
                    recorder.increment(
                        "january_knowledge_index_jobs_total",
                        operation=job.operation.value,
                        outcome="completed",
                    )
            except Exception as exc:
                status = await repository.release(
                    job.id,
                    lease_owner,
                    _error_category(exc),
                    _retry_delay(settings, job.attempt_count),
                    settings.knowledge_max_attempts,
                    _retryable(exc),
                )
                recorder.increment(
                    "january_knowledge_index_jobs_total",
                    operation=job.operation.value,
                    outcome="failed"
                    if status == KnowledgeIndexJobStatus.FAILED
                    else "released",
                )
        return processed
    finally:
        if owns_provider and active_provider is not None:
            await active_provider.aclose()
        if owns_index:
            await active_index.aclose()
        if limiter is not None:
            await limiter.aclose()
        if concurrency is not None:
            await concurrency.aclose()


def _error_category(exc: Exception) -> str:
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
            settings.knowledge_retry_max_delay_seconds,
            settings.knowledge_retry_min_delay_seconds * 2 ** (attempt_count - 1),
        )
    )


async def run(once: bool) -> None:
    settings = Settings()
    if not settings.knowledge_index_worker_enabled:
        return
    database = Database(settings)
    await database.start()
    lifecycle = RuntimeLifecycle("knowledge_index_worker")
    lifecycle.install()
    try:
        while not lifecycle.stopping:
            processed = await consume_once(settings, database)
            if once:
                return
            if not processed:
                await asyncio.sleep(1)
    finally:
        await database.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(run(parser.parse_args().once))
