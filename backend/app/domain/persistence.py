"""Platform-independent persistence records and validated string enums."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class TenantStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class AssistantStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class Platform(StrEnum):
    TELEGRAM = "telegram"
    ZALO = "zalo"


class PlatformConnectionStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"
    RETIRED = "retired"


class ConversationType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    SUPERGROUP = "supergroup"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class ResponseMode(StrEnum):
    MENTION_ONLY = "mention_only"
    MENTION_AND_NAME = "mention_and_name"
    AMBIENT_SELECTIVE = "ambient_selective"
    PAUSED = "paused"


class PersonalityProfileStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ParticipantRole(StrEnum):
    MEMBER = "member"
    ADMINISTRATOR = "administrator"
    OWNER = "owner"


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class MessageType(StrEnum):
    TEXT = "text"
    STICKER = "sticker"
    OTHER = "other"
    PHOTO = "photo"
    VOICE = "voice"
    AUDIO = "audio"


class MessageProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class IncomingUpdateStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    REJECTED = "rejected"


class IngressSource(StrEnum):
    WEBHOOK = "webhook"
    POLLING = "polling"


class IngressOutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"


class CommandJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


class CommandAuthorizationOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"


class MemoryKind(StrEnum):
    EXPLICIT_FACT = "explicit_fact"
    PERSONAL_CONTEXT = "personal_context"


class MemoryScope(StrEnum):
    PRIVATE_CONVERSATION = "private_conversation"
    GROUP_CONVERSATION = "group_conversation"


class MemoryVisibility(StrEnum):
    SAME_CONVERSATION = "same_conversation"
    CREATOR_ONLY = "creator_only"


class PersonalContextKey(StrEnum):
    PREFERRED_NAME = "preferred_name"
    PREFERRED_LANGUAGE = "preferred_language"
    RESPONSE_PREFERENCE = "response_preference"
    ACCESSIBILITY_PREFERENCE = "accessibility_preference"
    PERSONAL_NOTE = "personal_note"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"
    EXPIRED = "expired"


class MemoryDeletionReason(StrEnum):
    USER_REQUEST = "user_request"
    CREATOR_REQUEST = "creator_request"
    ADMINISTRATOR_RESET = "administrator_reset"
    PROFILE_DELETION = "profile_deletion"
    EXPIRATION = "expiration"


class SemanticMemoryIndexOperation(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


class SemanticMemoryIndexJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AssistantRecord:
    id: UUID
    tenant_id: UUID
    slug: str
    name: str
    status: AssistantStatus
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PlatformConnectionRecord:
    id: UUID
    tenant_id: UUID
    assistant_id: UUID
    platform: Platform
    external_bot_id: str
    status: PlatformConnectionStatus
    credential_reference: str | None
    configuration: dict[str, Any]
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: UUID
    platform_connection_id: UUID
    platform_conversation_id: str
    conversation_type: ConversationType
    title: str | None
    status: ConversationStatus
    response_mode: ResponseMode
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ParticipantRecord:
    id: UUID
    conversation_id: UUID
    platform_user_id: str
    username: str | None
    display_name: str
    role: ParticipantRole
    mention_allowed: bool
    teasing_allowed: bool
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    participant_id: UUID | None
    platform_message_id: str
    direction: MessageDirection
    message_type: MessageType
    text: str | None
    reply_to_message_id: UUID | None
    metadata: dict[str, Any]
    processing_status: MessageProcessingStatus
    created_at: datetime
    updated_at: datetime
