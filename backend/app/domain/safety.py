"""Platform-independent, deterministic safety policy vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class SafetyPolicyVersion(StrEnum):
    V1 = "safety-policy-v1"


class SafetyStage(StrEnum):
    PRE_GENERATION = "pre_generation"
    POST_GENERATION = "post_generation"
    PRE_DELIVERY = "pre_delivery"


class SafetyOutcome(StrEnum):
    ALLOW = "allow"
    TRANSFORM = "transform"
    REFUSE = "refuse"
    SILENT = "silent"


class SafetyReasonCode(StrEnum):
    MENTION_TARGET_OPTED_OUT = "mention_target_opted_out"
    TEASING_TARGET_OPTED_OUT = "teasing_target_opted_out"
    TARGET_PROTECTED = "target_protected"
    TARGET_NOT_IN_CONTEXT = "target_not_in_context"
    SENSITIVE_TEASING_DISALLOWED = "sensitive_teasing_disallowed"
    TEASING_CAP_EXCEEDED = "teasing_cap_exceeded"
    PRIVATE_DATA_BOUNDARY = "private_data_boundary"
    INVALID_MODEL_SAFETY_ANNOTATION = "invalid_model_safety_annotation"
    PROMPT_INJECTION_ACTION_ATTEMPT = "prompt_injection_action_attempt"
    PRIVATE_MEMORY_EXTRACTION_ATTEMPT = "private_memory_extraction_attempt"
    DANGEROUS_INSTRUCTION_REQUEST = "dangerous_instruction_request"
    MANIPULATION_ATTEMPT = "manipulation_attempt"
    UNSUPPORTED_ACTION = "unsupported_action"
    MODEL_REFUSAL = "model_refusal"
    SAFE_FALLBACK = "safe_fallback"
    RATE_LIMITED = "rate_limited"


class InteractionKind(StrEnum):
    NEUTRAL = "neutral"
    HUMOR = "humor"
    TEASING = "teasing"
    SUPPORTIVE = "supportive"
    REFUSAL = "refusal"


class SensitiveTopicCategory(StrEnum):
    BODY = "body"
    DISABILITY = "disability"
    RACE = "race"
    RELIGION = "religion"
    GENDER = "gender"
    SEXUALITY = "sexuality"
    MEDICAL_CONDITION = "medical_condition"
    FINANCIAL_HARDSHIP = "financial_hardship"
    PRIVATE_TRAUMA = "private_trauma"


class SafetyLevel(StrEnum):
    """Per-group safety setting; never weakens the structural hard boundaries."""

    STRICT = "strict"
    STANDARD = "standard"
    RELAXED = "relaxed"


class SafetySignalType(StrEnum):
    """Closed catalog of content-free abuse signals (SPEC-024 FR-06)."""

    SAFETY_DECISION_REFUSAL = "safety_decision_refusal"
    MENTION_FREQUENCY = "mention_frequency"
    TEASING_FREQUENCY = "teasing_frequency"
    RATE_LIMIT_VIOLATION = "rate_limit_violation"
    MEMORY_EXTRACTION_ATTEMPT = "memory_extraction_attempt"
    DANGEROUS_INSTRUCTION_REQUEST = "dangerous_instruction_request"
    PROMPT_INJECTION_ATTEMPT = "prompt_injection_attempt"
    MANIPULATION_ATTEMPT = "manipulation_attempt"
    PROTECTIVE_ACTION = "protective_action"


class SignalScope(StrEnum):
    CONVERSATION = "conversation"
    PARTICIPANT = "participant"
    DEPLOYMENT = "deployment"


class ProtectionAction(StrEnum):
    """Protective enforcement actions; never punitive, targeting-only."""

    STOP_TARGETING = "stop_targeting"
    REDUCE_INTERACTION = "reduce_interaction"
    PAUSE_INTERACTION = "pause_interaction"
    RESTORE_TARGETING = "restore_targeting"


class ReviewItemStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class ReviewAction(StrEnum):
    ACKNOWLEDGE = "acknowledge"
    ESCALATE = "escalate"
    RESTORE_TARGETING = "restore_targeting"
    PAUSE_OR_RESTRICT = "pause_or_restrict"


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    policy_version: SafetyPolicyVersion
    stage: SafetyStage
    outcome: SafetyOutcome
    reason_code: SafetyReasonCode | None = None
    transformed: bool = False


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Versioned hard boundaries; no configuration can disable them."""

    version: SafetyPolicyVersion = SafetyPolicyVersion.V1

    def system_instructions(self) -> str:
        return (
            "Safety policy safety-policy-v1 is mandatory. Never harass, attack an "
            "identity, target humiliation, disclose private data, produce sexual "
            "content involving minors, encourage self-harm, or provide dangerous "
            "instruction execution. Never request tools, raw platform identifiers, "
            "or arbitrary actions. Teasing requires explicit permitted targets and "
            "must stop after opt-out. Use calm supportive language for serious "
            "distress. Emit only the declared structured interaction metadata."
        )


def safe_fallback(language: str | None) -> str:
    """Short deterministic text that never repeats rejected content or targets."""

    if language and language.lower().startswith("vi"):
        return "Minh se giu cuoc tro chuyen nhe nhang va ton trong."
    return "I will keep this conversation respectful and safe."


def protection_notice(language: str | None) -> str:
    """Non-escalating notice used when the assistant reduces interaction.

    The notice is content-free, never shames the recipient, and never repeats
    the triggering content. It is used only for protective enforcement
    (FR-07), never as a sanction.
    """

    if language and language.lower().startswith("vi"):
        return "Minh se han che tuong tac them trong cuoc tro chuyen nay."
    return "I will limit further interaction in this conversation."


@dataclass(frozen=True, slots=True)
class SignalThresholds:
    """Content-free signal thresholds owned by the operating owner.

    Conservative defaults; never weaken the SPEC-012 hard boundaries.
    """

    participant_refusals: int
    mention_frequency: int
    teasing_frequency: int
    rate_limit_violations: int
    memory_extraction: int
    dangerous_instruction: int
    prompt_injection: int
    manipulation: int

    def for_signal(self, signal_type: SafetySignalType) -> int | None:
        return {
            SafetySignalType.SAFETY_DECISION_REFUSAL: self.participant_refusals,
            SafetySignalType.MENTION_FREQUENCY: self.mention_frequency,
            SafetySignalType.TEASING_FREQUENCY: self.teasing_frequency,
            SafetySignalType.RATE_LIMIT_VIOLATION: self.rate_limit_violations,
            SafetySignalType.MEMORY_EXTRACTION_ATTEMPT: self.memory_extraction,
            SafetySignalType.DANGEROUS_INSTRUCTION_REQUEST: (
                self.dangerous_instruction
            ),
            SafetySignalType.PROMPT_INJECTION_ATTEMPT: self.prompt_injection,
            SafetySignalType.MANIPULATION_ATTEMPT: self.manipulation,
        }.get(signal_type)


@dataclass(frozen=True, slots=True)
class AggregatedSignals:
    """Content-free per-conversation/per-participant signal counts (FR-06)."""

    conversation_id: UUID
    participant_id: UUID | None
    affected_target_participant_id: UUID | None
    since: datetime
    counts: dict[SafetySignalType, int]

    def count(self, signal_type: SafetySignalType) -> int:
        return self.counts.get(signal_type, 0)


@dataclass(frozen=True, slots=True)
class ProtectionState:
    """Protective state for one participant (targeting-only, never punitive)."""

    protected: bool
    interaction_mode: str | None
    pause_until: datetime | None


def evaluate_protection(
    signals: AggregatedSignals, thresholds: SignalThresholds
) -> ProtectionAction | None:
    """Return STOP_TARGETING when any content-free signal exceeds its threshold.

    Single signals never create permanent protection; the review path
    (RESTORE_TARGETING) is the only reversal. Returns None when no threshold
    is exceeded. The action is always protective, never a sanction.
    """

    exceeded = [
        signal_type
        for signal_type in SafetySignalType
        if (threshold := thresholds.for_signal(signal_type)) is not None
        and signals.count(signal_type) >= threshold
    ]
    if not exceeded:
        return None
    return ProtectionAction.STOP_TARGETING


def interaction_escalation(
    prior_protective_actions: int, pause_after_actions: int
) -> ProtectionAction:
    """Deterministic escalation ladder for the abusive participant (FR-07).

    The first protective action stops targeting; sustained signals escalate to
    reduced interaction and then a bounded pause. Every step is reversible
    through the FR-08 review path.
    """

    if prior_protective_actions >= max(1, pause_after_actions):
        return ProtectionAction.PAUSE_INTERACTION
    if prior_protective_actions >= max(1, pause_after_actions // 2):
        return ProtectionAction.REDUCE_INTERACTION
    return ProtectionAction.STOP_TARGETING
