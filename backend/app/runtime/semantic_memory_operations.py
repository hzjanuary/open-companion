"""Local-only, content-free semantic-memory derived-index operations."""

import argparse
import asyncio
import json
from uuid import uuid4

from app.application.semantic_memory import (
    EmbeddingProvider,
    SemanticMemoryIndex,
    collection_name,
    embedding_version,
)
from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)
from app.infrastructure.semantic_memory import (
    create_embedding_provider,
    create_semantic_index,
)


async def operate(
    command: str,
    confirmed: bool,
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    index: SemanticMemoryIndex | None = None,
    provider: EmbeddingProvider | None = None,
) -> dict[str, object]:
    configured_settings = settings or Settings()
    active_database = database or Database(configured_settings)
    owns_database = database is None
    if owns_database:
        await active_database.start()
    repository = SqlAlchemySemanticMemoryRepository(active_database.session_factory)
    try:
        if command == "status" and (
            not configured_settings.embedding_provider
            or not configured_settings.embedding_model
        ):
            return {
                "enabled": configured_settings.semantic_memory_enabled,
                "worker_enabled": configured_settings.semantic_memory_worker_enabled,
                "provider": None,
                "model": None,
                "embedding_version": None,
                "collection": None,
                "active_memory_count": await repository.active_count(),
                "job_counts": await repository.job_counts(),
                "index_available": False,
                "indexed_point_count": None,
                "drift_count": None,
                "scheduled": 0,
                "stale_deleted": 0,
            }
        if (
            not configured_settings.embedding_provider
            or not configured_settings.embedding_model
        ):
            raise RuntimeError("embedding provider/model must be configured")
        version = embedding_version(
            configured_settings.embedding_provider,
            configured_settings.embedding_model,
            configured_settings.embedding_dimension,
        )
        default_collection = collection_name(
            configured_settings.qdrant_collection_prefix, version
        )
        collection = await repository.active_collection(version, default_collection)
        active_index = index or create_semantic_index(configured_settings)
        owns_index = index is None
        try:
            if command != "status" and not confirmed:
                raise RuntimeError("--confirm is required")
            stale_deleted = 0
            scheduled = 0
            if command == "backfill":
                await active_index.ensure_collection(
                    collection, configured_settings.embedding_dimension
                )
                scheduled = await repository.schedule_upserts(
                    set(await repository.active_ids())
                    - set(await active_index.list_memory_ids(collection)),
                    version,
                    collection,
                )
            elif command == "reconcile":
                await active_index.ensure_collection(
                    collection, configured_settings.embedding_dimension
                )
                active = set(await repository.active_ids())
                indexed = set(await active_index.list_memory_ids(collection))
                scheduled = await repository.schedule_upserts(
                    active - indexed, version, collection
                )
                for memory_id in indexed:
                    if memory_id not in active:
                        await active_index.delete(collection, memory_id)
                        stale_deleted += 1
            elif command == "rebuild":
                collection = f"{default_collection}_rebuild_{uuid4().hex[:12]}"
                await active_index.ensure_collection(
                    collection, configured_settings.embedding_dimension
                )
                scheduled = await repository.schedule_active_upserts(
                    version, collection
                )
                await _build_and_activate(
                    configured_settings,
                    active_database,
                    repository,
                    active_index,
                    collection,
                    version,
                    provider,
                )
            index_available = await active_index.health()
            indexed_point_count: int | None = None
            drift_count: int | None = None
            if index_available:
                try:
                    indexed_point_count = await active_index.count(collection)
                    if command == "status":
                        drift_count = len(
                            set(await repository.active_ids())
                            ^ set(await active_index.list_memory_ids(collection))
                        )
                except RuntimeError:
                    if command != "status":
                        raise
                    index_available = False
            return {
                "enabled": configured_settings.semantic_memory_enabled,
                "worker_enabled": configured_settings.semantic_memory_worker_enabled,
                "provider": configured_settings.embedding_provider,
                "model": configured_settings.embedding_model,
                "embedding_version": version,
                "collection": collection,
                "active_memory_count": await repository.active_count(),
                "job_counts": await repository.job_counts(),
                "index_available": index_available,
                "indexed_point_count": indexed_point_count,
                "drift_count": drift_count,
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
    repository: SqlAlchemySemanticMemoryRepository,
    index: SemanticMemoryIndex,
    collection: str,
    version: str,
    provider: EmbeddingProvider | None = None,
) -> None:
    """Build from canonical rows, prove exact IDs, then atomically route queries."""
    from app.runtime.semantic_memory_index_worker import consume_once

    active_provider = provider or create_embedding_provider(settings)
    owns_provider = provider is None
    try:
        while await repository.target_jobs_remaining(version, collection):
            completed = await consume_once(
                settings,
                database,
                owner=f"semantic-rebuild-{uuid4().hex}",
                provider=active_provider,
                index=index,
                force=True,
            )
            if completed == 0:
                raise RuntimeError("fresh collection build did not complete")
        active_ids = set(await repository.active_ids())
        indexed_ids = set(await index.list_memory_ids(collection))
        for memory_id in indexed_ids - active_ids:
            await index.delete(collection, memory_id)
        if set(await index.list_memory_ids(collection)) != active_ids:
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
