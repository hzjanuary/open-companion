"""Live PostgreSQL proofs for SPEC-036 regeneration authority and concurrency."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.model_provider import (
    GenerationRequest,
    ProviderCapabilities,
    ProviderResult,
    ProviderUsage,
)
from app.application.ports.platform import (
    EditTextRequest,
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendChatActionRequest,
    SendTextRequest,
    SentMessage,
)
from app.application.response_plan import ResponsePlanCandidate
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.outbound import (
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
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
from app.domain.planning import (
    PlanningJobStatus,
    PlanReasonCode,
    ProviderId,
    StickerIntent,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation, RateLimitRule
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.database.regeneration import (
    RegenerationAdmission,
    SqlAlchemyRegenerationRepository,
)
from app.runtime.outbound_delivery_worker import consume_once as deliver_once
from app.runtime.response_planning_worker import consume_once as plan_once

pytestmark = [pytest.mark.integration, pytest.mark.telegram_regeneration_integration]


async def _authority(
    session: AsyncSession, *, suffix: str
) -> tuple[ConversationModel, AssistantModel]:
    tenant = ControlTenantModel(slug=f"regen-{suffix}", name="Regeneration")
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
        conversation_type=ConversationType.PRIVATE,
        status=ConversationStatus.ACTIVE,
        response_mode=ResponseMode.MENTION_ONLY,
    )
    session.add(conversation)
    await session.flush()
    await ensure_conversation_configuration(session, assistant, conversation)
    return conversation, assistant


async def _incoming(
    session: AsyncSession,
    conversation: ConversationModel,
    *,
    platform_id: str,
    body: str,
    reply_id: UUID | None = None,
    reply_platform_id: str | None = None,
) -> MessageModel:
    participant = ParticipantModel(
        conversation_id=conversation.id,
        platform_user_id=f"user-{platform_id}-{uuid4()}",
        display_name="User",
    )
    session.add(participant)
    await session.flush()
    message = MessageModel(
        conversation_id=conversation.id,
        participant_id=participant.id,
        platform_message_id=platform_id,
        direction=MessageDirection.INCOMING,
        message_type=MessageType.TEXT,
        text=body,
        reply_to_message_id=reply_id,
        reply_to_platform_message_id=reply_platform_id,
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
    )
    session.add(message)
    await session.flush()
    return message


async def _processing_record(
    session: AsyncSession, conversation: ConversationModel, message: MessageModel
) -> ConversationProcessingRecordModel:
    update = IncomingPlatformUpdateModel(
        platform_connection_id=conversation.platform_connection_id,
        platform=Platform.TELEGRAM,
        platform_update_id=f"update-{uuid4()}",
        update_type="message",
        ingress_source=IngressSource.WEBHOOK,
        raw_payload={},
        received_at=datetime.now(UTC),
    )
    session.add(update)
    await session.flush()
    record = ConversationProcessingRecordModel(
        incoming_update_id=update.id,
        outcome=ProcessingOutcome.MESSAGE_CREATED,
        conversation_id=conversation.id,
        message_id=message.id,
    )
    session.add(record)
    await session.flush()
    return record


async def _root_response(
    session: AsyncSession,
    conversation: ConversationModel,
    *,
    chunks: int,
    sticker: bool = False,
) -> tuple[MessageModel, ResponsePlanModel, list[MessageModel]]:
    source = await _incoming(
        session,
        conversation,
        platform_id=f"source-{uuid4()}",
        body="Original authoritative question",
    )
    record = await _processing_record(session, conversation, source)
    job = ResponsePlanningJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=source.id,
        prompt_version="spec-036-test",
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
        text="".join(f"chunk-{number}" for number in range(1, chunks + 1)),
        sticker_intent=StickerIntent.SUPPORT if sticker else None,
        reply_to_message_id=source.id,
        mention_participant_ids=[],
        confidence=1,
        prompt_version="spec-036-test",
        schema_version="response-plan-v1",
    )
    session.add(plan)
    await session.flush()
    delivered: list[MessageModel] = []
    for number in range(1, chunks + 1):
        action = OutboundActionModel(
            response_plan_id=plan.id,
            conversation_id=conversation.id,
            sequence_number=number,
            sequence_count=chunks + int(sticker),
            idempotency_key=uuid4().hex,
            kind=OutboundActionKind.TEXT,
            status=OutboundActionStatus.DELIVERED,
            text=f"chunk-{number}",
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
        delivered.append(message)
    if sticker:
        action = OutboundActionModel(
            response_plan_id=plan.id,
            conversation_id=conversation.id,
            sequence_number=chunks + 1,
            sequence_count=chunks + 1,
            idempotency_key=uuid4().hex,
            kind=OutboundActionKind.STICKER,
            status=OutboundActionStatus.DELIVERED,
            sticker_intent=StickerIntent.SUPPORT,
            mention_participant_ids=[],
            completed_at=datetime.now(UTC),
        )
        session.add(action)
        await session.flush()
        message = MessageModel(
            conversation_id=conversation.id,
            outbound_action_id=action.id,
            platform_message_id=f"sticker-{uuid4()}",
            direction=MessageDirection.OUTGOING,
            message_type=MessageType.STICKER,
            processing_status=MessageProcessingStatus.PROCESSED,
            platform_sent_at=datetime.now(UTC),
        )
        session.add(message)
        await session.flush()
        action.delivered_message_id = message.id
        delivered.append(message)
    return source, plan, delivered


async def _command(
    session: AsyncSession,
    conversation: ConversationModel,
    *,
    owner: str,
    reply_id: UUID | None,
    reply_platform_id: str | None = None,
) -> TelegramCommandJobModel:
    message = await _incoming(
        session,
        conversation,
        platform_id=f"command-{uuid4()}",
        body="/regenerate",
        reply_id=reply_id,
        reply_platform_id=reply_platform_id,
    )
    record = await _processing_record(session, conversation, message)
    assert message.participant_id is not None
    command = TelegramCommandJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=message.id,
        participant_id=message.participant_id,
        command_name="regenerate",
        arguments="",
        status=CommandJobStatus.LEASED,
        lease_owner=owner,
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
        attempt_count=1,
    )
    session.add(command)
    await session.flush()
    return command


async def _start_together(
    *calls: Callable[[], Awaitable[RegenerationAdmission]],
) -> list[RegenerationAdmission]:
    ready = 0
    lock = asyncio.Lock()
    start = asyncio.Event()

    async def run(
        call: Callable[[], Awaitable[RegenerationAdmission]],
    ) -> RegenerationAdmission:
        nonlocal ready
        async with lock:
            ready += 1
            if ready == len(calls):
                start.set()
        await start.wait()
        return await call()

    return list(await asyncio.gather(*(run(call) for call in calls)))


def test_reply_target_lineage_idempotency_limit_and_concurrency() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=suffix)
                source, root, chunks = await _root_response(
                    session, conversation, chunks=2
                )
                first = await _command(
                    session,
                    conversation,
                    owner="regen",
                    reply_id=chunks[1].id,
                )
            repository = SqlAlchemyRegenerationRepository(database.session_factory)
            duplicate_results = await _start_together(
                lambda: repository.accept(first.id, "regen"),
                lambda: repository.accept(first.id, "regen"),
            )
            assert sorted(duplicate_results) == sorted(
                [
                    RegenerationAdmission.ACCEPTED,
                    RegenerationAdmission.TARGET_UNAVAILABLE,
                ]
            )
            async with database.session_factory() as session, session.begin():
                job = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == first.id
                    )
                )
                assert job is not None
                assert (
                    job.message_id,
                    job.root_response_plan_id,
                    job.parent_response_plan_id,
                    job.regeneration_ordinal,
                ) == (source.id, root.id, root.id, 1)
                first_row = await session.get(TelegramCommandJobModel, first.id)
                assert first_row is not None
                first_row.status = CommandJobStatus.LEASED
                first_row.lease_owner = "regen"
                first_row.lease_expires_at = datetime.now(UTC) + timedelta(seconds=60)
            assert (
                await repository.accept(first.id, "regen")
                == RegenerationAdmission.ACCEPTED
            )
            async with database.session_factory() as session, session.begin():
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanningJobModel.id)).where(
                            ResponsePlanningJobModel.source_command_job_id == first.id
                        )
                    )
                    == 1
                )
                second = await _command(
                    session,
                    conversation,
                    owner="regen",
                    reply_id=chunks[0].id,
                )
            assert (
                await repository.accept(second.id, "regen")
                == RegenerationAdmission.ACCEPTED
            )
            async with database.session_factory() as session, session.begin():
                third = await _command(
                    session,
                    conversation,
                    owner="third",
                    reply_id=chunks[0].id,
                )
                fourth = await _command(
                    session,
                    conversation,
                    owner="fourth",
                    reply_id=chunks[1].id,
                )
            results = await _start_together(
                lambda: repository.accept(third.id, "third"),
                lambda: repository.accept(fourth.id, "fourth"),
            )
            assert sorted(results) == sorted(
                [RegenerationAdmission.ACCEPTED, RegenerationAdmission.LIMIT_REACHED]
            )
            async with database.session_factory() as session:
                ordinals = list(
                    await session.scalars(
                        select(ResponsePlanningJobModel.regeneration_ordinal)
                        .where(
                            ResponsePlanningJobModel.root_response_plan_id == root.id
                        )
                        .order_by(ResponsePlanningJobModel.regeneration_ordinal)
                    )
                )
                assert ordinals == [1, 2, 3]
                assert database.engine.pool.checkedout() == 1  # type: ignore[attr-defined]
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_foreign_platform_message_id_is_not_target_authority() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                local, _ = await _authority(session, suffix=f"local-{suffix}")
                foreign, _ = await _authority(session, suffix=f"foreign-{suffix}")
                _, _, foreign_messages = await _root_response(
                    session, foreign, chunks=1
                )
                command = await _command(
                    session,
                    local,
                    owner="foreign-test",
                    reply_id=None,
                    reply_platform_id=foreign_messages[0].platform_message_id,
                )
            result = await SqlAlchemyRegenerationRepository(
                database.session_factory
            ).accept(command.id, "foreign-test")
            assert result == RegenerationAdmission.TARGET_UNAVAILABLE
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanningJobModel.id)).where(
                            ResponsePlanningJobModel.source_command_job_id == command.id
                        )
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("erased", ["source", "target"])
def test_erased_source_or_target_is_not_resurrected(erased: str) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=uuid4().hex)
                source, _, messages = await _root_response(
                    session, conversation, chunks=1
                )
                erased_message = source if erased == "source" else messages[0]
                erased_message.text = None
                erased_message.content_redacted_at = datetime.now(UTC)
                command = await _command(
                    session,
                    conversation,
                    owner="erasure",
                    reply_id=messages[0].id,
                )
            result = await SqlAlchemyRegenerationRepository(
                database.session_factory
            ).accept(command.id, "erasure")
            assert result == RegenerationAdmission.TARGET_UNAVAILABLE
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanningJobModel.id)).where(
                            ResponsePlanningJobModel.source_command_job_id == command.id
                        )
                    )
                    == 0
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("chunks", [1, 2])
def test_planning_compiles_edit_only_for_one_visible_text(chunks: int) -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=suffix)
                source, root, messages = await _root_response(
                    session, conversation, chunks=chunks
                )
                command = await _command(
                    session,
                    conversation,
                    owner="admit",
                    reply_id=messages[-1].id,
                )
            assert (
                await SqlAlchemyRegenerationRepository(database.session_factory).accept(
                    command.id, "admit"
                )
                == RegenerationAdmission.ACCEPTED
            )
            planning = SqlAlchemyPlanningRepository(database.session_factory)
            async with database.session_factory() as session, session.begin():
                regeneration = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == command.id
                    )
                )
                assert regeneration is not None
                regeneration.status = PlanningJobStatus.LEASED
                regeneration.lease_owner = "planner"
                regeneration.lease_expires_at = datetime.now(UTC) + timedelta(
                    seconds=60
                )
                regeneration.attempt_count = 1
            plan_id = await planning.complete(
                regeneration.id,
                "planner",
                ResponsePlanCandidate(
                    should_respond=True,
                    reason_code=PlanReasonCode.ANSWER,
                    text="Current replacement",
                    reply_to_message_id=source.id,
                    confidence=1,
                ),
                ProviderId.OPENAI,
                "test-model",
                None,
                regeneration.prompt_version,
                regeneration.response_schema_version,
                expected_attempt=regeneration.attempt_count,
            )
            assert plan_id is not None
            async with database.session_factory() as session:
                actions = list(
                    await session.scalars(
                        select(OutboundActionModel)
                        .where(OutboundActionModel.response_plan_id == plan_id)
                        .order_by(OutboundActionModel.sequence_number)
                    )
                )
                if chunks == 1:
                    assert [item.kind for item in actions] == [
                        OutboundActionKind.EDIT_TEXT,
                        OutboundActionKind.TEXT,
                    ]
                    assert [item.status for item in actions] == [
                        OutboundActionStatus.PENDING,
                        OutboundActionStatus.FALLBACK_BLOCKED,
                    ]
                    assert actions[0].edit_target_message_id == messages[0].id
                    assert actions[1].fallback_for_action_id == actions[0].id
                else:
                    assert len(actions) == 1
                    assert actions[0].kind == OutboundActionKind.TEXT
                    assert actions[0].fallback_for_action_id is None
                lineage = await session.get(ResponsePlanningJobModel, regeneration.id)
                assert lineage is not None
                assert lineage.root_response_plan_id == root.id
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_sticker_chunk_resolves_whole_plan_and_forces_new_text_send() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))  # type: ignore[call-arg]
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=uuid4().hex)
                source, root, messages = await _root_response(
                    session, conversation, chunks=1, sticker=True
                )
                command = await _command(
                    session,
                    conversation,
                    owner="sticker-target",
                    reply_id=messages[-1].id,
                )
            repository = SqlAlchemyRegenerationRepository(database.session_factory)
            assert (
                await repository.accept(command.id, "sticker-target")
                == RegenerationAdmission.ACCEPTED
            )
            async with database.session_factory() as session, session.begin():
                regeneration = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == command.id
                    )
                )
                assert regeneration is not None
                assert regeneration.parent_response_plan_id == root.id
                regeneration.status = PlanningJobStatus.LEASED
                regeneration.lease_owner = "sticker-planner"
                regeneration.lease_expires_at = datetime.now(UTC) + timedelta(
                    seconds=60
                )
                regeneration.attempt_count = 1
            plan_id = await SqlAlchemyPlanningRepository(
                database.session_factory
            ).complete(
                regeneration.id,
                "sticker-planner",
                ResponsePlanCandidate(
                    should_respond=True,
                    reason_code=PlanReasonCode.ANSWER,
                    text="Fresh text replacement",
                    reply_to_message_id=source.id,
                    confidence=1,
                ),
                ProviderId.OPENAI,
                "test-model",
                None,
                regeneration.prompt_version,
                regeneration.response_schema_version,
                expected_attempt=1,
            )
            assert plan_id is not None
            async with database.session_factory() as session:
                actions = list(
                    await session.scalars(
                        select(OutboundActionModel).where(
                            OutboundActionModel.response_plan_id == plan_id
                        )
                    )
                )
                assert len(actions) == 1
                assert actions[0].kind == OutboundActionKind.TEXT
                assert actions[0].reply_to_message_id == source.id
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_regeneration_provider_io_is_fresh_governed_and_session_free() -> None:
    async def scenario() -> None:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token=SecretStr("fake-token"),
            llm_enabled=True,
            llm_openai_model="spec036-model",
            llm_openai_api_key=SecretStr("synthetic"),
            llm_max_output_tokens=300,
            provider_governance_mode="legacy",
            provider_governance_worker_enabled=False,
            rate_limit_enabled=False,
            provider_concurrency_enabled=False,
            outbound_delivery_enabled=True,
            telegram_platform_connection_id=uuid4(),
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=uuid4().hex)
                _, _, messages = await _root_response(session, conversation, chunks=1)
                command = await _command(
                    session,
                    conversation,
                    owner="admit-provider",
                    reply_id=messages[0].id,
                )
            assert (
                await SqlAlchemyRegenerationRepository(database.session_factory).accept(
                    command.id, "admit-provider"
                )
                == RegenerationAdmission.ACCEPTED
            )
            events: list[str] = []

            class Generator:
                provider_id = ProviderId.OPENAI
                model = "spec036-model"
                capabilities = ProviderCapabilities(
                    True, True, "max_tokens", True, True
                )

                async def generate(self, request: GenerationRequest) -> ProviderResult:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    assert "Original authoritative question" in request.user_content
                    assert "/regenerate" not in request.user_content
                    events.append("provider")
                    return ProviderResult(
                        self.provider_id,
                        self.model,
                        '{"should_respond":true,"reason_code":"answer",'
                        '"text":"Fresh governed replacement","confidence":1.0}',
                        None,
                        ProviderUsage(10, 5, 15),
                        timedelta(),
                        "stop",
                    )

                async def aclose(self) -> None:
                    return None

            class Presence:
                async def send_chat_action(
                    self, request: SendChatActionRequest
                ) -> None:
                    del request
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    events.append("presence")

            class PresenceLifecycle:
                def __init__(self, send: Callable[[], Awaitable[None]]) -> None:
                    self._send = send

                async def start(self) -> None:
                    await self._send()

                async def stop(self) -> None:
                    events.append("presence_stopped")

            def presence_factory(
                send: Callable[[], Awaitable[None]],
                fence: Callable[[], Awaitable[bool]],
                telemetry: object,
            ) -> PresenceLifecycle:
                del fence, telemetry
                return PresenceLifecycle(send)

            assert (
                await plan_once(
                    settings,
                    database,
                    owner="regen-provider",
                    primary_provider=Generator(),
                    presence_adapter=Presence(),
                    presence_controller_factory=presence_factory,  # type: ignore[arg-type]
                )
                == 1
            )
            assert events == ["presence", "provider", "presence_stopped"]
            async with database.session_factory() as session:
                job = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == command.id
                    )
                )
                assert job is not None
                assert job.status == PlanningJobStatus.COMPLETED
                assert job.selected_provider == ProviderId.OPENAI
                assert job.regeneration_ordinal == 1
                assert job.knowledge_provenance == []

            class DeliveryAdapter:
                @property
                def capabilities(self) -> frozenset[PlatformCapability]:
                    return frozenset(
                        {PlatformCapability.EDIT_TEXT, PlatformCapability.SEND_TEXT}
                    )

                async def edit_text(self, request: EditTextRequest) -> SentMessage:
                    assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
                    events.append("edit")
                    return SentMessage(
                        Platform.TELEGRAM,
                        request.platform_message_id,
                        request.conversation_id,
                        "bot",
                        None,
                        datetime.now(UTC),
                    )

                async def send_text(self, request: SendTextRequest) -> SentMessage:
                    del request
                    raise AssertionError("edit-eligible regeneration must not send")

                async def send_sticker(self, request: object) -> SentMessage:
                    del request
                    raise AssertionError("edit-eligible regeneration must not sticker")

                async def aclose(self) -> None:
                    return None

            assert (
                await deliver_once(
                    settings,
                    database,
                    adapter=DeliveryAdapter(),  # type: ignore[arg-type]
                )
                == 1
            )
            assert events == ["presence", "provider", "presence_stopped", "edit"]
            assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        finally:
            await database.stop()

    asyncio.run(scenario())


def test_regeneration_current_rate_denial_calls_provider_zero() -> None:
    async def scenario() -> None:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token=SecretStr("fake-token"),
            llm_enabled=True,
            llm_openai_model="spec036-model",
            llm_openai_api_key=SecretStr("synthetic"),
            llm_max_output_tokens=300,
            provider_governance_mode="legacy",
            provider_governance_worker_enabled=False,
            rate_limit_enabled=True,
            provider_concurrency_enabled=False,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=uuid4().hex)
                _, _, messages = await _root_response(session, conversation, chunks=1)
                command = await _command(
                    session,
                    conversation,
                    owner="admit-denied",
                    reply_id=messages[0].id,
                )
            assert (
                await SqlAlchemyRegenerationRepository(database.session_factory).accept(
                    command.id, "admit-denied"
                )
                == RegenerationAdmission.ACCEPTED
            )

            class DeniedLimiter:
                async def check(
                    self,
                    operation: RateLimitOperation,
                    rules: tuple[RateLimitRule, ...],
                ) -> RateLimitDecision:
                    assert operation == RateLimitOperation.GENERATION
                    assert rules
                    return RateLimitDecision(False, retry_after_seconds=1)

                async def is_ready(self) -> bool:
                    return True

                async def aclose(self) -> None:
                    return None

            class Generator:
                provider_id = ProviderId.OPENAI
                model = "spec036-model"
                capabilities = ProviderCapabilities(
                    True, True, "max_tokens", True, True
                )

                def __init__(self) -> None:
                    self.calls = 0

                async def generate(self, request: GenerationRequest) -> ProviderResult:
                    del request
                    self.calls += 1
                    raise AssertionError(
                        "current admission denial must precede provider I/O"
                    )

                async def aclose(self) -> None:
                    return None

            class Presence:
                def __init__(self) -> None:
                    self.calls = 0

                async def send_chat_action(
                    self, request: SendChatActionRequest
                ) -> None:
                    del request
                    self.calls += 1

            generator = Generator()
            presence = Presence()
            assert (
                await plan_once(
                    settings,
                    database,
                    owner="regen-denied",
                    primary_provider=generator,
                    rate_limiter=DeniedLimiter(),
                    presence_adapter=presence,
                )
                == 1
            )
            assert generator.calls == 0
            assert presence.calls == 0
            async with database.session_factory() as session:
                job = await session.scalar(
                    select(ResponsePlanningJobModel).where(
                        ResponsePlanningJobModel.source_command_job_id == command.id
                    )
                )
                assert job is not None
                assert job.status == PlanningJobStatus.PENDING
                assert (
                    await session.scalar(
                        select(func.count(ResponsePlanModel.id)).where(
                            ResponsePlanModel.planning_job_id == job.id
                        )
                    )
                    == 0
                )
            assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "success_race",
        "rejected",
        "rejected_race",
        "unknown",
        "unknown_race",
        "not_modified",
    ],
)
def test_durable_edit_outcomes_are_mutually_exclusive_and_io_is_session_free(
    mode: str,
) -> None:
    class Adapter:
        def __init__(self, database: Database, conversation_id: str) -> None:
            self.database = database
            self.conversation_id = conversation_id
            self.edit_calls = 0
            self.send_calls = 0
            self.edit_entered = asyncio.Event()
            self.release_edit = asyncio.Event()

        @property
        def capabilities(self) -> frozenset[PlatformCapability]:
            return frozenset(
                {PlatformCapability.EDIT_TEXT, PlatformCapability.SEND_TEXT}
            )

        async def edit_text(self, request: EditTextRequest) -> SentMessage:
            assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
            self.edit_calls += 1
            if mode.endswith("_race"):
                self.edit_entered.set()
                await self.release_edit.wait()
            if mode in {"rejected", "rejected_race"}:
                raise PlatformAdapterError(
                    PlatformErrorCategory.INVALID_REQUEST,
                    "editMessageText",
                    telegram_error_code=400,
                    edit_target_rejected=True,
                    delivery_certainty=DeliveryCertainty.REJECTED,
                )
            if mode in {"unknown", "unknown_race"}:
                raise PlatformAdapterError(
                    PlatformErrorCategory.TIMEOUT,
                    "editMessageText",
                    delivery_certainty=DeliveryCertainty.UNKNOWN,
                )
            if mode == "not_modified":
                raise PlatformAdapterError(
                    PlatformErrorCategory.INVALID_REQUEST,
                    "editMessageText",
                    telegram_error_code=400,
                    edit_not_modified=True,
                    delivery_certainty=DeliveryCertainty.REJECTED,
                )
            return SentMessage(
                Platform.TELEGRAM,
                request.platform_message_id,
                request.conversation_id,
                "bot",
                None,
                datetime.now(UTC),
            )

        async def send_text(self, request: SendTextRequest) -> SentMessage:
            assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
            self.send_calls += 1
            return SentMessage(
                Platform.TELEGRAM,
                f"fallback-{uuid4()}",
                request.conversation_id,
                "bot",
                None,
                datetime.now(UTC),
            )

        async def send_sticker(self, request: object) -> SentMessage:
            del request
            raise AssertionError("sticker delivery was not expected")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token=SecretStr("fake-token"),
            telegram_platform_connection_id=uuid4(),
            outbound_delivery_enabled=True,
            rate_limit_enabled=False,
        )
        database = Database(settings)
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(text("TRUNCATE assistants CASCADE"))
            suffix = uuid4().hex
            async with database.session_factory() as session, session.begin():
                conversation, _ = await _authority(session, suffix=suffix)
                source, _, messages = await _root_response(
                    session, conversation, chunks=1
                )
                record = await _processing_record(session, conversation, source)
                job = ResponsePlanningJobModel(
                    conversation_processing_record_id=record.id,
                    conversation_id=conversation.id,
                    message_id=source.id,
                    prompt_version="spec-036-test",
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
                    text="Replacement",
                    reply_to_message_id=source.id,
                    mention_participant_ids=[],
                    confidence=1,
                    prompt_version="spec-036-test",
                    schema_version="response-plan-v1",
                )
                session.add(plan)
                await session.flush()
                edit = OutboundActionModel(
                    response_plan_id=plan.id,
                    conversation_id=conversation.id,
                    sequence_number=1,
                    sequence_count=2,
                    idempotency_key=uuid4().hex,
                    kind=OutboundActionKind.EDIT_TEXT,
                    status=OutboundActionStatus.PENDING,
                    edit_target_message_id=messages[0].id,
                    edit_target_platform_message_id=messages[0].platform_message_id,
                    text="Replacement",
                    mention_participant_ids=[],
                )
                session.add(edit)
                await session.flush()
                fallback = OutboundActionModel(
                    response_plan_id=plan.id,
                    conversation_id=conversation.id,
                    sequence_number=2,
                    sequence_count=2,
                    idempotency_key=uuid4().hex,
                    kind=OutboundActionKind.TEXT,
                    status=OutboundActionStatus.FALLBACK_BLOCKED,
                    fallback_for_action_id=edit.id,
                    reply_to_message_id=source.id,
                    text="Replacement",
                    mention_participant_ids=[],
                )
                session.add(fallback)
                await session.flush()
                edit_id, fallback_id = edit.id, fallback.id
                target_message_id = messages[0].id
                platform_conversation_id = conversation.platform_conversation_id
            adapter = Adapter(database, platform_conversation_id)
            if mode.endswith("_race"):
                first = asyncio.create_task(
                    deliver_once(settings, database, adapter=adapter)  # type: ignore[arg-type]
                )
                await adapter.edit_entered.wait()
                assert await deliver_once(settings, database, adapter=adapter) == 0  # type: ignore[arg-type]
                adapter.release_edit.set()
                assert await first == 1
            else:
                assert await deliver_once(settings, database, adapter=adapter) == 1  # type: ignore[arg-type]
            if mode in {"rejected", "rejected_race"}:
                assert await deliver_once(settings, database, adapter=adapter) == 1  # type: ignore[arg-type]
            async with database.session_factory() as session:
                edit_row = await session.get(OutboundActionModel, edit_id)
                fallback_row = await session.get(OutboundActionModel, fallback_id)
                assert edit_row is not None and fallback_row is not None
                assert adapter.edit_calls == 1
                if mode in {"success", "success_race", "not_modified"}:
                    assert edit_row.status == OutboundActionStatus.DELIVERED
                    assert fallback_row.status == OutboundActionStatus.SKIPPED
                    assert adapter.send_calls == 0
                elif mode in {"rejected", "rejected_race"}:
                    assert edit_row.status == OutboundActionStatus.SKIPPED
                    assert fallback_row.status == OutboundActionStatus.DELIVERED
                    assert adapter.send_calls == 1
                else:
                    assert edit_row.status == OutboundActionStatus.DELIVERY_UNKNOWN
                    assert fallback_row.status == OutboundActionStatus.FALLBACK_BLOCKED
                    assert adapter.send_calls == 0
            if mode == "success":
                redacted_at = datetime.now(UTC)
                async with database.session_factory() as session, session.begin():
                    target = await session.get(MessageModel, target_message_id)
                    edit_row = await session.get(OutboundActionModel, edit_id)
                    fallback_row = await session.get(OutboundActionModel, fallback_id)
                    assert target is not None
                    assert edit_row is not None and fallback_row is not None
                    target.text = None
                    target.content_redacted_at = redacted_at
                    edit_row.text = None
                    edit_row.payload_redacted_at = redacted_at
                    fallback_row.text = None
                    fallback_row.payload_redacted_at = redacted_at
            assert database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        finally:
            await database.stop()

    asyncio.run(scenario())
