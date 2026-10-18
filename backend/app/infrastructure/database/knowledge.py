"""PostgreSQL authority for Assistant knowledge and its replayable derived index."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.knowledge import ContextKnowledge, KnowledgePoint
from app.domain.knowledge import (
    KNOWLEDGE_CHUNKING_VERSION,
    KNOWLEDGE_INDEX_SCHEMA_VERSION,
    MAX_DOCUMENTS_PER_KNOWLEDGE_BASE,
    MAX_KNOWLEDGE_BASES_PER_ASSISTANT,
    MAX_KNOWLEDGE_CONTEXT_CHARACTERS,
    MAX_KNOWLEDGE_CONTEXT_CHUNKS,
    MAX_OPEN_INDEX_JOBS_PER_ASSISTANT,
    MAX_REVISIONS_PER_DOCUMENT,
    MAX_STORED_REVISION_CHARACTERS_PER_ASSISTANT,
    KnowledgeBaseStatus,
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIndexJobStatus,
    KnowledgeIndexOperation,
    KnowledgeIndexState,
    chunk_knowledge_content,
    knowledge_base_transition_allowed,
    normalize_knowledge_content,
)
from app.domain.persistence import AssistantStatus, TenantStatus
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    KnowledgeBaseModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    KnowledgeIndexCollectionModel,
    KnowledgeIndexJobModel,
)


class KnowledgeConflict(RuntimeError):
    pass


class KnowledgeLimitExceeded(RuntimeError):
    pass


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    async def create_base(
        session: AsyncSession,
        *,
        tenant_id: UUID,
        assistant_id: UUID,
        slug: str,
        name: str,
    ) -> KnowledgeBaseModel:
        assistant = await session.get(
            AssistantModel,
            assistant_id,
            with_for_update=True,
            populate_existing=True,
        )
        if assistant is None or assistant.tenant_id != tenant_id:
            raise KnowledgeConflict("Assistant does not exist in tenant")
        count = await session.scalar(
            select(func.count(KnowledgeBaseModel.id)).where(
                KnowledgeBaseModel.tenant_id == tenant_id,
                KnowledgeBaseModel.assistant_id == assistant_id,
            )
        )
        if int(count or 0) >= MAX_KNOWLEDGE_BASES_PER_ASSISTANT:
            raise KnowledgeLimitExceeded("knowledge base limit exceeded")
        row = KnowledgeBaseModel(
            tenant_id=tenant_id, assistant_id=assistant_id, slug=slug, name=name
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def create_document(
        session: AsyncSession,
        *,
        knowledge_base: KnowledgeBaseModel,
        slug: str,
        title: str,
        source_label: str | None,
        source_reference: str | None,
        content_type: KnowledgeContentType,
    ) -> KnowledgeDocumentModel:
        locked = await session.get(
            KnowledgeBaseModel,
            knowledge_base.id,
            with_for_update=True,
            populate_existing=True,
        )
        if locked is None:
            raise KnowledgeConflict("knowledge base does not exist")
        knowledge_base = locked
        if knowledge_base.status == KnowledgeBaseStatus.RETIRED:
            raise KnowledgeConflict("retired knowledge base is immutable")
        count = await session.scalar(
            select(func.count(KnowledgeDocumentModel.id)).where(
                KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
                KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
            )
        )
        if int(count or 0) >= MAX_DOCUMENTS_PER_KNOWLEDGE_BASE:
            raise KnowledgeLimitExceeded("knowledge document limit exceeded")
        row = KnowledgeDocumentModel(
            tenant_id=knowledge_base.tenant_id,
            assistant_id=knowledge_base.assistant_id,
            knowledge_base_id=knowledge_base.id,
            slug=slug,
            title=title,
            source_label=source_label,
            source_reference=source_reference,
            content_type=content_type,
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def create_revision(
        session: AsyncSession,
        *,
        document: KnowledgeDocumentModel,
        expected_revision: int,
        content: str,
        actor_id: UUID,
        embedding_version: str,
        target_collection: str,
    ) -> KnowledgeDocumentRevisionModel:
        locked = await session.get(
            KnowledgeDocumentModel,
            document.id,
            with_for_update=True,
            populate_existing=True,
        )
        if locked is None:
            raise KnowledgeConflict("knowledge document does not exist")
        document = locked
        assistant = await session.get(
            AssistantModel, document.assistant_id, with_for_update=True
        )
        if assistant is None or assistant.tenant_id != document.tenant_id:
            raise KnowledgeConflict("Assistant does not exist in tenant")
        value = normalize_knowledge_content(content)
        checksum = sha256(value.encode("utf-8")).hexdigest()
        if document.revision != expected_revision:
            if document.revision == expected_revision + 1:
                existing = await session.scalar(
                    select(KnowledgeDocumentRevisionModel).where(
                        KnowledgeDocumentRevisionModel.document_id == document.id,
                        KnowledgeDocumentRevisionModel.revision_number
                        == document.latest_revision_number,
                        KnowledgeDocumentRevisionModel.content_checksum == checksum,
                        KnowledgeDocumentRevisionModel.deleted_at.is_(None),
                    )
                )
                if existing is not None:
                    return existing
            raise KnowledgeConflict("knowledge document revision conflict")
        if document.status != KnowledgeDocumentStatus.ACTIVE:
            raise KnowledgeConflict("deleted knowledge document is immutable")
        chunks = chunk_knowledge_content(value)
        if document.latest_revision_number >= MAX_REVISIONS_PER_DOCUMENT:
            raise KnowledgeLimitExceeded("knowledge revision limit exceeded")
        stored = await session.scalar(
            select(
                func.coalesce(
                    func.sum(KnowledgeDocumentRevisionModel.character_count), 0
                )
            ).where(
                KnowledgeDocumentRevisionModel.assistant_id == document.assistant_id,
                KnowledgeDocumentRevisionModel.deleted_at.is_(None),
            )
        )
        if int(stored or 0) + len(value) > MAX_STORED_REVISION_CHARACTERS_PER_ASSISTANT:
            raise KnowledgeLimitExceeded("Assistant knowledge storage limit exceeded")
        open_jobs = await session.scalar(
            select(func.count(KnowledgeIndexJobModel.id)).where(
                KnowledgeIndexJobModel.assistant_id == document.assistant_id,
                KnowledgeIndexJobModel.status.in_(
                    (KnowledgeIndexJobStatus.PENDING, KnowledgeIndexJobStatus.LEASED)
                ),
            )
        )
        if int(open_jobs or 0) + len(chunks) > MAX_OPEN_INDEX_JOBS_PER_ASSISTANT:
            raise KnowledgeLimitExceeded(
                "Assistant knowledge index queue limit exceeded"
            )
        document.latest_revision_number += 1
        document.revision += 1
        revision = KnowledgeDocumentRevisionModel(
            tenant_id=document.tenant_id,
            assistant_id=document.assistant_id,
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
            revision_number=document.latest_revision_number,
            content=value,
            content_checksum=checksum,
            character_count=len(value),
            byte_count=len(value.encode("utf-8")),
            chunking_version=KNOWLEDGE_CHUNKING_VERSION,
            index_state=KnowledgeIndexState.PENDING,
            created_by_identity_id=actor_id,
        )
        session.add(revision)
        await session.flush()
        now = datetime.now(UTC)
        for item in chunks:
            chunk = KnowledgeChunkModel(
                tenant_id=document.tenant_id,
                assistant_id=document.assistant_id,
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                revision_id=revision.id,
                ordinal=item.ordinal,
                start_offset=item.start_offset,
                end_offset=item.end_offset,
                content=item.content,
                content_checksum=item.checksum,
                character_count=len(item.content),
            )
            session.add(chunk)
            await session.flush()
            session.add(
                KnowledgeIndexJobModel(
                    tenant_id=document.tenant_id,
                    assistant_id=document.assistant_id,
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    revision_id=revision.id,
                    chunk_id=chunk.id,
                    operation=KnowledgeIndexOperation.UPSERT,
                    embedding_version=embedding_version,
                    target_collection=target_collection,
                    index_schema_version=KNOWLEDGE_INDEX_SCHEMA_VERSION,
                    status=KnowledgeIndexJobStatus.PENDING,
                    available_at=now,
                )
            )
        await session.flush()
        return revision

    @staticmethod
    async def transition_base(
        session: AsyncSession,
        knowledge_base: KnowledgeBaseModel,
        *,
        expected_revision: int,
        target: KnowledgeBaseStatus,
    ) -> KnowledgeBaseModel:
        locked = await session.get(
            KnowledgeBaseModel,
            knowledge_base.id,
            with_for_update=True,
            populate_existing=True,
        )
        if locked is None:
            raise KnowledgeConflict("knowledge base does not exist")
        knowledge_base = locked
        if knowledge_base.revision != expected_revision:
            raise KnowledgeConflict("knowledge base revision conflict")
        if not knowledge_base_transition_allowed(knowledge_base.status, target):
            raise KnowledgeConflict("knowledge base transition denied")
        if target == KnowledgeBaseStatus.ACTIVE:
            assistant = await session.scalar(
                select(AssistantModel)
                .join(
                    ControlTenantModel,
                    ControlTenantModel.id == AssistantModel.tenant_id,
                )
                .where(
                    AssistantModel.id == knowledge_base.assistant_id,
                    AssistantModel.tenant_id == knowledge_base.tenant_id,
                    AssistantModel.status == AssistantStatus.ACTIVE,
                    AssistantModel.knowledge_enabled.is_(True),
                    ControlTenantModel.status == TenantStatus.ACTIVE,
                )
            )
            invalid = await session.scalar(
                select(func.count(KnowledgeDocumentModel.id))
                .outerjoin(
                    KnowledgeDocumentRevisionModel,
                    KnowledgeDocumentRevisionModel.id
                    == KnowledgeDocumentModel.current_revision_id,
                )
                .where(
                    KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
                    KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                    or_(
                        KnowledgeDocumentModel.current_revision_id.is_(None),
                        KnowledgeDocumentRevisionModel.index_state
                        != KnowledgeIndexState.READY,
                    ),
                )
            )
            documents = await session.scalar(
                select(func.count(KnowledgeDocumentModel.id)).where(
                    KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
                    KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                )
            )
            if assistant is None or not documents or invalid:
                raise KnowledgeConflict("knowledge base is not activation-ready")
            knowledge_base.activated_at = datetime.now(UTC)
        if target == KnowledgeBaseStatus.RETIRED:
            knowledge_base.retired_at = datetime.now(UTC)
            chunks = list(
                await session.scalars(
                    select(KnowledgeChunkModel).where(
                        KnowledgeChunkModel.knowledge_base_id == knowledge_base.id
                    )
                )
            )
            versions = {
                (job.embedding_version, job.target_collection)
                for job in await session.scalars(
                    select(KnowledgeIndexJobModel).where(
                        KnowledgeIndexJobModel.knowledge_base_id == knowledge_base.id
                    )
                )
            }
            for chunk in chunks:
                for version, collection in versions:
                    await SqlAlchemyKnowledgeRepository._schedule(
                        session,
                        chunk,
                        KnowledgeIndexOperation.DELETE,
                        version,
                        collection,
                    )
        knowledge_base.status = target
        knowledge_base.revision += 1
        return knowledge_base

    @staticmethod
    async def delete_document(
        session: AsyncSession,
        document: KnowledgeDocumentModel,
        *,
        expected_revision: int,
    ) -> None:
        locked = await session.get(
            KnowledgeDocumentModel,
            document.id,
            with_for_update=True,
            populate_existing=True,
        )
        if locked is None:
            raise KnowledgeConflict("knowledge document does not exist")
        document = locked
        if (
            document.status == KnowledgeDocumentStatus.DELETED
            and document.revision == expected_revision + 1
        ):
            return
        if document.revision != expected_revision:
            raise KnowledgeConflict("knowledge document revision conflict")
        if document.status == KnowledgeDocumentStatus.DELETED:
            return
        now = datetime.now(UTC)
        document.status = KnowledgeDocumentStatus.DELETED
        document.deleted_at = now
        document.current_revision_id = None
        document.revision += 1
        revisions = list(
            await session.scalars(
                select(KnowledgeDocumentRevisionModel).where(
                    KnowledgeDocumentRevisionModel.document_id == document.id
                )
            )
        )
        chunks = list(
            await session.scalars(
                select(KnowledgeChunkModel).where(
                    KnowledgeChunkModel.document_id == document.id
                )
            )
        )
        versions = {
            (job.embedding_version, job.target_collection)
            for job in await session.scalars(
                select(KnowledgeIndexJobModel).where(
                    KnowledgeIndexJobModel.document_id == document.id
                )
            )
        }
        for revision in revisions:
            revision.content = None
            revision.content_checksum = None
            revision.deleted_at = now
            revision.index_state = KnowledgeIndexState.DELETED
        for chunk in chunks:
            chunk.content = None
            chunk.content_checksum = None
            chunk.deleted_at = now
            for version, collection in versions:
                await SqlAlchemyKnowledgeRepository._schedule(
                    session, chunk, KnowledgeIndexOperation.DELETE, version, collection
                )
        knowledge_base = await session.get(
            KnowledgeBaseModel, document.knowledge_base_id, with_for_update=True
        )
        if (
            knowledge_base is not None
            and knowledge_base.status == KnowledgeBaseStatus.ACTIVE
        ):
            await session.flush()
            documents = int(
                await session.scalar(
                    select(func.count(KnowledgeDocumentModel.id)).where(
                        KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
                        KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                    )
                )
                or 0
            )
            invalid = int(
                await session.scalar(
                    select(func.count(KnowledgeDocumentModel.id))
                    .outerjoin(
                        KnowledgeDocumentRevisionModel,
                        KnowledgeDocumentRevisionModel.id
                        == KnowledgeDocumentModel.current_revision_id,
                    )
                    .where(
                        KnowledgeDocumentModel.knowledge_base_id == knowledge_base.id,
                        KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                        or_(
                            KnowledgeDocumentModel.current_revision_id.is_(None),
                            KnowledgeDocumentRevisionModel.index_state
                            != KnowledgeIndexState.READY,
                        ),
                    )
                )
                or 0
            )
            if documents == 0 or invalid:
                knowledge_base.status = KnowledgeBaseStatus.DISABLED
                knowledge_base.revision += 1

    @staticmethod
    async def _schedule(
        session: AsyncSession,
        chunk: KnowledgeChunkModel,
        operation: KnowledgeIndexOperation,
        version: str,
        collection: str,
    ) -> None:
        now = datetime.now(UTC)
        statement = insert(KnowledgeIndexJobModel).values(
            tenant_id=chunk.tenant_id,
            assistant_id=chunk.assistant_id,
            knowledge_base_id=chunk.knowledge_base_id,
            document_id=chunk.document_id,
            revision_id=chunk.revision_id,
            chunk_id=chunk.id,
            operation=operation,
            embedding_version=version,
            target_collection=collection,
            index_schema_version=KNOWLEDGE_INDEX_SCHEMA_VERSION,
            status=KnowledgeIndexJobStatus.PENDING,
            available_at=now,
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint="uq_knowledge_index_jobs_idempotency",
                set_={
                    "status": KnowledgeIndexJobStatus.PENDING,
                    "available_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": None,
                    "last_error_category": None,
                    "updated_at": now,
                },
            )
        )

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[KnowledgeIndexJobModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                rows = list(
                    await session.scalars(
                        select(KnowledgeIndexJobModel)
                        .where(
                            or_(
                                and_(
                                    KnowledgeIndexJobModel.status
                                    == KnowledgeIndexJobStatus.PENDING,
                                    KnowledgeIndexJobModel.available_at <= now,
                                ),
                                and_(
                                    KnowledgeIndexJobModel.status
                                    == KnowledgeIndexJobStatus.LEASED,
                                    KnowledgeIndexJobModel.lease_expires_at < now,
                                ),
                            )
                        )
                        .order_by(
                            KnowledgeIndexJobModel.available_at,
                            KnowledgeIndexJobModel.created_at,
                            KnowledgeIndexJobModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for row in rows:
                    row.status = KnowledgeIndexJobStatus.LEASED
                    row.lease_owner = owner
                    row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    row.attempt_count += 1
                    if row.operation == KnowledgeIndexOperation.UPSERT:
                        revision = await session.get(
                            KnowledgeDocumentRevisionModel, row.revision_id
                        )
                        if (
                            revision is not None
                            and revision.index_state == KnowledgeIndexState.PENDING
                        ):
                            revision.index_state = KnowledgeIndexState.INDEXING
                return rows

    async def point_for_upsert(self, job_id: UUID) -> tuple[KnowledgePoint, str] | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        KnowledgeIndexJobModel,
                        KnowledgeChunkModel,
                        KnowledgeDocumentRevisionModel,
                        KnowledgeDocumentModel,
                        KnowledgeBaseModel,
                        AssistantModel,
                        ControlTenantModel,
                    )
                    .join(
                        KnowledgeChunkModel,
                        KnowledgeChunkModel.id == KnowledgeIndexJobModel.chunk_id,
                    )
                    .join(
                        KnowledgeDocumentRevisionModel,
                        KnowledgeDocumentRevisionModel.id
                        == KnowledgeIndexJobModel.revision_id,
                    )
                    .join(
                        KnowledgeDocumentModel,
                        KnowledgeDocumentModel.id == KnowledgeIndexJobModel.document_id,
                    )
                    .join(
                        KnowledgeBaseModel,
                        KnowledgeBaseModel.id
                        == KnowledgeIndexJobModel.knowledge_base_id,
                    )
                    .join(
                        AssistantModel,
                        AssistantModel.id == KnowledgeIndexJobModel.assistant_id,
                    )
                    .join(
                        ControlTenantModel,
                        ControlTenantModel.id == KnowledgeIndexJobModel.tenant_id,
                    )
                    .where(
                        KnowledgeIndexJobModel.id == job_id,
                        KnowledgeIndexJobModel.operation
                        == KnowledgeIndexOperation.UPSERT,
                        KnowledgeIndexJobModel.status == KnowledgeIndexJobStatus.LEASED,
                        KnowledgeChunkModel.content.is_not(None),
                        KnowledgeChunkModel.deleted_at.is_(None),
                        KnowledgeDocumentRevisionModel.content.is_not(None),
                        KnowledgeDocumentRevisionModel.deleted_at.is_(None),
                        KnowledgeDocumentRevisionModel.revision_number
                        == KnowledgeDocumentModel.latest_revision_number,
                        KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                        KnowledgeBaseModel.status != KnowledgeBaseStatus.RETIRED,
                        AssistantModel.status == AssistantStatus.ACTIVE,
                        ControlTenantModel.status == TenantStatus.ACTIVE,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            job, chunk, revision, document, base, assistant, tenant = row
            assert chunk.content is not None
            return KnowledgePoint(
                job.tenant_id,
                job.assistant_id,
                job.knowledge_base_id,
                job.document_id,
                job.revision_id,
                job.chunk_id,
                job.embedding_version,
                job.index_schema_version,
            ), chunk.content

    async def complete(self, job_id: UUID, owner: str) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    KnowledgeIndexJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != KnowledgeIndexJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return False
                job.status = KnowledgeIndexJobStatus.COMPLETED
                job.lease_owner = None
                job.lease_expires_at = None
                job.completed_at = datetime.now(UTC)
                job.last_error_category = None
                if job.operation == KnowledgeIndexOperation.UPSERT:
                    document = await session.get(
                        KnowledgeDocumentModel, job.document_id, with_for_update=True
                    )
                    revision = await session.get(
                        KnowledgeDocumentRevisionModel,
                        job.revision_id,
                        with_for_update=True,
                    )
                    knowledge_base = await session.get(
                        KnowledgeBaseModel,
                        job.knowledge_base_id,
                        with_for_update=True,
                    )
                    assistant = await session.get(AssistantModel, job.assistant_id)
                    tenant = await session.get(ControlTenantModel, job.tenant_id)
                    chunk = await session.get(
                        KnowledgeChunkModel, job.chunk_id, with_for_update=True
                    )
                    authoritative = (
                        revision is not None
                        and revision.content is not None
                        and revision.deleted_at is None
                        and document is not None
                        and document.status == KnowledgeDocumentStatus.ACTIVE
                        and revision.revision_number == document.latest_revision_number
                        and knowledge_base is not None
                        and knowledge_base.status != KnowledgeBaseStatus.RETIRED
                        and assistant is not None
                        and assistant.status == AssistantStatus.ACTIVE
                        and tenant is not None
                        and tenant.status == TenantStatus.ACTIVE
                        and chunk is not None
                        and chunk.content is not None
                        and chunk.deleted_at is None
                    )
                    if not authoritative:
                        if (
                            revision is not None
                            and revision.deleted_at is None
                            and revision.index_state
                            in {
                                KnowledgeIndexState.PENDING,
                                KnowledgeIndexState.INDEXING,
                            }
                        ):
                            revision.index_state = KnowledgeIndexState.FAILED
                            revision.failed_at = datetime.now(UTC)
                        if chunk is not None:
                            await self._schedule(
                                session,
                                chunk,
                                KnowledgeIndexOperation.DELETE,
                                job.embedding_version,
                                job.target_collection,
                            )
                        return True
                    assert chunk is not None
                    chunk.embedding_version = job.embedding_version
                    chunk.index_schema_version = job.index_schema_version
                    remaining = await session.scalar(
                        select(func.count(KnowledgeIndexJobModel.id)).where(
                            KnowledgeIndexJobModel.revision_id == job.revision_id,
                            KnowledgeIndexJobModel.operation
                            == KnowledgeIndexOperation.UPSERT,
                            KnowledgeIndexJobModel.id != job.id,
                            KnowledgeIndexJobModel.status
                            != KnowledgeIndexJobStatus.COMPLETED,
                        )
                    )
                    if (
                        revision is not None
                        and document is not None
                        and not remaining
                        and revision.revision_number == document.latest_revision_number
                        and document.status == KnowledgeDocumentStatus.ACTIVE
                    ):
                        previous_id = document.current_revision_id
                        revision.index_state = KnowledgeIndexState.READY
                        revision.ready_at = datetime.now(UTC)
                        document.current_revision_id = revision.id
                        if previous_id is not None and previous_id != revision.id:
                            old_chunks = list(
                                await session.scalars(
                                    select(KnowledgeChunkModel).where(
                                        KnowledgeChunkModel.revision_id == previous_id
                                    )
                                )
                            )
                            for chunk in old_chunks:
                                await self._schedule(
                                    session,
                                    chunk,
                                    KnowledgeIndexOperation.DELETE,
                                    job.embedding_version,
                                    job.target_collection,
                                )
                else:
                    remaining = await session.scalar(
                        select(func.count(KnowledgeIndexJobModel.id)).where(
                            KnowledgeIndexJobModel.revision_id == job.revision_id,
                            KnowledgeIndexJobModel.operation
                            == KnowledgeIndexOperation.DELETE,
                            KnowledgeIndexJobModel.id != job.id,
                            KnowledgeIndexJobModel.status
                            != KnowledgeIndexJobStatus.COMPLETED,
                        )
                    )
                    if not remaining:
                        revision = await session.get(
                            KnowledgeDocumentRevisionModel, job.revision_id
                        )
                        if revision is not None and revision.deleted_at is not None:
                            revision.index_state = KnowledgeIndexState.DELETED
                return True

    async def release(
        self,
        job_id: UUID,
        owner: str,
        category: str,
        delay: float,
        max_attempts: int,
        retryable: bool,
    ) -> KnowledgeIndexJobStatus | None:
        async with self._session_factory() as session:
            async with session.begin():
                job = await session.get(
                    KnowledgeIndexJobModel, job_id, with_for_update=True
                )
                if (
                    job is None
                    or job.status != KnowledgeIndexJobStatus.LEASED
                    or job.lease_owner != owner
                ):
                    return None
                terminal = not retryable or job.attempt_count >= max_attempts
                job.status = (
                    KnowledgeIndexJobStatus.FAILED
                    if terminal
                    else KnowledgeIndexJobStatus.PENDING
                )
                job.available_at = datetime.now(UTC) + timedelta(seconds=delay)
                job.lease_owner = None
                job.lease_expires_at = None
                job.last_error_category = category
                if terminal:
                    job.completed_at = datetime.now(UTC)
                    revision = await session.get(
                        KnowledgeDocumentRevisionModel, job.revision_id
                    )
                    if (
                        revision is not None
                        and job.operation == KnowledgeIndexOperation.UPSERT
                        and revision.index_state != KnowledgeIndexState.READY
                    ):
                        revision.index_state = KnowledgeIndexState.FAILED
                        revision.failed_at = datetime.now(UTC)
                return job.status

    async def retrieval_enabled(
        self, tenant_id: UUID, assistant_id: UUID
    ) -> tuple[UUID, ...]:
        async with self._session_factory() as session:
            enabled = await session.scalar(
                select(AssistantModel.id)
                .join(
                    ControlTenantModel,
                    ControlTenantModel.id == AssistantModel.tenant_id,
                )
                .where(
                    AssistantModel.id == assistant_id,
                    AssistantModel.tenant_id == tenant_id,
                    AssistantModel.status == AssistantStatus.ACTIVE,
                    AssistantModel.knowledge_enabled.is_(True),
                    ControlTenantModel.status == TenantStatus.ACTIVE,
                )
            )
            if enabled is None:
                return ()
            return tuple(
                await session.scalars(
                    select(KnowledgeBaseModel.id)
                    .where(
                        KnowledgeBaseModel.tenant_id == tenant_id,
                        KnowledgeBaseModel.assistant_id == assistant_id,
                        KnowledgeBaseModel.status == KnowledgeBaseStatus.ACTIVE,
                    )
                    .order_by(KnowledgeBaseModel.id)
                )
            )

    async def revalidate_candidates(
        self,
        candidate_ids: tuple[UUID, ...],
        *,
        tenant_id: UUID,
        assistant_id: UUID,
        eligible_base_ids: tuple[UUID, ...],
        scores: dict[UUID, float],
        embedding_version: str,
        index_schema_version: str,
        context_limit: int = MAX_KNOWLEDGE_CONTEXT_CHUNKS,
        character_budget: int = MAX_KNOWLEDGE_CONTEXT_CHARACTERS,
    ) -> tuple[ContextKnowledge, ...]:
        if not candidate_ids or not eligible_base_ids:
            return ()
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(
                            KnowledgeChunkModel,
                            KnowledgeDocumentModel.title,
                            KnowledgeDocumentModel.source_label,
                        )
                        .join(
                            KnowledgeDocumentModel,
                            KnowledgeDocumentModel.id
                            == KnowledgeChunkModel.document_id,
                        )
                        .join(
                            KnowledgeDocumentRevisionModel,
                            KnowledgeDocumentRevisionModel.id
                            == KnowledgeChunkModel.revision_id,
                        )
                        .join(
                            KnowledgeBaseModel,
                            KnowledgeBaseModel.id
                            == KnowledgeChunkModel.knowledge_base_id,
                        )
                        .join(
                            AssistantModel,
                            AssistantModel.id == KnowledgeChunkModel.assistant_id,
                        )
                        .join(
                            ControlTenantModel,
                            ControlTenantModel.id == KnowledgeChunkModel.tenant_id,
                        )
                        .where(
                            KnowledgeChunkModel.id.in_(candidate_ids),
                            KnowledgeChunkModel.tenant_id == tenant_id,
                            KnowledgeChunkModel.assistant_id == assistant_id,
                            KnowledgeChunkModel.knowledge_base_id.in_(
                                eligible_base_ids
                            ),
                            KnowledgeChunkModel.deleted_at.is_(None),
                            KnowledgeChunkModel.content.is_not(None),
                            KnowledgeChunkModel.embedding_version == embedding_version,
                            KnowledgeChunkModel.index_schema_version
                            == index_schema_version,
                            KnowledgeDocumentModel.status
                            == KnowledgeDocumentStatus.ACTIVE,
                            KnowledgeDocumentModel.current_revision_id
                            == KnowledgeChunkModel.revision_id,
                            KnowledgeDocumentRevisionModel.index_state
                            == KnowledgeIndexState.READY,
                            KnowledgeDocumentRevisionModel.deleted_at.is_(None),
                            KnowledgeBaseModel.status == KnowledgeBaseStatus.ACTIVE,
                            AssistantModel.status == AssistantStatus.ACTIVE,
                            AssistantModel.knowledge_enabled.is_(True),
                            ControlTenantModel.status == TenantStatus.ACTIVE,
                        )
                    )
                ).all()
            )
        ordered = sorted(
            rows, key=lambda item: (-scores.get(item[0].id, -2.0), str(item[0].id))
        )
        selected: list[ContextKnowledge] = []
        used = 0
        for item, title, source_label in ordered:
            if (
                item.content is None
                or len(selected) >= context_limit
                or used + len(item.content) > character_budget
            ):
                continue
            selected.append(
                ContextKnowledge(
                    item.knowledge_base_id,
                    item.document_id,
                    item.revision_id,
                    item.id,
                    item.content,
                    scores[item.id],
                    title,
                    source_label,
                )
            )
            used += len(item.content)
        return tuple(selected)

    async def active_collection(self, version: str, fallback: str) -> str:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(KnowledgeIndexCollectionModel.physical_collection).where(
                    KnowledgeIndexCollectionModel.embedding_version == version,
                    KnowledgeIndexCollectionModel.active.is_(True),
                )
            )
            return value or fallback

    async def activate_collection(self, version: str, collection: str) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.execute(
                    update(KnowledgeIndexCollectionModel)
                    .where(KnowledgeIndexCollectionModel.embedding_version == version)
                    .values(active=False, retired_at=datetime.now(UTC))
                )
                session.add(
                    KnowledgeIndexCollectionModel(
                        embedding_version=version,
                        physical_collection=collection,
                        index_schema_version=KNOWLEDGE_INDEX_SCHEMA_VERSION,
                        active=True,
                        activated_at=datetime.now(UTC),
                    )
                )

    async def schedule_rebuild(
        self,
        version: str,
        collection: str,
        *,
        tenant_id: UUID | None = None,
        assistant_id: UUID | None = None,
        include_nonretrievable_bases: bool = False,
    ) -> int:
        async with self._session_factory() as session:
            async with session.begin():
                chunks = list(
                    await session.scalars(
                        select(KnowledgeChunkModel)
                        .join(
                            KnowledgeDocumentModel,
                            KnowledgeDocumentModel.id
                            == KnowledgeChunkModel.document_id,
                        )
                        .join(
                            KnowledgeDocumentRevisionModel,
                            KnowledgeDocumentRevisionModel.id
                            == KnowledgeChunkModel.revision_id,
                        )
                        .join(
                            KnowledgeBaseModel,
                            KnowledgeBaseModel.id
                            == KnowledgeChunkModel.knowledge_base_id,
                        )
                        .join(
                            AssistantModel,
                            AssistantModel.id == KnowledgeChunkModel.assistant_id,
                        )
                        .join(
                            ControlTenantModel,
                            ControlTenantModel.id == KnowledgeChunkModel.tenant_id,
                        )
                        .where(
                            KnowledgeChunkModel.deleted_at.is_(None),
                            KnowledgeChunkModel.content.is_not(None),
                            KnowledgeDocumentModel.status
                            == KnowledgeDocumentStatus.ACTIVE,
                            KnowledgeDocumentModel.current_revision_id
                            == KnowledgeChunkModel.revision_id,
                            KnowledgeDocumentRevisionModel.index_state
                            == KnowledgeIndexState.READY,
                            (
                                KnowledgeBaseModel.status != KnowledgeBaseStatus.RETIRED
                                if include_nonretrievable_bases
                                else KnowledgeBaseModel.status
                                == KnowledgeBaseStatus.ACTIVE
                            ),
                            AssistantModel.status == AssistantStatus.ACTIVE,
                            ControlTenantModel.status == TenantStatus.ACTIVE,
                            *(
                                (KnowledgeChunkModel.tenant_id == tenant_id,)
                                if tenant_id is not None
                                else ()
                            ),
                            *(
                                (KnowledgeChunkModel.assistant_id == assistant_id,)
                                if assistant_id is not None
                                else ()
                            ),
                        )
                    )
                )
                for chunk in chunks:
                    await self._schedule(
                        session,
                        chunk,
                        KnowledgeIndexOperation.UPSERT,
                        version,
                        collection,
                    )
                return len(chunks)

    async def active_chunk_ids(self) -> tuple[UUID, ...]:
        async with self._session_factory() as session:
            return tuple(
                await session.scalars(
                    select(KnowledgeChunkModel.id)
                    .join(
                        KnowledgeDocumentModel,
                        KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id,
                    )
                    .join(
                        KnowledgeDocumentRevisionModel,
                        KnowledgeDocumentRevisionModel.id
                        == KnowledgeChunkModel.revision_id,
                    )
                    .join(
                        KnowledgeBaseModel,
                        KnowledgeBaseModel.id == KnowledgeChunkModel.knowledge_base_id,
                    )
                    .join(
                        AssistantModel,
                        AssistantModel.id == KnowledgeChunkModel.assistant_id,
                    )
                    .join(
                        ControlTenantModel,
                        ControlTenantModel.id == KnowledgeChunkModel.tenant_id,
                    )
                    .where(
                        KnowledgeChunkModel.deleted_at.is_(None),
                        KnowledgeChunkModel.content.is_not(None),
                        KnowledgeDocumentModel.status == KnowledgeDocumentStatus.ACTIVE,
                        KnowledgeDocumentModel.current_revision_id
                        == KnowledgeChunkModel.revision_id,
                        KnowledgeDocumentRevisionModel.index_state
                        == KnowledgeIndexState.READY,
                        KnowledgeBaseModel.status == KnowledgeBaseStatus.ACTIVE,
                        AssistantModel.status == AssistantStatus.ACTIVE,
                        ControlTenantModel.status == TenantStatus.ACTIVE,
                    )
                    .order_by(KnowledgeChunkModel.id)
                )
            )

    async def target_jobs_remaining(self, version: str, collection: str) -> int:
        async with self._session_factory() as session:
            value = await session.scalar(
                select(func.count(KnowledgeIndexJobModel.id)).where(
                    KnowledgeIndexJobModel.embedding_version == version,
                    KnowledgeIndexJobModel.target_collection == collection,
                    KnowledgeIndexJobModel.status != KnowledgeIndexJobStatus.COMPLETED,
                )
            )
            return int(value or 0)

    async def job_counts(self) -> dict[str, int]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    KnowledgeIndexJobModel.status, func.count(KnowledgeIndexJobModel.id)
                ).group_by(KnowledgeIndexJobModel.status)
            )
            return {status.value: int(count) for status, count in rows}
