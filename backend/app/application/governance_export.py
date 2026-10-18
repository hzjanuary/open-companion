"""Versioned SPEC-025 export package builders.

Subject exports (FR-02) contain the requesting subject's own data, the sole
content-bearing exception under NFR-01. Group exports (FR-03) are bounded to
group configuration, personality, safety settings, revision history, and
group-scope stored data — never individual member message content. Deployment
snapshots (FR-04) are counts and configuration only.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.governance import (
    DATA_INVENTORY,
    DATA_INVENTORY_VERSION,
    DEPLOYMENT_EXPORT_CATEGORIES,
    GOVERNANCE_EXPORT_SCHEMA_VERSION,
    GROUP_EXPORT_CATEGORIES,
    SUBJECT_EXPORT_CATEGORIES,
    ExportManifest,
)
from app.domain.media import MediaStatus
from app.domain.persistence import MemoryKind, MemoryScope, MemoryStatus, MessageType
from app.infrastructure.database.governance import GovernanceStateCounts
from app.infrastructure.database.models import (
    ConversationConfigurationRevisionModel,
    ConversationFeedbackEventModel,
    ConversationFeedbackModel,
    ConversationModel,
    MemoryItemModel,
    MemoryRecallPolicyModel,
    MessageMediaModel,
    MessageModel,
    ParticipantModel,
    ParticipantSchedulePreferenceModel,
    PersonalityProfileVersionModel,
    ProactiveScheduleModel,
    ProactiveScheduleOccurrenceModel,
    ResponsePlanModel,
)


class GovernanceExportBuilder:
    """Build versioned export packages from existing product state."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        retention_days: int = 30,
    ) -> None:
        self._session_factory = session_factory
        self._retention_days = retention_days

    async def build_subject_export(
        self,
        *,
        request_id: UUID,
        conversation_id: UUID,
        participant_id: UUID,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Assemble the subject-scoped export package (FR-02, NFR-01)."""

        created_at = now or datetime.now(UTC)
        async with self._session_factory() as session:
            participant = await session.scalar(
                select(ParticipantModel).where(
                    ParticipantModel.id == participant_id,
                    ParticipantModel.conversation_id == conversation_id,
                )
            )
            if participant is None:
                raise ValueError("participant not found in export conversation")

            messages = list(
                await session.scalars(
                    select(MessageModel).where(
                        MessageModel.conversation_id == conversation_id,
                        MessageModel.participant_id == participant_id,
                    )
                )
            )
            media_by_message = {
                item.message_id: item
                for item in await session.scalars(
                    select(MessageMediaModel)
                    .join(MessageModel, MessageMediaModel.message_id == MessageModel.id)
                    .where(
                        MessageModel.conversation_id == conversation_id,
                        MessageModel.participant_id == participant_id,
                        MessageMediaModel.conversation_id == conversation_id,
                    )
                )
            }
            memories = list(
                await session.scalars(
                    select(MemoryItemModel).where(
                        MemoryItemModel.creator_participant_id == participant_id,
                        MemoryItemModel.conversation_id == conversation_id,
                        MemoryItemModel.status == MemoryStatus.ACTIVE,
                        MemoryItemModel.deleted_at.is_(None),
                        or_(
                            MemoryItemModel.expires_at.is_(None),
                            MemoryItemModel.expires_at > created_at,
                        ),
                    )
                )
            )
            recall_policy = await session.scalar(
                select(MemoryRecallPolicyModel).where(
                    MemoryRecallPolicyModel.participant_id == participant_id,
                    MemoryRecallPolicyModel.conversation_id == conversation_id,
                )
            )
            schedule_preference = await session.scalar(
                select(ParticipantSchedulePreferenceModel).where(
                    ParticipantSchedulePreferenceModel.participant_id == participant_id,
                    ParticipantSchedulePreferenceModel.conversation_id
                    == conversation_id,
                )
            )
            schedules = list(
                await session.scalars(
                    select(ProactiveScheduleModel)
                    .where(
                        ProactiveScheduleModel.creator_participant_id == participant_id,
                        ProactiveScheduleModel.conversation_id == conversation_id,
                    )
                    .order_by(
                        ProactiveScheduleModel.created_at, ProactiveScheduleModel.id
                    )
                )
            )
            schedule_ids = [schedule.id for schedule in schedules]
            occurrences = (
                list(
                    await session.scalars(
                        select(ProactiveScheduleOccurrenceModel)
                        .where(
                            ProactiveScheduleOccurrenceModel.schedule_id.in_(
                                schedule_ids
                            )
                        )
                        .order_by(
                            ProactiveScheduleOccurrenceModel.scheduled_for.desc(),
                            ProactiveScheduleOccurrenceModel.id,
                        )
                        .limit(100)
                    )
                )
                if schedule_ids
                else []
            )
            feedback_current = list(
                await session.execute(
                    select(ConversationFeedbackModel, ResponsePlanModel.created_at)
                    .join(
                        ResponsePlanModel,
                        ResponsePlanModel.id
                        == ConversationFeedbackModel.response_plan_id,
                    )
                    .where(
                        ConversationFeedbackModel.conversation_id == conversation_id,
                        ConversationFeedbackModel.participant_id == participant_id,
                    )
                    .order_by(
                        ConversationFeedbackModel.created_at,
                        ConversationFeedbackModel.id,
                    )
                )
            )
            feedback_history = list(
                await session.execute(
                    select(ConversationFeedbackEventModel, ResponsePlanModel.created_at)
                    .join(
                        ResponsePlanModel,
                        ResponsePlanModel.id
                        == ConversationFeedbackEventModel.response_plan_id,
                    )
                    .where(
                        ConversationFeedbackEventModel.conversation_id
                        == conversation_id,
                        ConversationFeedbackEventModel.participant_id == participant_id,
                    )
                    .order_by(
                        ConversationFeedbackEventModel.created_at,
                        ConversationFeedbackEventModel.revision,
                    )
                )
            )

            data: dict[str, object] = {
                "participant": {
                    "platform_user_id": participant.platform_user_id,
                    "display_name": participant.display_name,
                    "username": participant.username,
                    "role": participant.role,
                    "membership_status": participant.membership_status,
                },
                "preferences": {
                    "mention_allowed": participant.mention_allowed,
                    "teasing_allowed": participant.teasing_allowed,
                    "protected_at": _iso(participant.protected_at),
                },
                "protection": {
                    "protected": participant.protected_at is not None,
                    "privacy_deleted_at": _iso(participant.privacy_deleted_at),
                },
                "messages": [
                    export_message(
                        message,
                        media_by_message.get(message.id),
                        created_at,
                        self._retention_days,
                        participant.privacy_deleted_at is not None,
                    )
                    for message in messages
                ],
                "memories": [
                    {
                        "kind": memory.kind,
                        "context_key": memory.context_key,
                        "scope": memory.scope,
                        "visibility": memory.visibility,
                        "revision": memory.revision,
                        "confidence": memory.confidence,
                        "created_at": _iso(memory.created_at),
                        "updated_at": _iso(memory.updated_at),
                        "expires_at": _iso(memory.expires_at),
                        "content": memory.content,
                    }
                    for memory in memories
                ],
                "memory_recall": {
                    "enabled": (
                        True if recall_policy is None else recall_policy.enabled
                    ),
                    "revision": 0 if recall_policy is None else recall_policy.revision,
                },
                "scheduling": {
                    "preferences": {
                        "timezone": (
                            None
                            if schedule_preference is None
                            else schedule_preference.timezone_name
                        ),
                        "quiet_hours_enabled": (
                            True
                            if schedule_preference is None
                            else schedule_preference.quiet_hours_enabled
                        ),
                        "quiet_start_minute": (
                            1320
                            if schedule_preference is None
                            else schedule_preference.quiet_start_minute
                        ),
                        "quiet_end_minute": (
                            480
                            if schedule_preference is None
                            else schedule_preference.quiet_end_minute
                        ),
                    },
                    "schedules": [
                        {
                            "public_id": schedule.public_id,
                            "kind": schedule.kind,
                            "status": schedule.status,
                            "recurrence": schedule.recurrence,
                            "timezone": schedule.timezone_name,
                            "local_time_minute": schedule.local_time_minute,
                            "weekday_mask": schedule.weekday_mask,
                            "next_run_at": _iso(schedule.next_run_at),
                            "ends_at": _iso(schedule.ends_at),
                            "reminder_text": schedule.reminder_text,
                        }
                        for schedule in schedules
                    ],
                    "recent_occurrences": [
                        {
                            "schedule_public_id": next(
                                (
                                    schedule.public_id
                                    for schedule in schedules
                                    if schedule.id == occurrence.schedule_id
                                ),
                                None,
                            ),
                            "scheduled_for": _iso(occurrence.scheduled_for),
                            "local_date": (
                                occurrence.local_date.isoformat()
                                if occurrence.local_date is not None
                                else None
                            ),
                            "status": occurrence.status,
                            "reason": occurrence.reason_code,
                        }
                        for occurrence in occurrences
                    ],
                },
                "feedback": {
                    "current": [
                        {
                            "value": row.value,
                            "revision": row.revision,
                            "target_response_created_at": _iso(target_created_at),
                            "created_at": _iso(row.created_at),
                            "updated_at": _iso(row.updated_at),
                        }
                        for row, target_created_at in feedback_current
                    ],
                    "history": [
                        {
                            "value": event.value,
                            "revision": event.revision,
                            "target_response_created_at": _iso(target_created_at),
                            "recorded_at": _iso(event.created_at),
                        }
                        for event, target_created_at in feedback_history
                    ],
                },
            }
        return self._package(
            data,
            created_at,
            request_id=request_id,
            scope="subject",
            categories=SUBJECT_EXPORT_CATEGORIES,
        )

    async def build_group_export(
        self,
        *,
        request_id: UUID,
        conversation_id: UUID,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Assemble the group-scoped export package (FR-03).

        Bounded to configuration, personality, safety settings, revision
        history, and group-scope stored data. Member message content is not
        included; member content is available only via the subject export.
        """

        created_at = now or datetime.now(UTC)
        async with self._session_factory() as session:
            conversation = await session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise ValueError("conversation not found")
            revisions = list(
                await session.scalars(
                    select(ConversationConfigurationRevisionModel)
                    .where(
                        ConversationConfigurationRevisionModel.conversation_id
                        == conversation_id
                    )
                    .order_by(
                        ConversationConfigurationRevisionModel.revision_number.asc()
                    )
                )
            )
            personality = list(
                await session.scalars(
                    select(PersonalityProfileVersionModel)
                    .join(
                        ConversationConfigurationRevisionModel,
                        ConversationConfigurationRevisionModel.personality_profile_version_id
                        == PersonalityProfileVersionModel.id,
                    )
                    .where(
                        ConversationConfigurationRevisionModel.conversation_id
                        == conversation_id
                    )
                )
            )
            group_memories = list(
                await session.scalars(
                    select(MemoryItemModel).where(
                        MemoryItemModel.conversation_id == conversation_id,
                        MemoryItemModel.scope == MemoryScope.GROUP_CONVERSATION,
                        MemoryItemModel.kind == MemoryKind.EXPLICIT_FACT,
                        MemoryItemModel.status == MemoryStatus.ACTIVE,
                        MemoryItemModel.deleted_at.is_(None),
                        or_(
                            MemoryItemModel.expires_at.is_(None),
                            MemoryItemModel.expires_at > created_at,
                        ),
                    )
                )
            )
            data: dict[str, object] = {
                "configuration": {
                    "response_mode": conversation.response_mode,
                    "title": conversation.title,
                    "settings": conversation.settings,
                },
                "personality": [
                    {
                        "version_number": version.version_number,
                        "schema_version": version.schema_version,
                        "role": version.role,
                        "primary_language": version.primary_language,
                        "default_length": version.default_length,
                        "formality": version.formality,
                    }
                    for version in personality
                ],
                "safety": [
                    {
                        "revision_number": revision.revision_number,
                        "safety_level": revision.safety_level,
                        "teasing_cap": revision.teasing_cap,
                        "change_source": revision.change_source,
                        "reason_code": revision.reason_code,
                    }
                    for revision in revisions
                ],
                "revision_history": [
                    {
                        "revision_number": revision.revision_number,
                        "response_mode": revision.response_mode,
                        "stickers_enabled": revision.stickers_enabled,
                        "ambient_frequency": revision.ambient_frequency,
                        "change_source": revision.change_source,
                        "changed_at": _iso(revision.updated_at),
                    }
                    for revision in revisions
                ],
                "memories": [
                    {
                        "kind": memory.kind,
                        "revision": memory.revision,
                        "confidence": memory.confidence,
                        "created_at": _iso(memory.created_at),
                        "expires_at": _iso(memory.expires_at),
                        "content": memory.content,
                    }
                    for memory in group_memories
                ],
            }
        return self._package(
            data,
            created_at,
            request_id=request_id,
            scope="group",
            categories=GROUP_EXPORT_CATEGORIES,
        )

    async def build_deployment_snapshot(
        self,
        *,
        request_id: str,
        settings: Settings,
        governance_counts: GovernanceStateCounts,
        now: datetime | None = None,
    ) -> dict[str, object]:
        """Assemble the content-free deployment snapshot (FR-04)."""

        created_at = now or datetime.now(UTC)
        async with self._session_factory() as session:
            volumes = await _data_volumes(session)

        data: dict[str, object] = {
            "data_inventory": {
                "version": DATA_INVENTORY_VERSION,
                "categories": [category.to_dict() for category in DATA_INVENTORY],
            },
            "data_volumes": volumes,
            "retention_configuration": {
                "raw_content_retention_days": settings.raw_content_retention_days,
                "summary_retention": "earliest source-message deadline",
                "safety_review_retention_days": settings.safety_review_retention_days,
                "governance_audit_retention_days": (
                    settings.governance_audit_retention_days
                ),
                "governance_export_ttl_days": settings.governance_export_ttl_days,
                "schedule_history_retention_days": (
                    settings.scheduler_history_retention_days
                ),
            },
            "governance_state": {
                "export_pending": governance_counts.export_pending,
                "export_retrieved": governance_counts.export_retrieved,
                "export_failed": governance_counts.export_failed,
                "erasure_complete": governance_counts.erasure_complete,
                "erasure_partial": governance_counts.erasure_partial,
                "erasure_failed": governance_counts.erasure_failed,
                "packages_cleared": governance_counts.packages_cleared,
                "audit_events": governance_counts.audit_events,
            },
        }
        return self._package(
            data,
            created_at,
            request_id=request_id,
            scope="deployment",
            categories=DEPLOYMENT_EXPORT_CATEGORIES,
        )

    def _package(
        self,
        data: dict[str, object],
        created_at: datetime,
        *,
        request_id: UUID | str,
        scope: str,
        categories: tuple[str, ...],
    ) -> dict[str, object]:
        manifest = ExportManifest(
            schema_version=GOVERNANCE_EXPORT_SCHEMA_VERSION,
            request_id=str(request_id),
            scope=scope,
            generated_at=created_at.isoformat(),
            categories=categories,
        ).to_dict()
        return {
            "schema_version": GOVERNANCE_EXPORT_SCHEMA_VERSION,
            "manifest": manifest,
            "data": data,
        }


def export_message(
    message: MessageModel,
    media: MessageMediaModel | None,
    now: datetime,
    retention_days: int,
    privacy_deleted: bool,
) -> dict[str, object]:
    """Allowlisted subject projection; no raw metadata dictionary is exported."""

    result: dict[str, object] = {
        "direction": message.direction,
        "message_type": message.message_type,
        "sent_at": _iso(message.platform_sent_at or message.created_at),
        "text": _message_text(message),
    }
    is_media = (
        media is not None
        or message.message_type
        in {MessageType.PHOTO, MessageType.VOICE, MessageType.AUDIO}
        or message.metadata_.get("media_kind") == "unsupported_media"
    )
    if not is_media:
        return result
    sent_at = message.platform_sent_at or message.created_at
    retained = (
        not privacy_deleted
        and message.content_redacted_at is None
        and sent_at > now - timedelta(days=retention_days)
        and (media is None or media.status != MediaStatus.REDACTED)
    )
    provenance = message.metadata_.get("content_provenance")
    result["content_provenance"] = (
        provenance
        if retained
        and isinstance(provenance, str)
        and provenance in {"media_caption", "voice_transcript", "audio_transcript"}
        else None
    )
    if not retained:
        result["text"] = None
    result["media"] = (
        {
            "kind": media.kind.value,
            "caption": media.caption,
            "mime_type": media.mime_type,
            "file_id": media.file_id,
            "file_unique_id": media.file_unique_id,
            "file_size": media.file_size,
            "width": media.width,
            "height": media.height,
            "duration_seconds": media.duration_seconds,
            "status": media.status.value,
        }
        if retained and media is not None
        else None
    )
    return result


def _message_text(message: MessageModel) -> str | None:
    if message.content_redacted_at is not None:
        return None
    return message.text


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _data_volumes(session: AsyncSession) -> dict[str, int]:
    """Count rows per primary data category for the deployment snapshot."""

    volumes: dict[str, int] = {}
    for table in (
        "conversations",
        "participants",
        "messages",
        "message_media",
        "memory_items",
        "memory_recall_policies",
        "memory_control_operations",
        "conversation_summaries",
        "safety_policy_decisions",
        "rate_limit_events",
        "safety_review_items",
        "control_deployment_authorities",
        "control_deployment_authority_operations",
        "governance_export_requests",
        "governance_erasure_requests",
        "governance_audit_events",
        "participant_schedule_preferences",
        "proactive_schedules",
        "proactive_schedule_command_receipts",
        "proactive_schedule_occurrences",
        "conversation_feedback",
        "conversation_feedback_events",
    ):
        volumes[table] = await _count_rows(session, table)
    return volumes


async def _count_rows(session: AsyncSession, table: str) -> int:
    result = await session.execute(select(func.count()).select_from(text(table)))
    value = result.scalar()
    return int(value) if value is not None else 0
