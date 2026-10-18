"""Platform-independent durable response-planning values."""

from enum import StrEnum


class ProviderId(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


class ProviderErrorCategory(StrEnum):
    INVALID_CONFIGURATION = "invalid_configuration"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    RATE_LIMITED = "rate_limited"
    CONCURRENCY_LIMITED = "concurrency_limited"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    STRUCTURED_OUTPUT = "structured_output"
    SAFETY_REFUSAL = "safety_refusal"
    CONTEXT_TOO_LARGE = "context_too_large"
    BUDGET_EXHAUSTED = "budget_exhausted"
    GOVERNANCE_UNAVAILABLE = "governance_unavailable"
    NO_ELIGIBLE_ROUTE = "no_eligible_route"


class PlanningJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    NO_RESPONSE = "no_response"
    FAILED = "failed"


class GenerationAttemptKind(StrEnum):
    PRIMARY = "primary"
    CORRECTION = "correction"
    FALLBACK = "fallback"


class GenerationAttemptStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"


class StickerIntent(StrEnum):
    LAUGH = "laugh"
    CELEBRATE = "celebrate"
    AWKWARD = "awkward"
    SUSPICIOUS = "suspicious"
    FACEPALM = "facepalm"
    SUPPORT = "support"
    SAD = "sad"
    ANGRY_CUTE = "angry_cute"
    CONFUSED = "confused"


class PlanReasonCode(StrEnum):
    SOCIAL_REPLY = "social_reply"
    ANSWER = "answer"
    ACKNOWLEDGEMENT = "acknowledgement"
    SILENCE = "silence"
    SAFETY_REFUSAL = "safety_refusal"
    INVALID_OUTPUT = "invalid_output"
