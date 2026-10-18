"""Platform-independent operational recovery vocabulary."""

from enum import StrEnum


class RecoveryKind(StrEnum):
    PLANNING = "planning"
    OUTBOUND = "outbound"


class RecoveryDisposition(StrEnum):
    DEAD_LETTER = "dead_letter"
    QUARANTINE = "quarantine"


class RecoveryReason(StrEnum):
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    LEASE_EXPIRED = "lease_expired"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    PROVIDER_RETRY_EXHAUSTED = "provider_retry_exhausted"
    DELIVERY_REJECTION_EXHAUSTED = "delivery_rejection_exhausted"
    INVALID_TERMINAL_PLAN = "invalid_terminal_plan"
    OPERATOR_REPLAY = "operator_replay"
    AMBIGUOUS_EXTERNAL_DELIVERY = "ambiguous_external_delivery"
    INVARIANT_VIOLATION = "invariant_violation"
