"""Set-based primary-database privacy erasure without content-bearing audit data."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.base import Executable

from app.domain.outbound import OutboundActionStatus
from app.domain.persistence import (
    MemoryDeletionReason,
    MemoryKind,
    MemoryStatus,
)
from app.domain.scheduling import OccurrenceStatus, ScheduleReason, ScheduleStatus
from app.domain.summary import ConversationSummaryStatus, SummaryInvalidationReason
from app.domain.voice import VoiceArtifactStatus
from app.infrastructure.database.governance import invalidate_export_packages
from app.infrastructure.database.media import redact_media_values
from app.infrastructure.database.models import (
    ConversationFeedbackEventModel,
    ConversationFeedbackModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    ConversationSummaryModel,
    GeneratedVoiceArtifactModel,
    IncomingPlatformUpdateModel,
    MemoryControlOperationModel,
    MemoryEventModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    MessageMediaModel,
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    ParticipantSchedulePreferenceModel,
    PlatformConnectionModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)

semantic_memory_jobs = SqlAlchemySemanticMemoryRepository


@dataclass(frozen=True, slots=True)
class PrivacyErasureResult:
    participants: int
    messages: int
    incoming_updates: int
    command_arguments: int
    response_plans: int
    outbound_actions: int
    memories: int
    summaries: int
    already_deleted: bool
    recall_policies: int = 0
    schedules: int = 0
    schedule_preferences: int = 0
    feedback: int = 0


class SqlAlchemyPrivacyRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_version: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_version = embedding_version

    async def erase_subject(
        self,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        platform_user_id: str,
        command_job_id: UUID,
        now: datetime | None = None,
    ) -> PrivacyErasureResult:
        """Clear subject content across this Assistant/connection, idempotently."""

        current = now or datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                participant_ids = list(
                    await session.scalars(
                        select(ParticipantModel.id)
                        .join(
                            ConversationModel,
                            ParticipantModel.conversation_id == ConversationModel.id,
                        )
                        .join(
                            PlatformConnectionModel,
                            ConversationModel.platform_connection_id
                            == PlatformConnectionModel.id,
                        )
                        .where(
                            ConversationModel.platform_connection_id
                            == platform_connection_id,
                            PlatformConnectionModel.assistant_id == assistant_id,
                            ParticipantModel.platform_user_id == platform_user_id,
                        )
                        .with_for_update()
                    )
                )
                if not participant_ids:
                    return PrivacyErasureResult(0, 0, 0, 0, 0, 0, 0, 0, True)
                await invalidate_export_packages(
                    session,
                    scope="subject",
                    participant_ids=participant_ids,
                    reason="subject_erasure",
                    now=current,
                )
                active = await session.scalar(
                    select(ParticipantModel.id).where(
                        ParticipantModel.id.in_(participant_ids),
                        ParticipantModel.privacy_deleted_at.is_(None),
                    )
                )
                if active is None:
                    return PrivacyErasureResult(0, 0, 0, 0, 0, 0, 0, 0, True)
                participant_count = await _count(
                    session,
                    update(ParticipantModel)
                    .where(ParticipantModel.id.in_(participant_ids))
                    .values(
                        username=None,
                        display_name="Deleted user",
                        metadata_={},
                        mention_allowed=False,
                        teasing_allowed=False,
                        privacy_deleted_at=current,
                    )
                    .returning(ParticipantModel.id),
                )
                feedback_event_count = await _count(
                    session,
                    delete(ConversationFeedbackEventModel)
                    .where(
                        ConversationFeedbackEventModel.participant_id.in_(
                            participant_ids
                        )
                    )
                    .returning(ConversationFeedbackEventModel.id),
                )
                feedback_current_count = await _count(
                    session,
                    delete(ConversationFeedbackModel)
                    .where(
                        ConversationFeedbackModel.participant_id.in_(participant_ids)
                    )
                    .returning(ConversationFeedbackModel.id),
                )
                message_ids = select(MessageModel.id).where(
                    MessageModel.participant_id.in_(participant_ids)
                )
                message_count = await _count(
                    session,
                    update(MessageModel)
                    .where(MessageModel.id.in_(message_ids))
                    .values(text=None, metadata_={}, content_redacted_at=current)
                    .returning(MessageModel.id),
                )
                await session.execute(
                    update(MessageMediaModel)
                    .where(MessageMediaModel.message_id.in_(message_ids))
                    .values(**redact_media_values(current))
                )
                update_ids = select(
                    ConversationProcessingRecordModel.incoming_update_id
                ).where(ConversationProcessingRecordModel.message_id.in_(message_ids))
                update_count = await _count(
                    session,
                    update(IncomingPlatformUpdateModel)
                    .where(IncomingPlatformUpdateModel.id.in_(update_ids))
                    .values(raw_payload={}, payload_redacted_at=current)
                    .returning(IncomingPlatformUpdateModel.id),
                )
                command_count = await _count(
                    session,
                    update(TelegramCommandJobModel)
                    .where(TelegramCommandJobModel.participant_id.in_(participant_ids))
                    .values(arguments="", arguments_redacted_at=current)
                    .returning(TelegramCommandJobModel.id),
                )
                schedule_ids = select(ProactiveScheduleModel.id).where(
                    ProactiveScheduleModel.creator_participant_id.in_(participant_ids)
                )
                schedule_count = await _count(
                    session,
                    update(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.id.in_(schedule_ids),
                        ProactiveScheduleModel.status != ScheduleStatus.ERASED,
                    )
                    .values(
                        status=ScheduleStatus.ERASED,
                        next_run_at=None,
                        reminder_text=None,
                        timezone_name=None,
                        local_time_minute=None,
                        weekday_mask=None,
                        starts_on=None,
                        one_time_at=None,
                        redacted_at=current,
                        version=ProactiveScheduleModel.version + 1,
                    )
                    .returning(ProactiveScheduleModel.id),
                )
                preference_count = await _count(
                    session,
                    update(ParticipantSchedulePreferenceModel)
                    .where(
                        ParticipantSchedulePreferenceModel.participant_id.in_(
                            participant_ids
                        )
                    )
                    .values(
                        timezone_name=None,
                        quiet_hours_enabled=False,
                        quiet_start_minute=1320,
                        quiet_end_minute=480,
                        revision=ParticipantSchedulePreferenceModel.revision + 1,
                    )
                    .returning(ParticipantSchedulePreferenceModel.id),
                )
                await session.execute(
                    update(ProactiveScheduleOccurrenceModel)
                    .where(
                        ProactiveScheduleOccurrenceModel.schedule_id.in_(schedule_ids),
                        ProactiveScheduleOccurrenceModel.status.in_(
                            [
                                OccurrenceStatus.PENDING,
                                OccurrenceStatus.LEASED,
                                OccurrenceStatus.ENQUEUED,
                                OccurrenceStatus.DELIVERED,
                                OccurrenceStatus.SKIPPED,
                                OccurrenceStatus.PERMANENTLY_FAILED,
                                OccurrenceStatus.DELIVERY_UNKNOWN,
                            ]
                        ),
                    )
                    .values(
                        status=OccurrenceStatus.HISTORY_REDACTED,
                        reason_code=ScheduleReason.PRIVACY,
                        scheduled_for=None,
                        local_date=None,
                        lease_owner=None,
                        lease_token=None,
                        lease_expires_at=None,
                        completed_at=current,
                        redacted_at=current,
                    )
                )
                occurrence_ids = select(ProactiveScheduleOccurrenceModel.id).where(
                    ProactiveScheduleOccurrenceModel.schedule_id.in_(schedule_ids)
                )
                plan_ids = select(ResponsePlanModel.id).where(
                    ResponsePlanModel.command_job_id.in_(
                        select(TelegramCommandJobModel.id).where(
                            TelegramCommandJobModel.participant_id.in_(participant_ids)
                        )
                    )
                    | ResponsePlanModel.planning_job_id.in_(
                        select(ResponsePlanningJobModel.id).where(
                            ResponsePlanningJobModel.message_id.in_(message_ids)
                        )
                    )
                    | ResponsePlanModel.schedule_occurrence_id.in_(occurrence_ids)
                )
                artifact_ids = select(GeneratedVoiceArtifactModel.id).where(
                    GeneratedVoiceArtifactModel.source_response_plan_id.in_(plan_ids)
                )
                await session.execute(
                    update(GeneratedVoiceArtifactModel)
                    .where(
                        GeneratedVoiceArtifactModel.id.in_(artifact_ids),
                        GeneratedVoiceArtifactModel.status == VoiceArtifactStatus.READY,
                    )
                    .values(
                        audio_bytes=None,
                        status=VoiceArtifactStatus.PURGED,
                        purged_at=current,
                    )
                )
                await session.execute(
                    update(OutboundActionModel)
                    .where(
                        OutboundActionModel.generated_voice_artifact_id.in_(
                            artifact_ids
                        ),
                        OutboundActionModel.status.in_(
                            [
                                OutboundActionStatus.PENDING,
                                OutboundActionStatus.LEASED,
                            ]
                        ),
                    )
                    .values(
                        status=OutboundActionStatus.PERMANENTLY_FAILED,
                        lease_owner=None,
                        lease_expires_at=None,
                        completed_at=current,
                        last_error_category="privacy_erasure",
                        last_error_at=current,
                    )
                )
                plan_count = await _count(
                    session,
                    update(ResponsePlanModel)
                    .where(ResponsePlanModel.id.in_(plan_ids))
                    .values(text=None, content_redacted_at=current)
                    .returning(ResponsePlanModel.id),
                )
                action_count = await _count(
                    session,
                    update(OutboundActionModel)
                    .where(OutboundActionModel.response_plan_id.in_(plan_ids))
                    .values(text=None, sticker_intent=None, payload_redacted_at=current)
                    .returning(OutboundActionModel.id),
                )
                memory_rows = list(
                    await session.execute(
                        update(MemoryItemModel)
                        .where(
                            MemoryItemModel.assistant_id == assistant_id,
                            MemoryItemModel.platform_connection_id
                            == platform_connection_id,
                            MemoryItemModel.creator_participant_id.in_(participant_ids),
                            MemoryItemModel.status == MemoryStatus.ACTIVE,
                        )
                        .values(
                            status=MemoryStatus.DELETED,
                            content=None,
                            normalized_content_hash=None,
                            deleted_at=current,
                            deletion_reason=MemoryDeletionReason.PROFILE_DELETION,
                        )
                        .returning(MemoryItemModel.id, MemoryItemModel.kind)
                    )
                )
                for memory_id, memory_kind in memory_rows:
                    session.add(
                        MemoryEventModel(
                            memory_id=memory_id,
                            command_job_id=command_job_id,
                            action_code="profile_deleted",
                            deletion_reason=MemoryDeletionReason.PROFILE_DELETION.value,
                        )
                    )
                    if memory_kind == MemoryKind.EXPLICIT_FACT:
                        await semantic_memory_jobs.schedule_deletes_for_memory(
                            session,
                            memory_id,
                            self._embedding_version,
                        )
                recall_count = await _count(
                    session,
                    update(MemoryRecallPolicyModel)
                    .where(
                        MemoryRecallPolicyModel.participant_id.in_(participant_ids),
                        MemoryRecallPolicyModel.enabled.is_(True),
                    )
                    .values(
                        enabled=False,
                        revision=MemoryRecallPolicyModel.revision + 1,
                        updated_at=current,
                    )
                    .returning(MemoryRecallPolicyModel.id),
                )
                await session.execute(
                    update(MemoryControlOperationModel)
                    .where(
                        MemoryControlOperationModel.actor_participant_id.in_(
                            participant_ids
                        ),
                        MemoryControlOperationModel.operation == "clear",
                        MemoryControlOperationModel.status == "in_progress",
                    )
                    .values(status="complete", outcome="cleared", updated_at=current)
                )
                conversation_ids = select(ConversationModel.id).where(
                    ConversationModel.id.in_(
                        select(ParticipantModel.conversation_id).where(
                            ParticipantModel.id.in_(participant_ids)
                        )
                    )
                )
                summary_count = await _count(
                    session,
                    update(ConversationSummaryModel)
                    .where(
                        ConversationSummaryModel.conversation_id.in_(conversation_ids),
                        ConversationSummaryModel.status
                        == ConversationSummaryStatus.COMPLETED,
                    )
                    .values(
                        summary_text=None,
                        status=ConversationSummaryStatus.INVALIDATED,
                        invalidated_at=current,
                        invalidation_reason=SummaryInvalidationReason.PRIVACY_ERASURE,
                    )
                    .returning(ConversationSummaryModel.id),
                )
                await session.execute(
                    update(ConversationModel)
                    .where(ConversationModel.id.in_(conversation_ids))
                    .values(
                        memory_privacy_revision=ConversationModel.memory_privacy_revision
                        + 1
                    )
                )
                return PrivacyErasureResult(
                    participant_count,
                    message_count,
                    update_count,
                    command_count,
                    plan_count,
                    action_count,
                    len(memory_rows),
                    summary_count,
                    False,
                    recall_policies=recall_count,
                    schedules=schedule_count,
                    schedule_preferences=preference_count,
                    feedback=feedback_event_count + feedback_current_count,
                )


async def _count(session: AsyncSession, statement: Executable) -> int:
    result = await session.scalars(statement)
    return len(list(result))
