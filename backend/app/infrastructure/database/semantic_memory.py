"""PostgreSQL authority, scheduling, and revalidation for semantic memory."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.application.semantic_memory import SemanticMemoryPoint
from app.domain.persistence import (
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    SemanticMemoryIndexJobStatus,
    SemanticMemoryIndexOperation,
)
from app.infrastructure.database.models import (
    ExplicitMemorySemanticIndexCollectionModel,
    ExplicitMemorySemanticIndexJobModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
)


class SqlAlchemySemanticMemoryRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    @staticmethod
    async def schedule(
        session: AsyncSession,
        memory_id: UUID,
        operation: SemanticMemoryIndexOperation,
        embedding_version: str,
        target_collection: str | None = None,
    ) -> None:
        """Coalesce replayable work; never include canonical text in the job."""
        now = datetime.now(UTC)
        statement = insert(ExplicitMemorySemanticIndexJobModel).values(
            memory_id=memory_id,
            operation=operation,
            embedding_version=embedding_version,
            target_collection=target_collection,
            status=SemanticMemoryIndexJobStatus.PENDING,
            available_at=now,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=None,
            last_error_category=None,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=("memory_id", "operation", "embedding_version"),
                set_={
                    "status": SemanticMemoryIndexJobStatus.PENDING,
                    "available_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": None,
                    "last_error_category": None,
                    "target_collection": target_collection,
                    "updated_at": now,
                },
            )
        )

    @staticmethod
    async def schedule_upserts_for_memory(
        session: AsyncSession,
        memory_id: UUID,
        current_embedding_version: str | None,
    ) -> None:
        """Reopen known correction work without losing an active rebuild target."""
        targets: dict[str, str | None] = {
            version: target
            for version, target in (
                await session.execute(
                    select(
                        ExplicitMemorySemanticIndexJobModel.embedding_version,
                        ExplicitMemorySemanticIndexJobModel.target_collection,
                    ).where(
                        ExplicitMemorySemanticIndexJobModel.memory_id == memory_id,
                        ExplicitMemorySemanticIndexJobModel.operation
                        == SemanticMemoryIndexOperation.UPSERT,
                    )
                )
            ).all()
        }
        if current_embedding_version is not None:
            targets.setdefault(current_embedding_version, None)
        for version, target in sorted(targets.items()):
            await SqlAlchemySemanticMemoryRepository.schedule(
                session, memory_id, SemanticMemoryIndexOperation.UPSERT, version, target
            )

    @staticmethod
    async def schedule_deletes_for_memory(
        session: AsyncSession,
        memory_id: UUID,
        current_embedding_version: str | None,
    ) -> None:
        """Delete every known derived version when canonical content is removed."""
        versions = set(
            await session.scalars(
                select(ExplicitMemorySemanticIndexJobModel.embedding_version).where(
                    ExplicitMemorySemanticIndexJobModel.memory_id == memory_id,
                    ExplicitMemorySemanticIndexJobModel.operation
                    == SemanticMemoryIndexOperation.UPSERT,
                )
            )
        )
        if current_embedding_version is not None:
            versions.add(current_embedding_version)
        for version in versions:
            await SqlAlchemySemanticMemoryRepository.schedule(
                session,
                memory_id,
                SemanticMemoryIndexOperation.DELETE,
                version,
            )

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[ExplicitMemorySemanticIndexJobModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(ExplicitMemorySemanticIndexJobModel)
                        .where(
                            or_(
                                and_(
                                    ExplicitMemorySemanticIndexJobModel.status
                                    == SemanticMemoryIndexJobStatus.PENDING,
                                    ExplicitMemorySemanticIndexJobModel.available_at
                                    <= now,
                                ),
                                and_(
                                    ExplicitMemorySemanticIndexJobModel.status
                                    == SemanticMemoryIndexJobStatus.LEASED,
                                    ExplicitMemorySemanticIndexJobModel.lease_expires_at
                                    < now,
                                ),
                            )
                        )
                        .order_by(
                            ExplicitMemorySemanticIndexJobModel.available_at,
                            ExplicitMemorySemanticIndexJobModel.created_at,
                            ExplicitMemorySemanticIndexJobModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for row in rows:
                    row.status = SemanticMemoryIndexJobStatus.LEASED
                    row.lease_owner = owner
                    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    row.attempt_count += 1
                return rows

    async def complete(self, job_id: UUID, owner: str) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ExplicitMemorySemanticIndexJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != SemanticMemoryIndexJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = SemanticMemoryIndexJobStatus.COMPLETED
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = datetime.now(UTC)
                job.last_error_category = None
                return True

    async def release(
        self,
        job_id: UUID,
        owner: str,
        category: str,
        delay: float,
        max_attempts: int,
        retryable: bool,
    ) -> SemanticMemoryIndexJobStatus | None:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    ExplicitMemorySemanticIndexJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != SemanticMemoryIndexJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return None
                if not retryable or job.attempt_count >= max_attempts:
                    job.status = SemanticMemoryIndexJobStatus.FAILED
                    job.completed_at = datetime.now(UTC)
                else:
                    job.status = SemanticMemoryIndexJobStatus.PENDING
                    job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error_category = category
                return job.status

    async def point_for_upsert(
        self, memory_id: UUID, embedding_version: str
    ) -> tuple[SemanticMemoryPoint, str] | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            item = await session.scalar(
                select(MemoryItemModel).where(
                    MemoryItemModel.id == memory_id,
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                    MemoryItemModel.content.is_not(None),
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
            )
            if item is None or not item.content:
                return None
            return (
                SemanticMemoryPoint(
                    item.id,
                    item.assistant_id,
                    item.platform_connection_id,
                    item.conversation_id,
                    item.scope,
                    embedding_version,
                ),
                item.content,
            )

    async def revalidate_matches(
        self,
        memory_ids: tuple[UUID, ...],
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        scope: MemoryScope,
    ) -> dict[UUID, tuple[str, str, datetime, str]]:
        if not memory_ids:
            return {}
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            owner_policy = aliased(MemoryRecallPolicyModel)
            rows = await session.scalars(
                select(MemoryItemModel)
                .outerjoin(
                    owner_policy,
                    and_(
                        owner_policy.participant_id
                        == MemoryItemModel.creator_participant_id,
                        owner_policy.conversation_id == MemoryItemModel.conversation_id,
                    ),
                )
                .where(
                    MemoryItemModel.id.in_(memory_ids),
                    MemoryItemModel.assistant_id == assistant_id,
                    MemoryItemModel.platform_connection_id == platform_connection_id,
                    MemoryItemModel.conversation_id == conversation_id,
                    MemoryItemModel.scope == scope,
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                    or_(owner_policy.id.is_(None), owner_policy.enabled.is_(True)),
                    MemoryItemModel.content.is_not(None),
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
            )
            return {
                item.id: (item.public_id, item.content, item.created_at, "Memory")
                for item in rows
                if item.content is not None
            }

    async def active_count(self) -> int:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.count(MemoryItemModel.id)).where(
                    MemoryItemModel.status == MemoryStatus.ACTIVE,
                    MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                    MemoryItemModel.visibility == MemoryVisibility.SAME_CONVERSATION,
                    MemoryItemModel.content.is_not(None),
                    or_(
                        MemoryItemModel.expires_at.is_(None),
                        MemoryItemModel.expires_at > now,
                    ),
                )
            )
            return int(value or 0)

    async def active_ids(self) -> tuple[UUID, ...]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            return tuple(
                await session.scalars(
                    select(MemoryItemModel.id).where(
                        MemoryItemModel.status == MemoryStatus.ACTIVE,
                        MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                        MemoryItemModel.visibility
                        == MemoryVisibility.SAME_CONVERSATION,
                        MemoryItemModel.content.is_not(None),
                        or_(
                            MemoryItemModel.expires_at.is_(None),
                            MemoryItemModel.expires_at > now,
                        ),
                    )
                )
            )

    async def schedule_active_upserts(
        self, version: str, target_collection: str | None = None
    ) -> int:
        return await self.schedule_upserts(
            await self.active_ids(), version, target_collection
        )

    async def schedule_upserts(
        self,
        memory_ids: tuple[UUID, ...] | set[UUID],
        version: str,
        target_collection: str | None = None,
    ) -> int:
        if not memory_ids:
            return 0
        async with self._session_factory() as session:
            async with session.begin():
                for memory_id in sorted(memory_ids, key=str):
                    await self.schedule(
                        session,
                        memory_id,
                        SemanticMemoryIndexOperation.UPSERT,
                        version,
                        target_collection,
                    )
                return len(memory_ids)

    async def active_collection(self, version: str, fallback: str) -> str:
        async with self._session_factory() as session:
            configured = await session.scalar(
                select(
                    ExplicitMemorySemanticIndexCollectionModel.collection_name
                ).where(
                    ExplicitMemorySemanticIndexCollectionModel.embedding_version
                    == version
                )
            )
            return configured or fallback

    async def activate_collection(self, version: str, collection: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                statement = insert(ExplicitMemorySemanticIndexCollectionModel).values(
                    embedding_version=version,
                    collection_name=collection,
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        index_elements=("embedding_version",),
                        set_={
                            "collection_name": collection,
                            "updated_at": datetime.now(UTC),
                        },
                    )
                )

    async def target_jobs_remaining(self, version: str, collection: str) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.count(ExplicitMemorySemanticIndexJobModel.id)).where(
                    ExplicitMemorySemanticIndexJobModel.embedding_version == version,
                    ExplicitMemorySemanticIndexJobModel.target_collection == collection,
                    ExplicitMemorySemanticIndexJobModel.status
                    != SemanticMemoryIndexJobStatus.COMPLETED,
                )
            )
            return int(value or 0)

    async def job_counts(self) -> dict[str, int]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    ExplicitMemorySemanticIndexJobModel.status,
                    func.count(ExplicitMemorySemanticIndexJobModel.id),
                ).group_by(ExplicitMemorySemanticIndexJobModel.status)
            )
            return {status.value: int(count) for status, count in rows}
