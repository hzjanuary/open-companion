"""Live PostgreSQL proofs for SPEC-039 explicit conversation feedback."""

import asyncio
import os
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.governance_export import GovernanceExportBuilder
from app.application.response_plan import ResponsePlanCandidate
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.feedback import FeedbackOutcome, FeedbackValue
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    AssistantStatus,
    CommandJobStatus,
    ConversationStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
)
from app.domain.planning import PlanningJobStatus, PlanReasonCode
from app.domain.voice import VoiceArtifactStatus, VoiceFormat, VoiceGenerationStatus
from app.infrastructure.database.context import SqlAlchemyConversationContextReader
from app.infrastructure.database.database import Database
from app.infrastructure.database.feedback import SqlAlchemyFeedbackRepository
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationFeedbackEventModel,
    ConversationFeedbackModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryJobModel,
    ConversationSummaryModel,
    ExplicitMemorySemanticIndexJobModel,
    GeneratedVoiceArtifactModel,
    IncomingPlatformUpdateModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    KnowledgeDocumentRevisionModel,
    KnowledgeIndexJobModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    ModelGenerationAttemptModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ProviderUsageAttemptModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
    TelegramVoiceGenerationJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.privacy import SqlAlchemyPrivacyRepository
from app.infrastructure.database.retention import SqlAlchemyRetentionRepository
from app.infrastructure.database.summaries import SqlAlchemySummaryRepository
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.telegram_command_worker import consume_once as consume_command_once

pytestmark = [pytest.mark.integration, pytest.mark.conversation_feedback_integration]


async def _authority(
    session: AsyncSession, suffix: str
) -> tuple[ConversationModel, ParticipantModel]:
    tenant = ControlTenantModel(slug=f"feedback-{suffix}", name="Feedback")
    session.add(tenant)
    await session.flush()
    assistant = AssistantModel(
        tenant_id=tenant.id,
        slug=f"assistant-{suffix}",
        name="January",
        status=AssistantStatus.ACTIVE,
    )
    session.add(assistant)
    await session.flush()
    connection = PlatformConnectionModel(
        tenant_id=tenant.id,
        assistant_id=assistant.id,
        platform=Platform.TELEGRAM,
        external_bot_id=f"bot-{suffix}",
        status=PlatformConnectionStatus.ACTIVE,
    )
    session.add(connection)
    await session.flush()
    conversation = ConversationModel(
        platform_connection_id=connection.id,
        platform_conversation_id=f"chat-{suffix}",
        conversation_type=ConversationType.GROUP,
        status=ConversationStatus.ACTIVE,
        response_mode=ResponseMode.MENTION_ONLY,
    )
    session.add(conversation)
    await session.flush()
    await ensure_conversation_configuration(session, assistant, conversation)
    participant = ParticipantModel(
        conversation_id=conversation.id,
        platform_user_id=f"user-{suffix}",
        display_name="Feedback user",
    )
    session.add(participant)
    await session.flush()
    return conversation, participant


async def _sibling_authority(
    session: AsyncSession,
    source_conversation: ConversationModel,
    suffix: str,
) -> tuple[ConversationModel, ParticipantModel]:
    """Create a real sibling Assistant scope under the source tenant."""

    source_connection = await session.get(
        PlatformConnectionModel, source_conversation.platform_connection_id
    )
    assert source_connection is not None
    assistant = AssistantModel(
        tenant_id=source_connection.tenant_id,
        slug=f"sibling-assistant-{suffix}",
        name="Sibling January",
        status=AssistantStatus.ACTIVE,
    )
    session.add(assistant)
    await session.flush()
    connection = PlatformConnectionModel(
        tenant_id=source_connection.tenant_id,
        assistant_id=assistant.id,
        platform=Platform.TELEGRAM,
        external_bot_id=f"sibling-bot-{suffix}",
        status=PlatformConnectionStatus.ACTIVE,
    )
    session.add(connection)
    await session.flush()
    conversation = ConversationModel(
        platform_connection_id=connection.id,
        platform_conversation_id=f"sibling-chat-{suffix}",
        conversation_type=ConversationType.GROUP,
        status=ConversationStatus.ACTIVE,
        response_mode=ResponseMode.MENTION_ONLY,
    )
    session.add(conversation)
    await session.flush()
    await ensure_conversation_configuration(session, assistant, conversation)
    participant = ParticipantModel(
        conversation_id=conversation.id,
        platform_user_id=f"sibling-user-{suffix}",
        display_name="Sibling feedback user",
    )
    session.add(participant)
    await session.flush()
    return conversation, participant


async def _processing_record(
    session: AsyncSession, conversation: ConversationModel, message: MessageModel
) -> ConversationProcessingRecordModel:
    incoming = IncomingPlatformUpdateModel(
        platform_connection_id=conversation.platform_connection_id,
        platform=Platform.TELEGRAM,
        platform_update_id=f"update-{uuid4()}",
        update_type="message",
        ingress_source=IngressSource.WEBHOOK,
        raw_payload={},
        received_at=datetime.now(UTC),
    )
    session.add(incoming)
    await session.flush()
    record = ConversationProcessingRecordModel(
        incoming_update_id=incoming.id,
        outcome=ProcessingOutcome.MESSAGE_CREATED,
        conversation_id=conversation.id,
        message_id=message.id,
    )
    session.add(record)
    await session.flush()
    return record


async def _response(
    session: AsyncSession,
    conversation: ConversationModel,
    participant: ParticipantModel,
) -> tuple[ResponsePlanModel, list[MessageModel]]:
    source = MessageModel(
        conversation_id=conversation.id,
        participant_id=participant.id,
        platform_message_id=f"question-{uuid4()}",
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text="Synthetic question",
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(source)
    await session.flush()
    record = await _processing_record(session, conversation, source)
    job = ResponsePlanningJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=source.id,
        prompt_version="spec-039-test",
        response_schema_version="response-plan-v1",
        status=PlanningJobStatus.COMPLETED,
        completed_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    plan = ResponsePlanModel(
        planning_job_id=job.id,
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text="One logical answer split into two chunks.",
        reply_to_message_id=source.id,
        mention_participant_ids=[],
        confidence=1,
        prompt_version="spec-039-test",
        schema_version="response-plan-v1",
    )
    session.add(plan)
    await session.flush()
    chunks: list[MessageModel] = []
    for number in (1, 2):
        action = OutboundActionModel(
            response_plan_id=plan.id,
            conversation_id=conversation.id,
            sequence_number=number,
            sequence_count=2,
            idempotency_key=uuid4().hex,
            kind=OutboundActionKind.TEXT,
            status=OutboundActionStatus.DELIVERED,
            text=f"chunk {number}",
            mention_participant_ids=[],
            completed_at=datetime.now(UTC),
        )
        session.add(action)
        await session.flush()
        message = MessageModel(
            conversation_id=conversation.id,
            outbound_action_id=action.id,
            platform_message_id=f"answer-{number}-{uuid4()}",
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.TEXT,
            text=action.text,
            processing_status=MessageProcessingStatus.PROCESSED,
            platform_sent_at=datetime.now(UTC),
        )
        session.add(message)
        await session.flush()
        action.delivered_message_id = message.id
        chunks.append(message)
    return plan, chunks


async def _command(
    session: AsyncSession,
    conversation: ConversationModel,
    participant: ParticipantModel,
    *,
    owner: str,
    value: FeedbackValue,
    reply_id: UUID | None,
    reply_platform_id: str | None = None,
) -> TelegramCommandJobModel:
    message = MessageModel(
        conversation_id=conversation.id,
        participant_id=participant.id,
        platform_message_id=f"feedback-command-{uuid4()}",
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text=f"/feedback {value.value}",
        reply_to_message_id=reply_id,
        reply_to_platform_message_id=reply_platform_id,
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    record = await _processing_record(session, conversation, message)
    command = TelegramCommandJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=message.id,
        participant_id=participant.id,
        command_name="feedback",
        arguments=value.value,
        status=CommandJobStatus.LEASED,
        lease_owner=owner,
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    session.add(command)
    await session.flush()
    return command


async def _control_command(
    session: AsyncSession,
    conversation: ConversationModel,
    participant: ParticipantModel,
    *,
    name: str,
    reply_id: UUID,
) -> TelegramCommandJobModel:
    message = MessageModel(
        conversation_id=conversation.id,
        participant_id=participant.id,
        platform_message_id=f"{name}-command-{uuid4()}",
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text=f"/{name}",
        reply_to_message_id=reply_id,
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    record = await _processing_record(session, conversation, message)
    command = TelegramCommandJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=message.id,
        participant_id=participant.id,
        command_name=name,
        arguments="",
        status=CommandJobStatus.COMPLETED,
        result_code=f"{name}_accepted",
        completed_at=datetime.now(UTC),
    )
    session.add(command)
    await session.flush()
    return command


def _candidate(message_id: UUID, text_value: str) -> ResponsePlanCandidate:
    return ResponsePlanCandidate(
        should_respond=True,
        reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
        text=text_value,
        reply_to_message_id=message_id,
        confidence=1,
        language="en",
    )


async def _apply(
    repository: SqlAlchemyFeedbackRepository,
    command: TelegramCommandJobModel,
    owner: str,
    value: FeedbackValue,
) -> FeedbackOutcome:
    return await repository.apply(
        command.id,
        owner,
        value,
        saved_candidate=_candidate(command.message_id, "Feedback saved."),
        no_change_candidate=_candidate(command.message_id, "Feedback already saved."),
        limit_candidate=_candidate(command.message_id, "Feedback limit reached."),
        unavailable_candidate=_candidate(command.message_id, "Target unavailable."),
    )


async def _start_together(
    *calls: Callable[[], Awaitable[FeedbackOutcome]],
) -> list[FeedbackOutcome]:
    ready = 0
    gate = asyncio.Event()
    guard = asyncio.Lock()

    async def run(call: Callable[[], Awaitable[FeedbackOutcome]]) -> FeedbackOutcome:
        nonlocal ready
        async with guard:
            ready += 1
            if ready == len(calls):
                gate.set()
        await gate.wait()
        return await call()

    async with asyncio.TaskGroup() as group:
        tasks = [group.create_task(run(call)) for call in calls]
    return [task.result() for task in tasks]


def test_feedback_concurrency_fixture_joins_failed_siblings() -> None:
    async def scenario() -> None:
        entered = asyncio.Event()
        parked = asyncio.Event()
        finished = asyncio.Event()
        failure = SQLAlchemyTimeoutError("Synthetic pool-acquisition failure")

        async def waiting() -> FeedbackOutcome:
            entered.set()
            try:
                await parked.wait()
            finally:
                finished.set()
            return FeedbackOutcome.SAVED

        async def failing() -> FeedbackOutcome:
            await entered.wait()
            raise failure

        async with asyncio.timeout(3):
            with pytest.raises((ExceptionGroup, SQLAlchemyTimeoutError)) as caught:
                await _start_together(waiting, failing)
        errors = (
            caught.value.exceptions
            if isinstance(caught.value, ExceptionGroup)
            else (caught.value,)
        )
        assert failure in errors
        assert finished.is_set()

    asyncio.run(scenario())


class _NoExternalCalls:
    """Instrument every worker-facing external boundary and fail on use."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> frozenset[object]:
        return frozenset()

    def __getattr__(self, name: str) -> Callable[..., Awaitable[object]]:
        async def reject(*_args: object, **_kwargs: object) -> object:
            self.calls += 1
            raise AssertionError(f"feedback invoked external boundary {name}")

        return reject


async def _separation_counts(session: AsyncSession) -> tuple[int, ...]:
    models = (
        ResponsePlanningJobModel,
        ModelGenerationAttemptModel,
        ProviderUsageAttemptModel,
        TelegramVoiceGenerationJobModel,
        GeneratedVoiceArtifactModel,
        MessageMediaModel,
        MemoryItemModel,
        MemoryEventModel,
        ExplicitMemorySemanticIndexJobModel,
        KnowledgeDocumentModel,
        KnowledgeDocumentRevisionModel,
        KnowledgeChunkModel,
        KnowledgeIndexJobModel,
        ConversationSummaryModel,
        ConversationSummaryJobModel,
    )
    counts: list[int] = []
    for model in models:
        counts.append(int(await session.scalar(select(func.count(model.id))) or 0))
    return tuple(counts)


async def _cleanup_feedback_authority(database: Database) -> None:
    """Remove synthetic SPEC-039 authority without deleting the baseline tenant."""

    if os.environ.get("JANUARY_SPEC039_PRESERVE_TEST_STATE") == "1":
        return
    async with database.session_factory() as session, session.begin():
        await session.execute(text("TRUNCATE assistants CASCADE"))
        await session.execute(
            text("DELETE FROM control_tenants WHERE slug LIKE 'feedback-%'")
        )


def test_feedback_state_split_target_revisions_participants_and_rejections() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            owner = "feedback-owner"
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
                helpful = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[1].id,
                )
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            assert (
                await _apply(repository, helpful, owner, FeedbackValue.HELPFUL)
                == FeedbackOutcome.SAVED
            )
            async with database.session_factory() as session, session.begin():
                current = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.response_plan_id == plan.id,
                        ConversationFeedbackModel.participant_id == participant.id,
                    )
                )
                assert current is not None
                assert (current.value, current.revision) == (FeedbackValue.HELPFUL, 1)
                repeat = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[0].id,
                )
            assert (
                await _apply(repository, repeat, owner, FeedbackValue.HELPFUL)
                == FeedbackOutcome.NO_CHANGE
            )
            async with database.session_factory() as session, session.begin():
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.feedback_id == current.id
                        )
                    )
                    == 1
                )
                change = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=chunks[0].id,
                )
                second_participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id=f"second-{suffix}",
                    display_name="Second user",
                )
                session.add(second_participant)
                await session.flush()
                independent = await _command(
                    session,
                    conversation,
                    second_participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[0].id,
                )
            assert (
                await _apply(repository, change, owner, FeedbackValue.UNHELPFUL)
                == FeedbackOutcome.SAVED
            )
            assert (
                await _apply(repository, independent, owner, FeedbackValue.HELPFUL)
                == FeedbackOutcome.SAVED
            )
            async with database.session_factory() as session, session.begin():
                states = list(
                    await session.scalars(
                        select(ConversationFeedbackModel).where(
                            ConversationFeedbackModel.response_plan_id == plan.id
                        )
                    )
                )
                assert sorted((row.value.value, row.revision) for row in states) == [
                    ("helpful", 1),
                    ("unhelpful", 2),
                ]
                no_reply = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=None,
                )
                loaded_plan = await session.get(ResponsePlanModel, plan.id)
                assert loaded_plan is not None
                user_target = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=loaded_plan.reply_to_message_id,
                )
                quote_only = await _command(
                    session,
                    conversation,
                    participant,
                    owner=owner,
                    value=FeedbackValue.HELPFUL,
                    reply_id=None,
                    reply_platform_id=chunks[0].platform_message_id,
                )
            for rejected in (no_reply, user_target, quote_only):
                assert (
                    await _apply(repository, rejected, owner, FeedbackValue.HELPFUL)
                    == FeedbackOutcome.TARGET_UNAVAILABLE
                )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id == plan.id
                        )
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.response_plan_id == plan.id
                        )
                    )
                    == 3
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_revision_limit_and_concurrent_final_slot() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            current_value = FeedbackValue.UNHELPFUL
            for revision in range(1, 10):
                current_value = (
                    FeedbackValue.HELPFUL
                    if current_value == FeedbackValue.UNHELPFUL
                    else FeedbackValue.UNHELPFUL
                )
                async with database.session_factory() as session, session.begin():
                    command = await _command(
                        session,
                        conversation,
                        participant,
                        owner=f"owner-{revision}",
                        value=current_value,
                        reply_id=chunks[revision % 2].id,
                    )
                assert (
                    await _apply(
                        repository, command, f"owner-{revision}", current_value
                    )
                    == FeedbackOutcome.SAVED
                )
            next_value = (
                FeedbackValue.UNHELPFUL
                if current_value == FeedbackValue.HELPFUL
                else FeedbackValue.HELPFUL
            )
            async with database.session_factory() as session, session.begin():
                contenders = [
                    await _command(
                        session,
                        conversation,
                        participant,
                        owner=f"race-{number}",
                        value=next_value,
                        reply_id=chunks[number % 2].id,
                    )
                    for number in range(50)
                ]
            results = await _start_together(
                *(
                    lambda command=command, number=number: _apply(
                        repository, command, f"race-{number}", next_value
                    )
                    for number, command in enumerate(contenders)
                )
            )
            assert results.count(FeedbackOutcome.SAVED) == 1
            assert results.count(FeedbackOutcome.NO_CHANGE) == 49
            opposite = current_value
            async with database.session_factory() as session, session.begin():
                rejected = await _command(
                    session,
                    conversation,
                    participant,
                    owner="limit",
                    value=opposite,
                    reply_id=chunks[0].id,
                )
            assert (
                await _apply(repository, rejected, "limit", opposite)
                == FeedbackOutcome.LIMIT_REACHED
            )
            async with database.session_factory() as session:
                current = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.response_plan_id == plan.id,
                        ConversationFeedbackModel.participant_id == participant.id,
                    )
                )
                assert current is not None and current.revision == 10
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.feedback_id == current.id
                        )
                    )
                    == 10
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_concurrent_duplicate_command_is_one_operation() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
                command = await _command(
                    session,
                    conversation,
                    participant,
                    owner="duplicate-race",
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[0].id,
                )
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            results = await _start_together(
                *(
                    lambda: _apply(
                        repository,
                        command,
                        "duplicate-race",
                        FeedbackValue.HELPFUL,
                    )
                    for _ in range(50)
                )
            )
            assert results.count(FeedbackOutcome.SAVED) == 1
            assert results.count(FeedbackOutcome.TARGET_UNAVAILABLE) == 49
            async with database.session_factory() as session:
                current = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.response_plan_id == plan.id,
                        ConversationFeedbackModel.participant_id == participant.id,
                    )
                )
                assert current is not None
                assert (current.value, current.revision) == (FeedbackValue.HELPFUL, 1)
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.feedback_id == current.id
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanModel.id)).where(
                            ResponsePlanModel.command_job_id == command.id
                        )
                    )
                    == 1
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_concurrent_opposite_commands_have_no_lost_updates() -> None:
    async def scenario() -> None:
        # Provision this atomicity proof for all 100 simultaneous operations.
        # All 100 operations still rendezvous together; the production pool
        # defaults and the connection-acquisition timeout remain unchanged.
        database = Database(
            Settings(  # type: ignore[call-arg]
                _env_file=None,
                environment="test",
                database_pool_size=50,
                database_max_overflow=50,
            )
        )
        await database.start()
        try:
            # Warm retained slots before the operation barrier; bounded overflow
            # admits the other 50 tasks without waiting for a pool slot.
            async with AsyncExitStack() as connections:
                for _ in range(50):
                    await connections.enter_async_context(database.engine.connect())
                assert database.engine.pool.checkedout() == 50
            assert database.engine.pool.checkedout() == 0
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, first_participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, first_participant)
                pairs: list[
                    tuple[
                        ParticipantModel,
                        TelegramCommandJobModel,
                        TelegramCommandJobModel,
                    ]
                ] = []
                for number in range(50):
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id=f"opposite-{number}-{suffix}",
                        display_name="Concurrent feedback user",
                    )
                    session.add(participant)
                    await session.flush()
                    helpful = await _command(
                        session,
                        conversation,
                        participant,
                        owner=f"helpful-{number}",
                        value=FeedbackValue.HELPFUL,
                        reply_id=chunks[number % 2].id,
                    )
                    unhelpful = await _command(
                        session,
                        conversation,
                        participant,
                        owner=f"unhelpful-{number}",
                        value=FeedbackValue.UNHELPFUL,
                        reply_id=chunks[number % 2].id,
                    )
                    pairs.append((participant, helpful, unhelpful))
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            calls: list[Callable[[], Awaitable[FeedbackOutcome]]] = []
            for number, (_, helpful, unhelpful) in enumerate(pairs):
                calls.extend(
                    (
                        lambda command=helpful, number=number: _apply(
                            repository,
                            command,
                            f"helpful-{number}",
                            FeedbackValue.HELPFUL,
                        ),
                        lambda command=unhelpful, number=number: _apply(
                            repository,
                            command,
                            f"unhelpful-{number}",
                            FeedbackValue.UNHELPFUL,
                        ),
                    )
                )
            results = await _start_together(*calls)
            assert results == [FeedbackOutcome.SAVED] * 100
            assert database.engine.pool.checkedout() == 0
            async with database.session_factory() as session:
                states = list(
                    await session.scalars(
                        select(ConversationFeedbackModel).where(
                            ConversationFeedbackModel.response_plan_id == plan.id,
                            ConversationFeedbackModel.participant_id.in_(
                                [participant.id for participant, _, _ in pairs]
                            ),
                        )
                    )
                )
                assert len(states) == 50
                assert all(state.revision == 2 for state in states)
                events = list(
                    await session.scalars(
                        select(ConversationFeedbackEventModel)
                        .where(
                            ConversationFeedbackEventModel.response_plan_id == plan.id,
                            ConversationFeedbackEventModel.participant_id.in_(
                                [participant.id for participant, _, _ in pairs]
                            ),
                        )
                        .order_by(
                            ConversationFeedbackEventModel.feedback_id,
                            ConversationFeedbackEventModel.revision,
                        )
                    )
                )
                assert len(events) == 100
                latest = {
                    event.feedback_id: event.value
                    for event in events
                    if event.revision == 2
                }
                assert len(latest) == 50
                assert all(state.value == latest[state.id] for state in states)
        finally:
            try:
                await _cleanup_feedback_authority(database)
                assert database.engine.pool.checkedout() == 0
            finally:
                await database.stop()

    asyncio.run(scenario())


def test_feedback_database_rejects_mutation_and_cross_scope_contradictions() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
                command = await _command(
                    session,
                    conversation,
                    participant,
                    owner="constraint",
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[0].id,
                )
                foreign_conversation, foreign_participant = await _authority(
                    session, f"foreign-{suffix}"
                )
                foreign_plan, foreign_chunks = await _response(
                    session, foreign_conversation, foreign_participant
                )
                sibling_conversation, sibling_participant = await _sibling_authority(
                    session, conversation, f"scope-{suffix}"
                )
                sibling_plan, sibling_chunks = await _response(
                    session, sibling_conversation, sibling_participant
                )
                sibling_command = await _command(
                    session,
                    sibling_conversation,
                    sibling_participant,
                    owner="sibling-constraint",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=sibling_chunks[0].id,
                )
                foreign_connection = await session.get(
                    PlatformConnectionModel,
                    foreign_conversation.platform_connection_id,
                )
                sibling_connection = await session.get(
                    PlatformConnectionModel,
                    sibling_conversation.platform_connection_id,
                )
                assert foreign_connection is not None
                assert sibling_connection is not None
            for cross_scope_target in (
                foreign_chunks[0].id,
                sibling_chunks[0].id,
            ):
                with pytest.raises(DBAPIError):
                    async with database.session_factory() as session, session.begin():
                        await _command(
                            session,
                            conversation,
                            participant,
                            owner="cross-scope",
                            value=FeedbackValue.HELPFUL,
                            reply_id=cross_scope_target,
                        )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id == plan.id
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.response_plan_id == plan.id
                        )
                    )
                    == 0
                )
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            assert (
                await _apply(repository, command, "constraint", FeedbackValue.HELPFUL)
                == FeedbackOutcome.SAVED
            )
            async with database.session_factory() as session:
                event_id = await session.scalar(
                    select(ConversationFeedbackEventModel.id).where(
                        ConversationFeedbackEventModel.command_job_id == command.id
                    )
                )
                assert event_id is not None
                await session.rollback()

                async def rejected(
                    statement: str, parameters: dict[str, object]
                ) -> None:
                    with pytest.raises(DBAPIError):
                        async with session.begin():
                            await session.execute(text(statement), parameters)
                    await session.rollback()

                current_where = " WHERE response_plan_id = :base_plan"
                await rejected(
                    "UPDATE conversation_feedback SET response_plan_id = :foreign_plan"
                    + current_where,
                    {"foreign_plan": foreign_plan.id, "base_plan": plan.id},
                )
                await rejected(
                    "UPDATE conversation_feedback SET assistant_id = :sibling_assistant"
                    + current_where,
                    {
                        "sibling_assistant": sibling_connection.assistant_id,
                        "base_plan": plan.id,
                    },
                )
                await rejected(
                    "UPDATE conversation_feedback "
                    "SET connection_id = :foreign_connection" + current_where,
                    {
                        "foreign_connection": foreign_connection.id,
                        "base_plan": plan.id,
                    },
                )
                await rejected(
                    "UPDATE conversation_feedback "
                    "SET conversation_id = :foreign_conversation" + current_where,
                    {
                        "foreign_conversation": foreign_conversation.id,
                        "base_plan": plan.id,
                    },
                )
                await rejected(
                    "UPDATE conversation_feedback "
                    "SET participant_id = :sibling_participant" + current_where,
                    {
                        "sibling_participant": sibling_participant.id,
                        "base_plan": plan.id,
                    },
                )
                await rejected(
                    "UPDATE conversation_feedback SET response_plan_id = :sibling_plan"
                    + current_where,
                    {"sibling_plan": sibling_plan.id, "base_plan": plan.id},
                )
                await rejected(
                    "UPDATE conversation_feedback SET value = 'invalid'"
                    + current_where,
                    {"base_plan": plan.id},
                )
                await rejected(
                    "UPDATE conversation_feedback SET revision = 0" + current_where,
                    {"base_plan": plan.id},
                )
                await rejected(
                    "INSERT INTO conversation_feedback "
                    "(id, tenant_id, assistant_id, connection_id, conversation_id, "
                    "response_plan_id, participant_id, target_message_id, "
                    "target_outbound_action_id, value, revision) "
                    "SELECT CAST(:duplicate_id AS uuid), tenant_id, assistant_id, "
                    "connection_id, conversation_id, response_plan_id, participant_id, "
                    "target_message_id, target_outbound_action_id, value, revision "
                    "FROM conversation_feedback WHERE response_plan_id = :base_plan",
                    {"duplicate_id": uuid4(), "base_plan": plan.id},
                )
                await rejected(
                    "UPDATE conversation_feedback_events "
                    "SET tenant_id = :foreign_tenant "
                    "WHERE id = :event_id",
                    {
                        "foreign_tenant": foreign_connection.tenant_id,
                        "event_id": event_id,
                    },
                )
                await rejected(
                    "UPDATE conversation_feedback_events "
                    "SET target_message_id = :foreign_target WHERE id = :event_id",
                    {"foreign_target": foreign_chunks[0].id, "event_id": event_id},
                )
                await rejected(
                    "UPDATE conversation_feedback_events "
                    "SET value = 'unhelpful' WHERE id = :event_id",
                    {"event_id": event_id},
                )
                await rejected(
                    "UPDATE conversation_feedback_events "
                    "SET command_job_id = :sibling_command WHERE id = :event_id",
                    {"sibling_command": sibling_command.id, "event_id": event_id},
                )
                await rejected(
                    "DELETE FROM conversation_feedback_events WHERE id = :event_id",
                    {"event_id": event_id},
                )
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id == plan.id
                        )
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.response_plan_id == plan.id
                        )
                    )
                    == 1
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_subject_export_privacy_erasure_and_retention() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
                command = await _command(
                    session,
                    conversation,
                    participant,
                    owner="privacy",
                    value=FeedbackValue.HELPFUL,
                    reply_id=chunks[0].id,
                )
                other_participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id=f"other-{suffix}",
                    display_name="Other feedback user",
                )
                session.add(other_participant)
                await session.flush()
                other_command = await _command(
                    session,
                    conversation,
                    other_participant,
                    owner="privacy-other",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=chunks[1].id,
                )
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            assert (
                await _apply(repository, command, "privacy", FeedbackValue.HELPFUL)
                == FeedbackOutcome.SAVED
            )
            assert (
                await _apply(
                    repository,
                    other_command,
                    "privacy-other",
                    FeedbackValue.UNHELPFUL,
                )
                == FeedbackOutcome.SAVED
            )
            package = await GovernanceExportBuilder(
                database.session_factory
            ).build_subject_export(
                request_id=uuid4(),
                conversation_id=conversation.id,
                participant_id=participant.id,
            )
            feedback_export = package["data"]["feedback"]  # type: ignore[index]
            assert feedback_export == {
                "current": [
                    {
                        "value": FeedbackValue.HELPFUL,
                        "revision": 1,
                        "target_response_created_at": plan.created_at.isoformat(),
                        "created_at": feedback_export["current"][0]["created_at"],
                        "updated_at": feedback_export["current"][0]["updated_at"],
                    }
                ],
                "history": [
                    {
                        "value": FeedbackValue.HELPFUL,
                        "revision": 1,
                        "target_response_created_at": plan.created_at.isoformat(),
                        "recorded_at": feedback_export["history"][0]["recorded_at"],
                    }
                ],
            }
            rendered = repr(feedback_export)
            assert str(plan.id) not in rendered
            assert plan.text not in rendered
            assert FeedbackValue.UNHELPFUL not in rendered
            assert other_participant.platform_user_id not in rendered

            result = await SqlAlchemyPrivacyRepository(
                database.session_factory
            ).erase_subject(
                assistant_id=connection.assistant_id,
                platform_connection_id=connection.id,
                platform_user_id=participant.platform_user_id,
                command_job_id=command.id,
            )
            assert result.feedback == 2
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id == plan.id,
                            ConversationFeedbackModel.participant_id == participant.id,
                        )
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackEventModel.id)).where(
                            ConversationFeedbackEventModel.response_plan_id == plan.id,
                            ConversationFeedbackEventModel.participant_id
                            == participant.id,
                        )
                    )
                    == 0
                )
                other_state = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.response_plan_id == plan.id,
                        ConversationFeedbackModel.participant_id
                        == other_participant.id,
                    )
                )
                assert other_state is not None
                assert (other_state.value, other_state.revision) == (
                    FeedbackValue.UNHELPFUL,
                    1,
                )

            async with database.session_factory() as session, session.begin():
                erased_command = await _command(
                    session,
                    conversation,
                    participant,
                    owner="privacy-erased",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=chunks[0].id,
                )
            assert (
                await _apply(
                    repository,
                    erased_command,
                    "privacy-erased",
                    FeedbackValue.UNHELPFUL,
                )
                == FeedbackOutcome.TARGET_UNAVAILABLE
            )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.participant_id == participant.id
                        )
                    )
                    == 0
                )

            async with database.session_factory() as session, session.begin():
                retained_conversation, retained_participant = await _authority(
                    session, f"retention-{suffix}"
                )
                retained_plan, retained_chunks = await _response(
                    session, retained_conversation, retained_participant
                )
                retained_command = await _command(
                    session,
                    retained_conversation,
                    retained_participant,
                    owner="retention",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=retained_chunks[0].id,
                )
            assert (
                await _apply(
                    repository,
                    retained_command,
                    "retention",
                    FeedbackValue.UNHELPFUL,
                )
                == FeedbackOutcome.SAVED
            )
            counts = await SqlAlchemyRetentionRepository(
                database.session_factory
            ).redact_once(
                now=datetime.now(UTC) + timedelta(days=31),
                retention_days=30,
                batch_size=1000,
            )
            assert counts.feedback >= 2
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id
                            == retained_plan.id
                        )
                    )
                    == 0
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_worker_is_local_and_emits_only_bounded_metric() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            command_worker_enabled=True,
            telegram_enabled=False,
            rate_limit_enabled=False,
        )  # type: ignore[call-arg]
        database = Database(settings)
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                plan, chunks = await _response(session, conversation, participant)
                command = await _command(
                    session,
                    conversation,
                    participant,
                    owner="not-yet-claimed",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=chunks[0].id,
                )
                command.status = CommandJobStatus.PENDING
                command.lease_owner = None
                command.lease_expires_at = None
                separation_before = await _separation_counts(session)
                response_plan_count_before = int(
                    await session.scalar(select(func.count(ResponsePlanModel.id))) or 0
                )
                action_count_before = int(
                    await session.scalar(select(func.count(OutboundActionModel.id)))
                    or 0
                )
            telemetry = InMemoryMetricsRecorder()
            platform_boundary = _NoExternalCalls()
            tts_boundary = _NoExternalCalls()
            rate_boundary = _NoExternalCalls()
            concurrency_boundary = _NoExternalCalls()
            assert (
                await consume_command_once(
                    settings,
                    database,
                    adapter=platform_boundary,  # type: ignore[arg-type]
                    owner="feedback-worker",
                    telemetry=telemetry,
                    tts_provider=tts_boundary,  # type: ignore[arg-type]
                    rate_limiter=rate_boundary,  # type: ignore[arg-type]
                    concurrency_limiter=concurrency_boundary,  # type: ignore[arg-type]
                )
                == 1
            )
            assert (
                platform_boundary.calls,
                tts_boundary.calls,
                rate_boundary.calls,
                concurrency_boundary.calls,
            ) == (0, 0, 0, 0)
            exposition = telemetry.exposition()
            assert (
                'january_conversation_feedback_total{outcome="unhelpful"} 1'
                in exposition
            )
            assert str(plan.id) not in exposition
            assert participant.platform_user_id not in exposition
            async with database.session_factory() as session:
                state = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.response_plan_id == plan.id,
                        ConversationFeedbackModel.participant_id == participant.id,
                    )
                )
                completed = await session.get(TelegramCommandJobModel, command.id)
                assert state is not None
                assert (state.value, state.revision) == (FeedbackValue.UNHELPFUL, 1)
                assert completed is not None
                assert (
                    completed.status,
                    completed.result_code,
                ) == (CommandJobStatus.COMPLETED, "feedback_saved")
                assert await _separation_counts(session) == separation_before
                assert (
                    int(
                        await session.scalar(select(func.count(ResponsePlanModel.id)))
                        or 0
                    )
                    == response_plan_count_before + 1
                )
                assert (
                    int(
                        await session.scalar(select(func.count(OutboundActionModel.id)))
                        or 0
                    )
                    == action_count_before + 1
                )
            async with database.session_factory() as session, session.begin():
                acknowledgement_plan = await session.scalar(
                    select(ResponsePlanModel).where(
                        ResponsePlanModel.command_job_id == command.id
                    )
                )
                assert acknowledgement_plan is not None
                acknowledgement_action = await session.scalar(
                    select(OutboundActionModel).where(
                        OutboundActionModel.response_plan_id == acknowledgement_plan.id
                    )
                )
                assert acknowledgement_action is not None
                acknowledgement_action.status = OutboundActionStatus.DELIVERED
                acknowledgement_action.completed_at = datetime.now(UTC)
                acknowledgement_message = MessageModel(
                    conversation_id=conversation.id,
                    outbound_action_id=acknowledgement_action.id,
                    platform_message_id=f"feedback-ack-{uuid4()}",
                    direction=MessageDirection.OUTGOING,
                    message_type=MessageType.TEXT,
                    text=acknowledgement_action.text,
                    processing_status=MessageProcessingStatus.PROCESSED,
                    platform_sent_at=datetime.now(UTC),
                )
                session.add(acknowledgement_message)
                await session.flush()
                acknowledgement_action.delivered_message_id = acknowledgement_message.id
                normal = MessageModel(
                    conversation_id=conversation.id,
                    participant_id=participant.id,
                    platform_message_id=f"normal-{uuid4()}",
                    direction=MessageDirection.INCOMING,
                    message_type=MessageType.TEXT,
                    text="Continue with an ordinary question.",
                    processing_status=MessageProcessingStatus.PROCESSED,
                    platform_sent_at=datetime.now(UTC) + timedelta(seconds=1),
                )
                session.add(normal)
                await session.flush()
                normal_id = normal.id
            context = await SqlAlchemyConversationContextReader(
                database.session_factory, settings
            ).build_for_message(normal_id, include_semantic=False)
            assert context is not None
            context_text = "\n".join(
                item.text or "" for item in (context.current, *context.recent_history)
            )
            assert "/feedback unhelpful" not in context_text
            assert "Feedback saved." not in context_text
            async with database.session_factory() as session:
                summary_sources = list(
                    await session.scalars(
                        SqlAlchemySummaryRepository._source_statement(
                            conversation.id, None
                        )
                    )
                )
                assert all(
                    item.text != "/feedback unhelpful" for item in summary_sources
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())


def test_feedback_resolves_exact_regenerated_and_voice_source_plans() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, participant = await _authority(session, suffix)
                root_plan, chunks = await _response(session, conversation, participant)
                regeneration_command = await _control_command(
                    session,
                    conversation,
                    participant,
                    name="regenerate",
                    reply_id=chunks[0].id,
                )
                root_job = await session.get(
                    ResponsePlanningJobModel, root_plan.planning_job_id
                )
                assert root_job is not None
                regeneration_job = ResponsePlanningJobModel(
                    conversation_processing_record_id=(
                        regeneration_command.conversation_processing_record_id
                    ),
                    conversation_id=conversation.id,
                    message_id=root_job.message_id,
                    source_command_job_id=regeneration_command.id,
                    root_response_plan_id=root_plan.id,
                    parent_response_plan_id=root_plan.id,
                    regeneration_ordinal=1,
                    prompt_version="spec-039-regenerated",
                    response_schema_version="response-plan-v1",
                    status=PlanningJobStatus.COMPLETED,
                    completed_at=datetime.now(UTC),
                )
                session.add(regeneration_job)
                await session.flush()
                regenerated_plan = ResponsePlanModel(
                    planning_job_id=regeneration_job.id,
                    should_respond=True,
                    reason_code=PlanReasonCode.ANSWER,
                    text="Exact regenerated answer.",
                    reply_to_message_id=root_job.message_id,
                    mention_participant_ids=[],
                    confidence=1,
                    prompt_version="spec-039-regenerated",
                    schema_version="response-plan-v1",
                )
                session.add(regenerated_plan)
                await session.flush()
                edit_action = OutboundActionModel(
                    response_plan_id=regenerated_plan.id,
                    conversation_id=conversation.id,
                    sequence_number=1,
                    sequence_count=1,
                    idempotency_key=uuid4().hex,
                    kind=OutboundActionKind.EDIT_TEXT,
                    status=OutboundActionStatus.DELIVERED,
                    edit_target_message_id=chunks[0].id,
                    edit_target_platform_message_id=chunks[0].platform_message_id,
                    text=regenerated_plan.text,
                    mention_participant_ids=[],
                    completed_at=datetime.now(UTC),
                )
                session.add(edit_action)
                await session.flush()
                regeneration_feedback = await _command(
                    session,
                    conversation,
                    participant,
                    owner="regen-feedback",
                    value=FeedbackValue.UNHELPFUL,
                    reply_id=chunks[0].id,
                )
            repository = SqlAlchemyFeedbackRepository(database.session_factory)
            assert (
                await _apply(
                    repository,
                    regeneration_feedback,
                    "regen-feedback",
                    FeedbackValue.UNHELPFUL,
                )
                == FeedbackOutcome.SAVED
            )
            async with database.session_factory() as session, session.begin():
                regenerated_state = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.participant_id == participant.id,
                        ConversationFeedbackModel.response_plan_id
                        == regenerated_plan.id,
                    )
                )
                assert regenerated_state is not None
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.participant_id == participant.id,
                            ConversationFeedbackModel.response_plan_id == root_plan.id,
                        )
                    )
                    == 0
                )

                voice_command = await _control_command(
                    session,
                    conversation,
                    participant,
                    name="voice",
                    reply_id=chunks[1].id,
                )
                connection = await session.get(
                    PlatformConnectionModel, conversation.platform_connection_id
                )
                assert connection is not None and root_plan.text is not None
                voice_job = TelegramVoiceGenerationJobModel(
                    command_job_id=voice_command.id,
                    tenant_id=connection.tenant_id,
                    assistant_id=connection.assistant_id,
                    connection_id=connection.id,
                    conversation_id=conversation.id,
                    source_response_plan_id=root_plan.id,
                    source_sha256=sha256(root_plan.text.encode()).hexdigest(),
                    source_character_count=len(root_plan.text),
                    privacy_revision=conversation.memory_privacy_revision,
                    status=VoiceGenerationStatus.COMPLETED,
                    attempt_count=1,
                    completed_at=datetime.now(UTC),
                )
                session.add(voice_job)
                await session.flush()
                audio = b"OggS\x00\x02spec-039"
                artifact = GeneratedVoiceArtifactModel(
                    generation_job_id=voice_job.id,
                    tenant_id=connection.tenant_id,
                    assistant_id=connection.assistant_id,
                    connection_id=connection.id,
                    conversation_id=conversation.id,
                    source_response_plan_id=root_plan.id,
                    format=VoiceFormat.OGG_OPUS,
                    mime_type="audio/ogg",
                    audio_bytes=audio,
                    byte_size=len(audio),
                    sha256=sha256(audio).hexdigest(),
                    status=VoiceArtifactStatus.READY,
                    expires_at=datetime.now(UTC) + timedelta(days=6),
                )
                session.add(artifact)
                await session.flush()
                voice_plan = ResponsePlanModel(
                    command_job_id=voice_command.id,
                    should_respond=True,
                    reason_code=PlanReasonCode.ACKNOWLEDGEMENT,
                    text=None,
                    reply_to_message_id=voice_command.message_id,
                    mention_participant_ids=[],
                    confidence=1,
                    prompt_version="telegram-command-v1",
                    schema_version="response-plan-v1",
                )
                session.add(voice_plan)
                await session.flush()
                voice_action = OutboundActionModel(
                    response_plan_id=voice_plan.id,
                    conversation_id=conversation.id,
                    sequence_number=1,
                    sequence_count=1,
                    idempotency_key=uuid4().hex,
                    kind=OutboundActionKind.VOICE,
                    status=OutboundActionStatus.DELIVERED,
                    reply_to_message_id=voice_command.message_id,
                    generated_voice_artifact_id=artifact.id,
                    mention_participant_ids=[],
                    completed_at=datetime.now(UTC),
                )
                session.add(voice_action)
                await session.flush()
                voice_message = MessageModel(
                    conversation_id=conversation.id,
                    outbound_action_id=voice_action.id,
                    platform_message_id=f"voice-presentation-{uuid4()}",
                    direction=MessageDirection.OUTGOING,
                    message_type=MessageType.VOICE,
                    text=None,
                    processing_status=MessageProcessingStatus.PROCESSED,
                    platform_sent_at=datetime.now(UTC),
                )
                session.add(voice_message)
                await session.flush()
                voice_action.delivered_message_id = voice_message.id
                voice_feedback = await _command(
                    session,
                    conversation,
                    participant,
                    owner="voice-feedback",
                    value=FeedbackValue.HELPFUL,
                    reply_id=voice_message.id,
                )
            assert (
                await _apply(
                    repository,
                    voice_feedback,
                    "voice-feedback",
                    FeedbackValue.HELPFUL,
                )
                == FeedbackOutcome.SAVED
            )
            async with database.session_factory() as session:
                voice_source_state = await session.scalar(
                    select(ConversationFeedbackModel).where(
                        ConversationFeedbackModel.participant_id == participant.id,
                        ConversationFeedbackModel.response_plan_id == root_plan.id,
                    )
                )
                assert voice_source_state is not None
                assert voice_source_state.value == FeedbackValue.HELPFUL
                assert (
                    await session.scalar(
                        select(func.count(ConversationFeedbackModel.id)).where(
                            ConversationFeedbackModel.response_plan_id == voice_plan.id
                        )
                    )
                    == 0
                )
        finally:
            await _cleanup_feedback_authority(database)
            await database.stop()

    asyncio.run(scenario())
