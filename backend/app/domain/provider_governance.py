"""Content-free provider routing, usage, pricing, and budget values."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

MAX_BIGINT = 9_223_372_036_854_775_807


class WorkloadClass(StrEnum):
    CHAT_GENERATION = "chat_generation"
    EMBEDDING = "embedding"
    TRANSCRIPTION = "transcription"
    TEXT_TO_SPEECH = "text_to_speech"


class ProviderOperation(StrEnum):
    RESPONSE_PLANNING = "response_planning"
    SUMMARY_GENERATION = "summary_generation"
    SEMANTIC_QUERY = "semantic_query"
    SEMANTIC_INDEX = "semantic_index"
    SEMANTIC_REBUILD = "semantic_rebuild"
    MEDIA_TRANSCRIPTION = "media_transcription"
    KNOWLEDGE_QUERY = "knowledge_query"
    KNOWLEDGE_INDEX = "knowledge_index"
    KNOWLEDGE_REBUILD = "knowledge_rebuild"
    VOICE_SYNTHESIS = "voice_synthesis"


class ProviderLifecycle(StrEnum):
    ENABLED = "enabled"
    DRAINING = "draining"
    DISABLED = "disabled"


class ProviderHealth(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderDataClass(StrEnum):
    LOCAL = "local"
    APPROVED_EXTERNAL = "approved_external"


class RouteRole(StrEnum):
    PRIMARY = "primary"
    RETRY = "retry"
    CORRECTION = "correction"
    FALLBACK = "fallback"


class UsageQuality(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"
    INVALID = "invalid"


class EstimateQuality(StrEnum):
    ESTIMATED = "estimated"
    PARTIAL = "partial"
    RESERVATION_ESTIMATE = "reservation_estimate"
    UNAVAILABLE = "unavailable"


class ProviderAttemptState(StrEnum):
    RESERVED = "reserved"
    IO_STARTED = "io_started"
    IO_COMPLETE = "io_complete"
    NO_IO = "no_io"
    IO_POSSIBLE = "io_possible"


class ProviderAttemptOutcome(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    REFUSED = "refused"
    PROVIDER_ERROR = "provider_error"
    INVALID_OUTPUT = "invalid_output"
    BUDGET_DENIED = "budget_denied"
    RATE_LIMITED = "rate_limited"
    CONCURRENCY_LIMITED = "concurrency_limited"
    NO_ELIGIBLE_ROUTE = "no_eligible_route"
    GOVERNANCE_UNAVAILABLE = "governance_unavailable"
    RECOVERED_NO_IO = "recovered_no_io"
    RECOVERED_IO_POSSIBLE = "recovered_io_possible"


class BudgetScope(StrEnum):
    DEPLOYMENT = "deployment"
    ASSISTANT = "assistant"
    PLATFORM_CONNECTION = "platform_connection"


class BudgetMeasurement(StrEnum):
    ESTIMATED_COST_MICROUSD = "estimated_cost_microusd"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    TOTAL_TOKENS = "total_tokens"
    REQUESTS = "requests"


class BudgetMode(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class BudgetWindowKind(StrEnum):
    DAILY_UTC = "daily_utc"
    MONTHLY_UTC = "monthly_utc"


class BudgetDecision(StrEnum):
    WITHIN = "within"
    EXCEEDED = "exceeded"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class ReservationState(StrEnum):
    RESERVED = "reserved"
    RELEASED = "released"
    CONSUMED = "consumed"
    AMBIGUOUS = "ambiguous"


class GovernanceMode(StrEnum):
    LEGACY = "legacy"
    OBSERVE = "observe"
    ENFORCE = "enforce"


@dataclass(frozen=True, slots=True)
class UsageObservation:
    quality: UsageQuality
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    @classmethod
    def classify(
        cls,
        input_tokens: object,
        output_tokens: object,
        total_tokens: object,
    ) -> UsageObservation:
        raw = (input_tokens, output_tokens, total_tokens)
        if any(
            value is not None and (type(value) is not int or value < 0) for value in raw
        ):
            return cls(UsageQuality.INVALID, None, None, None)
        values = tuple(value if isinstance(value, int) else None for value in raw)
        input_value, output_value, total_value = values
        if (
            total_value is not None
            and input_value is not None
            and output_value is not None
            and total_value != input_value + output_value
        ):
            return cls(UsageQuality.INVALID, None, None, None)
        if all(value is None for value in values):
            quality = UsageQuality.MISSING
        elif input_value is not None and output_value is not None:
            quality = UsageQuality.COMPLETE
        else:
            quality = UsageQuality.PARTIAL
        return cls(quality, input_value, output_value, total_value)


@dataclass(frozen=True, slots=True)
class GenerationPrice:
    input_microusd_per_million: int
    output_microusd_per_million: int

    def __post_init__(self) -> None:
        if (
            type(self.input_microusd_per_million) is not int
            or type(self.output_microusd_per_million) is not int
            or self.input_microusd_per_million < 0
            or self.output_microusd_per_million < 0
            or self.input_microusd_per_million > MAX_BIGINT
            or self.output_microusd_per_million > MAX_BIGINT
        ):
            raise ValueError("pricing must use nonnegative integer microusd rates")


def ceil_div(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError(
            "ceil_div requires a nonnegative numerator and positive denominator"
        )
    return (numerator + denominator - 1) // denominator


def estimate_generation_cost(
    input_tokens: int, output_tokens: int, price: GenerationPrice
) -> int:
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or input_tokens < 0
        or output_tokens < 0
        or input_tokens > MAX_BIGINT
        or output_tokens > MAX_BIGINT
    ):
        raise ValueError("token amounts must be nonnegative")
    result = ceil_div(
        input_tokens * price.input_microusd_per_million
        + output_tokens * price.output_microusd_per_million,
        1_000_000,
    )
    if result > MAX_BIGINT:
        raise ValueError("estimated cost exceeds durable integer range")
    return result


def reserve_generation_cost(
    maximum_input_tokens: int,
    maximum_output_tokens: int,
    price: GenerationPrice,
) -> int:
    if (
        type(maximum_input_tokens) is not int
        or type(maximum_output_tokens) is not int
        or maximum_input_tokens < 0
        or maximum_output_tokens < 0
        or maximum_input_tokens > MAX_BIGINT
        or maximum_output_tokens > MAX_BIGINT
    ):
        raise ValueError("token bounds must be nonnegative")
    result = ceil_div(
        maximum_input_tokens * price.input_microusd_per_million, 1_000_000
    ) + ceil_div(maximum_output_tokens * price.output_microusd_per_million, 1_000_000)
    if result > MAX_BIGINT:
        raise ValueError("reserved cost exceeds durable integer range")
    return result


def budget_window(kind: BudgetWindowKind, at: datetime) -> tuple[datetime, datetime]:
    if at.tzinfo is None:
        raise ValueError("budget window timestamps must be timezone-aware")
    current = at.astimezone(UTC)
    if kind == BudgetWindowKind.DAILY_UTC:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end
