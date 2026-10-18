import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.application.governance_export import GovernanceExportBuilder
from app.application.scheduling import build_definition
from app.core.config import Settings
from app.domain.conversation import EligibilityReason, ProcessingOutcome
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionStatus,
)
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.scheduling import (
    OccurrenceStatus,
    RecurrenceKind,
    ScheduleCommandOutcome,
    ScheduleDefinition,
    ScheduleKind,
    ScheduleReason,
    ScheduleStatus,
)
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ParticipantSchedulePreferenceModel,
    PlatformConnectionModel,
    ProactiveScheduleCommandReceiptModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.outbound import SqlAlchemyOutboundRepository
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.scheduling import SqlAlchemySchedulingRepository
from app.runtime.telegram_command_worker import consume_once as consume_command_once


@dataclass(frozen=True)
class Seed:
    assistant_id: UUID
    connection_id: UUID
    conversation_id: UUID
    participant_id: UUID
    command_ids: tuple[UUID, ...]


async def _seed(database: Database, command_count: int = 1) -> Seed:
    async with database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE assistants CASCADE"))
    async with database.session_factory() as session:
        async with session.begin():
            assistant = AssistantModel(
                tenant_id=LEGACY_TENANT_ID,
                slug="scheduling-january",
                name="January",
                status=AssistantStatus.ACTIVE,
            )
            session.add(assistant)
            await session.flush()
            connection = PlatformConnectionModel(
                tenant_id=LEGACY_TENANT_ID,
                assistant_id=assistant.id,
                platform=Platform.TELEGRAM,
                external_bot_id="scheduler-bot",
                status=PlatformConnectionStatus.ACTIVE,
            )
            session.add(connection)
            await session.flush()
            conversation = ConversationModel(
                platform_connection_id=connection.id,
                platform_conversation_id="private-1",
                conversation_type=ConversationType.PRIVATE,
            )
            session.add(conversation)
            await session.flush()
            participant = ParticipantModel(
                conversation_id=conversation.id,
                platform_user_id="user-1",
                display_name="User",
                last_seen_at=datetime.now(UTC) - timedelta(days=2),
            )
            session.add(participant)
            await session.flush()
            commands: list[UUID] = []
            for index in range(command_count):
                message = MessageModel(
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    platform_message_id=f"message-{index}",
                    direction=MessageDirection.INCOMING,
                    message_type=MessageType.TEXT,
                    text="fixture command",
                )
                incoming = IncomingPlatformUpdateModel(
                    platform_connection_id=connection.id,
                    platform=Platform.TELEGRAM,
                    platform_update_id=f"update-{index}",
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
                    conversation_id=conversation.id,
                    message_id=message.id,
                    eligible=False,
                    eligibility_reason=EligibilityReason.COMMAND_HANDOFF,
                )
                session.add(record)
                await session.flush()
                command = TelegramCommandJobModel(
                    conversation_processing_record_id=record.id,
                    conversation_id=conversation.id,
                    message_id=message.id,
                    participant_id=participant.id,
                    command_name="remind",
                    arguments="daily 09:00 fixture",
                )
                session.add(command)
                await session.flush()
                commands.append(command.id)
            return Seed(
                assistant.id,
                connection.id,
                conversation.id,
                participant.id,
                tuple(commands),
            )


async def _add_participant_command(
    database: Database, conversation_id: UUID, suffix: str
) -> tuple[UUID, UUID]:
    async with database.session_factory() as session:
        async with session.begin():
            participant = ParticipantModel(
                conversation_id=conversation_id,
                platform_user_id=f"user-{suffix}",
                display_name="Other",
                last_seen_at=datetime.now(UTC) - timedelta(days=2),
            )
            session.add(participant)
            await session.flush()
            conversation = await session.get(ConversationModel, conversation_id)
            assert conversation is not None
            message = MessageModel(
                conversation_id=conversation_id,
                participant_id=participant.id,
                platform_message_id=f"message-{suffix}",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="fixture command",
            )
            incoming = IncomingPlatformUpdateModel(
                platform_connection_id=conversation.platform_connection_id,
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
            command = TelegramCommandJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation_id,
                message_id=message.id,
                participant_id=participant.id,
                command_name="cancel_reminder",
                arguments="fixture",
            )
            session.add(command)
            await session.flush()
            return participant.id, command.id


def _definition(
    now: datetime, *, kind: ScheduleKind = ScheduleKind.REMINDER
) -> ScheduleDefinition:
    return build_definition(
        kind=kind,
        recurrence=RecurrenceKind.DAILY,
        timezone_name="UTC",
        local_date=None,
        local_time_minute=(now.hour * 60 + now.minute + 2) % 1440,
        weekday_mask_value=127,
        reminder_text="fixture reminder" if kind == ScheduleKind.REMINDER else None,
        now=now,
        minimum_lead_seconds=60,
        horizon_days=365,
        text_limit=100,
    )


def _due_once(
    intended: datetime, *, text_value: str = "fixture reminder"
) -> ScheduleDefinition:
    return ScheduleDefinition(
        kind=ScheduleKind.REMINDER,
        recurrence=RecurrenceKind.ONCE,
        timezone_name="UTC",
        local_time_minute=intended.hour * 60 + intended.minute,
        weekday_mask=0,
        starts_on=intended.date(),
        first_run_at=intended,
        ends_at=datetime.now(UTC) + timedelta(days=365),
        reminder_text=text_value,
    )


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_schema_head_and_constraints_are_current() -> None:
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
                names = set(
                    await connection.scalars(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conname IN "
                            "('ck_response_plans_response_plan_exactly_one_source',"
                            "'uq_proactive_schedules_source_command_job_id',"
                            "'uq_proactive_schedule_occurrences_schedule_id')"
                        )
                    )
                )
                assert "ck_response_plans_response_plan_exactly_one_source" in names
                tables = set(
                    await connection.scalars(
                        text(
                            "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                            "AND tablename LIKE 'proactive_schedule%'"
                        )
                    )
                )
                assert tables == {
                    "proactive_schedules",
                    "proactive_schedule_command_receipts",
                    "proactive_schedule_occurrences",
                }
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_private_command_worker_creates_schedule_without_provider_io() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 2)
            later = datetime.now(UTC) + timedelta(minutes=5)
            clock = f"{later.hour:02d}:{later.minute:02d}"
            async with database.session_factory() as session:
                async with session.begin():
                    first = await session.get(
                        TelegramCommandJobModel, seed.command_ids[0]
                    )
                    second = await session.get(
                        TelegramCommandJobModel, seed.command_ids[1]
                    )
                    assert first is not None and second is not None
                    first.command_name = "timezone"
                    first.arguments = "UTC"
                    second.arguments = f"daily {clock} fixture reminder"
                    second.available_at = datetime.now(UTC) + timedelta(hours=1)
            settings = Settings(
                _env_file=None,
                environment="test",
                command_worker_enabled=True,
                proactive_scheduling_enabled=True,
            )
            assert await consume_command_once(settings, database, owner="commands") == 1
            async with database.session_factory() as session:
                async with session.begin():
                    second = await session.get(
                        TelegramCommandJobModel, seed.command_ids[1]
                    )
                    assert second is not None
                    second.available_at = datetime.now(UTC)
            assert await consume_command_once(settings, database, owner="commands") == 1
            async with database.session_factory() as session:
                assert (
                    await session.scalar(select(func.count(ProactiveScheduleModel.id)))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(ProactiveScheduleCommandReceiptModel.id))
                    )
                    == 2
                )
                plans = list(await session.scalars(select(ResponsePlanModel)))
                assert len(plans) == 2
                assert all(plan.planning_job_id is None for plan in plans)
                assert all(plan.schedule_occurrence_id is None for plan in plans)
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_group_schedule_command_fails_closed_without_mutation() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database)
            async with database.session_factory() as session:
                async with session.begin():
                    conversation = await session.get(
                        ConversationModel, seed.conversation_id
                    )
                    command = await session.get(
                        TelegramCommandJobModel, seed.command_ids[0]
                    )
                    assert conversation is not None and command is not None
                    conversation.conversation_type = ConversationType.GROUP
                    command.command_name = "timezone"
                    command.arguments = "UTC"
            settings = Settings(
                _env_file=None,
                environment="test",
                command_worker_enabled=True,
                proactive_scheduling_enabled=True,
            )
            assert await consume_command_once(settings, database, owner="commands") == 1
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ProactiveScheduleCommandReceiptModel.id))
                    )
                    == 0
                )
                assert (
                    await session.scalar(select(func.count(ProactiveScheduleModel.id)))
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_checkin_quiet_hours_defer_then_recent_activity_suppresses() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 4)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            minute = now.hour * 60 + now.minute
            await repository.set_timezone(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                timezone_name="UTC",
                now=now,
            )
            await repository.set_quiet_hours(
                command_job_id=seed.command_ids[1],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                enabled=True,
                start_minute=(minute - 1) % 1440,
                end_minute=(minute + 60) % 1440,
            )
            definition = _definition(
                now - timedelta(days=2, hours=2), kind=ScheduleKind.CHECK_IN
            )
            await repository.enable_checkin(
                command_job_id=seed.command_ids[2],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=definition,
            )
            assert (await repository.materialize_due(now, 10)).count == 1
            claim = (await repository.claim("scheduler-a", now, 10, 60))[0]
            assert (
                await repository.enqueue_claim(claim, "scheduler-a", now) == "deferred"
            )
            await repository.set_quiet_hours(
                command_job_id=seed.command_ids[3],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                enabled=False,
            )
            async with database.session_factory() as session:
                async with session.begin():
                    participant = await session.get(
                        ParticipantModel, seed.participant_id
                    )
                    occurrence = await session.scalar(
                        select(ProactiveScheduleOccurrenceModel)
                    )
                    assert participant is not None and occurrence is not None
                    participant.last_seen_at = now
                    occurrence.available_at = now
            second = (await repository.claim("scheduler-b", now, 10, 60))[0]
            assert (
                await repository.enqueue_claim(second, "scheduler-b", now)
                == "recent_activity"
            )
            async with database.session_factory() as session:
                occurrence = await session.scalar(
                    select(ProactiveScheduleOccurrenceModel)
                )
                assert occurrence is not None
                assert occurrence.status == OccurrenceStatus.SKIPPED
                assert (
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_protected_subject_suppresses_checkin_before_outbox() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            await repository.enable_checkin(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_definition(
                    now - timedelta(days=2), kind=ScheduleKind.CHECK_IN
                ),
            )
            assert (await repository.materialize_due(now, 10)).count == 1
            claim = (await repository.claim("protected", now, 10, 60))[0]
            async with database.session_factory() as session:
                async with session.begin():
                    participant = await session.get(
                        ParticipantModel, seed.participant_id
                    )
                    assert participant is not None
                    participant.protected_at = now
            assert await repository.enqueue_claim(claim, "protected", now) == "paused"
            async with database.session_factory() as session:
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel, claim.occurrence_id
                )
                assert occurrence is not None
                assert occurrence.status == OccurrenceStatus.SKIPPED
                assert occurrence.reason_code == ScheduleReason.PAUSED
                assert (
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_concurrent_command_replay_and_active_limit_are_database_serialized() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 2)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC)
            common = dict(
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_definition(now),
                active_limit=1,
            )
            raced = await asyncio.gather(
                repository.create_reminder(
                    command_job_id=seed.command_ids[0], **common
                ),
                repository.create_reminder(
                    command_job_id=seed.command_ids[1], **common
                ),
            )
            assert {item.outcome for item in raced} == {
                ScheduleCommandOutcome.CREATED,
                ScheduleCommandOutcome.LIMIT_REACHED,
            }
            created = next(
                item for item in raced if item.outcome == ScheduleCommandOutcome.CREATED
            )
            created_command = seed.command_ids[raced.index(created)]
            replay = await repository.create_reminder(
                command_job_id=created_command, **common
            )
            assert replay.public_id == created.public_id
            async with database.session_factory() as session:
                assert (
                    await session.scalar(select(func.count(ProactiveScheduleModel.id)))
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(ProactiveScheduleCommandReceiptModel.id))
                    )
                    == 2
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_list_and_cancel_are_creator_scoped() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database)
            other_participant_id, other_command_id = await _add_participant_command(
                database, seed.conversation_id, "other"
            )
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            created = await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_definition(datetime.now(UTC)),
                active_limit=10,
            )
            assert created.public_id is not None
            assert (
                await repository.list_active(seed.conversation_id, other_participant_id)
                == []
            )
            denied = await repository.cancel_reminder(
                command_job_id=other_command_id,
                conversation_id=seed.conversation_id,
                participant_id=other_participant_id,
                public_id=created.public_id,
            )
            assert denied.outcome == ScheduleCommandOutcome.NOT_FOUND
            owner_rows = await repository.list_active(
                seed.conversation_id, seed.participant_id
            )
            assert [row.public_id for row in owner_rows] == [created.public_id]
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_concurrent_materialize_and_claim_create_one_outbox_per_occurrence() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            # Repeated same-occurrence materialization/claim races: exactly one
            # occurrence and one claim winner per schedule, every iteration.
            repetitions = 18
            seed = await _seed(database, repetitions)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC)
            for index, command_id in enumerate(seed.command_ids):
                intended = now - timedelta(minutes=10 + index)
                await repository.create_reminder(
                    command_job_id=command_id,
                    conversation_id=seed.conversation_id,
                    participant_id=seed.participant_id,
                    definition=_due_once(intended, text_value=f"fixture {index}"),
                    active_limit=10,
                )
                materialized = await asyncio.gather(
                    repository.materialize_due(now, 1),
                    repository.materialize_due(now, 1),
                )
                assert sum(result.count for result in materialized) == 1
                claims = await asyncio.gather(
                    repository.claim(f"worker-a-{index}", now, 1, 60),
                    repository.claim(f"worker-b-{index}", now, 1, 60),
                )
                winners = [claim for batch in claims for claim in batch]
                assert len(winners) == 1
                winner = winners[0]
                owner = f"worker-a-{index}" if claims[0] else f"worker-b-{index}"
                assert await repository.enqueue_claim(winner, owner, now) == "enqueued"
                async with database.session_factory() as session:
                    assert (
                        await session.scalar(
                            select(func.count(ProactiveScheduleOccurrenceModel.id))
                        )
                        == index + 1
                    )
                    assert (
                        await session.scalar(select(func.count(OutboundActionModel.id)))
                        == index + 1
                    )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_latest_only_materialization_and_expired_lease_fencing() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 2)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            created_at = datetime.now(UTC) - timedelta(days=10, hours=2)
            definition = _definition(created_at)
            created = await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=definition,
                active_limit=10,
            )
            assert created.schedule_id is not None
            due = datetime.now(UTC)
            assert (await repository.materialize_due(due, 10)).count == 1
            assert (await repository.materialize_due(due, 10)).count == 0
            first = await repository.claim("worker-a", due, 10, 60)
            assert len(first) == 1
            assert (
                await repository.claim("worker-b", due + timedelta(seconds=30), 10, 60)
                == []
            )
            second = await repository.claim(
                "worker-b", due + timedelta(seconds=61), 10, 60
            )
            assert len(second) == 1
            assert (
                await repository.enqueue_claim(
                    second[0], "worker-b", due + timedelta(seconds=61)
                )
                == "enqueued"
            )
            assert (
                await repository.enqueue_claim(
                    first[0], "worker-a", due + timedelta(seconds=61)
                )
                == "stale_lease"
            )
            async with database.session_factory() as session:
                fenced = await session.get(
                    ProactiveScheduleOccurrenceModel, first[0].occurrence_id
                )
                assert fenced is not None
                assert fenced.status == OccurrenceStatus.ENQUEUED
                assert fenced.scheduled_for is not None
                assert fenced.local_date == fenced.scheduled_for.date()
                assert fenced.scheduled_for <= due
                assert (
                    await session.scalar(select(func.count(ResponsePlanModel.id))) == 1
                )
                assert (
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    == 1
                )
            # Deliver a separately enqueued occurrence at real time so the
            # outbound action is actually claimable (the fence proof above used
            # a future enqueue instant, which keeps its action not yet available).
            envelope_now = datetime.now(UTC)
            fresh = await repository.create_reminder(
                command_job_id=seed.command_ids[1],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(
                    envelope_now - timedelta(minutes=1),
                    text_value="deliver me",
                ),
                active_limit=10,
            )
            assert fresh.schedule_id is not None
            assert (await repository.materialize_due(envelope_now, 10)).count == 1
            delivery_claim = (await repository.claim("sender", envelope_now, 10, 60))[0]
            assert (
                await repository.enqueue_claim(delivery_claim, "sender", envelope_now)
                == "enqueued"
            )
            outbound = SqlAlchemyOutboundRepository(database.session_factory)
            actions = await outbound.claim("sender", 10, 60)
            assert len(actions) == 1
            assert await outbound.mark_external_started(actions[0].id, "sender")
            assert await outbound.finalize(
                actions[0].id,
                "sender",
                OutboundActionStatus.DELIVERED,
                DeliveryAttemptStatus.CONFIRMED,
                DeliveryCertainty.CONFIRMED,
                delivered_platform_message_id="scheduled-delivery-1",
            )
            async with database.session_factory() as session:
                delivered = await session.get(
                    ProactiveScheduleOccurrenceModel, delivery_claim.occurrence_id
                )
                assert delivered is not None
                assert delivered.status == OccurrenceStatus.DELIVERED
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_old_one_time_reminder_materializes_only_its_original_instant() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            created_at = datetime.now(UTC) - timedelta(days=10)
            intended = created_at + timedelta(minutes=2)
            definition = ScheduleDefinition(
                kind=ScheduleKind.REMINDER,
                recurrence=RecurrenceKind.ONCE,
                timezone_name="UTC",
                local_time_minute=intended.hour * 60 + intended.minute,
                weekday_mask=0,
                starts_on=intended.date(),
                first_run_at=intended,
                ends_at=created_at + timedelta(days=365),
                reminder_text="old reminder",
            )
            await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=definition,
                active_limit=10,
            )
            now = datetime.now(UTC)
            assert (await repository.materialize_due(now, 10)).count == 1
            async with database.session_factory() as session:
                occurrence = await session.scalar(
                    select(ProactiveScheduleOccurrenceModel)
                )
                assert occurrence is not None
                assert occurrence.scheduled_for == intended
                assert occurrence.local_date == intended.date()
                assert occurrence.status == OccurrenceStatus.SKIPPED
                assert occurrence.reason_code == ScheduleReason.STALE
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_privacy_fences_enqueue_and_preserves_redaction_after_possible_io() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 3)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC)

            await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(now - timedelta(minutes=5)),
                active_limit=10,
            )
            assert (await repository.materialize_due(now, 1)).count == 1
            fenced_claim = (await repository.claim("privacy-a", now, 1, 60))[0]
            async with database.session_factory() as session:
                async with session.begin():
                    conversation = await session.get(
                        ConversationModel, seed.conversation_id
                    )
                    assert conversation is not None
                    conversation.memory_privacy_revision += 1
            assert (
                await repository.enqueue_claim(fenced_claim, "privacy-a", now)
                == "privacy"
            )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    == 0
                )

            await repository.create_reminder(
                command_job_id=seed.command_ids[1],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(now - timedelta(minutes=4), text_value="erase me"),
                active_limit=10,
            )
            assert (await repository.materialize_due(now, 1)).count == 1
            claim = (await repository.claim("privacy-b", now, 1, 60))[0]
            assert await repository.enqueue_claim(claim, "privacy-b", now) == "enqueued"
            outbound = SqlAlchemyOutboundRepository(database.session_factory)
            action = (await outbound.claim("sender", 1, 60))[0]
            assert await outbound.mark_external_started(action.id, "sender")
            await SqlAlchemyPrivacyRepository(database.session_factory).erase_subject(
                assistant_id=seed.assistant_id,
                platform_connection_id=seed.connection_id,
                platform_user_id="user-1",
                command_job_id=seed.command_ids[2],
                now=now,
            )
            assert await outbound.finalize(
                action.id,
                "sender",
                OutboundActionStatus.DELIVERED,
                DeliveryAttemptStatus.CONFIRMED,
                DeliveryCertainty.CONFIRMED,
                delivered_platform_message_id="possible-after-erasure",
            )
            async with database.session_factory() as session:
                action_row = await session.get(OutboundActionModel, action.id)
                occurrence = await session.scalar(
                    select(ProactiveScheduleOccurrenceModel).where(
                        ProactiveScheduleOccurrenceModel.id == claim.occurrence_id
                    )
                )
                plan = await session.scalar(
                    select(ResponsePlanModel).where(
                        ResponsePlanModel.schedule_occurrence_id == claim.occurrence_id
                    )
                )
                delivered_message = await session.scalar(
                    select(MessageModel).where(
                        MessageModel.outbound_action_id == action.id
                    )
                )
                assert action_row is not None and occurrence is not None
                assert plan is not None and delivered_message is not None
                assert action_row.status == OutboundActionStatus.DELIVERED
                assert action_row.text is None and plan.text is None
                assert delivered_message.text is None
                assert delivered_message.content_redacted_at is not None
                assert occurrence.status == OccurrenceStatus.HISTORY_REDACTED
                assert occurrence.scheduled_for is None
                assert occurrence.local_date is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_scheduled_delivery_rejects_cross_conversation_action() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC)
            await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(now - timedelta(minutes=5)),
                active_limit=10,
            )
            assert (await repository.materialize_due(now, 1)).count == 1
            claim = (await repository.claim("scope", now, 1, 60))[0]
            assert await repository.enqueue_claim(claim, "scope", now) == "enqueued"
            async with database.session_factory() as session:
                with pytest.raises(DBAPIError, match="sequence identity is immutable"):
                    async with session.begin():
                        foreign = ConversationModel(
                            platform_connection_id=seed.connection_id,
                            platform_conversation_id="private-foreign",
                            conversation_type=ConversationType.PRIVATE,
                        )
                        session.add(foreign)
                        await session.flush()
                        action = await session.scalar(select(OutboundActionModel))
                        assert action is not None
                        action.conversation_id = foreign.id
            async with database.session_factory() as session:
                action_row = await session.scalar(select(OutboundActionModel))
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel, claim.occurrence_id
                )
                assert action_row is not None and occurrence is not None
                assert action_row.conversation_id == seed.conversation_id
                assert action_row.status == OutboundActionStatus.PENDING
                assert occurrence.status == OccurrenceStatus.ENQUEUED
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_outbound_rechecks_quiet_hours_and_classifies_defer() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 3)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC).replace(second=0, microsecond=0)
            await repository.set_timezone(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                timezone_name="UTC",
                now=now,
            )
            await repository.set_quiet_hours(
                command_job_id=seed.command_ids[1],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                enabled=False,
            )
            intended = now - timedelta(seconds=30)
            await repository.enable_checkin(
                command_job_id=seed.command_ids[2],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=ScheduleDefinition(
                    kind=ScheduleKind.CHECK_IN,
                    recurrence=RecurrenceKind.ONCE,
                    timezone_name="UTC",
                    local_time_minute=intended.hour * 60 + intended.minute,
                    weekday_mask=0,
                    starts_on=intended.date(),
                    first_run_at=intended,
                    ends_at=datetime.now(UTC) + timedelta(days=365),
                    reminder_text=None,
                ),
            )
            assert (await repository.materialize_due(now, 1)).count == 1
            claim = (await repository.claim("quiet", now, 1, 60))[0]
            assert await repository.enqueue_claim(claim, "quiet", now) == "enqueued"
            minute = now.hour * 60 + now.minute
            async with database.session_factory() as session:
                async with session.begin():
                    preferences = await session.scalar(
                        select(ParticipantSchedulePreferenceModel)
                    )
                    assert preferences is not None
                    preferences.quiet_hours_enabled = True
                    preferences.quiet_start_minute = (minute - 5) % 1440
                    preferences.quiet_end_minute = (minute + 60) % 1440
            outbound = SqlAlchemyOutboundRepository(database.session_factory)
            action = (await outbound.claim("sender", 1, 60))[0]
            assert not await outbound.mark_external_started(action.id, "sender")
            assert await outbound.scheduled_preflight_outcome(action.id) == "deferred"
            async with database.session_factory() as session:
                action_row = await session.get(OutboundActionModel, action.id)
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel, claim.occurrence_id
                )
                assert action_row is not None and occurrence is not None
                assert action_row.status == OutboundActionStatus.PENDING
                assert action_row.available_at is not None
                assert action_row.last_error_category == "scheduled_quiet_hours"
                assert occurrence.status == OccurrenceStatus.ENQUEUED
                assert occurrence.reason_code == ScheduleReason.QUIET_HOURS
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_cancellation_stops_pre_io_work_but_preserves_possible_delivery() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 5)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            outbound = SqlAlchemyOutboundRepository(database.session_factory)
            now = datetime.now(UTC)

            first = await repository.create_reminder(
                command_job_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(now - timedelta(minutes=5)),
                active_limit=10,
            )
            assert first.public_id is not None
            assert (await repository.materialize_due(now, 1)).count == 1
            claim = (await repository.claim("cancel-a", now, 1, 60))[0]
            assert await repository.enqueue_claim(claim, "cancel-a", now) == "enqueued"
            action = (await outbound.claim("sender-a", 1, 60))[0]
            cancelled = await repository.cancel_reminder(
                command_job_id=seed.command_ids[1],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                public_id=first.public_id,
                now=now,
            )
            assert cancelled.outcome == ScheduleCommandOutcome.CANCELLED
            assert not await outbound.mark_external_started(action.id, "sender-a")
            async with database.session_factory() as session:
                action_row = await session.get(OutboundActionModel, action.id)
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel, claim.occurrence_id
                )
                assert action_row is not None and occurrence is not None
                assert action_row.status == OutboundActionStatus.SKIPPED
                assert occurrence.status == OccurrenceStatus.SKIPPED

            second = await repository.create_reminder(
                command_job_id=seed.command_ids[2],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                definition=_due_once(now - timedelta(minutes=4)),
                active_limit=10,
            )
            assert second.public_id is not None
            assert (await repository.materialize_due(now, 1)).count == 1
            claim = (await repository.claim("cancel-b", now, 1, 60))[0]
            assert await repository.enqueue_claim(claim, "cancel-b", now) == "enqueued"
            action = (await outbound.claim("sender-b", 1, 60))[0]
            assert await outbound.mark_external_started(action.id, "sender-b")
            cancelled = await repository.cancel_reminder(
                command_job_id=seed.command_ids[3],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                public_id=second.public_id,
                now=now,
            )
            assert cancelled.outcome == ScheduleCommandOutcome.CANCELLED
            assert await outbound.finalize(
                action.id,
                "sender-b",
                OutboundActionStatus.DELIVERED,
                DeliveryAttemptStatus.CONFIRMED,
                DeliveryCertainty.CONFIRMED,
                delivered_platform_message_id="possible-cancel-race",
            )
            async with database.session_factory() as session:
                occurrence = await session.get(
                    ProactiveScheduleOccurrenceModel, claim.occurrence_id
                )
                assert occurrence is not None
                assert occurrence.status == OccurrenceStatus.DELIVERED
            # The schedule was already cancelled by the first cancel; a
            # subsequent cancel resolves to NOT_FOUND (no ACTIVE/COMPLETED
            # schedule remains) rather than a broad outcome set.
            too_late = await repository.cancel_reminder(
                command_job_id=seed.command_ids[4],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                public_id=second.public_id,
                now=now,
            )
            assert too_late.outcome == ScheduleCommandOutcome.NOT_FOUND
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.scheduling_integration
def test_subject_export_erasure_and_bounded_schedule_retention() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            seed = await _seed(database, 2)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            now = datetime.now(UTC)
            for command_id in seed.command_ids:
                await repository.create_reminder(
                    command_job_id=command_id,
                    conversation_id=seed.conversation_id,
                    participant_id=seed.participant_id,
                    definition=_definition(now),
                    active_limit=10,
                )
            package = await GovernanceExportBuilder(
                database.session_factory
            ).build_subject_export(
                request_id=seed.command_ids[0],
                conversation_id=seed.conversation_id,
                participant_id=seed.participant_id,
                now=now,
            )
            data = package["data"]
            assert isinstance(data, dict)
            scheduling = data["scheduling"]
            assert isinstance(scheduling, dict)
            assert len(scheduling["schedules"]) == 2
            result = await SqlAlchemyPrivacyRepository(
                database.session_factory
            ).erase_subject(
                assistant_id=seed.assistant_id,
                platform_connection_id=seed.connection_id,
                platform_user_id="user-1",
                command_job_id=seed.command_ids[0],
                now=now,
            )
            assert result.schedules == 2
            async with database.session_factory() as session:
                rows = list(await session.scalars(select(ProactiveScheduleModel)))
                assert all(row.status == ScheduleStatus.ERASED for row in rows)
                assert all(row.reminder_text is None for row in rows)
                assert all(row.timezone_name is None for row in rows)
                assert all(row.local_time_minute is None for row in rows)

            # Re-seed terminal content to prove one-row batches drain, preserve
            # active state, and become idempotent.
            seed = await _seed(database, 5)
            repository = SqlAlchemySchedulingRepository(database.session_factory)
            results = []
            for command_id in seed.command_ids[:3]:
                results.append(
                    await repository.create_reminder(
                        command_job_id=command_id,
                        conversation_id=seed.conversation_id,
                        participant_id=seed.participant_id,
                        definition=_definition(now),
                        active_limit=10,
                    )
                )
            for index, result in enumerate(results[:2]):
                assert result.public_id is not None
                await repository.cancel_reminder(
                    command_job_id=seed.command_ids[index + 3],
                    conversation_id=seed.conversation_id,
                    participant_id=seed.participant_id,
                    public_id=result.public_id,
                    now=now - timedelta(days=31),
                )
            async with database.session_factory() as session:
                async with session.begin():
                    for index, result in enumerate(results[:2]):
                        assert result.schedule_id is not None
                        schedule = await session.get(
                            ProactiveScheduleModel, result.schedule_id
                        )
                        assert schedule is not None
                        session.add(
                            ProactiveScheduleOccurrenceModel(
                                schedule_id=schedule.id,
                                conversation_id=seed.conversation_id,
                                participant_id=seed.participant_id,
                                scheduled_for=now - timedelta(days=31 + index),
                                local_date=(now - timedelta(days=31 + index)).date(),
                                status=OccurrenceStatus.SKIPPED,
                                reason_code=ScheduleReason.STALE,
                                available_at=now - timedelta(days=31 + index),
                                schedule_version=schedule.version,
                                privacy_revision=0,
                                completed_at=now - timedelta(days=31 + index),
                            )
                        )
                    await session.execute(
                        update(ProactiveScheduleModel)
                        .where(
                            ProactiveScheduleModel.status == ScheduleStatus.CANCELLED
                        )
                        .values(updated_at=now - timedelta(days=31))
                    )
            retention = SqlAlchemyRetentionRepository(database.session_factory)
            counts1 = await retention.redact_once(
                now=now,
                retention_days=30,
                schedule_history_retention_days=30,
                batch_size=1,
            )
            counts2 = await retention.redact_once(
                now=now,
                retention_days=30,
                schedule_history_retention_days=30,
                batch_size=1,
            )
            counts3 = await retention.redact_once(
                now=now,
                retention_days=30,
                schedule_history_retention_days=30,
                batch_size=1,
            )
            assert (counts1.schedules, counts2.schedules, counts3.schedules) == (
                1,
                1,
                0,
            )
            assert (
                counts1.schedule_occurrences,
                counts2.schedule_occurrences,
                counts3.schedule_occurrences,
            ) == (1, 1, 0)
            async with database.session_factory() as session:
                active = await session.scalar(
                    select(ProactiveScheduleModel).where(
                        ProactiveScheduleModel.status == ScheduleStatus.ACTIVE
                    )
                )
                assert active is not None and active.reminder_text is not None
                redacted = list(
                    await session.scalars(
                        select(ProactiveScheduleModel).where(
                            ProactiveScheduleModel.status == ScheduleStatus.CANCELLED
                        )
                    )
                )
                assert all(row.reminder_text is None for row in redacted)
                assert all(row.timezone_name is None for row in redacted)
                assert all(row.local_time_minute is None for row in redacted)
                occurrence_rows = list(
                    await session.scalars(select(ProactiveScheduleOccurrenceModel))
                )
                assert all(
                    row.status == OccurrenceStatus.HISTORY_REDACTED
                    for row in occurrence_rows
                )
                assert all(row.scheduled_for is None for row in occurrence_rows)
                assert all(row.local_date is None for row in occurrence_rows)
        finally:
            await database.stop()

    asyncio.run(scenario())
