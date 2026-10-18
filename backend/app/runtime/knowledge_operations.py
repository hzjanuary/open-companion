"""Content-free status, reconciliation, and rebuild operations for knowledge RAG."""

import argparse
import asyncio
import json
from uuid import uuid4

from app.application.knowledge import KnowledgeVectorIndex, knowledge_collection_name
from app.application.semantic_memory import EmbeddingProvider, embedding_version
from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.knowledge import SqlAlchemyKnowledgeRepository
from app.infrastructure.knowledge import QdrantKnowledgeIndex
from app.infrastructure.semantic_memory import create_embedding_provider


async def operate(
    command: str,
    confirmed: bool,
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    index: KnowledgeVectorIndex | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    configured = settings or Settings()
    active_database = database or Database(configured)
    owns_database = database is None
    if owns_database:
        await active_database.start()
    repository = SqlAlchemyKnowledgeRepository(active_database.session_factory)
    try:
        if not configured.embedding_provider or not configured.embedding_model:
            if command != "status":
                raise RuntimeError("embedding provider/model must be configured")
            return {
                "enabled": configured.knowledge_rag_enabled,
                "worker_enabled": configured.knowledge_index_worker_enabled,
                "embedding_version": None,
                "collection": None,
                "active_chunk_count": len(await repository.active_chunk_ids()),
                "job_counts": await repository.job_counts(),
                "index_available": False,
                "indexed_point_count": None,
                "drift_count": None,
                "scheduled": 0,
                "stale_deleted": 0,
            }
        version = embedding_version(
            configured.embedding_provider,
            configured.embedding_model,
            configured.embedding_dimension,
        )
        default_collection = knowledge_collection_name(
            configured.knowledge_qdrant_collection_prefix, version
        )
        collection = await repository.active_collection(version, default_collection)
        active_index = index or QdrantKnowledgeIndex(configured.qdrant_url)
        owns_index = index is None
        try:
            if command != "status" and not confirmed:
                raise RuntimeError("--confirm is required")
            scheduled = stale_deleted = 0
            if command in {"backfill", "reconcile"}:
                await active_index.ensure_collection(
                    collection, configured.embedding_dimension
                )
                active = set(await repository.active_chunk_ids())
                indexed = set(await active_index.list_chunk_ids(collection))
                if command == "reconcile":
                    for chunk_id in indexed - active:
                        await active_index.delete(collection, chunk_id)
                        stale_deleted += 1
                # Rebuilding all active chunks is deterministic and coalesces jobs.
                scheduled = await repository.schedule_rebuild(version, collection)
            elif command == "rebuild":
                collection = f"{default_collection}_rebuild_{uuid4().hex[:12]}"
                await active_index.ensure_collection(
                    collection, configured.embedding_dimension
                )
                scheduled = await repository.schedule_rebuild(version, collection)
                await _build_and_activate(
                    configured,
                    active_database,
                    repository,
                    active_index,
                    collection,
                    version,
                    provider,
                )
            available = await active_index.health()
            indexed_count = await active_index.count(collection) if available else None
            drift = None
            if command == "status" and available:
                drift = len(
                    set(await repository.active_chunk_ids())
                    ^ set(await active_index.list_chunk_ids(collection))
                )
            return {
                "enabled": configured.knowledge_rag_enabled,
                "worker_enabled": configured.knowledge_index_worker_enabled,
                "embedding_version": version,
                "collection": collection,
                "active_chunk_count": len(await repository.active_chunk_ids()),
                "job_counts": await repository.job_counts(),
                "index_available": available,
                "indexed_point_count": indexed_count,
                "drift_count": drift,
                "scheduled": scheduled,
                "stale_deleted": stale_deleted,
            }
        finally:
            if owns_index:
                await active_index.aclose()
    finally:
        if owns_database:
            await active_database.stop()


async def _build_and_activate(
    settings: Settings,
    database: Database,
    repository: SqlAlchemyKnowledgeRepository,
    index: KnowledgeVectorIndex,
    collection: str,
    version: str,
    provider: EmbeddingProvider | None,
) -> None:
    from app.runtime.knowledge_index_worker import consume_once

    active_provider = provider or create_embedding_provider(settings)
    owns_provider = provider is None
    try:
        while await repository.target_jobs_remaining(version, collection):
            completed = await consume_once(
                settings,
                database,
                provider=active_provider,
                index=index,
                owner=f"knowledge-rebuild-{uuid4().hex}",
            )
            if not completed:
                raise RuntimeError("fresh knowledge collection build did not complete")
        active = set(await repository.active_chunk_ids())
        indexed = set(await index.list_chunk_ids(collection))
        for chunk_id in indexed - active:
            await index.delete(collection, chunk_id)
        if set(await index.list_chunk_ids(collection)) != active:
            raise RuntimeError("fresh collection does not match PostgreSQL authority")
        await repository.activate_collection(version, collection)
    finally:
        if owns_provider:
            await active_provider.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("status", "backfill", "reconcile", "rebuild")
    )
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(operate(args.command, args.confirm)), sort_keys=True))


if __name__ == "__main__":
    main()
