"""PostgreSQL proof for SPEC-027 ownership, replay, recall, and governance."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.governance_export import GovernanceExportBuilder
from app.application.memory import normalize_explicit_memory, normalize_personal_context
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    ParticipantRole,
    Platform,
    PlatformConnectionStatus,
    SemanticMemoryIndexJobStatus,
    SemanticMemoryIndexOperation,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.context import SqlAlchemyConversationContextReader
from app.infrastructure.database.database import Database
from app.infrastructure.database.memory import SqlAlchemyMemoryRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ExplicitMemorySemanticIndexJobModel,
    IncomingPlatformUpdateModel,
    MemoryControlOperationModel,
    MemoryEventModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)
from app.infrastructure.semantic_memory import SemanticMemoryRetriever


@pytest.mark.integration
@pytest.mark.memory_integration
def test_personal_context_schema_is_current() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == "0026_conversation_feedback"
                )
                memory_columns = set(
                    await connection.scalars(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = 'memory_items'"
                        )
                    )
                )
                assert {"context_key", "revision"} <= memory_columns
                assert {
                    "memory_recall_policies",
                    "memory_control_operations",
                } <= set(
                    await connection.scalars(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_explicit_correction_reopens_index_work_once() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                _,
            ) = await _seed_scope(database, suffix="explicit-correction")
            create_id, message_id = await _add_command(
                database, conversation_id, owner_id, connection_id, "fact-create"
            )
            repository = SqlAlchemyMemoryRepository(database.session_factory, "v1")
            memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                creator_participant_id=owner_id,
                source_message_id=message_id,
                source_command_job_id=create_id,
                draft=normalize_explicit_memory(
                    "old fact", MemoryScope.PRIVATE_CONVERSATION
                ),
            )
            async with database.session_factory() as session:
                async with session.begin():
                    job = await session.scalar(
                        select(ExplicitMemorySemanticIndexJobModel)
                    )
                    assert job is not None
                    job.status = SemanticMemoryIndexJobStatus.COMPLETED
                    job.target_collection = "synthetic_rebuild_target"
            edit_id, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "fact-edit"
            )
            arguments = dict(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=owner_id,
                command_job_id=edit_id,
                public_id=memory.public_id,
                expected_revision=1,
                content="corrected fact",
            )
            result = await repository.update_owned(**arguments)
            assert result.outcome == "updated"
            assert result.revision == 2
            assert await repository.update_owned(**arguments) == result
            async with database.session_factory() as session:
                jobs = list(
                    await session.scalars(select(ExplicitMemorySemanticIndexJobModel))
                )
                assert len(jobs) == 1
                assert jobs[0].operation == SemanticMemoryIndexOperation.UPSERT
                assert jobs[0].status == SemanticMemoryIndexJobStatus.PENDING
                assert jobs[0].target_collection == "synthetic_rebuild_target"
                stored = await session.get(MemoryItemModel, memory.id)
                assert stored is not None and stored.content == "corrected fact"
                assert stored.revision == 2
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(MemoryEventModel)
                        .where(MemoryEventModel.action_code == "updated")
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_default_recall_enable_replays_without_creating_policy() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                _,
            ) = await _seed_scope(database, suffix="default-recall")
            command_id, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "default-on"
            )
            repository = SqlAlchemyMemoryRepository(database.session_factory)
            arguments = dict(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=owner_id,
                command_job_id=command_id,
                enabled=True,
            )
            result = await repository.set_recall(**arguments)
            assert result.outcome == "unchanged"
            assert result.revision == 0
            assert result.recall_enabled is True
            assert await repository.set_recall(**arguments) == result
            # A known durable command ID does not authorize a different actor
            # or Assistant, including on the replay fast path.
            with pytest.raises(ValueError, match="scope is not authorized"):
                await repository.set_recall(**{**arguments, "participant_id": uuid4()})
            with pytest.raises(ValueError, match="scope is not authorized"):
                await repository.set_recall(**{**arguments, "assistant_id": uuid4()})
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(MemoryRecallPolicyModel)
                    )
                    == 0
                )
                operation = await session.scalar(select(MemoryControlOperationModel))
                assert operation is not None
                assert operation.resulting_revision is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_personal_context_creation_fails_closed_in_group() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                _,
            ) = await _seed_scope(
                database,
                suffix="group-denial",
                conversation_type=ConversationType.GROUP,
            )
            command_id, message_id = await _add_command(
                database, conversation_id, owner_id, connection_id, "group-context"
            )
            repository = SqlAlchemyMemoryRepository(database.session_factory)
            first = await repository.create_personal_context(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                creator_participant_id=owner_id,
                source_message_id=message_id,
                source_command_job_id=command_id,
                draft=normalize_personal_context("preferred_name", "Private value"),
            )
            replay = await repository.create_personal_context(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                creator_participant_id=owner_id,
                source_message_id=message_id,
                source_command_job_id=command_id,
                draft=normalize_personal_context("preferred_name", "Changed"),
            )
            assert first.outcome == "scope_denied"
            assert replay == first
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(MemoryItemModel.id)).where(
                            MemoryItemModel.kind == MemoryKind.PERSONAL_CONTEXT
                        )
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_personal_context_replay_race_ownership_recall_and_prompt_scope() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                foreign_id,
            ) = await _seed_scope(database, suffix="control")
            command_a, message_a = await _add_command(
                database, conversation_id, owner_id, connection_id, "create-a"
            )
            command_b, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "create-b"
            )
            repository = SqlAlchemyMemoryRepository(
                database.session_factory, "embedding-v1"
            )
            common = {
                "assistant_id": assistant_id,
                "platform_connection_id": connection_id,
                "conversation_id": conversation_id,
                "creator_participant_id": owner_id,
            }

            first, second = await asyncio.gather(
                repository.create_personal_context(
                    **common,
                    source_message_id=message_a,
                    source_command_job_id=command_a,
                    draft=normalize_personal_context("preferred_name", "Mai"),
                ),
                repository.create_personal_context(
                    **common,
                    source_message_id=(
                        await _message_id_for_command(database, command_b)
                    ),
                    source_command_job_id=command_b,
                    draft=normalize_personal_context("preferred_name", "Other"),
                ),
            )
            assert {first.outcome, second.outcome} == {"created", "conflict"}
            replay = await repository.create_personal_context(
                **common,
                source_message_id=message_a,
                source_command_job_id=command_a,
                draft=normalize_personal_context("preferred_name", "Changed replay"),
            )
            assert replay == first

            public_id = (
                first.public_id if first.outcome == "created" else second.public_id
            )
            assert public_id is not None
            other_conversation_id, same_platform_subject_id = await _add_private_scope(
                database,
                connection_id=connection_id,
                suffix="same-platform-subject",
                user_id="owner-user-control",
            )
            cross_conversation_command, _ = await _add_command(
                database,
                other_conversation_id,
                same_platform_subject_id,
                connection_id,
                "cross-conversation-update",
            )
            cross_conversation = await repository.update_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=other_conversation_id,
                actor_id=same_platform_subject_id,
                command_job_id=cross_conversation_command,
                public_id=public_id,
                expected_revision=1,
                content="cross conversation",
            )
            assert cross_conversation.outcome == "missing"
            wrong_scope_command, _ = await _add_command(
                database,
                conversation_id,
                owner_id,
                connection_id,
                "wrong-assistant-update",
            )
            with pytest.raises(ValueError, match="not authorized"):
                await repository.update_owned(
                    assistant_id=uuid4(),
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    actor_id=owner_id,
                    command_job_id=wrong_scope_command,
                    public_id=public_id,
                    expected_revision=1,
                    content="cross tenant",
                )
            foreign_command, _ = await _add_command(
                database, conversation_id, foreign_id, connection_id, "foreign-update"
            )
            denied = await repository.update_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=foreign_id,
                command_job_id=foreign_command,
                public_id=public_id,
                expected_revision=1,
                content="stolen",
            )
            assert denied.outcome == "denied"

            update_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "owner-update"
            )
            updated = await repository.update_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=owner_id,
                command_job_id=update_command,
                public_id=public_id,
                expected_revision=1,
                content="Mai Nguyen",
            )
            assert updated.outcome == "updated"
            assert updated.revision == 2
            stale_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "stale-update"
            )
            stale = await repository.update_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=owner_id,
                command_job_id=stale_command,
                public_id=public_id,
                expected_revision=1,
                content="stale",
            )
            assert stale.outcome == "conflict"
            assert stale.revision == 2

            visible_to_owner = await repository.active_for_conversation(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                viewer_participant_id=owner_id,
            )
            visible_to_foreign = await repository.active_for_conversation(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                viewer_participant_id=foreign_id,
            )
            assert [entry.item.public_id for entry in visible_to_owner] == [public_id]
            assert visible_to_foreign == []
            with pytest.raises(ValueError, match="scope is not authorized"):
                await repository.active_for_conversation(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    viewer_participant_id=same_platform_subject_id,
                )

            context = await SqlAlchemyConversationContextReader(
                database.session_factory, Settings(_env_file=None, environment="test")
            ).build_for_message(message_a)
            assert context is not None
            assert [item.content for item in context.personal_context] == ["Mai Nguyen"]

            race_update_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "race-update"
            )
            race_delete_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "race-delete"
            )
            race_update, race_delete = await asyncio.gather(
                repository.update_owned(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    actor_id=owner_id,
                    command_job_id=race_update_command,
                    public_id=public_id,
                    expected_revision=2,
                    content="race update",
                ),
                repository.delete_owned(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    actor_id=owner_id,
                    command_job_id=race_delete_command,
                    public_id=public_id,
                    expected_revision=2,
                ),
            )
            assert (race_update.outcome, race_delete.outcome) in {
                ("updated", "conflict"),
                ("missing", "deleted"),
            }

            recall_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "recall-off"
            )
            disabled = await repository.set_recall(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=owner_id,
                command_job_id=recall_command,
                enabled=False,
            )
            assert disabled.outcome == "disabled"
            context = await SqlAlchemyConversationContextReader(
                database.session_factory, Settings(_env_file=None, environment="test")
            ).build_for_message(message_a)
            assert context is not None
            assert context.personal_context == ()
            assert context.explicit_memories == ()

            recall_on_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "recall-on"
            )
            enabled = await repository.set_recall(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=owner_id,
                command_job_id=recall_on_command,
                enabled=True,
            )
            assert enabled.outcome == "enabled"
            assert enabled.revision == 2
            context = await SqlAlchemyConversationContextReader(
                database.session_factory, Settings(_env_file=None, environment="test")
            ).build_for_message(message_a)
            assert context is not None
            assert [item.content for item in context.personal_context] in [
                [],
                ["race update"],
            ]

            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(MemoryItemModel.id)).where(
                            MemoryItemModel.kind == MemoryKind.PERSONAL_CONTEXT
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(MemoryControlOperationModel.id))
                    )
                    == 10
                )
                assert (
                    await session.scalar(
                        select(func.count(ExplicitMemorySemanticIndexJobModel.id))
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_clear_is_bounded_replayable_and_subject_export_and_erasure_are_exact() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                foreign_id,
            ) = await _seed_scope(database, suffix="clear")
            repository = SqlAlchemyMemoryRepository(
                database.session_factory, "embedding-v1", control_batch_size=2
            )
            for index, key in enumerate(
                ("preferred_name", "preferred_language", "personal_note")
            ):
                command_id, message_id = await _add_command(
                    database,
                    conversation_id,
                    owner_id,
                    connection_id,
                    f"personal-{index}",
                )
                result = await repository.create_personal_context(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    creator_participant_id=owner_id,
                    source_message_id=message_id,
                    source_command_job_id=command_id,
                    draft=normalize_personal_context(key, f"value {index}"),
                )
                assert result.outcome == "created"
            explicit_command, explicit_message = await _add_command(
                database, conversation_id, owner_id, connection_id, "explicit"
            )
            await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                creator_participant_id=owner_id,
                source_message_id=explicit_message,
                source_command_job_id=explicit_command,
                draft=normalize_explicit_memory(
                    "owned explicit fact", MemoryScope.PRIVATE_CONVERSATION
                ),
            )
            foreign_command, foreign_message = await _add_command(
                database, conversation_id, foreign_id, connection_id, "foreign"
            )
            foreign_memory = await repository.create(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                creator_participant_id=foreign_id,
                source_message_id=foreign_message,
                source_command_job_id=foreign_command,
                draft=normalize_explicit_memory(
                    "foreign explicit fact", MemoryScope.PRIVATE_CONVERSATION
                ),
            )
            recall_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "recall"
            )
            await repository.set_recall(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=owner_id,
                command_job_id=recall_command,
                enabled=False,
            )
            exported = await GovernanceExportBuilder(
                database.session_factory
            ).build_subject_export(
                request_id=UUID("00000000-0000-0000-0000-000000000027"),
                conversation_id=conversation_id,
                participant_id=owner_id,
            )
            exported_data = exported["data"]
            assert isinstance(exported_data, dict)
            assert exported_data["memory_recall"] == {"enabled": False, "revision": 1}
            memories = exported_data["memories"]
            assert isinstance(memories, list)
            assert len(memories) == 4
            assert all(
                memory["content"] != "foreign explicit fact" for memory in memories
            )
            group_export = await GovernanceExportBuilder(
                database.session_factory
            ).build_group_export(
                request_id=UUID("00000000-0000-0000-0000-000000000127"),
                conversation_id=conversation_id,
            )
            group_data = group_export["data"]
            assert isinstance(group_data, dict)
            assert group_data["memories"] == []
            assert "memory_recall" not in group_data

            clear_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "clear-owned"
            )
            cleared = await repository.clear_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=owner_id,
                command_job_id=clear_command,
            )
            assert cleared.outcome == "cleared"
            assert cleared.affected_count == 4
            assert (
                await repository.clear_owned(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    actor_id=owner_id,
                    command_job_id=clear_command,
                )
                == cleared
            )
            async with database.session_factory() as session:
                foreign_after = await session.get(MemoryItemModel, foreign_memory.id)
                assert foreign_after is not None
                assert foreign_after.status == MemoryStatus.ACTIVE
                batch_sizes = list(
                    await session.scalars(
                        select(MemoryEventModel.affected_count)
                        .where(
                            MemoryEventModel.command_job_id == clear_command,
                            MemoryEventModel.action_code == "cleared_owned_batch",
                        )
                        .order_by(MemoryEventModel.created_at, MemoryEventModel.id)
                    )
                )
                assert batch_sizes == [2, 2]

            foreign_recall_off, _ = await _add_command(
                database,
                conversation_id,
                foreign_id,
                connection_id,
                "foreign-recall-off",
            )
            await repository.set_recall(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=foreign_id,
                command_job_id=foreign_recall_off,
                enabled=False,
            )
            assert (
                await SqlAlchemySemanticMemoryRepository(
                    database.session_factory
                ).revalidate_matches(
                    (foreign_memory.id,),
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    scope=MemoryScope.PRIVATE_CONVERSATION,
                )
                == {}
            )
            foreign_recall_on, _ = await _add_command(
                database,
                conversation_id,
                foreign_id,
                connection_id,
                "foreign-recall-on",
            )
            await repository.set_recall(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                participant_id=foreign_id,
                command_job_id=foreign_recall_on,
                enabled=True,
            )
            erase_command, _ = await _add_command(
                database, conversation_id, foreign_id, connection_id, "erase"
            )
            erased = await SqlAlchemyPrivacyRepository(
                database.session_factory, "embedding-v1"
            ).erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id="foreign-user-clear",
                command_job_id=erase_command,
            )
            assert erased.memories == 1
            assert erased.recall_policies == 1
            async with database.session_factory() as session:
                foreign_after = await session.get(MemoryItemModel, foreign_memory.id)
                assert foreign_after is not None
                assert foreign_after.content is None
                policies = list(
                    await session.scalars(
                        select(MemoryRecallPolicyModel).where(
                            MemoryRecallPolicyModel.participant_id == foreign_id
                        )
                    )
                )
                assert len(policies) == 1
                assert policies[0].enabled is False
                assert policies[0].revision == 3
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_context_closes_database_session_before_semantic_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        database = Database(
            Settings(
                _env_file=None,
                environment="test",
                semantic_memory_enabled=True,
                embedding_provider="ollama",
                embedding_model="fake",
                embedding_dimension=2,
            )
        )
        await database.start()
        try:
            _, connection_id, conversation_id, owner_id, _ = await _seed_scope(
                database, suffix="transaction-boundary"
            )
            _, message_id = await _add_command(
                database,
                conversation_id,
                owner_id,
                connection_id,
                "transaction-boundary",
            )

            semantic_calls: list[bool] = []

            async def retrieve_without_database_lock(
                self: SemanticMemoryRetriever, *args: object, **kwargs: object
            ) -> tuple[object, ...]:
                assert database.engine.pool.checkedout() == 0
                semantic_calls.append(True)
                return ()

            monkeypatch.setattr(
                SemanticMemoryRetriever, "retrieve", retrieve_without_database_lock
            )
            context = await SqlAlchemyConversationContextReader(
                database.session_factory,
                Settings(
                    _env_file=None,
                    environment="test",
                    semantic_memory_enabled=True,
                    embedding_provider="ollama",
                    embedding_model="fake",
                    embedding_dimension=2,
                ),
            ).build_for_message(message_id)
            assert context is not None
            assert semantic_calls == [True]

            scalar = AsyncSession.scalar

            async def failed_recall_lookup(
                self: AsyncSession, statement: object, *args: object, **kwargs: object
            ) -> object:
                if "memory_recall_policies" in str(statement):
                    raise SQLAlchemyError("synthetic recall lookup failure")
                return await scalar(self, statement, *args, **kwargs)

            monkeypatch.setattr(AsyncSession, "scalar", failed_recall_lookup)
            without_memory = await SqlAlchemyConversationContextReader(
                database.session_factory,
                Settings(
                    _env_file=None,
                    environment="test",
                    semantic_memory_enabled=True,
                    embedding_provider="ollama",
                    embedding_model="fake",
                    embedding_dimension=2,
                ),
            ).build_for_message(message_id)
            assert without_memory is not None
            assert without_memory.personal_context == ()
            assert without_memory.explicit_memories == ()
            assert semantic_calls == [True]
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.memory_integration
def test_personal_context_expiry_is_content_clearing_and_multi_batch() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            (
                assistant_id,
                connection_id,
                conversation_id,
                owner_id,
                _,
            ) = await _seed_scope(database, suffix="expiry")
            repository = SqlAlchemyMemoryRepository(database.session_factory)
            item_ids: list[UUID] = []
            for index, key in enumerate(
                ("preferred_name", "preferred_language", "personal_note")
            ):
                command_id, message_id = await _add_command(
                    database,
                    conversation_id,
                    owner_id,
                    connection_id,
                    f"expiry-{index}",
                )
                result = await repository.create_personal_context(
                    assistant_id=assistant_id,
                    platform_connection_id=connection_id,
                    conversation_id=conversation_id,
                    creator_participant_id=owner_id,
                    source_message_id=message_id,
                    source_command_job_id=command_id,
                    draft=normalize_personal_context(key, f"expire {index}"),
                )
                assert result.public_id is not None
                async with database.session_factory() as session:
                    async with session.begin():
                        item = await session.scalar(
                            select(MemoryItemModel).where(
                                MemoryItemModel.public_id == result.public_id
                            )
                        )
                        assert item is not None
                        item.expires_at = datetime(2026, 1, 1, tzinfo=UTC)
                        item_ids.append(item.id)

            edit_command, _ = await _add_command(
                database, conversation_id, owner_id, connection_id, "expired-edit"
            )
            assert result.public_id is not None
            edit = await repository.update_owned(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                conversation_id=conversation_id,
                actor_id=owner_id,
                command_job_id=edit_command,
                public_id=result.public_id,
                expected_revision=1,
                content="must not revive expired memory",
            )
            assert edit.outcome == "missing"

            retention = SqlAlchemyRetentionRepository(database.session_factory)
            first = await retention.redact_once(
                now=datetime(2026, 1, 2, tzinfo=UTC),
                retention_days=30,
                batch_size=2,
            )
            second = await retention.redact_once(
                now=datetime(2026, 1, 2, tzinfo=UTC),
                retention_days=30,
                batch_size=2,
            )
            third = await retention.redact_once(
                now=datetime(2026, 1, 2, tzinfo=UTC),
                retention_days=30,
                batch_size=2,
            )
            assert (first.memories, second.memories, third.memories) == (2, 1, 0)
            async with database.session_factory() as session:
                items = list(
                    await session.scalars(
                        select(MemoryItemModel).where(MemoryItemModel.id.in_(item_ids))
                    )
                )
                assert all(item.status == MemoryStatus.EXPIRED for item in items)
                assert all(item.content is None for item in items)
                assert all(item.normalized_content_hash is None for item in items)
                assert (
                    await session.scalar(
                        select(func.count(ExplicitMemorySemanticIndexJobModel.id))
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


async def _seed_scope(
    database: Database,
    *,
    suffix: str,
    conversation_type: ConversationType = ConversationType.PRIVATE,
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    async with database.session_factory() as session:
        async with session.begin():
            await session.execute(text("TRUNCATE assistants CASCADE"))
            assistant = AssistantModel(
                tenant_id=LEGACY_TENANT_ID,
                slug="context-january",
                name="January",
                status=AssistantStatus.ACTIVE,
            )
            session.add(assistant)
            await session.flush()
            connection = PlatformConnectionModel(
                tenant_id=LEGACY_TENANT_ID,
                assistant_id=assistant.id,
                platform=Platform.TELEGRAM,
                external_bot_id=f"personal-{suffix}",
                status=PlatformConnectionStatus.ACTIVE,
            )
            session.add(connection)
            await session.flush()
            conversation = ConversationModel(
                platform_connection_id=connection.id,
                platform_conversation_id=f"private-{suffix}",
                conversation_type=conversation_type,
            )
            session.add(conversation)
            await session.flush()
            owner = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id=f"owner-user-{suffix}",
                display_name="Owner",
            )
            foreign = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id=f"foreign-user-{suffix}",
                display_name="Foreign",
                role=ParticipantRole.ADMINISTRATOR,
            )
            session.add_all([owner, foreign])
            await session.flush()
            return assistant.id, connection.id, conversation.id, owner.id, foreign.id


async def _add_private_scope(
    database: Database, *, connection_id: UUID, suffix: str, user_id: str
) -> tuple[UUID, UUID]:
    async with database.session_factory() as session:
        async with session.begin():
            conversation = ConversationModel(
                platform_connection_id=connection_id,
                platform_conversation_id=f"private-{suffix}",
                conversation_type=ConversationType.PRIVATE,
            )
            session.add(conversation)
            await session.flush()
            participant = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id=user_id,
                display_name="Same platform subject, separate scope",
            )
            session.add(participant)
            await session.flush()
            return conversation.id, participant.id


async def _add_command(
    database: Database,
    conversation_id: UUID,
    participant_id: UUID,
    connection_id: UUID,
    suffix: str,
) -> tuple[UUID, UUID]:
    async with database.session_factory() as session:
        async with session.begin():
            message = MessageModel(
                conversation_id=conversation_id,
                participant_id=participant_id,
                platform_message_id=f"message-{suffix}",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="/memory",
                metadata_={},
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_sent_at=datetime.now(UTC),
            )
            incoming = IncomingPlatformUpdateModel(
                platform_connection_id=connection_id,
                platform=Platform.TELEGRAM,
                platform_update_id=f"update-{suffix}",
                update_type="message",
                ingress_source=IngressSource.POLLING,
                raw_payload={},
                received_at=datetime.now(UTC),
            )
            session.add_all([message, incoming])
            await session.flush()
            record = ConversationProcessingRecordModel(
                incoming_update_id=incoming.id,
                outcome=ProcessingOutcome.MESSAGE_CREATED,
                conversation_id=conversation_id,
                message_id=message.id,
                eligible=False,
                eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
            )
            session.add(record)
            await session.flush()
            job = TelegramCommandJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation_id,
                message_id=message.id,
                participant_id=participant_id,
                command_name="memory",
                arguments=suffix,
            )
            session.add(job)
            await session.flush()
            return job.id, message.id


async def _message_id_for_command(database: Database, command_id: UUID) -> UUID:
    async with database.session_factory() as session:
        value = await session.scalar(
            select(TelegramCommandJobModel.message_id).where(
                TelegramCommandJobModel.id == command_id
            )
        )
        assert value is not None
        return value
