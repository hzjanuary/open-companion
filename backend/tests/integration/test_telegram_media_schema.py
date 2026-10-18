"""SPEC-028 PostgreSQL recovery/privacy proof (isolated project database only)."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from app.application.governance_export import GovernanceExportBuilder
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.media import MediaKind, MediaStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageType,
    Platform,
)
from app.domain.planning import PlanningJobStatus
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.media import (
    SqlAlchemyMediaRepository,
    redact_media_values,
)
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository

pytestmark = [pytest.mark.integration, pytest.mark.telegram_media_integration]


async def seed(database: Database, now: datetime) -> tuple[UUID, UUID, UUID]:
    async with database.session_factory() as session, session.begin():
        assistant = AssistantModel(
            tenant_id=LEGACY_TENANT_ID,
            slug=f"media-{uuid4().hex}",
            name="Media synthetic",
            status=AssistantStatus.ACTIVE,
        )
        session.add(assistant)
        await session.flush()
        connection = PlatformConnectionModel(
            tenant_id=LEGACY_TENANT_ID,
            assistant_id=assistant.id,
            platform=Platform.TELEGRAM,
            external_bot_id=str(uuid4()),
        )
        session.add(connection)
        await session.flush()
        conversation = ConversationModel(
            platform_connection_id=connection.id,
            platform_conversation_id=str(uuid4()),
            conversation_type=ConversationType.PRIVATE,
        )
        session.add(conversation)
        await session.flush()
        participant = ParticipantModel(
            conversation_id=conversation.id,
            platform_user_id=str(uuid4()),
            display_name="Synthetic",
        )
        session.add(participant)
        await session.flush()
        message = MessageModel(
            conversation_id=conversation.id,
            participant_id=participant.id,
            platform_message_id=str(uuid4()),
            direction=MessageDirection.INCOMING,
            message_type=MessageType.VOICE,
            text="caption",
            platform_sent_at=now,
            eligible=True,
            metadata_={"content_provenance": "media_caption"},
        )
        incoming = IncomingPlatformUpdateModel(
            platform_connection_id=connection.id,
            platform=Platform.TELEGRAM,
            platform_update_id=str(uuid4()),
            update_type="message",
            ingress_source=IngressSource.WEBHOOK,
            raw_payload={},
            received_at=now,
        )
        session.add_all([message, incoming])
        await session.flush()
        record = ConversationProcessingRecordModel(
            incoming_update_id=incoming.id,
            conversation_id=conversation.id,
            message_id=message.id,
            outcome=ProcessingOutcome.MESSAGE_CREATED,
        )
        session.add(record)
        await session.flush()
        job = ResponsePlanningJobModel(
            conversation_processing_record_id=record.id,
            conversation_id=conversation.id,
            message_id=message.id,
            prompt_version="spec028",
            response_schema_version="response-plan-v2",
            status=PlanningJobStatus.LEASED,
            lease_owner="media-test",
            attempt_count=1,
            lease_expires_at=now + timedelta(seconds=60),
        )
        media = MessageMediaModel(
            message_id=message.id,
            conversation_id=conversation.id,
            kind=MediaKind.VOICE,
            file_id="synthetic_file",
            file_unique_id="synthetic_unique",
            mime_type="audio/ogg",
            duration_seconds=10,
            caption="caption",
        )
        session.add_all([job, media])
        await session.flush()
        return connection.id, message.id, job.id


def repo(database: Database, connection_id: UUID) -> SqlAlchemyMediaRepository:
    return SqlAlchemyMediaRepository(
        database.session_factory,
        connection_id=connection_id,
        retention_days=30,
        lease_seconds=60,
        transcript_limit=4000,
    )


def test_transcript_replay_and_no_automatic_memory() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection, message_id, job = await seed(database, now)
            repository = repo(database, connection)
            work = await repository.claim(job, "media-test", 1, now=now)
            assert work is not None and work.lease_token is not None
            assert await repository.claim(job, "media-test", 1, now=now) is None
            assert await repository.finish_transcript(
                job, "media-test", 1, work.lease_token, "derived words", now=now
            )
            assert not await repository.finish_transcript(
                job, "media-test", 1, work.lease_token, "overwrite", now=now
            )
            replay = await repository.claim(job, "media-test", 1, now=now)
            assert replay is not None and replay.status == MediaStatus.COMPLETE
            async with database.session_factory() as session:
                message = await session.get(MessageModel, message_id)
                assert message is not None and message.text == "derived words"
                assert message.metadata_["content_provenance"] == "voice_transcript"
                assert not await session.scalar(
                    select(MemoryItemModel.id).where(
                        MemoryItemModel.source_message_id == message_id
                    )
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_expired_lease_reclaim_fences_same_owner_and_wrong_connection() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection, _, job = await seed(database, now)
            repository = repo(database, connection)
            original = await repository.claim(job, "media-test", 1, now=now)
            assert original is not None and original.lease_token is not None
            assert (
                await repo(database, uuid4()).claim(job, "media-test", 1, now=now)
                is None
            )
            later = now + timedelta(seconds=61)
            assert not await repository.preflight(
                job, "media-test", 1, original.lease_token, now=later
            )
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    update(ResponsePlanningJobModel)
                    .where(ResponsePlanningJobModel.id == job)
                    .values(
                        attempt_count=2, lease_expires_at=later + timedelta(seconds=60)
                    )
                )
            recovered = await repository.claim(job, "media-test", 2, now=later)
            assert (
                recovered is not None and recovered.lease_token != original.lease_token
            )
            assert not await repository.finish_transcript(
                job, "media-test", 1, original.lease_token, "late", now=later
            )
            assert recovered.lease_token is not None
            assert await repository.finish_transcript(
                job, "media-test", 2, recovered.lease_token, "current", now=later
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_photo_generation_and_completion_require_current_media_token() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection, message, job = await seed(database, now)
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    update(MessageModel)
                    .where(MessageModel.id == message)
                    .values(message_type=MessageType.PHOTO)
                )
                await session.execute(
                    update(MessageMediaModel)
                    .where(MessageMediaModel.message_id == message)
                    .values(
                        kind=MediaKind.PHOTO,
                        mime_type="image/jpeg",
                        duration_seconds=None,
                        width=100,
                        height=100,
                    )
                )
            repository = repo(database, connection)
            work = await repository.claim(job, "media-test", 1, now=now)
            assert work is not None and work.lease_token is not None
            wrong_token = uuid4()
            async with database.session_factory() as session:
                privacy_revision = await session.scalar(
                    select(MessageMediaModel.privacy_revision).where(
                        MessageMediaModel.message_id == message
                    )
                )
            assert privacy_revision is not None
            assert not await repository.generation_preflight(
                job,
                "media-test",
                1,
                privacy_revision,
                media_token=wrong_token,
                now=now,
            )
            planning = SqlAlchemyPlanningRepository(database.session_factory)
            assert (
                await planning.complete(
                    job,
                    "media-test",
                    None,
                    None,
                    None,
                    None,
                    "spec028",
                    "response-plan-v2",
                    expected_attempt=1,
                    expected_media_token=wrong_token,
                )
                is None
            )
            async with database.session_factory() as session:
                current = await session.get(ResponsePlanningJobModel, job)
                assert (
                    current is not None and current.status == PlanningJobStatus.LEASED
                )
            assert await repository.generation_preflight(
                job,
                "media-test",
                1,
                privacy_revision,
                media_token=work.lease_token,
                now=now,
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_redaction_during_io_prevents_transcript_resurrection() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection, message_id, job = await seed(database, now)
            repository = repo(database, connection)
            work = await repository.claim(job, "media-test", 1, now=now)
            assert work is not None and work.lease_token is not None
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    update(MessageMediaModel)
                    .where(MessageMediaModel.message_id == message_id)
                    .values(**redact_media_values(now))
                )
                await session.execute(
                    update(MessageModel)
                    .where(MessageModel.id == message_id)
                    .values(text=None, metadata_={}, content_redacted_at=now)
                )
            assert not await repository.preflight(
                job, "media-test", 1, work.lease_token, now=now
            )
            assert not await repository.finish_transcript(
                job, "media-test", 1, work.lease_token, "private late words", now=now
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_media_retention_is_multibatch_and_preserves_fresh_records() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            stale: list[UUID] = []
            for _ in range(5):
                _, message_id, _ = await seed(database, now - timedelta(days=31))
                stale.append(message_id)
            _, fresh, _ = await seed(database, now)
            # Seed terminal processing state just as the conversation worker does.
            async with database.session_factory() as session, session.begin():
                await session.execute(
                    update(MessageModel)
                    .where(MessageModel.id.in_(stale))
                    .values(processing_status="processed")
                )
            repository = SqlAlchemyRetentionRepository(database.session_factory)
            for _ in range(20):
                await repository.redact_once(now=now, retention_days=30, batch_size=2)
                async with database.session_factory() as session:
                    remaining = await session.scalar(
                        select(func.count())
                        .select_from(MessageMediaModel)
                        .where(
                            MessageMediaModel.message_id.in_(stale),
                            MessageMediaModel.status != MediaStatus.REDACTED,
                        )
                    )
                if not remaining:
                    break
            assert remaining == 0
            async with database.session_factory() as session:
                row = await session.scalar(
                    select(MessageMediaModel).where(
                        MessageMediaModel.message_id == fresh
                    )
                )
                assert row is not None and row.file_id == "synthetic_file"
            repeated = await repository.redact_once(
                now=now, retention_days=30, batch_size=2
            )
            assert repeated.messages == 0
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_real_subject_export_erasure_and_cross_conversation_denial() -> None:
    async def scenario():
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection_id, message_id, job_id = await seed(database, now)
            _, other_message_id, _ = await seed(database, now)
            repository = repo(database, connection_id)
            work = await repository.claim(job_id, "media-test", 1, now=now)
            assert work is not None and work.lease_token is not None
            assert await repository.finish_transcript(
                job_id,
                "media-test",
                1,
                work.lease_token,
                "owned derived words",
                now=now,
            )
            async with database.session_factory() as session:
                message = await session.get(MessageModel, message_id)
                participant = await session.get(
                    ParticipantModel, message.participant_id
                )
                connection = await session.get(PlatformConnectionModel, connection_id)
                other = await session.get(MessageModel, other_message_id)
                conversation_id, participant_id = (
                    message.conversation_id,
                    participant.id,
                )
                other_conversation_id = other.conversation_id
                assistant_id, platform_user_id = (
                    connection.assistant_id,
                    participant.platform_user_id,
                )
            builder = GovernanceExportBuilder(database.session_factory)
            package = await builder.build_subject_export(
                request_id=uuid4(),
                conversation_id=conversation_id,
                participant_id=participant_id,
                now=now,
            )
            assert "owned derived words" in str(package)
            assert "voice_transcript" in str(package)
            with pytest.raises(ValueError):
                await builder.build_subject_export(
                    request_id=uuid4(),
                    conversation_id=other_conversation_id,
                    participant_id=participant_id,
                    now=now,
                )
            privacy = SqlAlchemyPrivacyRepository(database.session_factory)
            result = await privacy.erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id=platform_user_id,
                command_job_id=uuid4(),
                now=now,
            )
            assert result.messages == 1
            async with database.session_factory() as session:
                erased = await session.get(MessageModel, message_id)
                metadata = await session.scalar(
                    select(MessageMediaModel).where(
                        MessageMediaModel.message_id == message_id
                    )
                )
                unrelated = await session.get(MessageModel, other_message_id)
                assert erased.text is None
                assert metadata.status == MediaStatus.REDACTED
                assert metadata.file_id is None and metadata.caption is None
                assert unrelated.text == "caption"
            assert not await repository.finish_transcript(
                job_id, "media-test", 1, work.lease_token, "late resurrection", now=now
            )
            repeated = await privacy.erase_subject(
                assistant_id=assistant_id,
                platform_connection_id=connection_id,
                platform_user_id=platform_user_id,
                command_job_id=uuid4(),
                now=now,
            )
            assert repeated.already_deleted
            package = await builder.build_subject_export(
                request_id=uuid4(),
                conversation_id=conversation_id,
                participant_id=participant_id,
                now=now,
            )
            assert "owned derived words" not in str(package)
            assert "synthetic_file" not in str(package)
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_concurrent_media_claims_have_one_live_owner() -> None:
    async def scenario():
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            now = datetime.now(UTC)
            connection, _, job = await seed(database, now)
            repository = repo(database, connection)
            claims = await asyncio.gather(
                repository.claim(job, "media-test", 1, now=now),
                repository.claim(job, "media-test", 1, now=now),
            )
            assert sum(item is not None for item in claims) == 1
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_duplicate_photo_ingress_has_one_attachment_and_planning_job() -> None:
    from dataclasses import replace

    from app.infrastructure.database.conversation import SqlAlchemyConversationProcessor
    from app.infrastructure.database.ingress import SqlAlchemyDurableIngressRepository
    from app.infrastructure.database.models import IngressOutboxEventModel
    from app.infrastructure.telegram.normalizer import normalize_telegram_update
    from app.infrastructure.telegram.updates import parse_telegram_update

    from .test_ingress import envelope

    async def scenario():
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            connection, _, _ = await seed(database, datetime.now(UTC))
            inbound = envelope(connection, str(uuid4().int % 1_000_000_000))
            payload = dict(inbound.raw_payload)
            payload["message"] = {
                **payload["message"],
                "text": None,
                "caption": "photo caption",
                "photo": [
                    {
                        "file_id": "photo_file",
                        "file_unique_id": "photo_unique",
                        "width": 1,
                        "height": 1,
                    }
                ],
            }
            inbound = replace(inbound, raw_payload=payload)
            ingress = SqlAlchemyDurableIngressRepository(database.session_factory, 1)
            accepted = await ingress.accept(inbound)
            assert (await ingress.accept(inbound)).duplicate
            async with database.session_factory() as session:
                outbox = await session.scalar(
                    select(IngressOutboxEventModel.id).where(
                        IngressOutboxEventModel.incoming_update_id
                        == accepted.incoming_update_id
                    )
                )
            event = await ingress.event_for(outbox)
            normalized = normalize_telegram_update(
                parse_telegram_update(payload),
                platform_connection_id=connection,
                assistant_platform_user_id="900",
                assistant_display_name="Lumi",
                assistant_username=None,
            )
            processor = SqlAlchemyConversationProcessor(database.session_factory)
            first = await processor.process(event, normalized)
            second = await processor.process(event, normalized)
            assert second.duplicate
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(MessageMediaModel)
                        .where(MessageMediaModel.message_id == first.message_id)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ResponsePlanningJobModel)
                        .where(ResponsePlanningJobModel.message_id == first.message_id)
                    )
                    == 1
                )
        finally:
            await database.stop()

    asyncio.run(scenario())
