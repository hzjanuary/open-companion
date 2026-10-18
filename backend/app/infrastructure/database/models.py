"""Authoritative SQLAlchemy models for the SPEC-002 schema."""

from datetime import date, datetime
from enum import Enum as PythonEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.ambient import AmbientFrequency, ParticipationTrigger
from app.domain.conversation import (
    EligibilityReason,
    MembershipStatus,
    ProcessingOutcome,
)
from app.domain.feedback import FeedbackValue
from app.domain.governance import (
    DeploymentAuthority,
    ErasureRequestStatus,
    ExportRequestStatus,
    GovernanceScope,
)
from app.domain.knowledge import (
    KnowledgeBaseStatus,
    KnowledgeContentType,
    KnowledgeDocumentStatus,
    KnowledgeIndexJobStatus,
    KnowledgeIndexOperation,
    KnowledgeIndexState,
)
from app.domain.media import MediaFailureReason, MediaKind, MediaStatus
from app.domain.outbound import (
    DeliveryAttemptStatus,
    DeliveryCertainty,
    OutboundActionKind,
    OutboundActionStatus,
)
from app.domain.persistence import (
    AssistantStatus,
    CommandAuthorizationOutcome,
    CommandJobStatus,
    ConversationStatus,
    ConversationType,
    IncomingUpdateStatus,
    IngressOutboxStatus,
    IngressSource,
    MemoryDeletionReason,
    MemoryKind,
    MemoryScope,
    MemoryStatus,
    MemoryVisibility,
    MessageDirection,
    MessageProcessingStatus,
    MessageType,
    ParticipantRole,
    PersonalContextKey,
    PersonalityProfileStatus,
    Platform,
    PlatformConnectionStatus,
    ResponseMode,
    SemanticMemoryIndexJobStatus,
    SemanticMemoryIndexOperation,
    TenantStatus,
)
from app.domain.planning import (
    GenerationAttemptKind,
    GenerationAttemptStatus,
    PlanningJobStatus,
    PlanReasonCode,
    ProviderErrorCategory,
    ProviderId,
    StickerIntent,
)
from app.domain.provider_governance import (
    BudgetDecision,
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    BudgetWindowKind,
    EstimateQuality,
    ProviderAttemptOutcome,
    ProviderAttemptState,
    ProviderDataClass,
    ProviderHealth,
    ProviderLifecycle,
    ProviderOperation,
    ReservationState,
    RouteRole,
    UsageQuality,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitOperation, RateLimitScope
from app.domain.recovery import RecoveryDisposition, RecoveryKind, RecoveryReason
from app.domain.safety import (
    InteractionKind,
    ProtectionAction,
    ReviewAction,
    ReviewItemStatus,
    SafetyLevel,
    SafetyOutcome,
    SafetyPolicyVersion,
    SafetyReasonCode,
    SafetySignalType,
    SafetyStage,
)
from app.domain.scheduling import (
    OccurrenceStatus,
    RecurrenceKind,
    ScheduleCommandOutcome,
    ScheduleKind,
    ScheduleOperation,
    ScheduleReason,
    ScheduleStatus,
)
from app.domain.summary import ConversationSummaryStatus
from app.domain.voice import (
    VoiceArtifactStatus,
    VoiceFailureReason,
    VoiceFormat,
    VoiceGenerationStatus,
)
from app.infrastructure.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def string_enum(enum_type: type[PythonEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [str(member.value) for member in values],
        name=name,
    )


class AssistantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assistants"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_assistants_tenant_slug"),
        UniqueConstraint("id", "tenant_id", name="uq_assistants_id_tenant"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[AssistantStatus] = mapped_column(
        string_enum(AssistantStatus, "assistant_status"),
        default=AssistantStatus.DISABLED,
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    knowledge_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sql_text("false"), nullable=False
    )
    default_personality_profile_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personality_profile_versions.id", ondelete="RESTRICT"), index=True
    )


class PlatformConnectionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_connections"
    __table_args__ = (
        UniqueConstraint("platform", "external_bot_id"),
        UniqueConstraint("id", "tenant_id", name="uq_platform_connections_id_tenant"),
        UniqueConstraint(
            "id", "assistant_id", name="uq_platform_connections_id_assistant"
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_platform_connections_assistant_tenant",
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(
        string_enum(Platform, "platform"), nullable=False
    )
    external_bot_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PlatformConnectionStatus] = mapped_column(
        string_enum(PlatformConnectionStatus, "platform_connection_status"),
        default=PlatformConnectionStatus.ACTIVE,
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    credential_reference: Mapped[str | None] = mapped_column(String(255))
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )


class PersonalityProfileModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personality_profiles"
    __table_args__ = (UniqueConstraint("assistant_id", "slug"),)

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[PersonalityProfileStatus] = mapped_column(
        string_enum(PersonalityProfileStatus, "personality_profile_status"),
        default=PersonalityProfileStatus.ACTIVE,
        nullable=False,
    )


class PersonalityProfileVersionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personality_profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version_number"),)

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("personality_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_actor: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_language: Mapped[str] = mapped_column(String(16), nullable=False)
    self_reference: Mapped[str] = mapped_column(String(32), nullable=False)
    default_length: Mapped[str] = mapped_column(String(16), nullable=False)
    formality: Mapped[str] = mapped_column(String(16), nullable=False)
    humor_level: Mapped[float] = mapped_column(nullable=False)
    teasing_level: Mapped[float] = mapped_column(nullable=False)
    emoji_frequency: Mapped[float] = mapped_column(nullable=False)
    sticker_frequency: Mapped[float] = mapped_column(nullable=False)
    use_member_names: Mapped[bool] = mapped_column(Boolean, nullable=False)
    use_inside_jokes: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ask_follow_up_questions: Mapped[str] = mapped_column(String(16), nullable=False)
    allow_sensitive_teasing: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stop_teasing_on_request: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reveal_private_memory_in_groups: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )


class ConversationModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("platform_connection_id", "platform_conversation_id"),
        UniqueConstraint(
            "id", "platform_connection_id", name="uq_conversations_id_connection"
        ),
    )

    platform_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    platform_conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_type: Mapped[ConversationType] = mapped_column(
        string_enum(ConversationType, "conversation_type"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[ConversationStatus] = mapped_column(
        string_enum(ConversationStatus, "conversation_status"),
        default=ConversationStatus.ACTIVE,
        nullable=False,
    )
    response_mode: Mapped[ResponseMode] = mapped_column(
        string_enum(ResponseMode, "response_mode"),
        default=ResponseMode.MENTION_ONLY,
        nullable=False,
    )
    current_configuration_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_configuration_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    assistant_membership_status: Mapped[MembershipStatus | None] = mapped_column(
        string_enum(MembershipStatus, "assistant_membership_status")
    )
    assistant_membership_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_platform_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    memory_privacy_revision: Mapped[int] = mapped_column(default=0, nullable=False)


class ConversationConfigurationRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_configuration_revisions"
    __table_args__ = (UniqueConstraint("conversation_id", "revision_number"),)

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    personality_profile_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("personality_profile_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    response_mode: Mapped[ResponseMode] = mapped_column(
        string_enum(ResponseMode, "configuration_response_mode"), nullable=False
    )
    stickers_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ambient_frequency: Mapped[AmbientFrequency] = mapped_column(
        string_enum(AmbientFrequency, "ambient_frequency"),
        default=AmbientFrequency.NORMAL,
        nullable=False,
    )
    safety_level: Mapped[SafetyLevel] = mapped_column(
        string_enum(SafetyLevel, "configuration_safety_level"),
        default=SafetyLevel.STANDARD,
        nullable=False,
    )
    teasing_cap: Mapped[int] = mapped_column(default=3, nullable=False)
    default_length: Mapped[str | None] = mapped_column(String(16))
    formality: Mapped[str | None] = mapped_column(String(16))
    humor_level: Mapped[float | None] = mapped_column()
    teasing_level: Mapped[float | None] = mapped_column()
    emoji_frequency: Mapped[float | None] = mapped_column()
    sticker_frequency: Mapped[float | None] = mapped_column()
    use_member_names: Mapped[bool | None] = mapped_column(Boolean)
    ask_follow_up_questions: Mapped[str | None] = mapped_column(String(16))
    change_source: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(64))


class ParticipantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("conversation_id", "platform_user_id"),
        UniqueConstraint(
            "id", "conversation_id", name="uq_participants_id_conversation"
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[ParticipantRole] = mapped_column(
        string_enum(ParticipantRole, "participant_role"),
        default=ParticipantRole.MEMBER,
        nullable=False,
    )
    mention_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    teasing_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    protected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    privacy_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
        nullable=False,
    )
    membership_status: Mapped[MembershipStatus] = mapped_column(
        string_enum(MembershipStatus, "participant_membership_status"),
        default=MembershipStatus.MEMBER,
        nullable=False,
    )
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_membership_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class ParticipantSchedulePreferenceModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participant_schedule_preferences"
    __table_args__ = (
        UniqueConstraint("participant_id"),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_preferences_participant_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "quiet_start_minute BETWEEN 0 AND 1439 AND "
            "quiet_end_minute BETWEEN 0 AND 1439 AND "
            "(NOT quiet_hours_enabled OR quiet_start_minute <> quiet_end_minute)",
            name="schedule_preferences_quiet_bounds",
        ),
        CheckConstraint("revision > 0", name="schedule_preferences_revision"),
    )

    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    participant_id: Mapped[UUID] = mapped_column(nullable=False)
    timezone_name: Mapped[str | None] = mapped_column(String(64))
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=sql_text("true"), nullable=False
    )
    quiet_start_minute: Mapped[int] = mapped_column(default=1320, nullable=False)
    quiet_end_minute: Mapped[int] = mapped_column(default=480, nullable=False)
    revision: Mapped[int] = mapped_column(default=1, nullable=False)


class ProactiveScheduleModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proactive_schedules"
    __table_args__ = (
        UniqueConstraint("public_id"),
        UniqueConstraint("source_command_job_id"),
        ForeignKeyConstraint(
            ["creator_participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_proactive_schedule_creator_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "(redacted_at IS NULL AND timezone_name IS NOT NULL "
            "AND local_time_minute BETWEEN 0 AND 1439 "
            "AND starts_on IS NOT NULL AND weekday_mask BETWEEN 0 AND 127) OR "
            "(redacted_at IS NOT NULL AND timezone_name IS NULL "
            "AND local_time_minute IS NULL AND weekday_mask IS NULL "
            "AND starts_on IS NULL AND one_time_at IS NULL)",
            name="schedule_timing_shape",
        ),
        CheckConstraint("version > 0", name="schedule_version"),
        CheckConstraint(
            "(kind = 'reminder' AND ((redacted_at IS NULL "
            "AND reminder_text IS NOT NULL "
            "AND length(btrim(reminder_text)) BETWEEN 1 AND 100) OR "
            "(redacted_at IS NOT NULL AND reminder_text IS NULL))) OR "
            "(kind = 'check_in' AND reminder_text IS NULL)",
            name="schedule_content_shape",
        ),
        Index(
            "ix_proactive_schedules_due",
            "status",
            "next_run_at",
            "created_at",
            "id",
        ),
        Index(
            "ix_proactive_schedules_scope",
            "creator_participant_id",
            "conversation_id",
            "status",
        ),
        Index(
            "uq_proactive_schedules_active_checkin",
            "creator_participant_id",
            "conversation_id",
            unique=True,
            postgresql_where=sql_text("kind = 'check_in' AND status = 'active'"),
        ),
    )

    public_id: Mapped[str] = mapped_column(String(12), nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    creator_participant_id: Mapped[UUID] = mapped_column(nullable=False)
    source_command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[ScheduleKind] = mapped_column(
        string_enum(ScheduleKind, "schedule_kind"), nullable=False
    )
    status: Mapped[ScheduleStatus] = mapped_column(
        string_enum(ScheduleStatus, "schedule_status"),
        default=ScheduleStatus.ACTIVE,
        nullable=False,
    )
    recurrence: Mapped[RecurrenceKind] = mapped_column(
        string_enum(RecurrenceKind, "schedule_recurrence"), nullable=False
    )
    timezone_name: Mapped[str | None] = mapped_column(String(64))
    local_time_minute: Mapped[int | None] = mapped_column()
    weekday_mask: Mapped[int | None] = mapped_column()
    starts_on: Mapped[date | None] = mapped_column(Date)
    one_time_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminder_text: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProactiveScheduleCommandReceiptModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proactive_schedule_command_receipts"
    __table_args__ = (
        UniqueConstraint("command_job_id"),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_receipt_participant_conversation",
            ondelete="RESTRICT",
        ),
    )

    command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    participant_id: Mapped[UUID] = mapped_column(nullable=False)
    schedule_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proactive_schedules.id", ondelete="RESTRICT")
    )
    operation: Mapped[ScheduleOperation] = mapped_column(
        string_enum(ScheduleOperation, "schedule_receipt_operation"), nullable=False
    )
    outcome: Mapped[ScheduleCommandOutcome] = mapped_column(
        string_enum(ScheduleCommandOutcome, "schedule_receipt_outcome"), nullable=False
    )


class ProactiveScheduleOccurrenceModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "proactive_schedule_occurrences"
    __table_args__ = (
        UniqueConstraint("schedule_id", "local_date"),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_schedule_occurrence_participant_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint("attempt_count >= 0", name="schedule_occurrence_attempts"),
        CheckConstraint("schedule_version > 0", name="schedule_occurrence_version"),
        CheckConstraint("privacy_revision >= 0", name="schedule_occurrence_privacy"),
        CheckConstraint(
            "(redacted_at IS NULL AND scheduled_for IS NOT NULL "
            "AND local_date IS NOT NULL) OR "
            "(redacted_at IS NOT NULL AND status = 'history_redacted' "
            "AND scheduled_for IS NULL AND local_date IS NULL)",
            name="schedule_occurrence_history_shape",
        ),
        Index(
            "ix_schedule_occurrences_claim",
            "status",
            "available_at",
            "scheduled_for",
            "id",
        ),
        Index(
            "ix_schedule_occurrences_lease",
            "status",
            "lease_expires_at",
            "id",
        ),
    )

    schedule_id: Mapped[UUID] = mapped_column(
        ForeignKey("proactive_schedules.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    participant_id: Mapped[UUID] = mapped_column(nullable=False)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    local_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[OccurrenceStatus] = mapped_column(
        string_enum(OccurrenceStatus, "schedule_occurrence_status"),
        default=OccurrenceStatus.PENDING,
        nullable=False,
    )
    reason_code: Mapped[ScheduleReason] = mapped_column(
        string_enum(ScheduleReason, "schedule_occurrence_reason"),
        default=ScheduleReason.NONE,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    schedule_version: Mapped[int] = mapped_column(nullable=False)
    privacy_revision: Mapped[int] = mapped_column(nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "platform_message_id"),
        UniqueConstraint("id", "conversation_id", name="uq_messages_id_conversation"),
        ForeignKeyConstraint(
            ["reply_to_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_messages_reply_conversation",
            ondelete="RESTRICT",
        ),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    platform_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    outbound_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    direction: Mapped[MessageDirection] = mapped_column(
        string_enum(MessageDirection, "message_direction"), nullable=False
    )
    message_type: Mapped[MessageType] = mapped_column(
        string_enum(MessageType, "message_type"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(index=True)
    reply_to_platform_message_id: Mapped[str | None] = mapped_column(String(255))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
        nullable=False,
    )
    processing_status: Mapped[MessageProcessingStatus] = mapped_column(
        string_enum(MessageProcessingStatus, "message_processing_status"),
        default=MessageProcessingStatus.PENDING,
        nullable=False,
    )
    platform_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_thread_id: Mapped[str | None] = mapped_column(String(255))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    mentions_assistant: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    replies_to_assistant: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    eligible: Mapped[bool | None] = mapped_column(Boolean)
    eligibility_reason: Mapped[EligibilityReason | None] = mapped_column(
        string_enum(EligibilityReason, "message_eligibility_reason")
    )
    reply_to: Mapped["MessageModel | None"] = relationship(
        remote_side="MessageModel.id", foreign_keys=[reply_to_message_id]
    )


class MessageMediaModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Source-scoped fetch metadata and recovery state; never raw media bytes."""

    __tablename__ = "message_media"
    __table_args__ = (
        UniqueConstraint("message_id"),
        ForeignKeyConstraint(
            ["message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            ondelete="RESTRICT",
            name="fk_message_media_message_conversation",
        ),
        CheckConstraint(
            "file_size IS NULL OR file_size BETWEEN 1 AND 10485760",
            name="media_file_size",
        ),
        CheckConstraint(
            "width IS NULL OR width BETWEEN 1 AND 4096", name="media_width"
        ),
        CheckConstraint(
            "height IS NULL OR height BETWEEN 1 AND 4096", name="media_height"
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds BETWEEN 0 AND 300",
            name="media_duration",
        ),
        CheckConstraint(
            "planning_attempt >= 0 AND privacy_revision >= 0",
            name="media_revision_bounds",
        ),
        CheckConstraint(
            "(status = 'preparing' AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND planning_attempt > 0) OR "
            "(status <> 'preparing' AND lease_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="media_lease_shape",
        ),
        CheckConstraint(
            "(status IN ('pending','preparing','complete') AND failure_reason IS NULL) "
            "OR (status IN ('failed','ambiguous','redacted') "
            "AND failure_reason IS NOT NULL)",
            name="media_outcome_shape",
        ),
        CheckConstraint(
            "(status = 'redacted' AND file_id IS NULL AND file_unique_id IS NULL "
            "AND caption IS NULL AND file_size IS NULL AND width IS NULL "
            "AND height IS NULL AND duration_seconds IS NULL AND mime_type IS NULL "
            "AND redacted_at IS NOT NULL) OR "
            "(status <> 'redacted' AND file_id IS NOT NULL "
            "AND file_unique_id IS NOT NULL AND mime_type IS NOT NULL "
            "AND file_id ~ '^[A-Za-z0-9_-]{1,255}$' "
            "AND file_unique_id ~ '^[A-Za-z0-9_-]{1,255}$' "
            "AND redacted_at IS NULL AND "
            "((kind = 'photo' AND mime_type = 'image/jpeg' "
            "AND width IS NOT NULL AND height IS NOT NULL "
            "AND duration_seconds IS NULL) "
            "OR (kind IN ('voice','audio') AND duration_seconds IS NOT NULL "
            "AND width IS NULL AND height IS NULL AND "
            "((kind = 'voice' AND mime_type = 'audio/ogg') "
            "OR (kind = 'audio' AND mime_type = 'audio/mpeg')))))",
            name="media_content_shape",
        ),
        Index("ix_message_media_recovery", "status", "lease_expires_at", "id"),
    )

    message_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    kind: Mapped[MediaKind] = mapped_column(string_enum(MediaKind, "media_kind"))
    file_id: Mapped[str | None] = mapped_column(String(255))
    file_unique_id: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(32))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column()
    height: Mapped[int | None] = mapped_column()
    duration_seconds: Mapped[int | None] = mapped_column()
    caption: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[MediaStatus] = mapped_column(
        string_enum(MediaStatus, "media_status"),
        default=MediaStatus.PENDING,
        server_default="pending",
        nullable=False,
    )
    failure_reason: Mapped[MediaFailureReason | None] = mapped_column(
        string_enum(MediaFailureReason, "media_failure_reason")
    )
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planning_attempt: Mapped[int] = mapped_column(default=0, server_default="0")
    privacy_revision: Mapped[int] = mapped_column(default=0, server_default="0")
    source_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationSummaryModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint("conversation_id", "source_window_hash", "schema_version"),
        Index(
            "ix_conversation_summaries_active",
            "conversation_id",
            "platform_thread_id",
            "status",
            "expires_at",
        ),
        Index("ix_conversation_summaries_expiry", "status", "expires_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_thread_id: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[ProviderId | None] = mapped_column(
        string_enum(ProviderId, "conversation_summary_provider")
    )
    model: Mapped[str | None] = mapped_column(String(255))
    source_first_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    source_last_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    source_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_count: Mapped[int] = mapped_column(nullable=False)
    source_window_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ConversationSummaryStatus] = mapped_column(
        string_enum(ConversationSummaryStatus, "conversation_summary_status"),
        default=ConversationSummaryStatus.COMPLETED,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_reason: Mapped[str | None] = mapped_column(String(64))


class ConversationSummaryJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_summary_jobs"
    __table_args__ = (
        UniqueConstraint("conversation_id", "source_window_hash", "schema_version"),
        Index(
            "ix_conversation_summary_jobs_claim", "status", "available_at", "created_at"
        ),
        Index("ix_conversation_summary_jobs_lease", "status", "lease_expires_at"),
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_thread_id: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_first_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    source_last_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    source_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_count: Mapped[int] = mapped_column(nullable=False)
    source_window_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[ConversationSummaryStatus] = mapped_column(
        string_enum(ConversationSummaryStatus, "conversation_summary_job_status"),
        default=ConversationSummaryStatus.PENDING,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[ProviderErrorCategory | None] = mapped_column(
        string_enum(ProviderErrorCategory, "conversation_summary_error_category")
    )


class IncomingPlatformUpdateModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "incoming_platform_updates"
    __table_args__ = (
        UniqueConstraint("platform_connection_id", "platform_update_id"),
        Index("ix_incoming_platform_updates_pending", "status", "received_at"),
        Index(
            "ix_incoming_platform_updates_connection_received",
            "platform_connection_id",
            "received_at",
        ),
    )

    platform_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"), nullable=False
    )
    platform: Mapped[Platform] = mapped_column(
        string_enum(Platform, "incoming_platform"), nullable=False
    )
    platform_update_id: Mapped[str] = mapped_column(String(255), nullable=False)
    update_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ingress_source: Mapped[IngressSource] = mapped_column(
        string_enum(IngressSource, "ingress_source"), nullable=False
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[IncomingUpdateStatus] = mapped_column(
        string_enum(IncomingUpdateStatus, "incoming_update_status"),
        default=IncomingUpdateStatus.RECEIVED,
        nullable=False,
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class IngressOutboxEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingress_outbox_events"
    __table_args__ = (
        UniqueConstraint("incoming_update_id"),
        Index(
            "ix_ingress_outbox_events_pending", "status", "available_at", "created_at"
        ),
    )

    incoming_update_id: Mapped[UUID] = mapped_column(
        ForeignKey("incoming_platform_updates.id", ondelete="RESTRICT"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(
        String(64), default="ingress.received", nullable=False
    )
    schema_version: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[IngressOutboxStatus] = mapped_column(
        string_enum(IngressOutboxStatus, "ingress_outbox_status"),
        default=IngressOutboxStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(64))


class PollingCursorModel(Base):
    __tablename__ = "polling_cursors"

    platform_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"), primary_key=True
    )
    next_offset: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConversationProcessingRecordModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_processing_records"
    __table_args__ = (UniqueConstraint("incoming_update_id"),)

    incoming_update_id: Mapped[UUID] = mapped_column(
        ForeignKey("incoming_platform_updates.id", ondelete="RESTRICT"), nullable=False
    )
    outcome: Mapped[ProcessingOutcome] = mapped_column(
        string_enum(ProcessingOutcome, "conversation_processing_outcome"),
        nullable=False,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), index=True
    )
    eligible: Mapped[bool | None] = mapped_column(Boolean)
    eligibility_reason: Mapped[EligibilityReason | None] = mapped_column(
        string_enum(EligibilityReason, "processing_eligibility_reason")
    )
    permanent_error: Mapped[str | None] = mapped_column(String(64))


class ResponsePlanningJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "response_planning_jobs"
    __table_args__ = (
        UniqueConstraint("conversation_processing_record_id"),
        Index(
            "ix_response_planning_jobs_claim", "status", "available_at", "created_at"
        ),
        Index("ix_response_planning_jobs_lease", "status", "lease_expires_at"),
        CheckConstraint(
            "spec033_valid_knowledge_provenance(knowledge_provenance::jsonb)",
            name="response_planning_knowledge_provenance_shape",
        ),
        CheckConstraint(
            "(source_command_job_id IS NULL AND root_response_plan_id IS NULL "
            "AND parent_response_plan_id IS NULL AND regeneration_ordinal IS NULL) "
            "OR (source_command_job_id IS NOT NULL "
            "AND root_response_plan_id IS NOT NULL "
            "AND parent_response_plan_id IS NOT NULL "
            "AND regeneration_ordinal BETWEEN 1 AND 3)",
            name="response_planning_regeneration_shape",
        ),
        UniqueConstraint("root_response_plan_id", "regeneration_ordinal"),
    )

    conversation_processing_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_processing_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_command_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), unique=True
    )
    root_response_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), index=True
    )
    parent_response_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), index=True
    )
    regeneration_ordinal: Mapped[int | None] = mapped_column()
    personality_profile_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("personality_profile_versions.id", ondelete="RESTRICT"), index=True
    )
    configuration_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_configuration_revisions.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[PlanningJobStatus] = mapped_column(
        string_enum(PlanningJobStatus, "response_planning_job_status"),
        default=PlanningJobStatus.PENDING,
        nullable=False,
    )
    trigger: Mapped[ParticipationTrigger] = mapped_column(
        string_enum(ParticipationTrigger, "planning_participation_trigger"),
        default=ParticipationTrigger.ADDRESSED,
        nullable=False,
    )
    ambient_policy_version: Mapped[str | None] = mapped_column(String(64))
    ambient_reason: Mapped[str | None] = mapped_column(String(64))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    response_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_provider: Mapped[ProviderId | None] = mapped_column(
        string_enum(ProviderId, "response_planning_provider")
    )
    selected_model: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[ProviderErrorCategory | None] = mapped_column(
        string_enum(ProviderErrorCategory, "response_planning_error_category")
    )
    safety_policy_version: Mapped[SafetyPolicyVersion] = mapped_column(
        string_enum(SafetyPolicyVersion, "response_planning_safety_policy_version"),
        default=SafetyPolicyVersion.V1,
        nullable=False,
    )
    knowledge_provenance: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, default=list, server_default=sql_text("'[]'::jsonb"), nullable=False
    )


class TelegramCommandJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telegram_command_jobs"
    __table_args__ = (
        UniqueConstraint("conversation_processing_record_id"),
        Index("ix_telegram_command_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_telegram_command_jobs_lease", "status", "lease_expires_at"),
    )

    conversation_processing_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversation_processing_records.id", ondelete="RESTRICT"),
        nullable=False,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    command_name: Mapped[str] = mapped_column(String(32), nullable=False)
    arguments: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[CommandJobStatus] = mapped_column(
        string_enum(CommandJobStatus, "telegram_command_job_status"),
        default=CommandJobStatus.PENDING,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    authorization_outcome: Mapped[CommandAuthorizationOutcome | None] = mapped_column(
        string_enum(CommandAuthorizationOutcome, "command_authorization_outcome")
    )
    result_code: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    arguments_redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class TelegramVoiceGenerationJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "telegram_voice_generation_jobs"
    __table_args__ = (
        UniqueConstraint("command_job_id"),
        UniqueConstraint(
            "id",
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            name="uq_voice_jobs_id_scope",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_voice_jobs_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_voice_jobs_connection_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name="fk_voice_jobs_connection_assistant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name="fk_voice_jobs_conversation_connection",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "source_character_count BETWEEN 1 AND 4000",
            name="voice_job_source_size",
        ),
        CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'", name="voice_job_source_checksum"
        ),
        CheckConstraint("privacy_revision >= 0", name="voice_job_privacy_revision"),
        CheckConstraint(
            "(status = 'leased' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'leased' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="voice_job_lease_shape",
        ),
        CheckConstraint(
            "(status IN ('pending','leased') AND failure_reason IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND failure_reason IS NULL "
            "AND completed_at IS NOT NULL) OR "
            "(status IN ('io_possible','failed','stale') "
            "AND failure_reason IS NOT NULL AND completed_at IS NOT NULL)",
            name="voice_job_outcome_shape",
        ),
        Index("ix_voice_jobs_recovery", "status", "lease_expires_at", "created_at"),
    )

    command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"), nullable=False
    )
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    source_response_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), nullable=False
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_character_count: Mapped[int] = mapped_column(nullable=False)
    privacy_revision: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[VoiceGenerationStatus] = mapped_column(
        string_enum(VoiceGenerationStatus, "voice_generation_status"), nullable=False
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    provider_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_usage_attempts.id", ondelete="RESTRICT")
    )
    failure_reason: Mapped[VoiceFailureReason | None] = mapped_column(
        string_enum(VoiceFailureReason, "voice_failure_reason")
    )
    io_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationFeedbackModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_feedback"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            "response_plan_id",
            "participant_id",
            name="uq_conversation_feedback_current",
        ),
        UniqueConstraint(
            "id",
            "tenant_id",
            "assistant_id",
            "connection_id",
            "conversation_id",
            "response_plan_id",
            "participant_id",
            name="uq_conversation_feedback_id_scope",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_conversation_feedback_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_conversation_feedback_connection_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name="fk_conversation_feedback_connection_assistant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name="fk_conversation_feedback_conversation_connection",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_conversation_feedback_participant_conversation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_conversation_feedback_target_message",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_outbound_action_id", "conversation_id"],
            ["outbound_actions.id", "outbound_actions.conversation_id"],
            name="fk_conversation_feedback_target_action",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision BETWEEN 1 AND 10", name="conversation_feedback_revision"
        ),
        Index("ix_conversation_feedback_participant", "participant_id", "created_at"),
        Index("ix_conversation_feedback_response", "response_plan_id"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"), nullable=False
    )
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    response_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), nullable=False
    )
    participant_id: Mapped[UUID] = mapped_column(nullable=False)
    target_message_id: Mapped[UUID] = mapped_column(nullable=False)
    target_outbound_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[FeedbackValue] = mapped_column(
        string_enum(FeedbackValue, "conversation_feedback_value"), nullable=False
    )
    revision: Mapped[int] = mapped_column(nullable=False)


class ConversationFeedbackEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_feedback_events"
    __table_args__ = (
        UniqueConstraint("command_job_id"),
        UniqueConstraint("feedback_id", "revision"),
        ForeignKeyConstraint(
            [
                "feedback_id",
                "tenant_id",
                "assistant_id",
                "connection_id",
                "conversation_id",
                "response_plan_id",
                "participant_id",
            ],
            [
                "conversation_feedback.id",
                "conversation_feedback.tenant_id",
                "conversation_feedback.assistant_id",
                "conversation_feedback.connection_id",
                "conversation_feedback.conversation_id",
                "conversation_feedback.response_plan_id",
                "conversation_feedback.participant_id",
            ],
            name="fk_conversation_feedback_events_current_scope",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_conversation_feedback_events_target_message",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_outbound_action_id", "conversation_id"],
            ["outbound_actions.id", "outbound_actions.conversation_id"],
            name="fk_conversation_feedback_events_target_action",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "revision BETWEEN 1 AND 10",
            name="conversation_feedback_event_revision",
        ),
        Index(
            "ix_conversation_feedback_events_participant",
            "participant_id",
            "created_at",
        ),
    )

    feedback_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    response_plan_id: Mapped[UUID] = mapped_column(nullable=False)
    participant_id: Mapped[UUID] = mapped_column(nullable=False)
    target_message_id: Mapped[UUID] = mapped_column(nullable=False)
    target_outbound_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"), nullable=False
    )
    command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[FeedbackValue] = mapped_column(
        string_enum(FeedbackValue, "conversation_feedback_event_value"), nullable=False
    )
    revision: Mapped[int] = mapped_column(nullable=False)


class GeneratedVoiceArtifactModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "generated_voice_artifacts"
    __table_args__ = (
        UniqueConstraint("generation_job_id"),
        UniqueConstraint(
            "id", "conversation_id", name="uq_voice_artifacts_id_conversation"
        ),
        ForeignKeyConstraint(
            [
                "generation_job_id",
                "tenant_id",
                "assistant_id",
                "connection_id",
                "conversation_id",
            ],
            [
                "telegram_voice_generation_jobs.id",
                "telegram_voice_generation_jobs.tenant_id",
                "telegram_voice_generation_jobs.assistant_id",
                "telegram_voice_generation_jobs.connection_id",
                "telegram_voice_generation_jobs.conversation_id",
            ],
            name="fk_voice_artifacts_job_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "format = 'ogg_opus' AND mime_type = 'audio/ogg'",
            name="voice_artifact_format",
        ),
        CheckConstraint("byte_size BETWEEN 1 AND 5242880", name="voice_artifact_size"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="voice_artifact_checksum"),
        CheckConstraint(
            "(status = 'ready' AND audio_bytes IS NOT NULL "
            "AND octet_length(audio_bytes) = byte_size AND purged_at IS NULL) OR "
            "(status = 'purged' AND audio_bytes IS NULL AND purged_at IS NOT NULL)",
            name="voice_artifact_content_shape",
        ),
        CheckConstraint(
            "expires_at <= created_at + interval '7 days'",
            name="voice_artifact_expiry_bound",
        ),
        Index("ix_voice_artifacts_retention", "status", "expires_at", "created_at"),
    )

    generation_job_id: Mapped[UUID] = mapped_column(nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    connection_id: Mapped[UUID] = mapped_column(nullable=False)
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    source_response_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), nullable=False
    )
    format: Mapped[VoiceFormat] = mapped_column(
        string_enum(VoiceFormat, "voice_artifact_format_enum"), nullable=False
    )
    mime_type: Mapped[str] = mapped_column(String(32), nullable=False)
    audio_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    byte_size: Mapped[int] = mapped_column(nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[VoiceArtifactStatus] = mapped_column(
        string_enum(VoiceArtifactStatus, "voice_artifact_status"), nullable=False
    )
    action_terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MemoryItemModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (
        UniqueConstraint("public_id"),
        UniqueConstraint("source_command_job_id"),
        CheckConstraint("revision > 0", name="memory_revision_positive"),
        CheckConstraint(
            "(kind = 'explicit_fact' AND context_key IS NULL "
            "AND visibility = 'same_conversation') OR "
            "(kind = 'personal_context' AND context_key IS NOT NULL "
            "AND context_key IN ('preferred_name','preferred_language',"
            "'response_preference','accessibility_preference','personal_note') "
            "AND visibility = 'creator_only' AND scope = 'private_conversation')",
            name="memory_kind_shape",
        ),
        ForeignKeyConstraint(
            ["creator_participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_memory_items_creator_conversation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["platform_connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name="fk_memory_items_connection_assistant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "platform_connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name="fk_memory_items_conversation_connection",
            ondelete="RESTRICT",
        ),
        Index("ix_memory_items_active_conversation", "conversation_id", "status"),
        Index(
            "uq_memory_items_active_personal_context_key",
            "creator_participant_id",
            "conversation_id",
            "context_key",
            unique=True,
            postgresql_where=sql_text(
                "status = 'active' AND kind = 'personal_context'"
            ),
        ),
        Index(
            "ix_memory_items_owner_scope",
            "creator_participant_id",
            "conversation_id",
            "status",
        ),
    )

    public_id: Mapped[str] = mapped_column(String(24), nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False
    )
    creator_participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[MemoryKind] = mapped_column(
        string_enum(MemoryKind, "memory_kind"), nullable=False
    )
    scope: Mapped[MemoryScope] = mapped_column(
        string_enum(MemoryScope, "memory_scope"), nullable=False
    )
    visibility: Mapped[MemoryVisibility] = mapped_column(
        string_enum(MemoryVisibility, "memory_visibility"), nullable=False
    )
    context_key: Mapped[PersonalContextKey | None] = mapped_column(
        string_enum(PersonalContextKey, "personal_context_key")
    )
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[MemoryStatus] = mapped_column(
        string_enum(MemoryStatus, "memory_status"),
        default=MemoryStatus.ACTIVE,
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text)
    normalized_content_hash: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False
    )
    source_command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_reason: Mapped[MemoryDeletionReason | None] = mapped_column(
        string_enum(MemoryDeletionReason, "memory_deletion_reason")
    )


class MemoryEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free audit trail for memory mutations."""

    __tablename__ = "memory_events"

    memory_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="RESTRICT"), index=True
    )
    command_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), index=True
    )
    actor_participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    action_code: Mapped[str] = mapped_column(String(64), nullable=False)
    deletion_reason: Mapped[str | None] = mapped_column(String(32))
    affected_count: Mapped[int | None] = mapped_column()


class MemoryRecallPolicyModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Participant-owned exact-conversation memory recall authority."""

    __tablename__ = "memory_recall_policies"
    __table_args__ = (
        UniqueConstraint("participant_id", "conversation_id"),
        ForeignKeyConstraint(
            ["participant_id", "conversation_id"],
            ["participants.id", "participants.conversation_id"],
            name="fk_memory_recall_participant_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision > 0", name="memory_recall_revision_positive"),
        ForeignKeyConstraint(
            ["platform_connection_id", "assistant_id"],
            ["platform_connections.id", "platform_connections.assistant_id"],
            name="fk_memory_recall_connection_assistant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "platform_connection_id"],
            ["conversations.id", "conversations.platform_connection_id"],
            name="fk_memory_recall_conversation_connection",
            ondelete="RESTRICT",
        ),
    )

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    platform_connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    source_command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )


class MemoryControlOperationModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free idempotency/result ledger for SPEC-027 commands."""

    __tablename__ = "memory_control_operations"
    __table_args__ = (
        UniqueConstraint("command_job_id"),
        CheckConstraint(
            "operation IN ('remember','context_create','update','delete',"
            "'clear','recall_disable','recall_enable')",
            name="memory_control_operation_value",
        ),
        CheckConstraint(
            "status IN ('in_progress','complete')",
            name="memory_control_operation_status",
        ),
        CheckConstraint(
            "outcome IN ('created','updated','deleted','cleared','enabled',"
            "'disabled','unchanged','conflict','missing','denied',"
            "'scope_denied','limit_reached')",
            name="memory_control_operation_outcome",
        ),
        CheckConstraint(
            "affected_count >= 0", name="memory_control_affected_nonnegative"
        ),
        CheckConstraint(
            "resulting_revision IS NULL OR resulting_revision > 0",
            name="memory_control_revision_positive",
        ),
    )

    command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    actor_participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("memory_items.id", ondelete="RESTRICT"), index=True
    )
    resulting_revision: Mapped[int | None] = mapped_column()
    affected_count: Mapped[int] = mapped_column(default=0, nullable=False)
    recall_enabled: Mapped[bool | None] = mapped_column(Boolean)


class ExplicitMemorySemanticIndexJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable derived-index work; canonical memory text never enters this row."""

    __tablename__ = "explicit_memory_semantic_index_jobs"
    __table_args__ = (
        UniqueConstraint("memory_id", "operation", "embedding_version"),
        Index("ix_semantic_memory_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_semantic_memory_jobs_lease", "status", "lease_expires_at"),
    )

    memory_id: Mapped[UUID] = mapped_column(
        ForeignKey("memory_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    operation: Mapped[SemanticMemoryIndexOperation] = mapped_column(
        string_enum(SemanticMemoryIndexOperation, "semantic_memory_index_operation"),
        nullable=False,
    )
    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    target_collection: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[SemanticMemoryIndexJobStatus] = mapped_column(
        string_enum(SemanticMemoryIndexJobStatus, "semantic_memory_index_job_status"),
        default=SemanticMemoryIndexJobStatus.PENDING,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExplicitMemorySemanticIndexCollectionModel(
    UUIDPrimaryKeyMixin, TimestampMixin, Base
):
    """Active physical Qdrant collection for one compatible embedding version."""

    __tablename__ = "explicit_memory_semantic_index_collections"
    __table_args__ = (UniqueConstraint("embedding_version"),)

    embedding_version: Mapped[str] = mapped_column(String(64), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(128), nullable=False)


class ParticipantPreferenceEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "participant_preference_events"
    __table_args__ = (UniqueConstraint("command_job_id"),)

    participant_id: Mapped[UUID] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    command_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    previous_mention_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    mention_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    previous_teasing_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    teasing_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)


class ModelGenerationAttemptModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "model_generation_attempts"
    __table_args__ = (UniqueConstraint("planning_job_id", "attempt_number"),)

    planning_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[ProviderId] = mapped_column(
        string_enum(ProviderId, "generation_attempt_provider"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    attempt_kind: Mapped[GenerationAttemptKind] = mapped_column(
        string_enum(GenerationAttemptKind, "generation_attempt_kind"), nullable=False
    )
    status: Mapped[GenerationAttemptStatus] = mapped_column(
        string_enum(GenerationAttemptStatus, "generation_attempt_status"),
        nullable=False,
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()
    total_tokens: Mapped[int | None] = mapped_column()
    latency_milliseconds: Mapped[int | None] = mapped_column()
    error_category: Mapped[ProviderErrorCategory | None] = mapped_column(
        string_enum(ProviderErrorCategory, "generation_attempt_error_category")
    )
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    diagnostic_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )


class ResponsePlanModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "response_plans"
    __table_args__ = (
        UniqueConstraint("planning_job_id"),
        UniqueConstraint("command_job_id"),
        UniqueConstraint("schedule_occurrence_id"),
        CheckConstraint(
            "((planning_job_id IS NOT NULL)::int + "
            "(command_job_id IS NOT NULL)::int + "
            "(schedule_occurrence_id IS NOT NULL)::int) = 1",
            name="response_plan_exactly_one_source",
        ),
        CheckConstraint(
            "text IS NULL OR char_length(text) <= 13600",
            name="response_plan_text_size",
        ),
    )

    planning_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT")
    )
    command_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT")
    )
    schedule_occurrence_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("proactive_schedule_occurrences.id", ondelete="RESTRICT")
    )
    should_respond: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason_code: Mapped[PlanReasonCode] = mapped_column(
        string_enum(PlanReasonCode, "response_plan_reason_code"), nullable=False
    )
    text: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), index=True
    )
    mention_participant_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sticker_intent: Mapped[StickerIntent | None] = mapped_column(
        string_enum(StickerIntent, "response_plan_sticker_intent")
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    language: Mapped[str | None] = mapped_column(String(16))
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    content_redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    interaction_kind: Mapped[InteractionKind] = mapped_column(
        string_enum(InteractionKind, "response_plan_interaction_kind"),
        default=InteractionKind.NEUTRAL,
        nullable=False,
    )
    teasing_target_participant_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=sql_text("'[]'::jsonb"), nullable=False
    )


class SafetyPolicyDecisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free record of a deterministic safety gate outcome."""

    __tablename__ = "safety_policy_decisions"

    planning_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT"), index=True
    )
    response_plan_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    policy_version: Mapped[SafetyPolicyVersion] = mapped_column(
        string_enum(SafetyPolicyVersion, "safety_decision_policy_version"),
        nullable=False,
    )
    stage: Mapped[SafetyStage] = mapped_column(
        string_enum(SafetyStage, "safety_decision_stage"), nullable=False
    )
    outcome: Mapped[SafetyOutcome] = mapped_column(
        string_enum(SafetyOutcome, "safety_decision_outcome"), nullable=False
    )
    reason_code: Mapped[SafetyReasonCode | None] = mapped_column(
        string_enum(SafetyReasonCode, "safety_decision_reason_code")
    )
    transformed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class RateLimitEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free result of a distributed generation or delivery check."""

    __tablename__ = "rate_limit_events"

    planning_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT"), index=True
    )
    outbound_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"), index=True
    )
    voice_generation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_voice_generation_jobs.id", ondelete="RESTRICT"),
        index=True,
    )
    operation: Mapped[RateLimitOperation] = mapped_column(
        string_enum(RateLimitOperation, "rate_limit_operation"), nullable=False
    )
    limiting_scope: Mapped[RateLimitScope | None] = mapped_column(
        string_enum(RateLimitScope, "rate_limit_scope")
    )
    provider_id: Mapped[str | None] = mapped_column(String(32))
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    retry_after_seconds: Mapped[int | None] = mapped_column()
    configuration_version: Mapped[str] = mapped_column(String(64), nullable=False)


class SafetyReviewItemModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bounded, content-free SPEC-024 moderation review queue item.

    Carries categories, stage, outcome counts, opaque references, protection
    state, and status only. Never message text, prompts, memories, usernames,
    or raw platform identifiers (NFR-01/FR-12).
    """

    __tablename__ = "safety_review_items"

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[SafetySignalType] = mapped_column(
        string_enum(SafetySignalType, "safety_signal_type"), nullable=False
    )
    stage: Mapped[SafetyStage] = mapped_column(
        string_enum(SafetyStage, "safety_decision_stage"), nullable=False
    )
    outcome_counts: Mapped[dict[str, int]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    protection_state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    status: Mapped[ReviewItemStatus] = mapped_column(
        string_enum(ReviewItemStatus, "safety_review_status"),
        default=ReviewItemStatus.OPEN,
        nullable=False,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action: Mapped[ReviewAction | None] = mapped_column(
        string_enum(ReviewAction, "safety_review_action")
    )
    actor_participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    actioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(64))
    protection_action: Mapped[ProtectionAction | None] = mapped_column(
        string_enum(ProtectionAction, "safety_protection_action")
    )


class OutboundActionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_actions"
    __table_args__ = (
        UniqueConstraint("response_plan_id", "sequence_number"),
        UniqueConstraint("idempotency_key"),
        UniqueConstraint(
            "id", "conversation_id", name="uq_outbound_actions_id_conversation"
        ),
        ForeignKeyConstraint(
            ["reply_to_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_outbound_actions_reply_conversation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["generated_voice_artifact_id", "conversation_id"],
            [
                "generated_voice_artifacts.id",
                "generated_voice_artifacts.conversation_id",
            ],
            name="fk_outbound_voice_artifact_conversation",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["edit_target_message_id", "conversation_id"],
            ["messages.id", "messages.conversation_id"],
            name="fk_outbound_actions_edit_target_conversation",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "sequence_number BETWEEN 1 AND sequence_count "
            "AND sequence_count BETWEEN 1 AND 5",
            name="outbound_action_sequence_bounds",
        ),
        CheckConstraint(
            "text IS NULL OR char_length(text) <= 3400",
            name="outbound_action_text_size",
        ),
        CheckConstraint(
            "(kind = 'edit_text' AND edit_target_message_id IS NOT NULL "
            "AND edit_target_platform_message_id IS NOT NULL "
            "AND fallback_for_action_id IS NULL "
            "AND (text IS NOT NULL OR payload_redacted_at IS NOT NULL)) OR "
            "(kind <> 'edit_text' AND edit_target_message_id IS NULL "
            "AND edit_target_platform_message_id IS NULL) ",
            name="outbound_action_edit_shape",
        ),
        CheckConstraint(
            "fallback_for_action_id IS NULL OR "
            "(kind = 'text' AND fallback_for_action_id <> id)",
            name="outbound_action_fallback_shape",
        ),
        Index("ix_outbound_actions_claim", "status", "available_at", "created_at"),
        Index("ix_outbound_actions_lease", "status", "lease_expires_at"),
    )

    response_plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("response_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    governance_export_request_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("governance_export_requests.id", ondelete="RESTRICT"),
        unique=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    sequence_count: Mapped[int] = mapped_column(default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[OutboundActionKind] = mapped_column(
        string_enum(OutboundActionKind, "outbound_action_kind"), nullable=False
    )
    origin: Mapped[ParticipationTrigger] = mapped_column(
        string_enum(ParticipationTrigger, "outbound_participation_origin"),
        default=ParticipationTrigger.ADDRESSED,
        nullable=False,
    )
    status: Mapped[OutboundActionStatus] = mapped_column(
        string_enum(OutboundActionStatus, "outbound_action_status"),
        default=OutboundActionStatus.PENDING,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    reply_to_message_id: Mapped[UUID | None] = mapped_column(index=True)
    edit_target_message_id: Mapped[UUID | None] = mapped_column(index=True)
    edit_target_platform_message_id: Mapped[str | None] = mapped_column(String(255))
    fallback_for_action_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"), unique=True, index=True
    )
    generated_voice_artifact_id: Mapped[UUID | None] = mapped_column(
        unique=True, index=True
    )
    message_thread_id: Mapped[str | None] = mapped_column(String(255))
    text: Mapped[str | None] = mapped_column(Text)
    mention_participant_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sticker_intent: Mapped[StickerIntent | None] = mapped_column(
        string_enum(StickerIntent, "outbound_sticker_intent")
    )
    delivered_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("messages.id", ondelete="RESTRICT"), unique=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_unknown_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_redacted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )


class OutboundDeliveryAttemptModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("outbound_action_id", "attempt_number"),
        CheckConstraint(
            "(NOT reply_fallback_used AND reply_fallback_error_code IS NULL) OR "
            "(reply_fallback_used AND reply_fallback_error_code IS NOT NULL)",
            name="outbound_attempt_reply_fallback_shape",
        ),
    )

    outbound_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(nullable=False)
    platform: Mapped[str] = mapped_column(
        String(32), default="telegram", nullable=False
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    external_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_milliseconds: Mapped[int | None] = mapped_column()
    status: Mapped[DeliveryAttemptStatus] = mapped_column(
        string_enum(DeliveryAttemptStatus, "outbound_delivery_attempt_status"),
        nullable=False,
    )
    certainty: Mapped[DeliveryCertainty] = mapped_column(
        string_enum(DeliveryCertainty, "outbound_delivery_certainty"), nullable=False
    )
    error_category: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_after_seconds: Mapped[float | None] = mapped_column()
    reply_fallback_used: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    reply_fallback_error_code: Mapped[str | None] = mapped_column(String(64))
    migration_conversation_id: Mapped[str | None] = mapped_column(String(255))


class OutboundRecoveryEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "outbound_recovery_events"

    outbound_action_id: Mapped[UUID] = mapped_column(
        ForeignKey("outbound_actions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)


class OperationalRecoveryItemModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic recovery classification; deliberately contains no business content."""

    __tablename__ = "operational_recovery_items"
    __table_args__ = (
        UniqueConstraint("work_kind", "work_id"),
        Index("ix_operational_recovery_items_disposition", "disposition", "created_at"),
    )

    work_kind: Mapped[RecoveryKind] = mapped_column(
        string_enum(RecoveryKind, "recovery_work_kind"), nullable=False
    )
    work_id: Mapped[UUID] = mapped_column(nullable=False)
    disposition: Mapped[RecoveryDisposition] = mapped_column(
        string_enum(RecoveryDisposition, "recovery_disposition"), nullable=False
    )
    reason: Mapped[RecoveryReason] = mapped_column(
        string_enum(RecoveryReason, "recovery_reason"), nullable=False
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OperationalRecoveryEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "operational_recovery_events"

    recovery_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("operational_recovery_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)


class ControlTenantModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_tenants"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint("revision > 0", name="control_tenant_revision_positive"),
    )

    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        string_enum(TenantStatus, "tenant_status"),
        nullable=False,
        default=TenantStatus.ACTIVE,
    )
    revision: Mapped[int] = mapped_column(default=1, nullable=False)


class ControlOperatorIdentityModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_operator_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlOperatorMembershipModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_operator_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "identity_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlDeploymentAuthorityModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SPEC-025 deployment authority, deliberately independent of tenants."""

    __tablename__ = "control_deployment_authorities"
    __table_args__ = (
        UniqueConstraint("identity_id", "authority"),
        CheckConstraint(
            "authority = 'deployment_operator'",
            name="control_deployment_authority_value",
        ),
    )

    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    authority: Mapped[str] = mapped_column(
        String(32), default=DeploymentAuthority.DEPLOYMENT_OPERATOR, nullable=False
    )
    granted_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_by_identity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ControlDeploymentAuthorityOperationModel(
    UUIDPrimaryKeyMixin, TimestampMixin, Base
):
    """Content-free idempotency fence for deployment authority mutations."""

    __tablename__ = "control_deployment_authority_operations"
    __table_args__ = (
        UniqueConstraint("actor_identity_id", "operation", "request_id"),
        CheckConstraint(
            "operation IN ('grant', 'revoke')",
            name="control_deployment_authority_operation_value",
        ),
    )

    actor_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resulting_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ControlAssistantBindingModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_assistant_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "assistant_id"),
        UniqueConstraint(
            "assistant_id", name="uq_control_assistant_bindings_assistant"
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_control_assistant_binding_owner",
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class ControlConnectionBindingModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_connection_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id"),
        UniqueConstraint(
            "connection_id", name="uq_control_connection_bindings_connection"
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_control_connection_binding_owner",
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class ControlGroupBindingModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_group_bindings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "connection_id", "external_group_id"),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_control_group_binding_owner",
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_group_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    current_revision: Mapped[int] = mapped_column(default=0, nullable=False)


class ControlGroupRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_group_configuration_revisions"
    __table_args__ = (UniqueConstraint("group_id", "revision"),)

    group_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_group_bindings.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(nullable=False)
    parent_revision: Mapped[int | None] = mapped_column()
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255))


class ControlAuditEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_audit_events"

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        index=True,
    )
    actor_identity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
        nullable=False,
    )


class ControlIdempotencyKeyModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "control_idempotency_keys"
    __table_args__ = (UniqueConstraint("tenant_id", "identity_id", "operation", "key"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    operation: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int] = mapped_column(nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class GovernanceExportRequestModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free SPEC-025 export request lifecycle (FR-02/03/04).

    Carries scope, opaque references, status, and closed failure reasons only.
    The single-use token is stored as a hash; the package body lives in
    GovernanceExportPackageModel and is cleared on retrieval or expiry.
    """

    __tablename__ = "governance_export_requests"
    __table_args__ = (
        UniqueConstraint("single_use_token_hash"),
        UniqueConstraint("source_control_identity_id", "source_control_request_id"),
        CheckConstraint(
            "(source_control_identity_id IS NULL) = "
            "(source_control_request_id IS NULL)",
            name="governance_export_control_source_pair",
        ),
        CheckConstraint(
            "NOT (source_command_job_id IS NOT NULL AND "
            "source_control_identity_id IS NOT NULL)",
            name="governance_export_single_source",
        ),
        Index(
            "ix_governance_export_requests_status_available",
            "status",
            "available_at",
        ),
        Index(
            "ix_governance_export_requests_scope_subject",
            "scope",
            "conversation_id",
            "participant_id",
        ),
    )

    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=ExportRequestStatus.REQUESTED, nullable=False
    )
    categories: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=sql_text("'[]'::jsonb"), nullable=False
    )
    single_use_token_hash: Mapped[str | None] = mapped_column(String(64))
    source_command_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), unique=True
    )
    source_control_identity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT")
    )
    source_control_request_id: Mapped[str | None] = mapped_column(String(128))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(64))


class GovernanceExportPackageModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Temporary single-use export package (NFR-01 exception for subject scope).

    Carries the versioned JSON package and its content-free manifest. Cleared
    on single-use retrieval and purged on expiry by the retention worker.
    """

    __tablename__ = "governance_export_packages"

    export_request_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_export_requests.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    package: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceErasureRequestModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-free SPEC-025 erasure request and completion status (FR-05/06)."""

    __tablename__ = "governance_erasure_requests"
    __table_args__ = (
        Index(
            "ix_governance_erasure_requests_scope_subject",
            "scope",
            "conversation_id",
            "participant_id",
        ),
    )

    scope: Mapped[str] = mapped_column(
        String(16), default=GovernanceScope.SUBJECT, nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT"), index=True
    )
    source_command_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_command_jobs.id", ondelete="RESTRICT"), unique=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(32), default=ErasureRequestStatus.REQUESTED, nullable=False
    )
    partial_reason: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool] = mapped_column(default=True, nullable=False)
    requested_via: Mapped[str] = mapped_column(
        String(32), default="telegram_command", nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GovernanceAuditEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Content-safe SPEC-025 governance audit trail (FR-12).

    Carries event type, scope, opaque request references, closed outcomes, and
    timestamps only — never content, credentials, or secrets.
    """

    __tablename__ = "governance_audit_events"
    __table_args__ = (UniqueConstraint("request_id", "event_type"),)

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(100))
    conversation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    participant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("participants.id", ondelete="RESTRICT")
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT"), index=True
    )
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(128))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=sql_text("'{}'::jsonb"),
        nullable=False,
    )


class ProviderCapabilityModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Immutable, non-secret provider capability registration."""

    __tablename__ = "provider_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "provider_id", "model", "workload_class", "capability_schema_version"
        ),
        CheckConstraint(
            "capability_schema_version = 'provider-capability-v1'",
            name="provider_capability_schema_version",
        ),
        CheckConstraint(
            "provider_id = adapter_key AND credential_slot = adapter_key",
            name="provider_capability_adapter_identity",
        ),
        CheckConstraint(
            "workload_class <> 'embedding' OR "
            "(provider_id = 'ollama' AND data_class = 'local')",
            name="provider_capability_embedding_boundary",
        ),
        CheckConstraint(
            "workload_class <> 'transcription' OR provider_id = 'groq'",
            name="provider_capability_transcription_boundary",
        ),
    )

    provider_id: Mapped[ProviderId] = mapped_column(
        string_enum(ProviderId, "provider_capability_provider"), nullable=False
    )
    adapter_key: Mapped[ProviderId] = mapped_column(
        string_enum(ProviderId, "provider_capability_adapter"), nullable=False
    )
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_capability_workload"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    capability_schema_version: Mapped[str] = mapped_column(
        String(64), default="provider-capability-v1", nullable=False
    )
    capability_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    data_class: Mapped[ProviderDataClass] = mapped_column(
        string_enum(ProviderDataClass, "provider_capability_data_class"),
        nullable=False,
    )
    credential_slot: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_configured: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reservation_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProviderHealthPolicyRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_health_policy_revisions"
    __table_args__ = (
        UniqueConstraint("capability_id", "version"),
        CheckConstraint("version > 0", name="provider_health_policy_version_positive"),
        CheckConstraint(
            "observation_window_seconds > 0 AND degraded_threshold > 0 AND "
            "unavailable_threshold >= degraded_threshold AND "
            "recovery_success_threshold > 0 AND stale_after_seconds > 0",
            name="provider_health_policy_bounds",
        ),
    )

    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    observation_window_seconds: Mapped[int] = mapped_column(nullable=False)
    degraded_threshold: Mapped[int] = mapped_column(nullable=False)
    unavailable_threshold: Mapped[int] = mapped_column(nullable=False)
    recovery_success_threshold: Mapped[int] = mapped_column(nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProviderCapabilityStateModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_capability_states"
    __table_args__ = (UniqueConstraint("capability_id"),)

    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    lifecycle: Mapped[ProviderLifecycle] = mapped_column(
        string_enum(ProviderLifecycle, "provider_capability_lifecycle"),
        nullable=False,
    )
    health: Mapped[ProviderHealth | None] = mapped_column(
        string_enum(ProviderHealth, "provider_capability_health")
    )
    health_policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_health_policy_revisions.id", ondelete="RESTRICT")
    )
    consecutive_successes: Mapped[int] = mapped_column(default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(default=0, nullable=False)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(default=1, nullable=False)


class ProviderHealthEventModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_health_events"
    __table_args__ = (
        Index(
            "ix_provider_health_events_capability_created",
            "capability_id",
            "created_at",
        ),
    )

    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    from_state: Mapped[ProviderHealth | None] = mapped_column(
        string_enum(ProviderHealth, "provider_health_event_from")
    )
    to_state: Mapped[ProviderHealth | None] = mapped_column(
        string_enum(ProviderHealth, "provider_health_event_to")
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)


class ProviderRoutingPolicyRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_routing_policy_revisions"
    __table_args__ = (
        UniqueConstraint("scope_key", "workload_class", "version"),
        CheckConstraint("version > 0", name="provider_routing_version_positive"),
        CheckConstraint(
            "(scope_type = 'deployment' AND tenant_id IS NULL AND assistant_id IS NULL "
            "AND connection_id IS NULL) OR (scope_type = 'assistant' AND tenant_id IS "
            "NOT NULL AND assistant_id IS NOT NULL AND connection_id IS NULL) OR "
            "(scope_type = 'platform_connection' AND tenant_id IS NOT NULL AND "
            "assistant_id IS NULL AND connection_id IS NOT NULL)",
            name="provider_routing_scope_shape",
        ),
        CheckConstraint(
            "schema_version = 'provider-routing-v1'",
            name="provider_routing_schema_version",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_provider_routing_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_provider_routing_connection_owner",
            ondelete="RESTRICT",
        ),
    )

    scope_type: Mapped[BudgetScope] = mapped_column(
        string_enum(BudgetScope, "provider_routing_scope"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT")
    )
    assistant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT")
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT")
    )
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_routing_workload"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=sql_text("'{}'::jsonb"), nullable=False
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProviderRoutingPolicyRouteModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_routing_policy_routes"
    __table_args__ = (
        UniqueConstraint("policy_revision_id", "position"),
        UniqueConstraint("policy_revision_id", "capability_id"),
        CheckConstraint("position >= 0", name="provider_route_position_nonnegative"),
    )

    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_routing_policy_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(nullable=False)


class ProviderRoutingFallbackReasonModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_routing_fallback_reasons"
    __table_args__ = (UniqueConstraint("policy_revision_id", "reason"),)

    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_routing_policy_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(64), nullable=False)


class ProviderRoutingPolicyHeadModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_routing_policy_heads"
    __table_args__ = (UniqueConstraint("scope_key", "workload_class"),)

    scope_key: Mapped[str] = mapped_column(String(80), nullable=False)
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_routing_head_workload"), nullable=False
    )
    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_routing_policy_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    lock_version: Mapped[int] = mapped_column(default=1, nullable=False)


class ProviderWorkPolicySnapshotModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_work_policy_snapshots"
    __table_args__ = (
        UniqueConstraint("source_key", "workload_class"),
        CheckConstraint(
            "num_nonnulls(planning_job_id, summary_job_id, "
            "semantic_index_job_id, knowledge_index_job_id, "
            "voice_generation_job_id) = 1",
            name="provider_work_snapshot_one_source",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_provider_snapshot_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_provider_snapshot_connection_owner",
            ondelete="RESTRICT",
        ),
    )

    source_key: Mapped[str] = mapped_column(String(96), nullable=False)
    planning_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT")
    )
    summary_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_summary_jobs.id", ondelete="RESTRICT")
    )
    semantic_index_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("explicit_memory_semantic_index_jobs.id", ondelete="RESTRICT")
    )
    knowledge_index_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_index_jobs.id", ondelete="RESTRICT")
    )
    voice_generation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_voice_generation_jobs.id", ondelete="RESTRICT")
    )
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_work_snapshot_workload"), nullable=False
    )
    policy_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_routing_policy_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT")
    )
    assistant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT")
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT")
    )


class ProviderPriceRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_price_revisions"
    __table_args__ = (
        UniqueConstraint("capability_id", "currency", "unit_basis", "effective_from"),
        CheckConstraint("currency = 'USD'", name="provider_price_currency"),
        CheckConstraint(
            "unit_basis IN ('generation_tokens','embedding_request',"
            "'transcription_request','tts_request')",
            name="provider_price_unit_basis",
        ),
        CheckConstraint(
            "(unit_basis = 'generation_tokens' AND input_rate IS NOT NULL AND "
            "output_rate IS NOT NULL AND request_rate IS NULL) OR "
            "(unit_basis IN "
            "('embedding_request','transcription_request','tts_request') "
            "AND input_rate IS NULL AND output_rate IS NULL "
            "AND request_rate IS NOT NULL)",
            name="provider_price_shape",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="provider_price_effective_range",
        ),
        CheckConstraint(
            "input_rate IS NULL OR input_rate >= 0", name="provider_price_input_rate"
        ),
        CheckConstraint(
            "output_rate IS NULL OR output_rate >= 0", name="provider_price_output_rate"
        ),
        CheckConstraint(
            "request_rate IS NULL OR request_rate >= 0",
            name="provider_price_request_rate",
        ),
    )

    capability_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    unit_basis: Mapped[str] = mapped_column(String(32), nullable=False)
    input_rate: Mapped[int | None] = mapped_column(BigInteger)
    output_rate: Mapped[int | None] = mapped_column(BigInteger)
    request_rate: Mapped[int | None] = mapped_column(BigInteger)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProviderBudgetModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budgets"
    __table_args__ = (
        UniqueConstraint("scope_key", "workload_class", "measurement", "window_kind"),
        CheckConstraint(
            "(scope_type = 'deployment' AND tenant_id IS NULL AND assistant_id IS NULL "
            "AND connection_id IS NULL) OR (scope_type = 'assistant' AND tenant_id IS "
            "NOT NULL AND assistant_id IS NOT NULL AND connection_id IS NULL) OR "
            "(scope_type = 'platform_connection' AND tenant_id IS NOT NULL AND "
            "assistant_id IS NULL AND connection_id IS NOT NULL)",
            name="provider_budget_scope_shape",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_provider_budget_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_provider_budget_connection_owner",
            ondelete="RESTRICT",
        ),
    )

    scope_type: Mapped[BudgetScope] = mapped_column(
        string_enum(BudgetScope, "provider_budget_scope"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT")
    )
    assistant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT")
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT")
    )
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_budget_workload"), nullable=False
    )
    measurement: Mapped[BudgetMeasurement] = mapped_column(
        string_enum(BudgetMeasurement, "provider_budget_measurement"), nullable=False
    )
    window_kind: Mapped[BudgetWindowKind] = mapped_column(
        string_enum(BudgetWindowKind, "provider_budget_window_kind"), nullable=False
    )


class ProviderBudgetRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budget_revisions"
    __table_args__ = (
        UniqueConstraint("budget_id", "version"),
        CheckConstraint("version > 0", name="provider_budget_version_positive"),
        CheckConstraint("amount > 0", name="provider_budget_amount_positive"),
        CheckConstraint(
            "alert_threshold_bps BETWEEN 0 AND 10000",
            name="provider_budget_alert_threshold",
        ),
    )

    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mode: Mapped[BudgetMode] = mapped_column(
        string_enum(BudgetMode, "provider_budget_mode"), nullable=False
    )
    alert_threshold_bps: Mapped[int] = mapped_column(nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )


class ProviderBudgetHeadModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budget_heads"
    __table_args__ = (UniqueConstraint("budget_id"),)

    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    budget_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budget_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    lock_version: Mapped[int] = mapped_column(default=1, nullable=False)


class ProviderBudgetWindowModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budget_windows"
    __table_args__ = (
        UniqueConstraint("budget_id", "window_start"),
        CheckConstraint(
            "window_end > window_start", name="provider_budget_window_range"
        ),
        CheckConstraint(
            "reserved_amount >= 0 AND consumed_amount >= 0",
            name="provider_budget_window_nonnegative",
        ),
    )

    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    reserved_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    consumed_amount: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    lock_version: Mapped[int] = mapped_column(default=1, nullable=False)


class ProviderUsageAttemptModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_usage_attempts"
    __table_args__ = (
        UniqueConstraint("attempt_key"),
        UniqueConstraint("source_key", "operation", "attempt_ordinal"),
        CheckConstraint(
            "num_nonnulls(planning_job_id, summary_job_id, "
            "semantic_index_job_id, knowledge_index_job_id, "
            "voice_generation_job_id) = 1",
            name="provider_usage_attempt_one_source",
        ),
        CheckConstraint(
            "attempt_ordinal > 0", name="provider_attempt_ordinal_positive"
        ),
        CheckConstraint(
            "request_count BETWEEN 0 AND 1", name="provider_attempt_request_count"
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="provider_usage_input"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="provider_usage_output"
        ),
        CheckConstraint(
            "total_tokens IS NULL OR total_tokens >= 0", name="provider_usage_total"
        ),
        CheckConstraint(
            "(usage_quality IN ('missing','invalid') AND input_tokens IS NULL "
            "AND output_tokens IS NULL AND total_tokens IS NULL) OR "
            "(usage_quality = 'complete' AND input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND (total_tokens IS NULL OR "
            "total_tokens = input_tokens + output_tokens)) OR "
            "(usage_quality = 'partial' "
            "AND num_nonnulls(input_tokens, output_tokens, total_tokens) > 0 "
            "AND NOT (input_tokens IS NOT NULL AND output_tokens IS NOT NULL))",
            name="provider_usage_quality_shape",
        ),
        CheckConstraint(
            "estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0",
            name="provider_usage_cost",
        ),
        CheckConstraint(
            "(estimate_quality = 'unavailable' "
            "AND estimated_cost_microusd IS NULL) OR "
            "(estimate_quality <> 'unavailable' "
            "AND estimated_cost_microusd IS NOT NULL)",
            name="provider_estimate_quality_shape",
        ),
        CheckConstraint(
            "state <> 'no_io' OR (estimate_quality = 'unavailable' "
            "AND estimated_cost_microusd IS NULL)",
            name="provider_no_io_has_no_cost",
        ),
        CheckConstraint(
            "(state IN ('reserved','io_started') AND provider_outcome = 'pending') OR "
            "(state = 'io_complete' AND provider_outcome IN "
            "('success','refused','provider_error','invalid_output')) OR "
            "(state = 'no_io' AND provider_outcome IN "
            "('budget_denied','rate_limited','concurrency_limited',"
            "'no_eligible_route','governance_unavailable','recovered_no_io')) OR "
            "(state = 'io_possible' "
            "AND provider_outcome = 'recovered_io_possible')",
            name="provider_attempt_state_outcome_shape",
        ),
        CheckConstraint(
            "application_outcome IS NULL OR application_outcome IN "
            "('accepted','refused','invalid_output')",
            name="provider_application_outcome",
        ),
        CheckConstraint(
            "state = 'no_io' OR record_origin = 'legacy_backfill' OR "
            "health_policy_revision_id IS NOT NULL",
            name="provider_usage_health_policy_reference",
        ),
        CheckConstraint(
            "state <> 'reserved' OR "
            "(reserved_at IS NOT NULL AND reservation_owner IS NOT NULL "
            "AND reservation_expires_at IS NOT NULL AND request_count = 0 "
            "AND io_started_at IS NULL AND io_completed_at IS NULL)",
            name="provider_usage_reserved_lease_shape",
        ),
        CheckConstraint(
            "(state IN ('reserved','no_io') AND request_count = 0) OR "
            "(state IN ('io_started','io_complete','io_possible') "
            "AND request_count = 1)",
            name="provider_usage_io_count_shape",
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_provider_usage_assistant_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["platform_connections.id", "platform_connections.tenant_id"],
            name="fk_provider_usage_connection_owner",
            ondelete="RESTRICT",
        ),
    )

    attempt_key: Mapped[str] = mapped_column(String(96), nullable=False)
    source_key: Mapped[str] = mapped_column(String(96), nullable=False)
    record_origin: Mapped[str] = mapped_column(String(32), nullable=False)
    planning_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("response_planning_jobs.id", ondelete="RESTRICT")
    )
    summary_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("conversation_summary_jobs.id", ondelete="RESTRICT")
    )
    semantic_index_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("explicit_memory_semantic_index_jobs.id", ondelete="RESTRICT")
    )
    knowledge_index_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_index_jobs.id", ondelete="RESTRICT")
    )
    voice_generation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("telegram_voice_generation_jobs.id", ondelete="RESTRICT")
    )
    workload_class: Mapped[WorkloadClass] = mapped_column(
        string_enum(WorkloadClass, "provider_usage_workload"), nullable=False
    )
    operation: Mapped[ProviderOperation] = mapped_column(
        string_enum(ProviderOperation, "provider_usage_operation"), nullable=False
    )
    attempt_ordinal: Mapped[int] = mapped_column(nullable=False)
    route_role: Mapped[RouteRole] = mapped_column(
        string_enum(RouteRole, "provider_usage_route_role"), nullable=False
    )
    capability_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_capabilities.id", ondelete="RESTRICT")
    )
    policy_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_work_policy_snapshots.id", ondelete="RESTRICT")
    )
    price_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_price_revisions.id", ondelete="RESTRICT")
    )
    health_policy_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("provider_health_policy_revisions.id", ondelete="RESTRICT")
    )
    provider_id: Mapped[ProviderId] = mapped_column(
        string_enum(ProviderId, "provider_usage_provider"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control_tenants.id", ondelete="RESTRICT")
    )
    assistant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assistants.id", ondelete="RESTRICT")
    )
    connection_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_connections.id", ondelete="RESTRICT")
    )
    state: Mapped[ProviderAttemptState] = mapped_column(
        string_enum(ProviderAttemptState, "provider_attempt_state"), nullable=False
    )
    provider_outcome: Mapped[ProviderAttemptOutcome] = mapped_column(
        string_enum(ProviderAttemptOutcome, "provider_attempt_outcome"), nullable=False
    )
    application_outcome: Mapped[str | None] = mapped_column(String(64))
    error_category: Mapped[str | None] = mapped_column(String(64))
    retryable: Mapped[bool | None] = mapped_column(Boolean)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    request_count: Mapped[int] = mapped_column(default=0, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    usage_quality: Mapped[UsageQuality] = mapped_column(
        string_enum(UsageQuality, "provider_usage_quality"), nullable=False
    )
    estimate_quality: Mapped[EstimateQuality] = mapped_column(
        string_enum(EstimateQuality, "provider_estimate_quality"), nullable=False
    )
    estimated_cost_microusd: Mapped[int | None] = mapped_column(BigInteger)
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reservation_owner: Mapped[str | None] = mapped_column(String(255))
    reservation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    io_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    io_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovery_reason: Mapped[str | None] = mapped_column(String(64))


class ProviderBudgetEvaluationModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budget_evaluations"
    __table_args__ = (
        UniqueConstraint("attempt_id", "budget_id"),
        CheckConstraint(
            "limit_amount > 0 AND reserved_before >= 0 AND consumed_before >= 0 "
            "AND (requested_amount IS NULL OR requested_amount >= 0)",
            name="provider_budget_evaluation_amounts",
        ),
        CheckConstraint(
            "(decision = 'unavailable' AND requested_amount IS NULL) OR "
            "(decision <> 'unavailable' AND requested_amount IS NOT NULL)",
            name="provider_budget_evaluation_unknown_shape",
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_usage_attempts.id", ondelete="CASCADE"), nullable=False
    )
    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    budget_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budget_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    window_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budget_windows.id", ondelete="RESTRICT"), nullable=False
    )
    decision: Mapped[BudgetDecision] = mapped_column(
        string_enum(BudgetDecision, "provider_budget_decision"), nullable=False
    )
    limit_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reserved_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    consumed_before: Mapped[int] = mapped_column(BigInteger, nullable=False)
    requested_amount: Mapped[int | None] = mapped_column(BigInteger)


class ProviderBudgetReservationModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "provider_budget_reservations"
    __table_args__ = (
        UniqueConstraint("attempt_id", "budget_id"),
        CheckConstraint(
            "reserved_amount >= 0 AND reconciled_amount >= 0",
            name="provider_reservation_nonnegative",
        ),
    )

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_usage_attempts.id", ondelete="CASCADE"), nullable=False
    )
    budget_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budgets.id", ondelete="RESTRICT"), nullable=False
    )
    window_id: Mapped[UUID] = mapped_column(
        ForeignKey("provider_budget_windows.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[ReservationState] = mapped_column(
        string_enum(ReservationState, "provider_reservation_state"), nullable=False
    )
    reserved_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reconciled_amount: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False
    )


class KnowledgeBaseModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint(
            "assistant_id", "slug", name="uq_knowledge_bases_assistant_slug"
        ),
        UniqueConstraint(
            "id", "tenant_id", "assistant_id", name="uq_knowledge_bases_owner"
        ),
        ForeignKeyConstraint(
            ["assistant_id", "tenant_id"],
            ["assistants.id", "assistants.tenant_id"],
            name="fk_knowledge_bases_assistant_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_knowledge_bases_owner_status", "tenant_id", "assistant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        string_enum(KnowledgeBaseStatus, "knowledge_base_status"),
        default=KnowledgeBaseStatus.DRAFT,
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id", "slug", name="uq_knowledge_documents_base_slug"
        ),
        UniqueConstraint(
            "id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_documents_owner",
        ),
        ForeignKeyConstraint(
            ["knowledge_base_id", "tenant_id", "assistant_id"],
            [
                "knowledge_bases.id",
                "knowledge_bases.tenant_id",
                "knowledge_bases.assistant_id",
            ],
            name="fk_knowledge_documents_base_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "current_revision_id",
                "id",
                "knowledge_base_id",
                "tenant_id",
                "assistant_id",
            ],
            [
                "knowledge_document_revisions.id",
                "knowledge_document_revisions.document_id",
                "knowledge_document_revisions.knowledge_base_id",
                "knowledge_document_revisions.tenant_id",
                "knowledge_document_revisions.assistant_id",
            ],
            name="fk_knowledge_documents_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    source_label: Mapped[str | None] = mapped_column(String(160))
    source_reference: Mapped[str | None] = mapped_column(String(2048))
    content_type: Mapped[KnowledgeContentType] = mapped_column(
        string_enum(KnowledgeContentType, "knowledge_document_content_type"),
        nullable=False,
    )
    status: Mapped[KnowledgeDocumentStatus] = mapped_column(
        string_enum(KnowledgeDocumentStatus, "knowledge_document_status"),
        default=KnowledgeDocumentStatus.ACTIVE,
        nullable=False,
    )
    latest_revision_number: Mapped[int] = mapped_column(default=0, nullable=False)
    current_revision_id: Mapped[UUID | None] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDocumentRevisionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "revision_number",
            name="uq_knowledge_revisions_document_number",
        ),
        UniqueConstraint(
            "id",
            "document_id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_revisions_owner",
        ),
        ForeignKeyConstraint(
            ["document_id", "knowledge_base_id", "tenant_id", "assistant_id"],
            [
                "knowledge_documents.id",
                "knowledge_documents.knowledge_base_id",
                "knowledge_documents.tenant_id",
                "knowledge_documents.assistant_id",
            ],
            name="fk_knowledge_revisions_document_owner",
            ondelete="RESTRICT",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_checksum: Mapped[str | None] = mapped_column(String(64))
    character_count: Mapped[int] = mapped_column(nullable=False)
    byte_count: Mapped[int] = mapped_column(nullable=False)
    chunking_version: Mapped[str] = mapped_column(String(64), nullable=False)
    index_state: Mapped[KnowledgeIndexState] = mapped_column(
        string_enum(KnowledgeIndexState, "knowledge_revision_index_state"),
        default=KnowledgeIndexState.PENDING,
        nullable=False,
    )
    created_by_identity_id: Mapped[UUID] = mapped_column(
        ForeignKey("control_operator_identities.id", ondelete="RESTRICT"),
        nullable=False,
    )
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunkModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "revision_id", "ordinal", name="uq_knowledge_chunks_revision_ordinal"
        ),
        UniqueConstraint(
            "id",
            "revision_id",
            "document_id",
            "knowledge_base_id",
            "tenant_id",
            "assistant_id",
            name="uq_knowledge_chunks_owner",
        ),
        ForeignKeyConstraint(
            [
                "revision_id",
                "document_id",
                "knowledge_base_id",
                "tenant_id",
                "assistant_id",
            ],
            [
                "knowledge_document_revisions.id",
                "knowledge_document_revisions.document_id",
                "knowledge_document_revisions.knowledge_base_id",
                "knowledge_document_revisions.tenant_id",
                "knowledge_document_revisions.assistant_id",
            ],
            name="fk_knowledge_chunks_revision_owner",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_knowledge_chunks_revalidation",
            "tenant_id",
            "assistant_id",
            "knowledge_base_id",
            "id",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_id: Mapped[UUID] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    start_offset: Mapped[int] = mapped_column(nullable=False)
    end_offset: Mapped[int] = mapped_column(nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    content_checksum: Mapped[str | None] = mapped_column(String(64))
    character_count: Mapped[int] = mapped_column(nullable=False)
    embedding_version: Mapped[str | None] = mapped_column(String(160))
    index_schema_version: Mapped[str | None] = mapped_column(String(64))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeIndexCollectionModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_index_collections"
    __table_args__ = (
        UniqueConstraint(
            "embedding_version",
            "physical_collection",
            name="uq_knowledge_collections_version_physical",
        ),
        Index(
            "uq_knowledge_collections_one_active",
            "embedding_version",
            unique=True,
            postgresql_where=sql_text("active"),
        ),
    )

    embedding_version: Mapped[str] = mapped_column(String(160), nullable=False)
    physical_collection: Mapped[str] = mapped_column(String(160), nullable=False)
    index_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeIndexJobModel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_index_jobs"
    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "operation",
            "embedding_version",
            "target_collection",
            name="uq_knowledge_index_jobs_idempotency",
        ),
        ForeignKeyConstraint(
            [
                "chunk_id",
                "revision_id",
                "document_id",
                "knowledge_base_id",
                "tenant_id",
                "assistant_id",
            ],
            [
                "knowledge_chunks.id",
                "knowledge_chunks.revision_id",
                "knowledge_chunks.document_id",
                "knowledge_chunks.knowledge_base_id",
                "knowledge_chunks.tenant_id",
                "knowledge_chunks.assistant_id",
            ],
            name="fk_knowledge_jobs_chunk_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_knowledge_index_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_knowledge_index_jobs_lease", "status", "lease_expires_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    assistant_id: Mapped[UUID] = mapped_column(nullable=False)
    knowledge_base_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    revision_id: Mapped[UUID] = mapped_column(nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(nullable=False)
    operation: Mapped[KnowledgeIndexOperation] = mapped_column(
        string_enum(KnowledgeIndexOperation, "knowledge_job_operation"), nullable=False
    )
    embedding_version: Mapped[str] = mapped_column(String(160), nullable=False)
    target_collection: Mapped[str] = mapped_column(String(160), nullable=False)
    index_schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[KnowledgeIndexJobStatus] = mapped_column(
        string_enum(KnowledgeIndexJobStatus, "knowledge_job_status"),
        default=KnowledgeIndexJobStatus.PENDING,
        nullable=False,
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_category: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
