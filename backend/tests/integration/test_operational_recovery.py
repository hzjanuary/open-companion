"""PostgreSQL proof for content-safe, one-item operational recovery."""

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from app.core.config import Settings
from app.domain.outbound import OutboundActionKind, OutboundActionStatus
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IncomingUpdateStatus,
    IngressSource,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    Platform,
)
from app.domain.planning import PlanningJobStatus, PlanReasonCode
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageModel,
    OperationalRecoveryEventModel,
    OperationalRecoveryItemModel,
    OutboundActionModel,
    ParticipantModel,
    PlatformConnectionModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.planning import SqlAlchemyPlanningRepository
from app.infrastructure.database.recovery import SqlAlchemyRecoveryRepository


@pytest.mark.integration
def test_replay_is_single_winner_and_quarantine_is_refused() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            async with database.engine.begin() as connection:
                await connection.execute(
                    text("TRUNCATE assistants, operational_recovery_items CASCADE")
                )
            async with database.session_factory() as session:
                async with session.begin():
                    assistant = AssistantModel(
                        tenant_id=LEGACY_TENANT_ID,
                        slug="recovery-test",
                        name="Recovery test",
                        status=AssistantStatus.ACTIVE,
                    )
                    session.add(assistant)
                    await session.flush()
                    connection = PlatformConnectionModel(
                        tenant_id=LEGACY_TENANT_ID,
                        assistant_id=assistant.id,
                        platform=Platform.TELEGRAM,
                        external_bot_id=f"recovery-{uuid4()}",
                    )
                    session.add(connection)
                    await session.flush()
                    conversation = ConversationModel(
                        platform_connection_id=connection.id,
                        platform_conversation_id=f"conversation-{uuid4()}",
                        conversation_type=ConversationType.PRIVATE,
                    )
                    session.add(conversation)
                    await session.flush()
                    participant = ParticipantModel(
                        conversation_id=conversation.id,
                        platform_user_id=f"participant-{uuid4()}",
                        display_name="Synthetic",
                    )
                    session.add(participant)
                    incoming = IncomingPlatformUpdateModel(
                        platform_connection_id=connection.id,
                        platform=Platform.TELEGRAM,
                        platform_update_id=f"update-{uuid4()}",
                        update_type="message",
                        ingress_source=IngressSource.POLLING,
                        raw_payload={},
                        status=IncomingUpdateStatus.RECEIVED,
                        received_at=datetime.now(UTC),
                    )
                    session.add(incoming)
                    await session.flush()
                    message = MessageModel(
                        conversation_id=conversation.id,
                        participant_id=participant.id,
                        platform_message_id=f"message-{uuid4()}",
                        direction=MessageDirection.INCOMING,
                        message_type=MessageType.TEXT,
                        text="not returned by recovery inspection",
                        processing_status=MessageProcessingStatus.PROCESSED,
                    )
                    session.add(message)
                    await session.flush()
                    record = ConversationProcessingRecordModel(
                        incoming_update_id=incoming.id,
                        outcome="message_created",
                        conversation_id=conversation.id,
                        message_id=message.id,
                    )
                    session.add(record)
                    await session.flush()
                    planning = ResponsePlanningJobModel(
                        conversation_processing_record_id=record.id,
                        conversation_id=conversation.id,
                        message_id=message.id,
                        status=PlanningJobStatus.FAILED,
                        prompt_version="test",
                        response_schema_version="test",
                    )
                    session.add(planning)
                    await session.flush()
                    plan = ResponsePlanModel(
                        planning_job_id=planning.id,
                        should_respond=True,
                        reason_code=PlanReasonCode.ANSWER,
                        text="never returned by recovery inspection",
                        mention_participant_ids=[],
                        confidence=1.0,
                        prompt_version="test",
                        schema_version="test",
                    )
                    session.add(plan)
                    await session.flush()
                    outbound = OutboundActionModel(
                        response_plan_id=plan.id,
                        conversation_id=conversation.id,
                        sequence_number=1,
                        idempotency_key=uuid4().hex,
                        kind=OutboundActionKind.TEXT,
                        status=OutboundActionStatus.DELIVERY_UNKNOWN,
                        mention_participant_ids=[],
                        text="never returned by recovery inspection",
                    )
                    session.add(outbound)
                    await session.flush()
                    planning_id, outbound_id = planning.id, outbound.id

            repository = SqlAlchemyRecoveryRepository(database.session_factory)
            await repository.classify(
                RecoveryKind.PLANNING,
                planning_id,
                RecoveryDisposition.DEAD_LETTER,
                RecoveryReason.PROVIDER_RETRY_EXHAUSTED,
            )
            await repository.classify(
                RecoveryKind.OUTBOUND,
                outbound_id,
                RecoveryDisposition.QUARANTINE,
                RecoveryReason.AMBIGUOUS_EXTERNAL_DELIVERY,
            )
            inspection = await repository.show(planning_id)
            assert inspection is not None
            assert inspection.state == "failed"
            assert inspection.next_available_at is not None
            assert inspection.lease_expires_at is None
            assert "text" not in inspection.__dict__
            summary = await repository.summarize()
            assert summary["recovery"] == {
                "outbound.quarantine": 1,
                "planning.dead_letter": 1,
            }
            assert summary["planning"] == {
                "count_by_state": {"failed": 1},
                "oldest_pending_age_seconds": None,
                "active_lease_count": 0,
                "stale_lease_count": 0,
            }
            assert "never returned" not in json.dumps(summary)
            winners = await asyncio.gather(
                repository.replay(RecoveryKind.PLANNING, planning_id),
                repository.replay(RecoveryKind.PLANNING, planning_id),
            )
            assert winners.count(True) == 1
            assert not await repository.replay(RecoveryKind.OUTBOUND, outbound_id)
            # A worker can only claim after replay has atomically made the work
            # pending; it cannot race into a second continuation.
            async with database.session_factory() as session:
                async with session.begin():
                    planning_model = await session.get(
                        ResponsePlanningJobModel, planning_id
                    )
                    recovery_item = await session.scalar(
                        select(OperationalRecoveryItemModel).where(
                            OperationalRecoveryItemModel.work_id == planning_id
                        )
                    )
                    assert planning_model is not None and recovery_item is not None
                    planning_model.status = PlanningJobStatus.FAILED
                    recovery_item.replayed_at = None
            replayed, claimed = await asyncio.gather(
                repository.replay(RecoveryKind.PLANNING, planning_id),
                SqlAlchemyPlanningRepository(database.session_factory).claim(
                    "replay-racing-worker", 1, 60
                ),
            )
            assert replayed
            assert [item.id for item in claimed] in ([], [planning_id])
            async with database.session_factory() as session:
                async with session.begin():
                    planning_model = await session.get(
                        ResponsePlanningJobModel, planning_id
                    )
                    recovery_item = await session.scalar(
                        select(OperationalRecoveryItemModel).where(
                            OperationalRecoveryItemModel.work_id == planning_id
                        )
                    )
                    assert planning_model is not None and recovery_item is not None
                    planning_model.status = PlanningJobStatus.COMPLETED
                    recovery_item.replayed_at = None
            assert not await repository.replay(RecoveryKind.PLANNING, planning_id)
            async with database.session_factory() as session:
                async with session.begin():
                    planning_model = await session.get(
                        ResponsePlanningJobModel, planning_id
                    )
                    assert planning_model is not None
                    planning_model.status = PlanningJobStatus.LEASED
                    planning_model.lease_owner = "active-worker"
                    planning_model.lease_expires_at = datetime.now(UTC)
            assert not await repository.replay(RecoveryKind.PLANNING, planning_id)
            async with database.session_factory() as session:
                assert (
                    await session.get(ResponsePlanningJobModel, planning_id)
                ).status == PlanningJobStatus.LEASED
                assert (
                    await session.get(OutboundActionModel, outbound_id)
                ).status == OutboundActionStatus.DELIVERY_UNKNOWN
                assert (
                    await session.scalar(
                        select(func.count(OperationalRecoveryEventModel.id))
                        .join(OperationalRecoveryItemModel)
                        .where(
                            OperationalRecoveryItemModel.work_id.in_(
                                [planning_id, outbound_id]
                            )
                        )
                    )
                    == 4
                )
        finally:
            await database.stop()

    asyncio.run(scenario())
