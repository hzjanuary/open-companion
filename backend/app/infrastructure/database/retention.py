"""Bounded, content-clearing retention mutations for terminal records."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.base import Executable

from app.domain.outbound import OutboundActionStatus
from app.domain.persistence import (
    CommandJobStatus,
    MemoryDeletionReason,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MessageProcessingStatus,
)
from app.domain.scheduling import OccurrenceStatus, ScheduleStatus
from app.domain.summary import ConversationSummaryStatus, SummaryInvalidationReason
from app.domain.voice import VoiceArtifactStatus
from app.infrastructure.database.governance import invalidate_export_packages
from app.infrastructure.database.media import redact_media_values
from app.infrastructure.database.models import (
    ControlAuditEventModel,
    ConversationFeedbackEventModel,
    ConversationFeedbackModel,
    ConversationModel,
    ConversationSummaryModel,
    GeneratedVoiceArtifactModel,
    GovernanceAuditEventModel,
    IncomingPlatformUpdateModel,
    MemoryEventModel,
    MemoryItemModel,
    MessageMediaModel,
    MessageModel,
    OutboundActionModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
    TelegramCommandJobModel,
)
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)


@dataclass(frozen=True, slots=True)
class RetentionCounts:
    incoming_updates: int = 0
    messages: int = 0
    response_plans: int = 0
    outbound_actions: int = 0
    command_arguments: int = 0
    summaries: int = 0
    audit_events: int = 0
    control_audit_events: int = 0
    memories: int = 0
    schedules: int = 0
    schedule_occurrences: int = 0
    voice_artifacts: int = 0
    feedback: int = 0


class SqlAlchemyRetentionRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_version: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedding_version = embedding_version

    async def redact_once(
        self,
        *,
        now: datetime | None = None,
        retention_days: int,
        governance_audit_retention_days: int = 90,
        schedule_history_retention_days: int = 30,
        batch_size: int,
    ) -> RetentionCounts:
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(days=retention_days)
        audit_cutoff = current - timedelta(days=governance_audit_retention_days)
        schedule_cutoff = current - timedelta(days=schedule_history_retention_days)
        async with self._session_factory() as session:
            async with session.begin():
                counts = RetentionCounts(
                    incoming_updates=await _redact_updates(
                        session, cutoff, current, batch_size
                    ),
                    messages=await _redact_messages(
                        session, cutoff, current, batch_size
                    ),
                    response_plans=await _redact_plans(
                        session, cutoff, current, batch_size
                    ),
                    feedback=await _purge_feedback(session, batch_size),
                    outbound_actions=await _redact_actions(
                        session, cutoff, current, batch_size
                    ),
                    command_arguments=await _redact_commands(
                        session, cutoff, current, batch_size
                    ),
                    summaries=await _expire_summaries(session, current, batch_size),
                    audit_events=await _purge_governance_audit_events(
                        session, audit_cutoff, batch_size
                    ),
                    control_audit_events=await _purge_control_audit_events(
                        session, audit_cutoff, batch_size
                    ),
                    memories=await _expire_memories(
                        session, current, batch_size, self._embedding_version
                    ),
                    schedules=await _redact_schedules(
                        session, schedule_cutoff, current, batch_size
                    ),
                    schedule_occurrences=await _redact_schedule_occurrences(
                        session, schedule_cutoff, current, batch_size
                    ),
                    voice_artifacts=await _purge_voice_artifacts(
                        session, current, batch_size
                    ),
                )
        return counts


async def _purge_feedback(session: AsyncSession, limit: int) -> int:
    feedback_ids = list(
        await session.scalars(
            select(ConversationFeedbackModel.id)
            .join(
                ResponsePlanModel,
                ResponsePlanModel.id == ConversationFeedbackModel.response_plan_id,
            )
            .where(ResponsePlanModel.content_redacted_at.is_not(None))
            .order_by(
                ConversationFeedbackModel.created_at, ConversationFeedbackModel.id
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not feedback_ids:
        return 0
    event_count = await _count(
        session,
        delete(ConversationFeedbackEventModel)
        .where(ConversationFeedbackEventModel.feedback_id.in_(feedback_ids))
        .returning(ConversationFeedbackEventModel.id),
    )
    current_count = await _count(
        session,
        delete(ConversationFeedbackModel)
        .where(ConversationFeedbackModel.id.in_(feedback_ids))
        .returning(ConversationFeedbackModel.id),
    )
    return event_count + current_count


async def _purge_voice_artifacts(
    session: AsyncSession, now: datetime, limit: int
) -> int:
    rows = list(
        await session.scalars(
            select(GeneratedVoiceArtifactModel)
            .where(
                GeneratedVoiceArtifactModel.status == VoiceArtifactStatus.READY,
                GeneratedVoiceArtifactModel.expires_at <= now,
            )
            .order_by(
                GeneratedVoiceArtifactModel.expires_at,
                GeneratedVoiceArtifactModel.id,
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    if not rows:
        return 0
    artifact_ids = [row.id for row in rows]
    await session.execute(
        update(OutboundActionModel)
        .where(
            OutboundActionModel.generated_voice_artifact_id.in_(artifact_ids),
            OutboundActionModel.status.in_(
                [OutboundActionStatus.PENDING, OutboundActionStatus.LEASED]
            ),
        )
        .values(
            status=OutboundActionStatus.PERMANENTLY_FAILED,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=now,
            last_error_category="voice_artifact_expired",
            last_error_at=now,
        )
    )
    for row in rows:
        row.audio_bytes = None
        row.status = VoiceArtifactStatus.PURGED
        row.purged_at = now
    return len(rows)


async def _redact_updates(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = (
        select(IncomingPlatformUpdateModel.id)
        .where(
            IncomingPlatformUpdateModel.received_at <= cutoff,
            IncomingPlatformUpdateModel.payload_redacted_at.is_(None),
        )
        .order_by(
            IncomingPlatformUpdateModel.received_at, IncomingPlatformUpdateModel.id
        )
        .limit(limit)
    )
    return await _count(
        session,
        update(IncomingPlatformUpdateModel)
        .where(IncomingPlatformUpdateModel.id.in_(ids))
        .values(raw_payload={}, payload_redacted_at=now)
        .returning(IncomingPlatformUpdateModel.id),
    )


async def _redact_messages(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids_query = (
        select(MessageModel.id)
        .where(
            MessageModel.platform_sent_at <= cutoff,
            MessageModel.content_redacted_at.is_(None),
            MessageModel.processing_status != MessageProcessingStatus.PENDING,
        )
        .order_by(MessageModel.platform_sent_at, MessageModel.id)
        .limit(limit)
    )
    ids = list(await session.scalars(ids_query))
    if not ids:
        return 0
    await session.execute(
        update(MessageMediaModel)
        .where(MessageMediaModel.message_id.in_(ids))
        .values(**redact_media_values(now))
    )
    return await _count(
        session,
        update(MessageModel)
        .where(MessageModel.id.in_(ids))
        .values(text=None, metadata_={}, content_redacted_at=now)
        .returning(MessageModel.id),
    )


async def _redact_plans(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = (
        select(ResponsePlanModel.id)
        .where(
            ResponsePlanModel.created_at <= cutoff,
            ResponsePlanModel.content_redacted_at.is_(None),
        )
        .order_by(ResponsePlanModel.created_at, ResponsePlanModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        update(ResponsePlanModel)
        .where(ResponsePlanModel.id.in_(ids))
        .values(text=None, content_redacted_at=now)
        .returning(ResponsePlanModel.id),
    )


async def _redact_actions(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    terminal = (
        OutboundActionStatus.DELIVERED,
        OutboundActionStatus.SKIPPED,
        OutboundActionStatus.PERMANENTLY_FAILED,
        OutboundActionStatus.DELIVERY_UNKNOWN,
    )
    ids = (
        select(OutboundActionModel.id)
        .where(
            OutboundActionModel.created_at <= cutoff,
            OutboundActionModel.payload_redacted_at.is_(None),
            OutboundActionModel.status.in_(terminal),
        )
        .order_by(OutboundActionModel.created_at, OutboundActionModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        update(OutboundActionModel)
        .where(OutboundActionModel.id.in_(ids))
        .values(text=None, sticker_intent=None, payload_redacted_at=now)
        .returning(OutboundActionModel.id),
    )


async def _redact_commands(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = (
        select(TelegramCommandJobModel.id)
        .where(
            TelegramCommandJobModel.completed_at <= cutoff,
            TelegramCommandJobModel.arguments_redacted_at.is_(None),
            TelegramCommandJobModel.status.in_(
                (CommandJobStatus.COMPLETED, CommandJobStatus.FAILED)
            ),
        )
        .order_by(TelegramCommandJobModel.completed_at, TelegramCommandJobModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        update(TelegramCommandJobModel)
        .where(TelegramCommandJobModel.id.in_(ids))
        .values(arguments="", arguments_redacted_at=now)
        .returning(TelegramCommandJobModel.id),
    )


async def _expire_summaries(session: AsyncSession, now: datetime, limit: int) -> int:
    ids = (
        select(ConversationSummaryModel.id)
        .where(
            ConversationSummaryModel.expires_at <= now,
            ConversationSummaryModel.status == ConversationSummaryStatus.COMPLETED,
        )
        .order_by(ConversationSummaryModel.expires_at, ConversationSummaryModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        update(ConversationSummaryModel)
        .where(ConversationSummaryModel.id.in_(ids))
        .values(
            summary_text=None,
            status=ConversationSummaryStatus.EXPIRED,
            invalidated_at=now,
            invalidation_reason=SummaryInvalidationReason.RETENTION_EXPIRED,
        )
        .returning(ConversationSummaryModel.id),
    )


async def _expire_memories(
    session: AsyncSession,
    now: datetime,
    limit: int,
    embedding_version: str | None,
) -> int:
    rows = list(
        await session.scalars(
            select(MemoryItemModel)
            .where(
                MemoryItemModel.status == MemoryStatus.ACTIVE,
                MemoryItemModel.expires_at.is_not(None),
                MemoryItemModel.expires_at <= now,
            )
            .order_by(MemoryItemModel.expires_at, MemoryItemModel.id)
            .limit(limit)
            .with_for_update()
        )
    )
    if not rows:
        return 0
    conversation_ids: set[UUID] = set()
    for item in rows:
        item.status = MemoryStatus.EXPIRED
        item.content = None
        item.normalized_content_hash = None
        item.deleted_at = now
        item.deletion_reason = MemoryDeletionReason.EXPIRATION
        conversation_ids.add(item.conversation_id)
        session.add(
            MemoryEventModel(
                memory_id=item.id,
                actor_participant_id=item.creator_participant_id,
                action_code="expired",
                deletion_reason=MemoryDeletionReason.EXPIRATION.value,
            )
        )
        if item.kind == MemoryKind.EXPLICIT_FACT:
            await SqlAlchemySemanticMemoryRepository.schedule_deletes_for_memory(
                session, item.id, embedding_version
            )
        await invalidate_export_packages(
            session,
            scope="subject",
            participant_ids=[item.creator_participant_id],
            reason="memory_expired",
            now=now,
        )
        if item.scope == MemoryScope.GROUP_CONVERSATION:
            await invalidate_export_packages(
                session,
                scope="group",
                conversation_id=item.conversation_id,
                reason="memory_expired",
                now=now,
            )
    await session.execute(
        update(ConversationModel)
        .where(ConversationModel.id.in_(conversation_ids))
        .values(memory_privacy_revision=ConversationModel.memory_privacy_revision + 1)
    )
    return len(rows)


async def _purge_governance_audit_events(
    session: AsyncSession, before: datetime, limit: int
) -> int:
    """Enforce FR-12 bounded governance audit retention (FR-08 schedule)."""
    ids = (
        select(GovernanceAuditEventModel.id)
        .where(GovernanceAuditEventModel.created_at < before)
        .order_by(GovernanceAuditEventModel.created_at, GovernanceAuditEventModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        delete(GovernanceAuditEventModel)
        .where(GovernanceAuditEventModel.id.in_(ids))
        .returning(GovernanceAuditEventModel.id),
    )


async def _redact_schedules(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = (
        select(ProactiveScheduleModel.id)
        .where(
            ProactiveScheduleModel.status.in_(
                [ScheduleStatus.COMPLETED, ScheduleStatus.CANCELLED]
            ),
            ProactiveScheduleModel.updated_at <= cutoff,
            ProactiveScheduleModel.redacted_at.is_(None),
        )
        .order_by(ProactiveScheduleModel.updated_at, ProactiveScheduleModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        update(ProactiveScheduleModel)
        .where(ProactiveScheduleModel.id.in_(ids))
        .values(
            reminder_text=None,
            timezone_name=None,
            local_time_minute=None,
            weekday_mask=None,
            starts_on=None,
            one_time_at=None,
            redacted_at=now,
        )
        .returning(ProactiveScheduleModel.id),
    )


async def _redact_schedule_occurrences(
    session: AsyncSession, cutoff: datetime, now: datetime, limit: int
) -> int:
    ids = (
        select(ProactiveScheduleOccurrenceModel.id)
        .where(
            ProactiveScheduleOccurrenceModel.status.in_(
                [
                    OccurrenceStatus.DELIVERED,
                    OccurrenceStatus.SKIPPED,
                    OccurrenceStatus.PERMANENTLY_FAILED,
                    OccurrenceStatus.DELIVERY_UNKNOWN,
                ]
            ),
            ProactiveScheduleOccurrenceModel.completed_at <= cutoff,
            ProactiveScheduleOccurrenceModel.redacted_at.is_(None),
        )
        .order_by(
            ProactiveScheduleOccurrenceModel.completed_at,
            ProactiveScheduleOccurrenceModel.id,
        )
        .limit(limit)
    )
    return await _count(
        session,
        update(ProactiveScheduleOccurrenceModel)
        .where(ProactiveScheduleOccurrenceModel.id.in_(ids))
        .values(
            status=OccurrenceStatus.HISTORY_REDACTED,
            reason_code="none",
            scheduled_for=None,
            local_date=None,
            redacted_at=now,
        )
        .returning(ProactiveScheduleOccurrenceModel.id),
    )


async def _purge_control_audit_events(
    session: AsyncSession, before: datetime, limit: int
) -> int:
    """Enforce the documented control-plane audit retention (FR-08 schedule)."""
    ids = (
        select(ControlAuditEventModel.id)
        .where(ControlAuditEventModel.created_at < before)
        .order_by(ControlAuditEventModel.created_at, ControlAuditEventModel.id)
        .limit(limit)
    )
    return await _count(
        session,
        delete(ControlAuditEventModel)
        .where(ControlAuditEventModel.id.in_(ids))
        .returning(ControlAuditEventModel.id),
    )


async def _count(session: AsyncSession, statement: Executable) -> int:
    result = await session.scalars(statement)
    return len(list(result))
