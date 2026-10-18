"""Application port for durable SPEC-026 provider governance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    BudgetDecision,
    BudgetMode,
    BudgetScope,
    EstimateQuality,
    ProviderAttemptOutcome,
    ProviderDataClass,
    ProviderHealth,
    ProviderOperation,
    RouteRole,
    UsageQuality,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation


@dataclass(frozen=True, slots=True)
class BudgetAdmissionEvent:
    scope: BudgetScope
    mode: BudgetMode
    decision: BudgetDecision
    reserved: bool


@dataclass(frozen=True, slots=True)
class ProviderWorkSource:
    source_key: str
    execution_ordinal: int = 1
    execution_owner: str | None = None
    planning_job_id: UUID | None = None
    summary_job_id: UUID | None = None
    semantic_index_job_id: UUID | None = None
    knowledge_index_job_id: UUID | None = None
    voice_generation_job_id: UUID | None = None
    tenant_id: UUID | None = None
    assistant_id: UUID | None = None
    connection_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.execution_ordinal < 1:
            raise ValueError("provider work execution ordinal must be positive")
        if self.execution_owner is not None and not self.execution_owner:
            raise ValueError("provider work execution owner must not be empty")
        if (
            sum(
                value is not None
                for value in (
                    self.planning_job_id,
                    self.summary_job_id,
                    self.semantic_index_job_id,
                    self.knowledge_index_job_id,
                    self.voice_generation_job_id,
                )
            )
            != 1
        ):
            raise ValueError(
                "provider work source must identify exactly one durable job"
            )


@dataclass(frozen=True, slots=True)
class ResolvedProviderRoute:
    snapshot_id: UUID
    policy_revision_id: UUID
    capability_id: UUID
    provider_id: ProviderId
    model: str
    adapter_key: ProviderId
    position: int
    data_class: ProviderDataClass
    credential_slot: str | None
    reservation_strategy: str
    capability_metadata: dict[str, object]
    allowed_fallback_reasons: frozenset[str]


@dataclass(frozen=True, slots=True)
class ProviderAdmission:
    allowed: bool
    attempt_id: UUID
    attempt_key: str
    outcome: ProviderAttemptOutcome
    reset_at: datetime | None = None
    budget_events: tuple[BudgetAdmissionEvent, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderUsageCompletion:
    usage_quality: UsageQuality
    estimate_quality: EstimateQuality
    estimated_cost_microusd: int | None
    health_from: ProviderHealth | None = None
    health_to: ProviderHealth | None = None
    health_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderHealthTransition:
    provider_id: ProviderId
    from_state: ProviderHealth | None
    to_state: ProviderHealth | None
    reason: str


@dataclass(frozen=True, slots=True)
class ProviderRecoveryResult:
    released: int
    ambiguous: int
    health_transitions: tuple[ProviderHealthTransition, ...] = ()


class ProviderGovernanceRepository(Protocol):
    async def validate_prerequisites(self, workload: WorkloadClass) -> None: ...

    async def planning_source(self, job_id: UUID) -> ProviderWorkSource: ...

    async def summary_source(self, job_id: UUID) -> ProviderWorkSource: ...

    async def semantic_source(self, job_id: UUID) -> ProviderWorkSource: ...

    async def knowledge_source(self, job_id: UUID) -> ProviderWorkSource: ...

    async def voice_source(self, job_id: UUID) -> ProviderWorkSource: ...

    async def resolve_routes(
        self,
        source: ProviderWorkSource,
        workload: WorkloadClass,
        requirements: dict[str, object],
    ) -> tuple[ResolvedProviderRoute, ...]: ...

    async def reserve_attempt(
        self,
        source: ProviderWorkSource,
        route: ResolvedProviderRoute,
        workload: WorkloadClass,
        operation: ProviderOperation,
        role: RouteRole,
        attempt_ordinal: int,
        maximum_input_tokens: int | None,
        maximum_output_tokens: int | None,
    ) -> ProviderAdmission: ...

    async def mark_io_started(self, attempt_id: UUID, owner: str) -> bool: ...

    async def record_rate_decision(
        self,
        source: ProviderWorkSource,
        operation: RateLimitOperation,
        provider_id: ProviderId,
        decision: RateLimitDecision,
    ) -> None: ...

    async def finish_no_io(
        self, attempt_id: UUID, outcome: ProviderAttemptOutcome
    ) -> bool: ...

    async def finish_io(
        self,
        attempt_id: UUID,
        *,
        outcome: ProviderAttemptOutcome,
        input_tokens: object,
        output_tokens: object,
        total_tokens: object,
        provider_request_id: str | None,
        retryable: bool | None,
        error_category: str | None,
    ) -> ProviderUsageCompletion | None: ...

    async def set_application_outcome(self, attempt_id: UUID, outcome: str) -> bool: ...

    async def recover_stale(self, limit: int) -> ProviderRecoveryResult: ...
