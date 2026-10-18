"""Typed, deterministic ambient participation policy values."""

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ParticipationTrigger(StrEnum):
    ADDRESSED = "addressed"
    AMBIENT = "ambient"
    COMMAND = "command"
    SCHEDULED = "scheduled"


class AmbientFrequency(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class AmbientReason(StrEnum):
    FEATURE_DISABLED = "ambient_feature_disabled"
    NOT_SAMPLED = "ambient_not_sampled"
    COOLDOWN = "ambient_cooldown"
    MODEL_SILENCE = "ambient_model_silence"
    LOW_CONFIDENCE = "ambient_low_confidence"
    POLICY_SUPPRESSED = "ambient_policy_suppressed"
    RESPONSE = "ambient_response"


def is_ambient_trigger(trigger: ParticipationTrigger) -> bool:
    return trigger == ParticipationTrigger.AMBIENT


@dataclass(frozen=True, slots=True)
class AmbientProfile:
    sample_permyriad: int
    cooldown_seconds: int
    minimum_confidence: float


AMBIENT_POLICY_VERSION = "ambient-policy-v1"
AMBIENT_PROFILES: dict[AmbientFrequency, AmbientProfile] = {
    AmbientFrequency.LOW: AmbientProfile(1000, 180, 0.85),
    AmbientFrequency.NORMAL: AmbientProfile(2500, 90, 0.75),
    AmbientFrequency.HIGH: AmbientProfile(5000, 45, 0.65),
}


def deterministic_score(
    incoming_message_id: UUID,
    configuration_revision_id: UUID,
    policy_version: str = AMBIENT_POLICY_VERSION,
) -> int:
    """Return a stable 0..9999 sample score without content or external IDs."""
    payload = f"{incoming_message_id}:{configuration_revision_id}:{policy_version}"
    digest = hashlib.sha256(payload.encode("ascii")).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def is_sampled(
    incoming_message_id: UUID,
    configuration_revision_id: UUID,
    frequency: AmbientFrequency,
    policy_version: str = AMBIENT_POLICY_VERSION,
) -> bool:
    score = deterministic_score(
        incoming_message_id, configuration_revision_id, policy_version
    )
    return score < AMBIENT_PROFILES[frequency].sample_permyriad
