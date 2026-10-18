"""Platform-independent durable outbound delivery values."""

from enum import StrEnum


class OutboundActionKind(StrEnum):
    TEXT = "text"
    EDIT_TEXT = "edit_text"
    STICKER = "sticker"
    VOICE = "voice"


class OutboundActionStatus(StrEnum):
    PENDING = "pending"
    FALLBACK_BLOCKED = "fallback_blocked"
    LEASED = "leased"
    DELIVERED = "delivered"
    SKIPPED = "skipped"
    PERMANENTLY_FAILED = "permanently_failed"
    DELIVERY_UNKNOWN = "delivery_unknown"


class DeliveryAttemptStatus(StrEnum):
    STARTED = "started"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class DeliveryCertainty(StrEnum):
    NOT_SENT = "not_sent"
    REJECTED = "rejected"
    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
