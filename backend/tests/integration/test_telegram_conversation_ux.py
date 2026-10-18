"""Live PostgreSQL and fake-Telegram proof for SPEC-034."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.context import ContextReply
from app.application.ports.platform import (
    PlatformAdapterError,
    PlatformCapability,
    PlatformErrorCategory,
    SendStickerRequest,
    SendTextRequest,
    SentMessage,
)
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.media import MediaKind
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.persistence import (
    AssistantStatus,
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
from app.domain.planning import PlanReasonCode
from app.infrastructure.database.context import SqlAlchemyReplyContextResolver
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    KnowledgeBaseModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.outbound import SqlAlchemyOutboundRepository
from app.runtime.outbound_delivery_worker import consume_once

pytestmark = [
    pytest.mark.integration,
    pytest.mark.telegram_conversation_ux_integration,
]


async def _conversation(
    session: AsyncSession,
    tenant: ControlTenantModel,
    assistant: AssistantModel,
    *,
    suffix: str,
) -> ConversationModel:
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
    return conversation


async def _participant_message(
    session: AsyncSession,
    conversation: ConversationModel,
    *,
    platform_id: str,
    text_value: str | None,
    reply_platform_id: str | None = None,
    reply_id: UUID | None = None,
    redacted: bool = False,
    message_type: MessageType = MessageType.TEXT,
    metadata: dict[str, str] | None = None,
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
        message_type=message_type,
        text=text_value,
        reply_to_message_id=reply_id,
        reply_to_platform_message_id=reply_platform_id,
        processing_status=MessageProcessingStatus.PROCESSED,
        platform_sent_at=datetime.now(UTC),
        content_redacted_at=datetime.now(UTC) if redacted else None,
        metadata_=metadata or {},
    )
    session.add(message)
    await session.flush()
    return message


async def _plan(
    session: AsyncSession,
    conversation: ConversationModel,
    source: MessageModel,
    *,
    text_value: str,
    reply_to: UUID | None = None,
) -> ResponsePlanModel:
    connection_id = conversation.platform_connection_id
    update = IncomingPlatformUpdateModel(
        platform_connection_id=connection_id,
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
        message_id=source.id,
    )
    session.add(record)
    await session.flush()
    job = ResponsePlanningJobModel(
        conversation_processing_record_id=record.id,
        conversation_id=conversation.id,
        message_id=source.id,
        prompt_version="spec-034-test",
        response_schema_version="response-plan-v2",
    )
    session.add(job)
    await session.flush()
    plan = ResponsePlanModel(
        planning_job_id=job.id,
        should_respond=True,
        reason_code=PlanReasonCode.ANSWER,
        text=text_value,
        reply_to_message_id=reply_to,
        mention_participant_ids=[],
        confidence=1,
        prompt_version="spec-034-test",
        schema_version="response-plan-v2",
    )
    session.add(plan)
    await session.flush()
    return plan


async def _authority_scenario() -> None:
    settings = Settings(_env_file=None, environment="test")
    database = Database(settings)
    await database.start()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text("TRUNCATE assistants CASCADE"))
        async with database.session_factory() as session:
            initial_memory_count = await session.scalar(
                select(func.count(MemoryItemModel.id))
            )
            initial_knowledge_count = await session.scalar(
                select(func.count(KnowledgeBaseModel.id))
            )
            initial_media_count = await session.scalar(
                select(func.count(MessageMediaModel.id))
            )
        async with database.session_factory() as session, session.begin():
            authority_suffix = uuid4().hex
            tenant = ControlTenantModel(
                slug=f"spec034-{authority_suffix}", name="SPEC 034"
            )
            foreign_tenant = ControlTenantModel(
                slug=f"spec034-foreign-{authority_suffix}", name="Foreign"
            )
            session.add_all([tenant, foreign_tenant])
            await session.flush()
            assistant = AssistantModel(
                tenant_id=tenant.id,
                slug=f"assistant-{authority_suffix}",
                name="Assistant",
                status=AssistantStatus.ACTIVE,
            )
            sibling = AssistantModel(
                tenant_id=tenant.id,
                slug=f"sibling-{authority_suffix}",
                name="Sibling",
                status=AssistantStatus.ACTIVE,
            )
            foreign_assistant = AssistantModel(
                tenant_id=foreign_tenant.id,
                slug=f"foreign-{authority_suffix}",
                name="Foreign",
                status=AssistantStatus.ACTIVE,
            )
            session.add_all([assistant, sibling, foreign_assistant])
            await session.flush()
            conversation = await _conversation(
                session, tenant, assistant, suffix=f"canonical-{authority_suffix}"
            )
            sibling_conversation = await _conversation(
                session, tenant, sibling, suffix=f"sibling-{authority_suffix}"
            )
            foreign_conversation = await _conversation(
                session,
                foreign_tenant,
                foreign_assistant,
                suffix=f"foreign-{authority_suffix}",
            )
            target = await _participant_message(
                session,
                conversation,
                platform_id="target",
                text_value="authoritative target",
            )
            current = await _participant_message(
                session,
                conversation,
                platform_id="current",
                text_value="what about this?",
                reply_platform_id="target",
                reply_id=target.id,
            )
            unknown = await _participant_message(
                session,
                conversation,
                platform_id="unknown-current",
                text_value="unknown",
                reply_platform_id="not-local",
            )
            erased_target = await _participant_message(
                session,
                conversation,
                platform_id="erased",
                text_value=None,
                redacted=True,
            )
            erased = await _participant_message(
                session,
                conversation,
                platform_id="erased-current",
                text_value="erased?",
                reply_platform_id="erased",
                reply_id=erased_target.id,
            )
            await _participant_message(
                session,
                sibling_conversation,
                platform_id="sibling-target",
                text_value="sibling secret",
            )
            sibling_probe = await _participant_message(
                session,
                conversation,
                platform_id="sibling-probe",
                text_value="probe",
                reply_platform_id="sibling-target",
            )
            await _participant_message(
                session,
                foreign_conversation,
                platform_id="foreign-target",
                text_value="foreign secret",
            )
            foreign_probe = await _participant_message(
                session,
                conversation,
                platform_id="foreign-probe",
                text_value="probe",
                reply_platform_id="foreign-target",
            )
            expired_target = await _participant_message(
                session,
                conversation,
                platform_id="expired-target",
                text_value="expired secret",
            )
            expired_target.platform_sent_at = None
            expired_target.created_at = datetime.now(UTC) - timedelta(days=31)
            expired_probe = await _participant_message(
                session,
                conversation,
                platform_id="expired-probe",
                text_value="probe",
                reply_platform_id="expired-target",
                reply_id=expired_target.id,
            )
            media_target = await _participant_message(
                session,
                conversation,
                platform_id="media-target",
                text_value="retained media caption",
                message_type=MessageType.PHOTO,
                metadata={"content_provenance": "media_caption"},
            )
            session.add(
                MessageMediaModel(
                    message_id=media_target.id,
                    conversation_id=conversation.id,
                    kind=MediaKind.PHOTO,
                    file_id="synthetic_file",
                    file_unique_id="synthetic_unique",
                    mime_type="image/jpeg",
                    width=640,
                    height=480,
                    caption="retained media caption",
                )
            )
            media_reply = await _participant_message(
                session,
                conversation,
                platform_id="media-reply",
                text_value="about that photo",
                reply_platform_id="media-target",
                reply_id=media_target.id,
            )

            plan = await _plan(
                session,
                conversation,
                current,
                text_value="whole authoritative assistant response " * 80,
                reply_to=current.id,
            )
            first = OutboundActionModel(
                response_plan_id=plan.id,
                conversation_id=conversation.id,
                sequence_number=1,
                sequence_count=2,
                idempotency_key=uuid4().hex * 2,
                kind=OutboundActionKind.TEXT,
                status=OutboundActionStatus.DELIVERED,
                text="first chunk",
                reply_to_message_id=current.id,
                mention_participant_ids=[],
            )
            second = OutboundActionModel(
                response_plan_id=plan.id,
                conversation_id=conversation.id,
                sequence_number=2,
                sequence_count=2,
                idempotency_key=uuid4().hex * 2,
                kind=OutboundActionKind.TEXT,
                status=OutboundActionStatus.DELIVERED,
                text="second chunk",
                mention_participant_ids=[],
            )
            session.add_all([first, second])
            await session.flush()
            bot_first = MessageModel(
                conversation_id=conversation.id,
                platform_message_id="bot-first",
                outbound_action_id=first.id,
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                text=first.text,
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_sent_at=datetime.now(UTC),
            )
            bot_second = MessageModel(
                conversation_id=conversation.id,
                platform_message_id="bot-second",
                outbound_action_id=second.id,
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                text=second.text,
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_sent_at=datetime.now(UTC),
            )
            session.add_all([bot_first, bot_second])
            await session.flush()
            bot_reply = await _participant_message(
                session,
                conversation,
                platform_id="bot-reply",
                text_value="explain",
                reply_platform_id="bot-second",
                reply_id=bot_second.id,
            )
            ids = {
                "current": current.id,
                "unknown": unknown.id,
                "erased": erased.id,
                "sibling": sibling_probe.id,
                "foreign": foreign_probe.id,
                "expired": expired_probe.id,
                "media": media_reply.id,
                "bot": bot_reply.id,
                "plan": plan.id,
                "bot_first": bot_first.id,
                "bot_second": bot_second.id,
            }

        resolver = SqlAlchemyReplyContextResolver(
            database.session_factory, max_age_days=30
        )
        resolved = await resolver.resolve(ids["current"], now=datetime.now(UTC))
        assert isinstance(resolved, ContextReply)
        assert resolved.text == "authoritative target"
        assert await resolver.resolve(ids["unknown"], now=datetime.now(UTC)) is None
        assert await resolver.resolve(ids["erased"], now=datetime.now(UTC)) is None
        assert await resolver.resolve(ids["sibling"], now=datetime.now(UTC)) is None
        assert await resolver.resolve(ids["foreign"], now=datetime.now(UTC)) is None
        assert await resolver.resolve(ids["expired"], now=datetime.now(UTC)) is None
        media = await resolver.resolve(ids["media"], now=datetime.now(UTC))
        assert media is not None
        assert media.text == "retained media caption"
        assert media.content_provenance == "media_caption"
        bot = await resolver.resolve(ids["bot"], now=datetime.now(UTC))
        assert bot is not None
        assert bot.response_plan_id == ids["plan"]
        assert len(bot.text) == 1200 and bot.truncated
        assert set(bot.related_message_ids) == {ids["bot_first"], ids["bot_second"]}

        async with database.session_factory() as session:
            assert await session.scalar(select(func.count(MemoryItemModel.id))) == (
                initial_memory_count
            )
            assert await session.scalar(select(func.count(KnowledgeBaseModel.id))) == (
                initial_knowledge_count
            )
            assert await session.scalar(select(func.count(MessageMediaModel.id))) == (
                initial_media_count + 1
            )

        async with database.session_factory() as session, session.begin():
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    cross = await _participant_message(
                        session,
                        conversation,
                        platform_id="cross-edge",
                        text_value="cross",
                        reply_id=ids["bot_first"],
                    )
                    cross.conversation_id = sibling_conversation.id
                    await session.flush()
    finally:
        await database.stop()


def test_reply_authority_retention_and_split_assistant_resolution() -> None:
    asyncio.run(_authority_scenario())


class _FallbackAdapter:
    def __init__(self, database: Database, *, ambiguous: bool = False) -> None:
        self.database = database
        self.ambiguous = ambiguous
        self.requests: list[SendTextRequest] = []

    @property
    def capabilities(self) -> frozenset[PlatformCapability]:
        return frozenset({PlatformCapability.SEND_TEXT})

    async def send_text(self, request: SendTextRequest) -> SentMessage:
        assert self.database.engine.pool.checkedout() == 0  # type: ignore[attr-defined]
        self.requests.append(request)
        if len(self.requests) == 1:
            if self.ambiguous:
                raise PlatformAdapterError(
                    PlatformErrorCategory.TIMEOUT,
                    "sendMessage",
                    delivery_certainty=DeliveryCertainty.UNKNOWN,
                )
            raise PlatformAdapterError(
                PlatformErrorCategory.INVALID_REQUEST,
                "sendMessage",
                telegram_error_code=400,
                reply_target_rejected=True,
                delivery_certainty=DeliveryCertainty.REJECTED,
            )
        return SentMessage(
            Platform.TELEGRAM,
            f"sent-{len(self.requests)}",
            request.conversation_id,
            "bot",
            request.message_thread_id,
            datetime.now(UTC),
        )

    async def send_sticker(self, request: SendStickerRequest) -> SentMessage:
        raise AssertionError(f"unexpected sticker: {request.asset_reference}")

    async def aclose(self) -> None:
        return None


async def _sequence_scenario() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        telegram_enabled=True,
        telegram_bot_token="spec-034-fake-token",
        telegram_platform_connection_id=uuid4(),
        outbound_delivery_enabled=True,
    )
    database = Database(settings)
    await database.start()
    try:
        async with database.engine.begin() as connection:
            await connection.execute(text("TRUNCATE assistants CASCADE"))
        async with database.session_factory() as session, session.begin():
            sequence_suffix = uuid4().hex
            tenant = ControlTenantModel(
                slug=f"sequence-{sequence_suffix}", name="Sequence"
            )
            session.add(tenant)
            await session.flush()
            assistant = AssistantModel(
                tenant_id=tenant.id,
                slug=f"sequence-{sequence_suffix}",
                name="Sequence",
                status=AssistantStatus.ACTIVE,
            )
            session.add(assistant)
            await session.flush()
            conversation = await _conversation(
                session, tenant, assistant, suffix=f"sequence-{sequence_suffix}"
            )
            source = await _participant_message(
                session,
                conversation,
                platform_id="source",
                text_value="source",
            )
            plan = await _plan(
                session, conversation, source, text_value="one two three"
            )
            actions = [
                OutboundActionModel(
                    response_plan_id=plan.id,
                    conversation_id=conversation.id,
                    sequence_number=number,
                    sequence_count=3,
                    idempotency_key=uuid4().hex * 2,
                    kind=OutboundActionKind.TEXT,
                    text=str(number),
                    mention_participant_ids=[],
                )
                for number in (1, 2, 3)
            ]
            session.add_all(actions)
            await session.flush()
            action_ids = [item.id for item in actions]

        first_repo = SqlAlchemyOutboundRepository(database.session_factory)
        second_repo = SqlAlchemyOutboundRepository(database.session_factory)
        first_claim_barrier = asyncio.Barrier(3)

        async def coordinated_claim(
            repository: SqlAlchemyOutboundRepository, worker: str
        ) -> list[OutboundActionModel]:
            await first_claim_barrier.wait()
            return await repository.claim(worker, 1, 60)

        first_claim_tasks = (
            asyncio.create_task(coordinated_claim(first_repo, "worker-a")),
            asyncio.create_task(coordinated_claim(second_repo, "worker-b")),
        )
        await first_claim_barrier.wait()
        claims = await asyncio.gather(*first_claim_tasks)
        claimed = [item for group in claims for item in group]
        assert [item.sequence_number for item in claimed] == [1]
        owner = claimed[0].lease_owner
        assert owner is not None

        transition_barrier = asyncio.Barrier(3)

        async def finalize_first() -> bool:
            await transition_barrier.wait()
            return await first_repo.finalize(
                action_ids[0],
                owner,
                OutboundActionStatus.DELIVERED,
                DeliveryAttemptStatus.CONFIRMED,
                DeliveryCertainty.CONFIRMED,
            )

        async def race_second_claim() -> list[OutboundActionModel]:
            await transition_barrier.wait()
            return await second_repo.claim("worker-c-racing", 1, 60)

        transition_tasks = (
            asyncio.create_task(finalize_first()),
            asyncio.create_task(race_second_claim()),
        )
        await transition_barrier.wait()
        finalized, second_claim = await asyncio.gather(*transition_tasks)
        assert finalized
        if not second_claim:
            second_claim = await first_repo.claim("worker-c", 1, 60)
        assert [item.sequence_number for item in second_claim] == [2]
        second_owner = second_claim[0].lease_owner
        assert second_owner is not None
        assert await first_repo.mark_external_started(action_ids[1], second_owner)
        async with database.session_factory() as session, session.begin():
            leased = await session.get(OutboundActionModel, action_ids[1])
            assert leased is not None
            leased.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert await first_repo.claim("worker-d", 2, 60) == []
        assert await first_repo.claim("worker-e", 2, 60) == []
        async with database.session_factory() as session:
            prefix = list(
                await session.scalars(
                    select(OutboundActionModel)
                    .where(OutboundActionModel.response_plan_id == plan.id)
                    .order_by(OutboundActionModel.sequence_number)
                )
            )
            assert [item.id for item in prefix] == action_ids
            assert [item.status.value for item in prefix] == [
                "delivered",
                "delivery_unknown",
                "pending",
            ]

        async with database.session_factory() as session, session.begin():
            fallback_plan = await _plan(
                session,
                conversation,
                source,
                text_value="fallback",
                reply_to=source.id,
            )
            fallback_action = OutboundActionModel(
                response_plan_id=fallback_plan.id,
                conversation_id=conversation.id,
                sequence_number=1,
                sequence_count=1,
                idempotency_key=uuid4().hex * 2,
                kind=OutboundActionKind.TEXT,
                text="fallback",
                reply_to_message_id=source.id,
                mention_participant_ids=[],
            )
            session.add(fallback_action)
            await session.flush()
            fallback_id = fallback_action.id
        fallback = _FallbackAdapter(database)
        assert await consume_once(settings, database, fallback) == 1  # type: ignore[arg-type]
        assert [item.reply_to_message_id for item in fallback.requests] == [
            "source",
            None,
        ]
        async with database.session_factory() as session:
            attempt = await session.scalar(
                select(OutboundDeliveryAttemptModel).where(
                    OutboundDeliveryAttemptModel.outbound_action_id == fallback_id
                )
            )
            assert attempt is not None and attempt.reply_fallback_used
            assert attempt.reply_fallback_error_code == "400"

        async with database.session_factory() as session, session.begin():
            ambiguous_plan = await _plan(
                session,
                conversation,
                source,
                text_value="ambiguous",
                reply_to=source.id,
            )
            ambiguous_action = OutboundActionModel(
                response_plan_id=ambiguous_plan.id,
                conversation_id=conversation.id,
                sequence_number=1,
                sequence_count=1,
                idempotency_key=uuid4().hex * 2,
                kind=OutboundActionKind.TEXT,
                text="ambiguous",
                reply_to_message_id=source.id,
                mention_participant_ids=[],
            )
            session.add(ambiguous_action)
            await session.flush()
            ambiguous_id = ambiguous_action.id
        ambiguous = _FallbackAdapter(database, ambiguous=True)
        assert await consume_once(settings, database, ambiguous) == 1  # type: ignore[arg-type]
        assert len(ambiguous.requests) == 1
        async with database.session_factory() as session:
            action = await session.get(OutboundActionModel, ambiguous_id)
            attempt = await session.scalar(
                select(OutboundDeliveryAttemptModel).where(
                    OutboundDeliveryAttemptModel.outbound_action_id == ambiguous_id
                )
            )
            assert action is not None
            assert action.status == OutboundActionStatus.DELIVERY_UNKNOWN
            assert attempt is not None and not attempt.reply_fallback_used
    finally:
        await database.stop()


def test_sequence_claim_order_recovery_fallback_and_session_fencing() -> None:
    asyncio.run(_sequence_scenario())
