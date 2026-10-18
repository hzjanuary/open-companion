"""Bounded media metadata, never a raw-media persistence contract."""

from dataclasses import dataclass, field
from enum import StrEnum


class MediaKind(StrEnum):
    PHOTO = "photo"
    VOICE = "voice"
    AUDIO = "audio"


class MediaStatus(StrEnum):
    PENDING = "pending"
    PREPARING = "preparing"
    COMPLETE = "complete"
    FAILED = "failed"
    AMBIGUOUS = "ambiguous"
    REDACTED = "redacted"


class MediaFailureReason(StrEnum):
    UNSUPPORTED = "unsupported"
    INVALID_FORMAT = "invalid_format"
    TOO_LARGE = "too_large"
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    AMBIGUOUS = "ambiguous"
    PRIVACY_CHANGED = "privacy_changed"
    STALE_LEASE = "stale_lease"
    BUDGET_DENIED = "budget_denied"
    RATE_LIMITED = "rate_limited"
    CONCURRENCY_LIMITED = "concurrency_limited"


@dataclass(frozen=True, slots=True)
class MediaLimits:
    photo_max_bytes: int = 5 * 1024 * 1024
    audio_max_bytes: int = 5 * 1024 * 1024
    photo_max_side: int = 1280
    audio_max_duration_seconds: int = 120
    caption_max_characters: int = 1024
    transcript_max_characters: int = 4000

    def __post_init__(self) -> None:
        for value, cap in (
            (self.photo_max_bytes, 10 * 1024 * 1024),
            (self.audio_max_bytes, 10 * 1024 * 1024),
            (self.photo_max_side, 4096),
            (self.audio_max_duration_seconds, 300),
            (self.caption_max_characters, 1024),
            (self.transcript_max_characters, 8000),
        ):
            if type(value) is not int or not 1 <= value <= cap:
                raise ValueError("media limit is outside approved bounds")


@dataclass(frozen=True, slots=True)
class MediaAttachment:
    kind: MediaKind
    file_id: str = field(repr=False)
    file_unique_id: str = field(repr=False)
    mime_type: str
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class EphemeralMedia:
    """Provider-bound bytes; not serializable application persistence data."""

    kind: MediaKind
    mime_type: str
    data: bytes = field(repr=False)
    width: int | None = None
    height: int | None = None
