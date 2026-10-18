"""PostgreSQL proof for the FR-08 outbound teasing recheck gate."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.application.ports.platform import PlatformCapability, SentMessage
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
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
from app.domain.safety import (
    InteractionKind,
    SafetyOutcome,
    SafetyPolicyVersion,
    SafetyReasonCode,
    SafetyStage,
)
from app.domain.tenancy import LEGACY_TENANT_ID
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
    SafetyPolicyDecisionModel,
)
from app.infrastructure.database.personality import ensure_conversation_configuration
from app.runtime.outbound_delivery_worker import _safety_recheck, consume_once


async def _truncate(database: Database) -> None:
    async with database.engine.begin() as connection:
        await connection.execute(text("TRUNCATE assistants CASCADE"))


async def _seed_base(
    database: Database,
    *,
    target_count: int = 1,
    interaction_kind: InteractionKind = InteractionKind.TEASING,
    cap: int = 3,
    revision: bool = True,
    tag: str = "",
    platform_conversation_id: str | None = None,
) -> tuple[UUID, UUID, UUID, list[UUID]]:
    """Seed an assistant, group conversation, targets, and one pending tease."""
    async with database.session_factory() as session:
        async with session.begin():
            if await session.get(ControlTenantModel, LEGACY_TENANT_ID) is None:
                session.add(
                    ControlTenantModel(
                        id=LEGACY_TENANT_ID,
                        slug="legacy-default",
                        name="Legacy default",
                    )
                )
                await session.flush()
            assistant = AssistantModel(
                tenant_id=LEGACY_TENANT_ID,
                slug=f"safety-{tag}",
                name=f"test{tag}",
                status=AssistantStatus.ACTIVE,
            )
            session.add(assistant)
            await session.flush()
            connection = PlatformConnectionModel(
                tenant_id=LEGACY_TENANT_ID,
                assistant_id=assistant.id,
                platform=Platform.TELEGRAM,
                external_bot_id=f"bot-{tag}",
                status=PlatformConnectionStatus.ACTIVE,
            )
            session.add(connection)
            await session.flush()
            conversation = ConversationModel(
                platform_connection_id=connection.id,
                platform_conversation_id=platform_conversation_id
                or f"4000000{tag:>3}".replace(" ", "0"),
                conversation_type=ConversationType.GROUP,
                status=ConversationStatus.ACTIVE,
                response_mode=ResponseMode.AMBIENT_SELECTIVE,
            )
            session.add(conversation)
            await session.flush()
            participants: list[ParticipantModel] = []
            for index in range(target_count):
                participant = ParticipantModel(
                    conversation_id=conversation.id,
                    platform_user_id=f"user-{tag}-{index}",
                    username=f"u{index}",
                    display_name="U",
                    teasing_allowed=True,
                )
                session.add(participant)
                participants.append(participant)
            await session.flush()
            incoming = MessageModel(
                conversation_id=conversation.id,
                participant_id=participants[0].id,
                platform_message_id=f"42-{tag}",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="hi",
                processing_status=MessageProcessingStatus.PROCESSED,
                platform_thread_id="thread-1",
            )
            session.add(incoming)
            await session.flush()
            update = IncomingPlatformUpdateModel(
                platform_connection_id=connection.id,
                platform=Platform.TELEGRAM,
                platform_update_id=f"update-{tag}",
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
                message_id=incoming.id,
            )
            session.add(record)
            await session.flush()
            job = ResponsePlanningJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation.id,
                message_id=incoming.id,
                prompt_version="test",
                response_schema_version="test",
            )
            session.add(job)
            await session.flush()
            target_ids = [participant.id for participant in participants]
            plan = ResponsePlanModel(
                planning_job_id=job.id,
                should_respond=True,
                reason_code=PlanReasonCode.ANSWER,
                text="ha",
                reply_to_message_id=incoming.id,
                mention_participant_ids=[str(target_ids[0])],
                confidence=1,
                prompt_version="test",
                schema_version="test",
                interaction_kind=interaction_kind,
                teasing_target_participant_ids=[
                    str(target_id) for target_id in target_ids
                ],
            )
            session.add(plan)
            await session.flush()
            action = OutboundActionModel(
                response_plan_id=plan.id,
                conversation_id=conversation.id,
                sequence_number=1,
                idempotency_key=f"{tag or 'a'}".ljust(64, "a"),
                kind=OutboundActionKind.TEXT,
                reply_to_message_id=incoming.id,
                message_thread_id="thread-1",
                text="ha",
                mention_participant_ids=[str(target_ids[0])],
            )
            session.add(action)
            await session.flush()
            if revision:
                current = await ensure_conversation_configuration(
                    session, assistant, conversation
                )
                current.teasing_cap = cap
            return connection.id, conversation.id, action.id, target_ids


async def _set_target_flag(
    database: Database,
    target_id: UUID,
    *,
    teasing_allowed: bool | None = None,
    protected: bool = False,
    privacy_deleted: bool = False,
) -> None:
    async with database.session_factory() as session:
        async with session.begin():
            participant = await session.get(ParticipantModel, target_id)
            assert participant is not None
            if teasing_allowed is not None:
                participant.teasing_allowed = teasing_allowed
            participant.protected_at = datetime.now(UTC) if protected else None
            participant.privacy_deleted_at = (
                datetime.now(UTC) if privacy_deleted else None
            )


async def _seed_delivered(
    database: Database,
    *,
    connection_id: UUID,
    conversation_id: UUID,
    target_ids: list[UUID],
    interaction_kind: InteractionKind = InteractionKind.TEASING,
    tag: str,
) -> None:
    """Insert one already-delivered action toward the given targets."""
    async with database.session_factory() as session:
        async with session.begin():
            update = IncomingPlatformUpdateModel(
                platform_connection_id=connection_id,
                platform=Platform.TELEGRAM,
                platform_update_id=f"delivered-{tag}",
                update_type="message",
                ingress_source=IngressSource.WEBHOOK,
                raw_payload={},
                received_at=datetime.now(UTC),
            )
            session.add(update)
            await session.flush()
            delivered = MessageModel(
                conversation_id=conversation_id,
                platform_message_id=f"delivered-message-{tag}",
                direction=MessageDirection.OUTGOING,
                message_type=MessageType.TEXT,
                text=None,
                processing_status=MessageProcessingStatus.PROCESSED,
            )
            session.add(delivered)
            await session.flush()
            record = ConversationProcessingRecordModel(
                incoming_update_id=update.id,
                outcome=ProcessingOutcome.MESSAGE_CREATED,
                conversation_id=conversation_id,
                message_id=delivered.id,
            )
            session.add(record)
            await session.flush()
            job = ResponsePlanningJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation_id,
                message_id=delivered.id,
                prompt_version="test",
                response_schema_version="test",
            )
            session.add(job)
            await session.flush()
            plan = ResponsePlanModel(
                planning_job_id=job.id,
                should_respond=True,
                reason_code=PlanReasonCode.ANSWER,
                text=None,
                mention_participant_ids=[],
                confidence=1,
                prompt_version="test",
                schema_version="test",
                interaction_kind=interaction_kind,
                teasing_target_participant_ids=[
                    str(target_id) for target_id in target_ids
                ],
            )
            session.add(plan)
            await session.flush()
            session.add(
                OutboundActionModel(
                    response_plan_id=plan.id,
                    conversation_id=conversation_id,
                    sequence_number=1,
                    idempotency_key=f"{tag}".ljust(64, "0"),
                    kind=OutboundActionKind.TEXT,
                    text="ha",
                    mention_participant_ids=[],
                    status=OutboundActionStatus.DELIVERED,
                    completed_at=datetime.now(UTC),
                )
            )


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_ignores_non_teasing_plans() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, _ = await _seed_base(
                database, interaction_kind=InteractionKind.NEUTRAL
            )
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert await _safety_recheck(database, action, settings) is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_opted_out_when_no_targets() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, _ = await _seed_base(database)
            async with database.session_factory() as session:
                async with session.begin():
                    action = await session.get(OutboundActionModel, action_id)
                    assert action is not None
                    plan = await session.get(ResponsePlanModel, action.response_plan_id)
                    assert plan is not None
                    plan.teasing_target_participant_ids = []
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TEASING_TARGET_OPTED_OUT
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_opted_out_when_target_missing_from_conversation() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, _ = await _seed_base(database)
            async with database.session_factory() as session:
                async with session.begin():
                    action = await session.get(OutboundActionModel, action_id)
                    assert action is not None
                    plan = await session.get(ResponsePlanModel, action.response_plan_id)
                    assert plan is not None
                    plan.teasing_target_participant_ids = [str(uuid4())]
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TEASING_TARGET_OPTED_OUT
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_opted_out_when_target_privacy_deleted() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, target_ids = await _seed_base(database)
            await _set_target_flag(database, target_ids[0], privacy_deleted=True)
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TEASING_TARGET_OPTED_OUT
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_opted_out_when_target_disallows_teasing() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, target_ids = await _seed_base(database)
            await _set_target_flag(database, target_ids[0], teasing_allowed=False)
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TEASING_TARGET_OPTED_OUT
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_target_protected_blocks_delivery() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, target_ids = await _seed_base(database)
            await _set_target_flag(database, target_ids[0], protected=True)
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TARGET_PROTECTED
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_disabled_when_safety_moderation_off() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            safety_moderation_enabled=False,
        )
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, _ = await _seed_base(database, cap=0)
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert await _safety_recheck(database, action, settings) is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_allows_below_cap_and_ignores_unrelated_deliveries() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            safety_moderation_enabled=True,
        )
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            (
                main_connection,
                main_conversation,
                action_id,
                target_ids,
            ) = await _seed_base(database, cap=1, tag="main")
            (
                other_connection,
                other_conversation,
                _,
                other_target_ids,
            ) = await _seed_base(database, cap=1, tag="other")
            await _seed_delivered(
                database,
                connection_id=other_connection,
                conversation_id=other_conversation,
                target_ids=other_target_ids,
                tag="other-conversation-tease",
            )
            await _seed_delivered(
                database,
                connection_id=main_connection,
                conversation_id=main_conversation,
                target_ids=[target_ids[0]],
                interaction_kind=InteractionKind.NEUTRAL,
                tag="neutral-toward-target",
            )
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert await _safety_recheck(database, action, settings) is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_blocks_at_cap() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            safety_moderation_enabled=True,
        )
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            connection, conversation, action_id, target_ids = await _seed_base(
                database, cap=1, tag="cap"
            )
            await _seed_delivered(
                database,
                connection_id=connection,
                conversation_id=conversation,
                target_ids=[target_ids[0]],
                tag="one-tease",
            )
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert (
                    await _safety_recheck(database, action, settings)
                    == SafetyReasonCode.TEASING_CAP_EXCEEDED
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_recheck_no_revision_means_no_cap() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            safety_moderation_enabled=True,
        )
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            _, _, action_id, _ = await _seed_base(database, revision=False)
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert await _safety_recheck(database, action, settings) is None
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.safety_integration
@pytest.mark.delivery_integration
def test_worker_skips_at_cap_and_records_pre_delivery_silent() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.requests: list[object] = []

        @property
        def capabilities(self) -> frozenset[PlatformCapability]:
            return frozenset({PlatformCapability.SEND_TEXT})

        async def send_text(self, request: object) -> SentMessage:
            self.requests.append(request)
            return SentMessage(
                Platform.TELEGRAM,
                "900",
                "chat-1",
                "bot-1",
                "thread-1",
                datetime.now(UTC),
            )

        async def send_sticker(self, request: object) -> SentMessage:
            raise AssertionError("sticker was not expected")

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            telegram_enabled=True,
            telegram_bot_token="fake-token",
            telegram_platform_connection_id=uuid4(),
            telegram_delivery_mode="polling",
            outbound_delivery_enabled=True,
            safety_moderation_enabled=True,
            llm_enabled=True,
            llm_primary_provider="ollama",
            llm_ollama_model="synthetic",
            demo_live_enabled=True,
            demo_allowed_chat_ids=("4000000001",),
        )
        database = Database(settings)
        await database.start()
        try:
            await _truncate(database)
            connection, conversation, action_id, target_ids = await _seed_base(
                database, cap=1, tag="worker", platform_conversation_id="4000000001"
            )
            await _seed_delivered(
                database,
                connection_id=connection,
                conversation_id=conversation,
                target_ids=[target_ids[0]],
                tag="one-tease",
            )
            fake = FakeAdapter()
            assert await consume_once(settings, database, fake) == 1
            assert fake.requests == []
            async with database.session_factory() as session:
                action = await session.get(OutboundActionModel, action_id)
                assert action is not None
                assert action.status == OutboundActionStatus.SKIPPED
                assert action.last_error_category == "stale_safety_boundary"
                decision = await session.scalar(select(SafetyPolicyDecisionModel))
                assert decision is not None
                assert decision.policy_version == SafetyPolicyVersion.V1
                assert decision.stage == SafetyStage.PRE_DELIVERY
                assert decision.outcome == SafetyOutcome.SILENT
                assert decision.reason_code == SafetyReasonCode.TEASING_CAP_EXCEEDED
                assert decision.conversation_id == conversation
                assert decision.response_plan_id is not None
        finally:
            await database.stop()

    asyncio.run(scenario())
