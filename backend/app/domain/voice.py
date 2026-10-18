"""Closed product values for explicit Telegram voice playback."""

from __future__ import annotations

from enum import StrEnum

VOICE_SOURCE_MAX_CHARACTERS = 4_000
VOICE_ARTIFACT_MAX_BYTES = 5 * 1024 * 1024
VOICE_ARTIFACT_GRACE_HOURS = 24
VOICE_ARTIFACT_HARD_RETENTION_DAYS = 7


class VoiceFormat(StrEnum):
    OGG_OPUS = "ogg_opus"


class VoiceGenerationStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    IO_POSSIBLE = "io_possible"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"


class VoiceArtifactStatus(StrEnum):
    READY = "ready"
    PURGED = "purged"


class VoiceFailureReason(StrEnum):
    TARGET_UNAVAILABLE = "target_unavailable"
    TOO_LONG = "too_long"
    UNSUPPORTED = "unsupported"
    ADMISSION_DENIED = "admission_denied"
    PROVIDER_FAILED = "provider_failed"
    PROVIDER_UNCERTAIN = "provider_uncertain"
    STALE_AUTHORITY = "stale_authority"
