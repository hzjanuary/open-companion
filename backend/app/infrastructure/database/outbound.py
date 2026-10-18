"""PostgreSQL leasing and finalization for outbound delivery."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.scheduling import in_quiet_hours, quiet_hours_end
from app.domain.ambient import ParticipationTrigger
from app.domain.conversation import MembershipStatus
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.persistence import (
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
)
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.domain.scheduling import (
    OccurrenceStatus,
    ScheduleKind,
    SchedulePreferences,
    ScheduleReason,
    ScheduleStatus,
)
from app.domain.voice import (
    VOICE_ARTIFACT_GRACE_HOURS,
    VoiceArtifactStatus,
)
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationModel,
    GeneratedVoiceArtifactModel,
    MessageModel,
    OperationalRecoveryEventModel,
    OperationalRecoveryItemModel,
    OutboundActionModel,
    OutboundDeliveryAttemptModel,
    OutboundRecoveryEventModel,
    ParticipantModel,
    ParticipantSchedulePreferenceModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
)
from app.infrastructure.database.tenancy import connection_authority


async def _scheduled_preflight(
    session: AsyncSession,
    action: OutboundActionModel,
    attempt: OutboundDeliveryAttemptModel,
    now: datetime,
) -> bool:
    """Re-authorize scheduled delivery in the external-start transaction."""

    plan = await session.get(ResponsePlanModel, action.response_plan_id)
    occurrence = (
        await session.get(
            ProactiveScheduleOccurrenceModel,
            plan.schedule_occurrence_id,
            with_for_update=True,
        )
        if plan is not None and plan.schedule_occurrence_id is not None
        else None
    )
    schedule = (
        await session.get(ProactiveScheduleModel, occurrence.schedule_id)
        if occurrence is not None
        else None
    )
    conversation = (
        await session.get(ConversationModel, occurrence.conversation_id)
        if occurrence is not None
        else None
    )
    participant = (
        await session.get(ParticipantModel, occurrence.participant_id)
        if occurrence is not None
        else None
    )
    authority = (
        await connection_authority(session, conversation.platform_connection_id)
        if conversation is not None
        else None
    )
    connection = authority.connection if authority is not None else None
    assistant = authority.assistant if authority is not None else None
    if (
        occurrence is None
        or schedule is None
        or conversation is None
        or participant is None
        or connection is None
        or assistant is None
        or authority is None
        or action.conversation_id != occurrence.conversation_id
        or occurrence.status != OccurrenceStatus.ENQUEUED
        or schedule.status not in {ScheduleStatus.ACTIVE, ScheduleStatus.COMPLETED}
        or occurrence.schedule_version != schedule.version
        or not authority.permits_external_io
        or conversation.assistant_membership_status
        in {MembershipStatus.LEFT, MembershipStatus.KICKED, MembershipStatus.RESTRICTED}
    ):
        _reject_scheduled(
            action,
            attempt,
            occurrence,
            now,
            ScheduleReason.CANCELLED,
            "scheduled_cancelled",
        )
        return False
    revision = (
        await session.get(
            ConversationConfigurationRevisionModel,
            conversation.current_configuration_revision_id,
        )
        if conversation.current_configuration_revision_id is not None
        else None
    )
    if conversation.status.value != "active" or (
        revision is not None and revision.response_mode.value == "paused"
    ):
        _reject_scheduled(
            action,
            attempt,
            occurrence,
            now,
            ScheduleReason.PAUSED,
            "scheduled_paused",
        )
        return False
    if (
        participant.conversation_id != conversation.id
        or participant.membership_status != MembershipStatus.MEMBER
    ):
        _reject_scheduled(
            action,
            attempt,
            occurrence,
            now,
            ScheduleReason.MEMBERSHIP,
            "scheduled_membership_invalid",
        )
        return False
    if (
        participant.privacy_deleted_at is not None
        or occurrence.privacy_revision != conversation.memory_privacy_revision
    ):
        _reject_scheduled(
            action,
            attempt,
            occurrence,
            now,
            ScheduleReason.PRIVACY,
            "scheduled_privacy_changed",
        )
        return False
    if schedule.kind == ScheduleKind.CHECK_IN:
        if participant.protected_at is not None:
            _reject_scheduled(
                action,
                attempt,
                occurrence,
                now,
                ScheduleReason.PAUSED,
                "scheduled_subject_protected",
            )
            return False
        if occurrence.scheduled_for is None:
            _reject_scheduled(
                action,
                attempt,
                occurrence,
                now,
                ScheduleReason.PRIVACY,
                "scheduled_history_redacted",
            )
            return False
        preference = await session.scalar(
            select(ParticipantSchedulePreferenceModel).where(
                ParticipantSchedulePreferenceModel.participant_id == participant.id
            )
        )
        preferences = (
            SchedulePreferences(None, True, 1320, 480, 1)
            if preference is None
            else SchedulePreferences(
                preference.timezone_name,
                preference.quiet_hours_enabled,
                preference.quiet_start_minute,
                preference.quiet_end_minute,
                preference.revision,
            )
        )
        if now - occurrence.scheduled_for > timedelta(hours=24):
            _reject_scheduled(
                action,
                attempt,
                occurrence,
                now,
                ScheduleReason.STALE,
                "scheduled_stale",
            )
            return False
        if in_quiet_hours(now, preferences):
            end = quiet_hours_end(now, preferences)
            if end - occurrence.scheduled_for <= timedelta(hours=24):
                attempt.status = DeliveryAttemptStatus.REJECTED
                attempt.certainty = DeliveryCertainty.NOT_SENT
                attempt.error_category = "scheduled_quiet_hours"
                attempt.finished_at = now
                action.status = OutboundActionStatus.PENDING
                action.available_at = end
                action.lease_owner = None
                action.lease_expires_at = None
                action.last_error_category = "scheduled_quiet_hours"
                action.last_error_at = now
                occurrence.reason_code = ScheduleReason.QUIET_HOURS
                return False
            _reject_scheduled(
                action,
                attempt,
                occurrence,
                now,
                ScheduleReason.STALE,
                "scheduled_stale",
            )
            return False
        if (
            participant.last_seen_at is not None
            and now - participant.last_seen_at < timedelta(hours=24)
        ):
            _reject_scheduled(
                action,
                attempt,
                occurrence,
                now,
                ScheduleReason.RECENT_ACTIVITY,
                "scheduled_recent_activity",
            )
            return False
    occurrence.reason_code = ScheduleReason.NONE
    return True


def _reject_scheduled(
    action: OutboundActionModel,
    attempt: OutboundDeliveryAttemptModel,
    occurrence: ProactiveScheduleOccurrenceModel | None,
    now: datetime,
    reason: ScheduleReason,
    error: str,
) -> None:
    attempt.status = DeliveryAttemptStatus.REJECTED
    attempt.certainty = DeliveryCertainty.NOT_SENT
    attempt.error_category = error
    attempt.finished_at = now
    action.status = OutboundActionStatus.SKIPPED
    action.lease_owner = None
    action.lease_expires_at = None
    action.completed_at = now
    action.last_error_category = error
    action.last_error_at = now
    if occurrence is not None and (
        occurrence.status != OccurrenceStatus.HISTORY_REDACTED
        and occurrence.redacted_at is None
    ):
        occurrence.status = OccurrenceStatus.SKIPPED
        occurrence.reason_code = reason
        occurrence.completed_at = now


async def _update_scheduled_occurrence(
    session: AsyncSession,
    action: OutboundActionModel,
    status: OutboundActionStatus,
    certainty: DeliveryCertainty,
    now: datetime,
    error_category: str | None,
) -> None:
    if action.origin != ParticipationTrigger.SCHEDULED:
        return
    plan = await session.get(ResponsePlanModel, action.response_plan_id)
    occurrence = (
        await session.get(
            ProactiveScheduleOccurrenceModel,
            plan.schedule_occurrence_id,
            with_for_update=True,
        )
        if plan is not None and plan.schedule_occurrence_id is not None
        else None
    )
    if (
        occurrence is None
        or status == OutboundActionStatus.PENDING
        or occurrence.status == OccurrenceStatus.HISTORY_REDACTED
        or occurrence.redacted_at is not None
    ):
        return
    if status == OutboundActionStatus.DELIVERED:
        occurrence.status = OccurrenceStatus.DELIVERED
        occurrence.reason_code = ScheduleReason.NONE
    elif (
        status == OutboundActionStatus.DELIVERY_UNKNOWN
        or certainty == DeliveryCertainty.UNKNOWN
    ):
        occurrence.status = OccurrenceStatus.DELIVERY_UNKNOWN
        occurrence.reason_code = ScheduleReason.DELIVERY_UNKNOWN
    elif status == OutboundActionStatus.PERMANENTLY_FAILED:
        occurrence.status = OccurrenceStatus.PERMANENTLY_FAILED
        occurrence.reason_code = ScheduleReason.DELIVERY_REJECTED
    else:
        occurrence.status = OccurrenceStatus.SKIPPED
        occurrence.reason_code = (
            ScheduleReason.PRIVACY
            if error_category == "payload_redacted"
            else ScheduleReason.DELIVERY_REJECTED
        )
    occurrence.completed_at = now


class SqlAlchemyOutboundRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim(
        self, owner: str, limit: int, lease_seconds: int
    ) -> list[OutboundActionModel]:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                earlier = OutboundActionModel.__table__.alias("earlier")
                conversation_earlier = OutboundActionModel.__table__.alias(
                    "conversation_earlier"
                )
                actions = list(
                    await session.scalars(
                        select(OutboundActionModel)
                        .where(
                            or_(
                                (
                                    OutboundActionModel.status
                                    == OutboundActionStatus.PENDING
                                )
                                & (OutboundActionModel.available_at <= now),
                                (
                                    OutboundActionModel.status
                                    == OutboundActionStatus.LEASED
                                )
                                & (OutboundActionModel.lease_expires_at < now),
                            ),
                            ~exists(
                                select(earlier.c.id).where(
                                    (
                                        earlier.c.response_plan_id
                                        == OutboundActionModel.response_plan_id
                                    )
                                    & (
                                        earlier.c.sequence_number
                                        < OutboundActionModel.sequence_number
                                    )
                                    & (earlier.c.status != "delivered")
                                    & ~(
                                        (
                                            OutboundActionModel.fallback_for_action_id
                                            == earlier.c.id
                                        )
                                        & (earlier.c.status == "skipped")
                                    )
                                )
                            ),
                            ~exists(
                                select(conversation_earlier.c.id).where(
                                    (OutboundActionModel.origin == "ambient")
                                    & (
                                        conversation_earlier.c.conversation_id
                                        == OutboundActionModel.conversation_id
                                    )
                                    & (conversation_earlier.c.origin == "ambient")
                                    & conversation_earlier.c.status.in_(
                                        ["pending", "leased"]
                                    )
                                    & (
                                        (
                                            conversation_earlier.c.created_at
                                            < OutboundActionModel.created_at
                                        )
                                        | (
                                            (
                                                conversation_earlier.c.created_at
                                                == OutboundActionModel.created_at
                                            )
                                            & (
                                                conversation_earlier.c.id
                                                < OutboundActionModel.id
                                            )
                                        )
                                    )
                                )
                            ),
                        )
                        .order_by(
                            OutboundActionModel.available_at,
                            OutboundActionModel.created_at,
                            OutboundActionModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for action in actions:
                    if action.status == OutboundActionStatus.LEASED:
                        attempt = await session.scalar(
                            select(OutboundDeliveryAttemptModel)
                            .where(
                                OutboundDeliveryAttemptModel.outbound_action_id
                                == action.id,
                                OutboundDeliveryAttemptModel.attempt_number
                                == action.attempt_count,
                            )
                            .with_for_update()
                        )
                        if (
                            attempt is not None
                            and attempt.external_started_at is not None
                        ):
                            action.status = OutboundActionStatus.DELIVERY_UNKNOWN
                            action.last_error_category = "lease_expired"
                            action.last_error_at = now
                            action.completed_at = now
                            action.delivery_unknown_at = now
                            attempt.status = DeliveryAttemptStatus.UNKNOWN
                            attempt.certainty = DeliveryCertainty.UNKNOWN
                            attempt.error_category = "lease_expired"
                            attempt.finished_at = now
                            recovery = await session.scalar(
                                select(OperationalRecoveryItemModel)
                                .where(
                                    OperationalRecoveryItemModel.work_kind
                                    == RecoveryKind.OUTBOUND,
                                    OperationalRecoveryItemModel.work_id == action.id,
                                )
                                .with_for_update()
                            )
                            if recovery is None:
                                recovery = OperationalRecoveryItemModel(
                                    work_kind=RecoveryKind.OUTBOUND,
                                    work_id=action.id,
                                    disposition=RecoveryDisposition.QUARANTINE,
                                    reason=RecoveryReason.AMBIGUOUS_EXTERNAL_DELIVERY,
                                )
                                session.add(recovery)
                                await session.flush()
                            session.add(
                                OperationalRecoveryEventModel(
                                    recovery_item_id=recovery.id,
                                    event_type="classified",
                                    actor="runtime",
                                )
                            )
                            await _update_scheduled_occurrence(
                                session,
                                action,
                                OutboundActionStatus.DELIVERY_UNKNOWN,
                                DeliveryCertainty.UNKNOWN,
                                now,
                                "lease_expired",
                            )
                        else:
                            action.status = OutboundActionStatus.PENDING
                            action.lease_owner = None
                            action.lease_expires_at = None
                            action.available_at = now
                            if attempt is not None:
                                attempt.status = DeliveryAttemptStatus.REJECTED
                                attempt.certainty = DeliveryCertainty.NOT_SENT
                                attempt.error_category = "lease_expired_before_send"
                                attempt.finished_at = now
                        continue
                    action.status = OutboundActionStatus.LEASED
                    action.lease_owner = owner
                    action.lease_expires_at = now + timedelta(seconds=lease_seconds)
                    action.attempt_count += 1
                    session.add(
                        OutboundDeliveryAttemptModel(
                            outbound_action_id=action.id,
                            attempt_number=action.attempt_count,
                            operation=(
                                "editMessageText"
                                if action.kind == OutboundActionKind.EDIT_TEXT
                                else "sendMessage"
                                if action.kind == OutboundActionKind.TEXT
                                else "sendSticker"
                            ),
                            status=DeliveryAttemptStatus.STARTED,
                            certainty=DeliveryCertainty.NOT_SENT,
                            started_at=now,
                        )
                    )
                return [a for a in actions if a.status == OutboundActionStatus.LEASED]

    async def mark_external_started(self, action_id: UUID, owner: str) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.status != OutboundActionStatus.LEASED
                    or action.lease_owner != owner
                ):
                    return False
                attempt = await session.scalar(
                    select(OutboundDeliveryAttemptModel)
                    .where(
                        OutboundDeliveryAttemptModel.outbound_action_id == action.id,
                        OutboundDeliveryAttemptModel.attempt_number
                        == action.attempt_count,
                    )
                    .with_for_update()
                )
                if attempt is None:
                    return False
                now = datetime.now(UTC)
                if action.kind == OutboundActionKind.VOICE:
                    artifact = (
                        await session.get(
                            GeneratedVoiceArtifactModel,
                            action.generated_voice_artifact_id,
                            with_for_update=True,
                        )
                        if action.generated_voice_artifact_id is not None
                        else None
                    )
                    if (
                        artifact is None
                        or artifact.status != VoiceArtifactStatus.READY
                        or artifact.audio_bytes is None
                        or artifact.expires_at <= now
                    ):
                        attempt.status = DeliveryAttemptStatus.REJECTED
                        attempt.certainty = DeliveryCertainty.NOT_SENT
                        attempt.finished_at = now
                        attempt.error_category = "voice_artifact_unavailable"
                        action.status = OutboundActionStatus.PERMANENTLY_FAILED
                        action.lease_owner = None
                        action.lease_expires_at = None
                        action.last_error_category = "voice_artifact_unavailable"
                        action.last_error_at = now
                        action.completed_at = now
                        return False
                if action.origin == ParticipationTrigger.SCHEDULED:
                    allowed = await _scheduled_preflight(session, action, attempt, now)
                    if not allowed:
                        return False
                attempt.external_started_at = now
                return True

    async def scheduled_preflight_outcome(self, action_id: UUID) -> str:
        """Classify a completed scheduled preflight without exposing identifiers."""

        async with self._session_factory() as session:
            row = await session.execute(
                select(
                    OutboundActionModel.status,
                    OutboundActionModel.last_error_category,
                ).where(OutboundActionModel.id == action_id)
            )
            value = row.one_or_none()
            if (
                value is not None
                and value.status == OutboundActionStatus.PENDING
                and value.last_error_category == "scheduled_quiet_hours"
            ):
                return "deferred"
            return "skipped"

    async def mark_reply_fallback(
        self, action_id: UUID, owner: str, error_code: str
    ) -> bool:
        """Durably record the one exact rejected-reply fallback on its attempt."""

        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.status != OutboundActionStatus.LEASED
                    or action.lease_owner != owner
                ):
                    return False
                attempt = await session.scalar(
                    select(OutboundDeliveryAttemptModel)
                    .where(
                        OutboundDeliveryAttemptModel.outbound_action_id == action.id,
                        OutboundDeliveryAttemptModel.attempt_number
                        == action.attempt_count,
                    )
                    .with_for_update()
                )
                if (
                    attempt is None
                    or attempt.external_started_at is None
                    or attempt.reply_fallback_used
                ):
                    return False
                attempt.reply_fallback_used = True
                attempt.reply_fallback_error_code = error_code
                return True

    async def finalize(
        self,
        action_id: UUID,
        owner: str,
        status: OutboundActionStatus,
        attempt_status: DeliveryAttemptStatus,
        certainty: DeliveryCertainty,
        *,
        error_category: str | None = None,
        error_code: str | None = None,
        retry_after_seconds: float | None = None,
        migration_conversation_id: str | None = None,
        available_at: datetime | None = None,
        delivered_platform_message_id: str | None = None,
        delivered_thread_id: str | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.status != OutboundActionStatus.LEASED
                    or action.lease_owner != owner
                ):
                    return False
                now = datetime.now(UTC)
                attempt = await session.scalar(
                    select(OutboundDeliveryAttemptModel)
                    .where(
                        OutboundDeliveryAttemptModel.outbound_action_id == action.id,
                        OutboundDeliveryAttemptModel.attempt_number
                        == action.attempt_count,
                    )
                    .with_for_update()
                )
                if attempt is None:
                    return False
                attempt.status = attempt_status
                attempt.certainty = certainty
                attempt.finished_at = now
                attempt.error_category = error_category
                attempt.error_code = error_code
                attempt.retry_after_seconds = retry_after_seconds
                attempt.migration_conversation_id = migration_conversation_id
                action.status = status
                action.lease_owner = None
                action.lease_expires_at = None
                action.last_error_category = error_category
                action.last_error_code = error_code
                action.last_error_at = now if error_category else None
                action.completed_at = (
                    now if status != OutboundActionStatus.PENDING else None
                )
                action.delivery_unknown_at = (
                    now if status == OutboundActionStatus.DELIVERY_UNKNOWN else None
                )
                if (
                    action.kind == OutboundActionKind.VOICE
                    and action.generated_voice_artifact_id is not None
                    and status != OutboundActionStatus.PENDING
                ):
                    artifact = await session.get(
                        GeneratedVoiceArtifactModel,
                        action.generated_voice_artifact_id,
                        with_for_update=True,
                    )
                    if artifact is not None:
                        artifact.action_terminal_at = now
                        artifact.expires_at = min(
                            artifact.expires_at,
                            now + timedelta(hours=VOICE_ARTIFACT_GRACE_HOURS),
                        )
                if available_at is not None:
                    action.available_at = available_at
                if migration_conversation_id is not None:
                    conversation = await session.get(
                        ConversationModel, action.conversation_id, with_for_update=True
                    )
                    if conversation is None:
                        return False
                    collision = await session.scalar(
                        select(ConversationModel.id).where(
                            ConversationModel.platform_connection_id
                            == conversation.platform_connection_id,
                            ConversationModel.platform_conversation_id
                            == migration_conversation_id,
                            ConversationModel.id != conversation.id,
                        )
                    )
                    if collision is not None:
                        action.status = OutboundActionStatus.PERMANENTLY_FAILED
                        action.available_at = now
                        action.last_error_category = "migration_identity_conflict"
                        action.completed_at = now
                    else:
                        conversation.platform_conversation_id = (
                            migration_conversation_id
                        )
                if delivered_platform_message_id is not None:
                    message = MessageModel(
                        conversation_id=action.conversation_id,
                        outbound_action_id=action.id,
                        platform_message_id=delivered_platform_message_id,
                        direction=MessageDirection.OUTGOING,
                        message_type=(
                            MessageType.TEXT
                            if action.kind == OutboundActionKind.TEXT
                            else MessageType.VOICE
                            if action.kind == OutboundActionKind.VOICE
                            else MessageType.STICKER
                        ),
                        text=(
                            action.text
                            if action.kind == OutboundActionKind.TEXT
                            else None
                        ),
                        reply_to_message_id=action.reply_to_message_id,
                        processing_status=MessageProcessingStatus.PROCESSED,
                        platform_thread_id=delivered_thread_id,
                        content_redacted_at=(
                            action.payload_redacted_at
                            if action.kind.value == "text" and action.text is None
                            else None
                        ),
                    )
                    session.add(message)
                    await session.flush()
                    action.delivered_message_id = message.id
                await _update_scheduled_occurrence(
                    session, action, status, certainty, now, error_category
                )
                return True

    async def finalize_edit_success(
        self, action_id: UUID, owner: str, *, not_modified: bool = False
    ) -> bool:
        """Make edit canonical and terminally suppress its blocked fallback."""

        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.kind != OutboundActionKind.EDIT_TEXT
                    or action.status != OutboundActionStatus.LEASED
                    or action.lease_owner != owner
                    or action.edit_target_message_id is None
                ):
                    return False
                attempt = await self._locked_attempt(session, action)
                fallback = await session.scalar(
                    select(OutboundActionModel)
                    .where(OutboundActionModel.fallback_for_action_id == action.id)
                    .with_for_update()
                )
                target = await session.get(
                    MessageModel, action.edit_target_message_id, with_for_update=True
                )
                if (
                    attempt is None
                    or attempt.external_started_at is None
                    or fallback is None
                    or fallback.status != OutboundActionStatus.FALLBACK_BLOCKED
                    or target is None
                    or target.conversation_id != action.conversation_id
                    or target.platform_message_id
                    != action.edit_target_platform_message_id
                ):
                    return False
                now = datetime.now(UTC)
                attempt.status = DeliveryAttemptStatus.CONFIRMED
                attempt.certainty = DeliveryCertainty.CONFIRMED
                attempt.finished_at = now
                attempt.error_category = (
                    "message_not_modified" if not_modified else None
                )
                action.status = OutboundActionStatus.DELIVERED
                action.lease_owner = None
                action.lease_expires_at = None
                action.completed_at = now
                action.last_error_category = (
                    "message_not_modified" if not_modified else None
                )
                action.last_error_at = now if not_modified else None
                target.text = action.text
                target.edited_at = now
                await session.flush()
                fallback.status = OutboundActionStatus.SKIPPED
                fallback.completed_at = now
                fallback.last_error_category = "edit_succeeded"
                fallback.last_error_at = now
                return True

    async def activate_edit_fallback(
        self, action_id: UUID, owner: str, error_code: str
    ) -> bool:
        """Activate SEND_TEXT only after an exact rejected/non-applied edit."""

        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.kind != OutboundActionKind.EDIT_TEXT
                    or action.status != OutboundActionStatus.LEASED
                    or action.lease_owner != owner
                ):
                    return False
                attempt = await self._locked_attempt(session, action)
                fallback = await session.scalar(
                    select(OutboundActionModel)
                    .where(OutboundActionModel.fallback_for_action_id == action.id)
                    .with_for_update()
                )
                if (
                    attempt is None
                    or attempt.external_started_at is None
                    or fallback is None
                    or fallback.status != OutboundActionStatus.FALLBACK_BLOCKED
                ):
                    return False
                now = datetime.now(UTC)
                attempt.status = DeliveryAttemptStatus.REJECTED
                attempt.certainty = DeliveryCertainty.REJECTED
                attempt.finished_at = now
                attempt.error_category = "edit_target_rejected"
                attempt.error_code = error_code
                action.status = OutboundActionStatus.SKIPPED
                action.lease_owner = None
                action.lease_expires_at = None
                action.completed_at = now
                action.last_error_category = "edit_target_rejected"
                action.last_error_code = error_code
                action.last_error_at = now
                await session.flush()
                fallback.status = OutboundActionStatus.PENDING
                fallback.available_at = now
                return True

    @staticmethod
    async def _locked_attempt(
        session: AsyncSession, action: OutboundActionModel
    ) -> OutboundDeliveryAttemptModel | None:
        attempt: OutboundDeliveryAttemptModel | None = await session.scalar(
            select(OutboundDeliveryAttemptModel)
            .where(
                OutboundDeliveryAttemptModel.outbound_action_id == action.id,
                OutboundDeliveryAttemptModel.attempt_number == action.attempt_count,
            )
            .with_for_update()
        )
        return attempt

    async def requeue_unknown(self, action_id: UUID, actor: str = "operator") -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                action = await session.get(
                    OutboundActionModel, action_id, with_for_update=True
                )
                if (
                    action is None
                    or action.status != OutboundActionStatus.DELIVERY_UNKNOWN
                    or action.governance_export_request_id is not None
                ):
                    return False
                action.status = OutboundActionStatus.PENDING
                action.available_at = datetime.now(UTC)
                action.last_error_category = "operator_requeue_possible_duplicate"
                session.add(
                    OutboundRecoveryEventModel(
                        outbound_action_id=action.id,
                        event_type="requeued_possible_duplicate",
                        actor=actor,
                    )
                )
                return True

    async def classify_recovery(
        self,
        action_id: UUID,
        disposition: RecoveryDisposition,
        reason: RecoveryReason,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                item = await session.scalar(
                    select(OperationalRecoveryItemModel)
                    .where(
                        OperationalRecoveryItemModel.work_kind == RecoveryKind.OUTBOUND,
                        OperationalRecoveryItemModel.work_id == action_id,
                    )
                    .with_for_update()
                )
                if item is None:
                    item = OperationalRecoveryItemModel(
                        work_kind=RecoveryKind.OUTBOUND,
                        work_id=action_id,
                        disposition=disposition,
                        reason=reason,
                    )
                    session.add(item)
                    await session.flush()
                session.add(
                    OperationalRecoveryEventModel(
                        recovery_item_id=item.id,
                        event_type="classified",
                        actor="runtime",
                    )
                )
