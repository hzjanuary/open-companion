"""Migration-level proof for the explicit memory/privacy schema."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.memory import normalize_explicit_memory
from app.application.semantic_memory import (
    EmbeddingVector,
    SemanticMemoryMatch,
    collection_name,
    embedding_version,
)
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    AssistantStatus,
    CommandJobStatus,
    ConversationType,
    IngressSource,
    MemoryDeletionReason,
    MemoryScope,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
    PlatformConnectionStatus,
    SemanticMemoryIndexJobStatus,
    SemanticMemoryIndexOperation,
)
from app.domain.planning import PlanReasonCode
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.models import (
    AssistantModel as DatabaseAssistantModel,
)
from app.infrastructure.database.models import (
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ExplicitMemorySemanticIndexJobModel,
    IncomingPlatformUpdateModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.models import (
    PlatformConnectionModel as DatabasePlatformConnectionModel,
)
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)
from app.infrastructure.semantic_memory import SemanticMemoryRetriever
from app.runtime.demo_inspector import inspect_latest
from app.runtime.semantic_memory_index_worker import (
    consume_once as consume_semantic_once,
)
from app.runtime.semantic_memory_operations import operate as operate_semantic_memory

AssistantModel = partial(
    DatabaseAssistantModel,
    tenant_id=LEGACY_TENANT_ID,
    slug="memory-january",
    status=AssistantStatus.ACTIVE,
)
PlatformConnectionModel = partial(
    DatabasePlatformConnectionModel,
    tenant_id=LEGACY_TENANT_ID,
)


async def _ensure_legacy_tenant(session: AsyncSession) -> None:
    if await session.get(ControlTenantModel, LEGACY_TENANT_ID) is None:
        session.add(
            ControlTenantModel(
                id=LEGACY_TENANT_ID,
                slug="legacy-default",
                name="Legacy default",
            )
        )
        await session.flush()


@pytest.mark.integration
@pytest.mark.memory_integration
def test_memory_privacy_retention_schema_is_current() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.connect() as connection:
                assert await connection.scalar(
                    text("SELECT version_num FROM alembic_version")
                ) == ("0026_conversation_feedback")
                columns = set(
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'memory_items'"
                        )
                    )
                )
                assert {
                    "public_id",
                    "assistant_id",
                    "platform_connection_id",
                    "conversation_id",
                    "creator_participant_id",
                    "content",
                    "normalized_content_hash",
                    "deletion_reason",
                } <= columns
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_explicit_memory_index_jobs_schedule_create_and_delete() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="semantic-memory-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    assistant_id, connection_id = assistant.id, connection.id
            conversation, participant, message, command = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic",
            )
            repository = SqlAlchemyMemoryRepository(
                database.session_factory, "test-version"
            )
            memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation.id,
                creator_participant_id=participant.id,
                source_message_id=message.id,
                source_command_job_id=command.id,
                draft=normalize_explicit_memory(
                    "saved fact", MemoryScope.GROUP_CONVERSATION
                ),
            )
            cleanup_repository = SqlAlchemyMemoryRepository(
                database.session_factory, "new-version"
            )
            assert await cleanup_repository.delete(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation.id,
                public_id=memory.public_id,
                actor_id=participant.id,
                reason=MemoryDeletionReason.CREATOR_REQUEST,
            )
            reset_seed = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-reset",
            )
            reset_memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=reset_seed[0].id,
                creator_participant_id=reset_seed[1].id,
                source_message_id=reset_seed[2].id,
                source_command_job_id=reset_seed[3].id,
                draft=normalize_explicit_memory(
                    "reset fact", MemoryScope.GROUP_CONVERSATION
                ),
            )
            assert (
                await cleanup_repository.reset_group(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=reset_seed[0].id,
                    actor_id=reset_seed[1].id,
                    command_job_id=reset_seed[3].id,
                )
                == 1
            )
            async with database.session_factory() as session:
                jobs = list(
                    await session.scalars(
                        select(ExplicitMemorySemanticIndexJobModel).order_by(
                            ExplicitMemorySemanticIndexJobModel.operation
                        )
                    )
                )
                assert len(jobs) == 6
                assert all(
                    job.status == SemanticMemoryIndexJobStatus.PENDING for job in jobs
                )
                assert {job.operation for job in jobs} == {
                    SemanticMemoryIndexOperation.DELETE,
                    SemanticMemoryIndexOperation.UPSERT,
                }
                assert {job.memory_id for job in jobs} == {memory.id, reset_memory.id}
                assert {
                    (job.memory_id, job.embedding_version)
                    for job in jobs
                    if job.operation == SemanticMemoryIndexOperation.DELETE
                } == {
                    (memory.id, "test-version"),
                    (memory.id, "new-version"),
                    (reset_memory.id, "test-version"),
                    (reset_memory.id, "new-version"),
                }
                assert all(not hasattr(job, "content") for job in jobs)
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_delete_before_semantic_upsert_never_embeds_or_restores_memory() -> None:
    class FakeEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        def __init__(self) -> None:
            self.inputs: list[str] = []

        async def embed_text(self, text: str) -> EmbeddingVector:
            self.inputs.append(text)
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    class FakeIndex:
        def __init__(self) -> None:
            self.upserts: list[object] = []
            self.deletes: list[tuple[str, UUID]] = []

        async def ensure_collection(self, collection: str, dimension: int) -> None:
            return None

        async def upsert(self, collection: str, point: object, vector: object) -> None:
            self.upserts.append(point)

        async def delete(self, collection: str, memory_id: UUID) -> None:
            self.deletes.append((collection, memory_id))

        async def query(
            self, *args: object, **kwargs: object
        ) -> tuple[SemanticMemoryMatch, ...]:
            return ()

        async def count(self, collection: str) -> int | None:
            return 0

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            semantic_memory_enabled=True,
            semantic_memory_worker_enabled=True,
            embedding_provider="ollama",
            embedding_model="fake",
            embedding_dimension=2,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="semantic-race-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    assistant_id, connection_id = assistant.id, connection.id
            conversation, participant, message, command = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-race",
            )
            repository = SqlAlchemyMemoryRepository(
                database.session_factory, "previous-version"
            )
            memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation.id,
                creator_participant_id=participant.id,
                source_message_id=message.id,
                source_command_job_id=command.id,
                draft=normalize_explicit_memory(
                    "deleted before index", MemoryScope.GROUP_CONVERSATION
                ),
            )
            current_version = embedding_version("ollama", "fake", 2)
            assert await SqlAlchemyMemoryRepository(
                database.session_factory, current_version
            ).delete(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation.id,
                public_id=memory.public_id,
                actor_id=participant.id,
                reason=MemoryDeletionReason.CREATOR_REQUEST,
            )
            provider, index = FakeEmbeddingProvider(), FakeIndex()
            assert (
                await consume_semantic_once(settings, database, "test", provider, index)
                >= 2
            )
            assert provider.inputs == []
            assert index.upserts == []
            assert set(index.deletes) == {
                (
                    collection_name(
                        settings.qdrant_collection_prefix, "previous-version"
                    ),
                    memory.id,
                ),
                (
                    collection_name(settings.qdrant_collection_prefix, current_version),
                    memory.id,
                ),
            }
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_semantic_retrieval_revalidates_exact_scope_and_stale_deletion() -> None:
    class FakeEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        def __init__(self) -> None:
            self.inputs: list[str] = []

        async def embed_text(self, text: str) -> EmbeddingVector:
            self.inputs.append(text)
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    class FakeIndex:
        def __init__(self, matches: tuple[SemanticMemoryMatch, ...]) -> None:
            self.matches = matches
            self.queries: list[dict[str, object]] = []

        async def ensure_collection(self, collection: str, dimension: int) -> None:
            return None

        async def upsert(self, *args: object, **kwargs: object) -> None:
            return None

        async def delete(self, *args: object, **kwargs: object) -> None:
            return None

        async def query(
            self, *args: object, **kwargs: object
        ) -> tuple[SemanticMemoryMatch, ...]:
            self.queries.append(kwargs)
            return self.matches

        async def count(self, collection: str) -> int | None:
            return 0

        async def list_memory_ids(self, collection: str) -> tuple[UUID, ...]:
            return ()

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            semantic_memory_enabled=True,
            embedding_provider="ollama",
            embedding_model="fake",
            embedding_dimension=2,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="semantic-revalidate-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    assistant_id, connection_id = assistant.id, connection.id
            primary = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-primary",
            )
            sibling = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-sibling",
            )
            private = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-private",
                conversation_type=ConversationType.PRIVATE,
            )
            memory_repository = SqlAlchemyMemoryRepository(database.session_factory)

            async def create_memory(
                seed: tuple[
                    ConversationModel,
                    ParticipantModel,
                    MessageModel,
                    TelegramCommandJobModel,
                ],
                text_value: str,
                scope: MemoryScope,
            ) -> object:
                return await memory_repository.create(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=seed[0].id,
                    creator_participant_id=seed[1].id,
                    source_message_id=seed[2].id,
                    source_command_job_id=seed[3].id,
                    draft=normalize_explicit_memory(text_value, scope),
                )

            primary_memory = await create_memory(
                primary, "allowed canonical memory", MemoryScope.GROUP_CONVERSATION
            )
            sibling_memory = await create_memory(
                sibling, "wrong group memory", MemoryScope.GROUP_CONVERSATION
            )
            private_memory = await create_memory(
                private, "private memory", MemoryScope.PRIVATE_CONVERSATION
            )
            provider = FakeEmbeddingProvider()
            index = FakeIndex(
                (
                    SemanticMemoryMatch(sibling_memory.id, 0.99),
                    SemanticMemoryMatch(private_memory.id, 0.98),
                    SemanticMemoryMatch(primary_memory.id, 0.97),
                )
            )
            retriever = SemanticMemoryRetriever(
                settings,
                database.session_factory,
                embedding_provider_factory=lambda _: provider,
                index_factory=lambda _: index,
            )
            first = await retriever.retrieve(
                "current semantic query",
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=primary[0].id,
                scope=MemoryScope.GROUP_CONVERSATION,
            )
            assert [memory.public_id for memory in first] == [primary_memory.public_id]
            assert provider.inputs == ["current semantic query"]
            assert index.queries == [
                {
                    "assistant_id": assistant_id,
                    "platform_connection_id": connection_id,
                    "conversation_id": primary[0].id,
                    "scope": MemoryScope.GROUP_CONVERSATION,
                    "embedding_version": index.queries[0]["embedding_version"],
                    "limit": settings.semantic_memory_top_k,
                    "minimum_score": settings.semantic_memory_min_score,
                }
            ]
            assert await memory_repository.delete(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=primary[0].id,
                public_id=primary_memory.public_id,
                actor_id=primary[1].id,
                reason=MemoryDeletionReason.CREATOR_REQUEST,
            )
            assert (
                await retriever.retrieve(
                    "second current query",
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=primary[0].id,
                    scope=MemoryScope.GROUP_CONVERSATION,
                )
                == ()
            )
            assert "allowed canonical memory" not in provider.inputs
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_semantic_rebuild_activates_only_a_verified_fresh_collection() -> None:
    class FakeEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        def __init__(self) -> None:
            self.inputs: list[str] = []

        async def embed_text(self, text_value: str) -> EmbeddingVector:
            self.inputs.append(text_value)
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    class FakeIndex:
        def __init__(self) -> None:
            self.points: dict[str, set[UUID]] = {}

        async def health(self) -> bool:
            return True

        async def ensure_collection(self, collection: str, dimension: int) -> None:
            self.points.setdefault(collection, set())

        async def upsert(self, collection: str, point: object, vector: object) -> None:
            self.points.setdefault(collection, set()).add(point.memory_id)

        async def delete(self, collection: str, memory_id: UUID) -> None:
            self.points.setdefault(collection, set()).discard(memory_id)

        async def query(
            self, *args: object, **kwargs: object
        ) -> tuple[SemanticMemoryMatch, ...]:
            return ()

        async def count(self, collection: str) -> int | None:
            return len(self.points.get(collection, set()))

        async def list_memory_ids(self, collection: str) -> tuple[UUID, ...]:
            return tuple(sorted(self.points.get(collection, set()), key=str))

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            semantic_memory_enabled=True,
            semantic_memory_worker_enabled=False,
            embedding_provider="ollama",
            embedding_model="fake",
            embedding_dimension=2,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="semantic-rebuild-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    assistant_id, connection_id = assistant.id, connection.id
            seed = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="semantic-rebuild",
            )
            memory = await SqlAlchemyMemoryRepository(
                database.session_factory, "version"
            ).create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=seed[0].id,
                creator_participant_id=seed[1].id,
                source_message_id=seed[2].id,
                source_command_job_id=seed[3].id,
                draft=normalize_explicit_memory(
                    "rebuild canonical memory", MemoryScope.GROUP_CONVERSATION
                ),
            )
            index = FakeIndex()
            provider = FakeEmbeddingProvider()
            result = await operate_semantic_memory(
                "rebuild",
                True,
                settings=settings,
                database=database,
                index=index,
                provider=provider,
            )
            collection = result["collection"]
            assert isinstance(collection, str)
            assert "_rebuild_" in collection
            assert index.points[collection] == {memory.id}
            assert result["indexed_point_count"] == 1
            assert provider.inputs == ["rebuild canonical memory"]
            assert "/memory remember secret fact" not in provider.inputs
            version = embedding_version("ollama", "fake", 2)
            assert (
                await SqlAlchemySemanticMemoryRepository(
                    database.session_factory
                ).active_collection(version, "unexpected")
                == collection
            )
            assert (
                await operate_semantic_memory(
                    "backfill",
                    True,
                    settings=settings,
                    database=database,
                    index=index,
                )
            )["scheduled"] == 0
            index.points[collection].clear()
            missing = await operate_semantic_memory(
                "backfill",
                True,
                settings=settings,
                database=database,
                index=index,
            )
            assert missing["scheduled"] == 1
            stale_id = UUID("00000000-0000-0000-0000-000000000001")
            index.points[collection].add(stale_id)
            reconciled = await operate_semantic_memory(
                "reconcile",
                True,
                settings=settings,
                database=database,
                index=index,
            )
            assert reconciled["scheduled"] == 1
            assert reconciled["stale_deleted"] == 1
            assert stale_id not in index.points[collection]
        finally:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        text("DELETE FROM explicit_memory_semantic_index_collections")
                    )
            await database.stop()

    asyncio.run(scenario())


async def _seed_command(
    database: Database,
    *,
    assistant_id: UUID,
    connection_id: UUID,
    suffix: str,
    user_id: str = "user-1",
    conversation_type: ConversationType = ConversationType.GROUP,
) -> tuple[ConversationModel, ParticipantModel, MessageModel, TelegramCommandJobModel]:
    async with database.session_factory() as session:
        async with session.begin():
            conversation = ConversationModel(
                platform_connection_id=connection_id,
                platform_conversation_id=f"chat-{suffix}",
                conversation_type=conversation_type,
            )
            session.add(conversation)
            await session.flush()
            participant = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id=user_id,
                username="private-username",
                display_name="Private Name",
                metadata_={"private": "metadata"},
            )
            session.add(participant)
            await session.flush()
            message = MessageModel(
                conversation_id=conversation.id,
                participant_id=participant.id,
                platform_message_id=f"message-{suffix}",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="/memory remember secret fact",
                metadata_={"private": "message-metadata"},
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_sent_at=datetime.now(UTC),
            )
            incoming = IncomingPlatformUpdateModel(
                platform_connection_id=connection_id,
                platform=Platform.TELEGRAM,
                platform_update_id=f"update-{suffix}",
                update_type="message",
                ingress_source=IngressSource.POLLING,
                raw_payload={"private": "payload"},
                received_at=datetime.now(UTC),
            )
            session.add_all([message, incoming])
            await session.flush()
            record = ConversationProcessingRecordModel(
                incoming_update_id=incoming.id,
                outcome=ProcessingOutcome.MESSAGE_CREATED,
                conversation_id=conversation.id,
                message_id=message.id,
                eligible=False,
                eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
            )
            session.add(record)
            await session.flush()
            job = TelegramCommandJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation.id,
                message_id=message.id,
                participant_id=participant.id,
                command_name="memory",
                arguments="remember secret fact",
            )
            session.add(job)
            await session.flush()
            return conversation, participant, message, job


@pytest.mark.integration
@pytest.mark.memory_integration
def test_memory_scope_profile_erasure_and_inspector_are_content_safe() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    other_assistant = AssistantModel(slug="memory-other", name="Other")
                    session.add_all([assistant, other_assistant])
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="memory-primary",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    other_connection = PlatformConnectionModel(
                        assistant_id=other_assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="memory-other",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add_all([connection, other_connection])
                    await session.flush()
                    (
                        assistant_id,
                        connection_id,
                        other_assistant_id,
                        other_connection_id,
                    ) = (
                        assistant.id,
                        connection.id,
                        other_assistant.id,
                        other_connection.id,
                    )

            primary = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="primary",
            )
            sibling = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="sibling",
            )
            other = await _seed_command(
                database,
                assistant_id=other_assistant_id,
                connection_id=other_connection_id,
                suffix="other",
            )
            repository = SqlAlchemyMemoryRepository(database.session_factory, "version")
            primary_memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=primary[0].id,
                creator_participant_id=primary[1].id,
                source_message_id=primary[2].id,
                source_command_job_id=primary[3].id,
                draft=normalize_explicit_memory(
                    "secret memory primary", MemoryScope.GROUP_CONVERSATION
                ),
            )
            sibling_memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=sibling[0].id,
                creator_participant_id=sibling[1].id,
                source_message_id=sibling[2].id,
                source_command_job_id=sibling[3].id,
                draft=normalize_explicit_memory(
                    "secret memory sibling", MemoryScope.GROUP_CONVERSATION
                ),
            )
            other_memory = await repository.create(
                assistant_id=other_assistant_id,
                platform_connection_id=other_connection_id,
                conversation_id=other[0].id,
                creator_participant_id=other[1].id,
                source_message_id=other[2].id,
                source_command_job_id=other[3].id,
                draft=normalize_explicit_memory(
                    "secret memory other", MemoryScope.GROUP_CONVERSATION
                ),
            )
            listed = await repository.active_for_conversation(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=primary[0].id,
            )
            assert [entry.item.id for entry in listed] == [primary_memory.id]

            erased = await SqlAlchemyPrivacyRepository(
                database.session_factory, "version"
            ).erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id="user-1",
                command_job_id=primary[3].id,
            )
            assert erased.memories == 2
            assert erased.participants == 2
            assert erased.messages == 2
            assert erased.incoming_updates == 2
            assert erased.command_arguments == 2
            assert not erased.already_deleted
            async with database.session_factory() as session:
                primary_after = await session.get(MemoryItemModel, primary_memory.id)
                sibling_after = await session.get(MemoryItemModel, sibling_memory.id)
                other_after = await session.get(MemoryItemModel, other_memory.id)
                primary_participant = await session.get(ParticipantModel, primary[1].id)
                primary_message = await session.get(MessageModel, primary[2].id)
                primary_job = await session.get(TelegramCommandJobModel, primary[3].id)
                primary_update = await session.scalar(
                    select(IncomingPlatformUpdateModel).where(
                        IncomingPlatformUpdateModel.platform_update_id
                        == "update-primary"
                    )
                )
                event_codes = list(
                    await session.scalars(select(MemoryEventModel.action_code))
                )
                assert primary_after is not None
                assert primary_after.content is None
                assert primary_after.normalized_content_hash is None
                assert sibling_after is not None
                assert sibling_after.content is None
                assert other_after is not None
                assert other_after.content == "secret memory other"
                assert primary_participant is not None
                assert primary_participant.display_name == "Deleted user"
                assert primary_message is not None and primary_message.text is None
                assert primary_job is not None and primary_job.arguments == ""
                assert primary_update is not None and primary_update.raw_payload == {}
                assert "profile_deleted" in event_codes
                semantic_delete_ids = set(
                    await session.scalars(
                        select(ExplicitMemorySemanticIndexJobModel.memory_id).where(
                            ExplicitMemorySemanticIndexJobModel.operation
                            == SemanticMemoryIndexOperation.DELETE
                        )
                    )
                )
                assert semantic_delete_ids == {primary_memory.id, sibling_memory.id}
            other_list = await repository.active_for_conversation(
                assistant_id=other_assistant_id,
                platform_connection_id=other_connection_id,
                conversation_id=other[0].id,
            )
            assert [entry.item.content for entry in other_list] == [
                "secret memory other"
            ]
            report = await inspect_latest(settings, conversation_id=primary[0].id)
            report_json = json.dumps(report)
            assert "secret memory primary" not in report_json
            assert "private-username" not in report_json
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_retention_redacts_terminal_content_at_the_exact_cutoff_idempotently() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(text("TRUNCATE assistants CASCADE"))
                    await _ensure_legacy_tenant(session)
                    assistant = AssistantModel(name="January")
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id="retention-bot",
                        status=PlatformConnectionStatus.ACTIVE,
                    )
                    session.add(connection)
                    await session.flush()
                    assistant_id, connection_id = assistant.id, connection.id
            conversation, participant, message, job = await _seed_command(
                database,
                assistant_id=assistant_id,
                connection_id=connection_id,
                suffix="retention",
            )
            now = datetime(2026, 8, 1, tzinfo=UTC)
            cutoff = now - timedelta(days=30)
            async with database.session_factory() as session:
                async with session.begin():
                    job = await session.get(TelegramCommandJobModel, job.id)
                    assert job is not None
                    job.status = CommandJobStatus.COMPLETED
                    job.completed_at = cutoff
                    plan = ResponsePlanModel(
                        command_job_id=job.id,
                        should_respond=True,
                        reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                        text="secret response plan",
                        reply_to_message_id=message.id,
                        mention_participant_ids=[],
                        confidence=1.0,
                        language="en",
                        prompt_version="test",
                        schema_version="test",
                        created_at=cutoff,
                    )
                    session.add(plan)
                    await session.flush()
                    action = OutboundActionModel(
                        response_plan_id=plan.id,
                        conversation_id=conversation.id,
                        sequence_number=1,
                        idempotency_key="retention-action",
                        kind=OutboundActionKind.TEXT,
                        status=OutboundActionStatus.DELIVERED,
                        text="secret outbound action",
                        mention_participant_ids=[],
                        created_at=cutoff,
                    )
                    session.add(action)
                    persisted_message = await session.get(MessageModel, message.id)
                    assert persisted_message is not None
                    persisted_message.platform_sent_at = cutoff
                    persisted_message.text = "secret source message"
                    incoming = await session.scalar(
                        select(IncomingPlatformUpdateModel).where(
                            IncomingPlatformUpdateModel.platform_update_id
                            == "update-retention"
                        )
                    )
                    assert incoming is not None
                    incoming.received_at = cutoff
            counts = await SqlAlchemyRetentionRepository(
                database.session_factory
            ).redact_once(now=now, retention_days=30, batch_size=10)
            assert counts.incoming_updates == 1
            assert counts.messages == 1
            assert counts.response_plans == 1
            assert counts.outbound_actions == 1
            assert counts.command_arguments == 1
            assert (
                await SqlAlchemyRetentionRepository(
                    database.session_factory
                ).redact_once(now=now, retention_days=30, batch_size=10)
                == type(counts)()
            )
            async with database.session_factory() as session:
                message_after = await session.get(MessageModel, message.id)
                job_after = await session.get(TelegramCommandJobModel, job.id)
                plan_after = await session.scalar(
                    select(ResponsePlanModel).where(
                        ResponsePlanModel.command_job_id == job.id
                    )
                )
                action_after = await session.scalar(
                    select(OutboundActionModel).where(
                        OutboundActionModel.idempotency_key == "retention-action"
                    )
                )
                assert message_after is not None and message_after.text is None
                assert job_after is not None and job_after.arguments == ""
                assert plan_after is not None and plan_after.text is None
                assert action_after is not None and action_after.text is None
        finally:
            await database.stop()

    asyncio.run(scenario())
