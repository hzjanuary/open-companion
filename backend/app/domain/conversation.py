"""Platform-independent conversation values for business processing."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domain.ambient import ParticipationTrigger
from app.domain.media import MediaAttachment, MediaFailureReason
from app.domain.persistence import ConversationType, ParticipantRole, Platform


class MembershipStatus(StrEnum):
    MEMBER = "member"
    RESTRICTED = "restricted"
    LEFT = "left"
    KICKED = "kicked"
    UNKNOWN = "unknown"


class EligibilityReason(StrEnum):
    ELIGIBLE_PRIVATE_MESSAGE = "eligible_private_message"
    ELIGIBLE_ASSISTANT_MENTIONED = "eligible_assistant_mentioned"
    ELIGIBLE_REPLY_TO_ASSISTANT = "eligible_reply_to_assistant"
    ELIGIBLE_ASSISTANT_NAME = "eligible_assistant_name"
    ELIGIBLE_AMBIENT_CANDIDATE = "eligible_ambient_candidate"
    CONVERSATION_PAUSED = "conversation_paused"
    CONNECTION_INACTIVE = "connection_inactive"
    ASSISTANT_INACTIVE = "assistant_inactive"
    TENANT_INACTIVE = "tenant_inactive"
    SENDER_IS_ASSISTANT = "sender_is_assistant"
    SENDER_IS_BOT = "sender_is_bot"
    UNSUPPORTED_MESSAGE_TYPE = "unsupported_message_type"
    EDITED_MESSAGE_NO_RESPONSE = "edited_message_no_response"
    NOT_ADDRESSED_TO_ASSISTANT = "not_addressed_to_assistant"
    MEMBERSHIP_EVENT_NO_RESPONSE = "membership_event_no_response"
    COMMAND_HANDOFF = "command_handoff"


class ProcessingOutcome(StrEnum):
    MESSAGE_CREATED = "message_created"
    MESSAGE_EDITED = "message_edited"
    MEMBERSHIP_APPLIED = "membership_applied"
    IGNORED = "ignored"
    REJECTED_MALFORMED = "rejected_malformed"


@dataclass(frozen=True, slots=True)
class NormalizedCommand:
    """A Telegram-independent command recognized at the adapter boundary."""

    name: str
    arguments: str
    addressed_to_assistant: bool


@dataclass(frozen=True, slots=True)
class ConversationIdentity:
    platform: Platform
    platform_connection_id: UUID
    platform_conversation_id: str
    conversation_type: ConversationType
    title: str | None
    platform_thread_id: str | None


@dataclass(frozen=True, slots=True)
class ParticipantIdentity:
    platform_user_id: str
    username: str | None
    display_name: str
    is_bot: bool
    membership_status: MembershipStatus
    role: ParticipantRole


@dataclass(frozen=True, slots=True)
class MentionReference:
    platform_user_id: str | None
    username: str | None


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    conversation: ConversationIdentity
    sender: ParticipantIdentity
    platform_message_id: str
    sent_at: datetime
    message_type: str
    text: str | None
    reply_to_platform_message_id: str | None
    platform_thread_id: str | None
    mentions_assistant: bool
    replies_to_assistant: bool
    mentions: tuple[MentionReference, ...]
    is_edit: bool
    edited_at: datetime | None
    command: NormalizedCommand | None = None
    attachment: MediaAttachment | None = None
    media_failure: MediaFailureReason | None = None


@dataclass(frozen=True, slots=True)
class NormalizedMembership:
    conversation: ConversationIdentity
    participant: ParticipantIdentity
    is_assistant_membership: bool
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason: EligibilityReason
    trigger: ParticipationTrigger | None = None
