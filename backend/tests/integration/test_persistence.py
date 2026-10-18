import asyncio
from datetime import UTC

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.domain.persistence import (
    AssistantStatus,
    ConversationStatus,
    ConversationType,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    ParticipantRole,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database, get_session
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
)
from app.infrastructure.database.repositories import (
    SqlAlchemyAssistantRepository,
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyParticipantRepository,
    SqlAlchemyPlatformConnectionRepository,
)


@pytest.fixture
def database() -> Database:
    return Database(Settings(_env_file=None, environment="test"))


async def clear_database(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE messages, participants, conversations, "
                "platform_connections, assistants CASCADE"
            )
        )


@pytest.mark.integration
def test_models_constraints_jsonb_repositories_and_timestamps(
    database: Database,
) -> None:
    async def scenario() -> None:
        await database.start()
        assert await database.is_ready()
        await clear_database(database)
        async with database.session_factory() as session:
            async with session.begin():
                assistant = AssistantModel(
                    tenant_id=LEGACY_TENANT_ID,
                    slug="january",
                    name="January",
                    status=AssistantStatus.ACTIVE,
                )
                session.add(assistant)
                await session.flush()
                connection = PlatformConnectionModel(
                    tenant_id=LEGACY_TENANT_ID,
                    assistant_id=assistant.id,
                    platform=Platform.TELEGRAM,
                    external_bot_id="bot-1",
                    status=PlatformConnectionStatus.ACTIVE,
                    configuration={"capability": "future"},
                )
                session.add(connection)
                await session.flush()
                conversation = ConversationModel(
                    platform_connection_id=connection.id,
                    platform_conversation_id="conversation-1",
                    conversation_type=ConversationType.GROUP,
                    status=ConversationStatus.ACTIVE,
                    response_mode=ResponseMode.MENTION_ONLY,
                    settings={"language": "vi"},
                )
                session.add(conversation)
                await session.flush()
                participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id="user-1",
                    display_name="Member",
                    role=ParticipantRole.MEMBER,
                    metadata_={"source": "platform"},
                )
                session.add(participant)
                await session.flush()
                parent = MessageModel(
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    platform_message_id="message-1",
                    direction=MessageDirection.INCOMING,
                    message_type=MessageType.TEXT,
                    text="hello",
                    metadata_={"kind": "text"},
                    processing_status=MessageProcessingStatus.PENDING,
                )
                session.add(parent)
                await session.flush()
                reply = MessageModel(
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    platform_message_id="message-2",
                    direction=MessageDirection.OUTGOING,
                    message_type=MessageType.STICKER,
                    reply_to_message_id=parent.id,
                    metadata_={"intent": "laugh"},
                    processing_status=MessageProcessingStatus.PROCESSED,
                )
                session.add(reply)
                await session.flush()

                assert assistant.id is not None
                assert assistant.created_at.tzinfo is not None
                assert assistant.created_at.tzinfo == UTC
                original_updated_at = assistant.updated_at
                assistant.name = "January Updated"
                await session.flush()
                await session.refresh(assistant)
                assert assistant.updated_at >= original_updated_at
                assert connection.configuration == {"capability": "future"}
                assert reply.reply_to_message_id == parent.id
                assert participant.mention_allowed is True
                assert participant.teasing_allowed is False

            async with session.begin():
                assistants = SqlAlchemyAssistantRepository(session)
                connections = SqlAlchemyPlatformConnectionRepository(session)
                conversations = SqlAlchemyConversationRepository(session)
                participants = SqlAlchemyParticipantRepository(session)
                messages = SqlAlchemyMessageRepository(session)
                assert await assistants.get(assistant.id)
                assert await connections.get_by_platform_identity(
                    Platform.TELEGRAM, "bot-1"
                )
                assert await conversations.get_by_platform_identity(
                    connection.id, "conversation-1"
                )
                assert await participants.get_by_platform_identity(
                    conversation.id, "user-1"
                )
                assert await messages.get_by_platform_identity(
                    conversation.id, "message-2"
                )
                assert (
                    await messages.get_by_platform_identity(conversation.id, "other")
                    is None
                )

            session.add(
                PlatformConnectionModel(
                    tenant_id=LEGACY_TENANT_ID,
                    assistant_id=assistant.id,
                    platform=Platform.TELEGRAM,
                    external_bot_id="bot-1",
                    status=PlatformConnectionStatus.ACTIVE,
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
            await session.rollback()

        async with database.session_factory() as session:
            async with session.begin():
                added = await SqlAlchemyAssistantRepository(session).add(
                    LEGACY_TENANT_ID, "second", "Second"
                )
                assert added.name == "Second"

        async with database.engine.connect() as connection:
            foreign_key_transaction = await connection.begin()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO participants (id, conversation_id, "
                        "platform_user_id, "
                        "display_name, role, mention_allowed, teasing_allowed) "
                        "VALUES ('00000000-0000-0000-0000-000000000001', "
                        "'00000000-0000-0000-0000-000000000002', 'bad', 'bad', "
                        "'member', true, false)"
                    )
                )
            await foreign_key_transaction.rollback()

            enum_transaction = await connection.begin()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "INSERT INTO assistants "
                        "(id, tenant_id, slug, name, status) VALUES "
                        "('00000000-0000-0000-0000-000000000003', "
                        f"'{LEGACY_TENANT_ID}', 'invalid', 'invalid', 'wrongxxx')"
                    )
                )
            await enum_transaction.rollback()

        await clear_database(database)
        await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
def test_session_dependency_rolls_back_failed_work(database: Database) -> None:
    async def scenario() -> None:
        await database.start()
        await clear_database(database)
        with pytest.raises(RuntimeError):
            async for session in get_session(database):
                session.add(
                    AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="rolled-back",
                        name="Rolled back",
                    )
                )
                raise RuntimeError("force rollback")
        async with database.session_factory() as session:
            count = await session.scalar(text("SELECT count(*) FROM assistants"))
            assert count == 0
        await database.stop()

    asyncio.run(scenario())
