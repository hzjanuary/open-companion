"""Platform-independent conversation-summary vocabulary."""

from enum import StrEnum


class ConversationSummaryStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    FAILED = "failed"


class SummaryInvalidationReason(StrEnum):
    PRIVACY_ERASURE = "privacy_erasure"
    SOURCE_REDACTED = "source_redacted"
    RETENTION_EXPIRED = "retention_expired"
    SOURCE_WINDOW_CHANGED = "source_window_changed"
    GROUP_RESET = "group_reset"


SUMMARY_SCHEMA_VERSION = "conversation-summary-v1"
SUMMARY_PROMPT_VERSION = "conversation-summary-prompt-v1"
