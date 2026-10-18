"""Provider decorator enforcing SPEC-026 immediately before each external call."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import TypeVar
from uuid import UUID

from app.application.model_provider import (
    GenerationRequest,
    ModelProvider,
    ProviderError,
    ProviderIdentity,
    ProviderResult,
    TranscriptionProvider,
    TranscriptionRequest,
    TranscriptionResult,
)
from app.application.ports.concurrency import ConcurrencyLease, ConcurrencyLimiter
from app.application.ports.provider_governance import (
    ProviderAdmission,
    ProviderUsageCompletion,
    ProviderWorkSource,
    ResolvedProviderRoute,
)
from app.application.ports.rate_limit import RateLimiter
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.provider_governance import (
    capability_matches,
    conservative_utf8_input_bound,
)
from app.application.rate_limit_rules import embedding_provider_rule, provider_rule
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingErrorCategory,
    EmbeddingProvider,
    EmbeddingVector,
)
from app.core.config import Settings
from app.domain.planning import ProviderErrorCategory
from app.domain.provider_governance import (
    ProviderAttemptOutcome,
    ProviderOperation,
    RouteRole,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.infrastructure.concurrency import ConcurrencyUnavailable
from app.infrastructure.database.provider_governance import (
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.rate_limit import RateLimitUnavailable

_Result = TypeVar("_Result", ProviderResult, TranscriptionResult)


class _GovernedProvider:
    def __init__(
        self,
        provider: ProviderIdentity,
        route: ResolvedProviderRoute,
        source: ProviderWorkSource,
        operation: ProviderOperation,
        repository: SqlAlchemyProviderGovernanceRepository,
        settings: Settings,
        rate_limiter: RateLimiter | None,
        concurrency_limiter: ConcurrencyLimiter | None,
        telemetry: MetricsRecorder | None = None,
        *,
        workload: WorkloadClass = WorkloadClass.CHAT_GENERATION,
        before_io: Callable[[], Awaitable[bool]] | None = None,
        on_io_start: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._provider = provider
        self._route = route
        self._source = source
        self._operation = operation
        self._repository = repository
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._concurrency_limiter = concurrency_limiter
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self._workload = workload
        self._before_io = before_io
        self._on_io_start = on_io_start
        self._last_attempt_id: UUID | None = None
        self.provider_id = provider.provider_id
        self.model = provider.model
        self.capabilities = provider.capabilities

    async def _run_attempt(
        self,
        call: Callable[[], Awaitable[_Result]],
        maximum_input_tokens: int | None,
        maximum_output_tokens: int | None,
        role: RouteRole,
        ordinal: int,
    ) -> _Result:
        durable_ordinal = (
            1
            if self._workload == WorkloadClass.TRANSCRIPTION
            else (self._source.execution_ordinal - 1) * 1000 + ordinal
        )
        admission = await self._repository.reserve_attempt(
            self._source,
            self._route,
            self._workload,
            self._operation,
            role,
            durable_ordinal,
            maximum_input_tokens,
            maximum_output_tokens,
        )
        self._last_attempt_id = admission.attempt_id
        self._record_budget_events(admission, self._workload)
        if not admission.allowed:
            self._telemetry.increment(
                "january_provider_routing_decisions_total",
                workload=self._workload.value,
                operation=self._operation.value,
                route_role=role.value,
                outcome="denied",
                reason=(
                    "budget_denied"
                    if admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
                    else "no_route"
                ),
            )
            category = (
                ProviderErrorCategory.BUDGET_EXHAUSTED
                if admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
                else ProviderErrorCategory.GOVERNANCE_UNAVAILABLE
            )
            raise ProviderError(
                category,
                self.provider_id,
                self.model,
                False,
                "generate",
                "provider governance denied external I/O",
                retry_after=(
                    timedelta(
                        seconds=max(
                            0,
                            (admission.reset_at - datetime.now(UTC)).total_seconds(),
                        )
                    )
                    if admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
                    and admission.reset_at is not None
                    else None
                ),
            )
        self._telemetry.increment(
            "january_provider_routing_decisions_total",
            workload=self._workload.value,
            operation=self._operation.value,
            route_role=role.value,
            outcome="selected",
            reason="eligible",
        )
        if self._rate_limiter is not None:
            try:
                decision = await self._rate_limiter.check(
                    RateLimitOperation.GENERATION,
                    (provider_rule(self._settings, self.provider_id.value),),
                )
            except RateLimitUnavailable as exc:
                decision = RateLimitDecision(
                    False,
                    retry_after_seconds=(
                        self._settings.rate_limit_redis_failure_retry_seconds
                    ),
                )
                await self._repository.record_rate_decision(
                    self._source,
                    RateLimitOperation.GENERATION,
                    self.provider_id,
                    decision,
                )
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.RATE_LIMITED,
                )
                self._record_budget_state(admission, "released")
                self._record_route_denial(role, "rate_limited")
                raise ProviderError(
                    ProviderErrorCategory.RATE_LIMITED,
                    self.provider_id,
                    self.model,
                    True,
                    "generate",
                    "distributed rate coordination unavailable",
                ) from exc
            await self._repository.record_rate_decision(
                self._source,
                RateLimitOperation.GENERATION,
                self.provider_id,
                decision,
            )
            if not decision.allowed:
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.RATE_LIMITED,
                )
                self._record_budget_state(admission, "released")
                self._record_route_denial(role, "rate_limited")
                raise ProviderError(
                    ProviderErrorCategory.RATE_LIMITED,
                    self.provider_id,
                    self.model,
                    True,
                    "generate",
                    "distributed provider rate limit denied external I/O",
                )
        lease = None
        if self._concurrency_limiter is not None:
            try:
                lease = await self._concurrency_limiter.acquire(self.provider_id)
            except ConcurrencyUnavailable as exc:
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.CONCURRENCY_LIMITED,
                )
                self._record_budget_state(admission, "released")
                self._record_route_denial(role, "concurrency_limited")
                raise ProviderError(
                    ProviderErrorCategory.CONCURRENCY_LIMITED,
                    self.provider_id,
                    self.model,
                    True,
                    "generate",
                    "provider concurrency coordination unavailable",
                ) from exc
            if lease is None:
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.CONCURRENCY_LIMITED,
                )
                self._record_budget_state(admission, "released")
                self._record_route_denial(role, "concurrency_limited")
                raise ProviderError(
                    ProviderErrorCategory.CONCURRENCY_LIMITED,
                    self.provider_id,
                    self.model,
                    True,
                    "generate",
                    "provider concurrency capacity unavailable",
                )
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="acquired",
            )
        try:
            authority_current = self._before_io is None or await self._before_io()
        except BaseException:
            if lease is not None:
                await self._safe_release(lease)
            # No external call occurred. Durable reservation recovery can release
            # this attempt even if cancellation prevents further database work.
            raise
        if not authority_current:
            if lease is not None:
                await self._safe_release(lease)
            await self._repository.finish_no_io(
                admission.attempt_id, ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
            )
            self._record_budget_state(admission, "released")
            raise ProviderError(
                ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                self.provider_id,
                self.model,
                False,
                "admission",
                "media authority is no longer current",
            )
        if not await self._repository.mark_io_started(
            admission.attempt_id,
            self._source.execution_owner or self._source.source_key,
        ):
            if lease is not None and self._concurrency_limiter is not None:
                await self._safe_release(lease)
            self._record_route_denial(role, "invalid_policy")
            raise ProviderError(
                ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                self.provider_id,
                self.model,
                False,
                "generate",
                "provider attempt could not enter I/O state",
            )
        if self._on_io_start is not None:
            try:
                await self._on_io_start()
            except BaseException:
                if lease is not None:
                    await self._safe_release(lease)
                # No external call occurred. Durable reservation recovery can release
                # this attempt even if cancellation prevents further database work.
                raise
        io_started = perf_counter()
        try:
            result = await call()
        except ProviderError as error:
            self._record_attempt(role, "provider_error", perf_counter() - io_started)
            if not await self._finish_error(admission.attempt_id, error):
                raise ProviderError(
                    ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                    self.provider_id,
                    self.model,
                    False,
                    "generate",
                    "provider error usage could not be finalized",
                ) from error
            self._record_budget_state(admission, "consumed")
            raise
        except Exception:
            self._record_attempt(role, "unexpected_error", perf_counter() - io_started)
            raise
        finally:
            if lease is not None and self._concurrency_limiter is not None:
                await self._safe_release(lease)
        self._record_attempt(
            role,
            "refused" if result.refused or result.safety_blocked else "success",
            perf_counter() - io_started,
        )
        completion = await self._repository.finish_io(
            admission.attempt_id,
            outcome=(
                ProviderAttemptOutcome.REFUSED
                if result.refused or result.safety_blocked
                else ProviderAttemptOutcome.SUCCESS
            ),
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            provider_request_id=result.provider_request_id,
            retryable=False,
            error_category=None,
        )
        if completion is None:
            raise ProviderError(
                ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                self.provider_id,
                self.model,
                False,
                "generate",
                "provider usage could not be finalized",
            )
        self._record_completion(completion)
        self._record_budget_state(admission, "consumed")
        return result

    async def record_application_outcome(self, outcome: str) -> None:
        if self._last_attempt_id is not None:
            await self._repository.set_application_outcome(
                self._last_attempt_id, outcome
            )

    def fallback_allowed(self, category: ProviderErrorCategory) -> bool:
        return category.value in self._route.allowed_fallback_reasons

    async def _finish_error(self, attempt_id: UUID, error: ProviderError) -> bool:
        completion = await self._repository.finish_io(
            attempt_id,
            outcome=ProviderAttemptOutcome.PROVIDER_ERROR,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_request_id=error.provider_request_id,
            retryable=error.retryable,
            error_category=error.category.value,
        )
        if completion is not None:
            self._record_completion(completion)
            return True
        return False

    def _record_completion(self, completion: ProviderUsageCompletion) -> None:
        self._telemetry.increment(
            "january_provider_usage_quality_total",
            provider=self.provider_id.value,
            workload=self._workload.value,
            usage_quality=completion.usage_quality.value,
        )
        self._telemetry.increment(
            "january_provider_estimate_outcomes_total",
            provider=self.provider_id.value,
            workload=self._workload.value,
            estimate_quality=completion.estimate_quality.value,
        )
        if completion.estimated_cost_microusd is not None:
            self._telemetry.increment(
                "january_provider_estimated_cost_microusd_total",
                completion.estimated_cost_microusd,
                provider=self.provider_id.value,
                workload=self._workload.value,
            )
        self._record_health_transition(completion)

    def _record_attempt(self, role: RouteRole, outcome: str, duration: float) -> None:
        labels = {
            "provider": self.provider_id.value,
            "workload": self._workload.value,
            "operation": self._operation.value,
            "route_role": role.value,
            "outcome": outcome,
        }
        self._telemetry.increment("january_provider_attempts_total", **labels)
        self._telemetry.observe(
            "january_provider_attempt_duration_seconds", duration, **labels
        )

    def _record_health_transition(self, completion: ProviderUsageCompletion) -> None:
        if completion.health_reason is None:
            return
        self._telemetry.increment(
            "january_provider_health_transitions_total",
            provider=self.provider_id.value,
            from_state=(
                completion.health_from.value
                if completion.health_from is not None
                else "unknown"
            ),
            to_state=(
                completion.health_to.value
                if completion.health_to is not None
                else "unknown"
            ),
            reason=completion.health_reason,
        )

    def _record_budget_events(
        self, admission: ProviderAdmission, workload: WorkloadClass
    ) -> None:
        for event in admission.budget_events:
            self._telemetry.increment(
                "january_provider_budget_decisions_total",
                workload=workload.value,
                scope=event.scope.value,
                mode=event.mode.value,
                outcome=event.decision.value,
            )
            if event.reserved:
                self._telemetry.increment(
                    "january_provider_budget_reservations_total",
                    workload=workload.value,
                    scope=event.scope.value,
                    outcome="reserved",
                )

    def _record_route_denial(self, role: RouteRole, reason: str) -> None:
        self._telemetry.increment(
            "january_provider_routing_decisions_total",
            workload=self._workload.value,
            operation=self._operation.value,
            route_role=role.value,
            outcome="denied",
            reason=reason,
        )

    def _record_budget_state(self, admission: ProviderAdmission, outcome: str) -> None:
        for event in admission.budget_events:
            if event.reserved:
                self._telemetry.increment(
                    "january_provider_budget_reservations_total",
                    workload=self._workload.value,
                    scope=event.scope.value,
                    outcome=outcome,
                )

    async def _safe_release(self, lease: ConcurrencyLease) -> None:
        limiter = self._concurrency_limiter
        if limiter is None:
            return
        try:
            await limiter.release(lease)
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="released",
            )
        except ConcurrencyUnavailable:
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id.value,
                outcome="unavailable",
            )

    async def aclose(self) -> None:
        await self._provider.aclose()


class GovernedModelProvider(_GovernedProvider):
    def __init__(
        self,
        provider: ModelProvider,
        route: ResolvedProviderRoute,
        source: ProviderWorkSource,
        operation: ProviderOperation,
        repository: SqlAlchemyProviderGovernanceRepository,
        settings: Settings,
        rate_limiter: RateLimiter | None,
        concurrency_limiter: ConcurrencyLimiter | None,
        telemetry: MetricsRecorder | None = None,
        *,
        before_io: Callable[[], Awaitable[bool]] | None = None,
        on_io_start: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(
            provider,
            route,
            source,
            operation,
            repository,
            settings,
            rate_limiter,
            concurrency_limiter,
            telemetry,
            before_io=before_io,
            on_io_start=on_io_start,
        )
        self._model_provider = provider

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        return await self.generate_attempt(request, RouteRole.PRIMARY, 1)

    async def generate_attempt(
        self, request: GenerationRequest, role: RouteRole, ordinal: int
    ) -> ProviderResult:
        maximum_input = conservative_utf8_input_bound(
            request.system_instructions, request.user_content
        )
        if request.current_image is not None:
            bound = self._route.capability_metadata.get("maximum_image_input_tokens")
            if (
                not self.capabilities.image_input
                or self._route.capability_metadata.get("image_input") is not True
                or type(bound) is not int
                or not 1 <= bound <= 1_000_000
                or self._rate_limiter is None
                or self._concurrency_limiter is None
                or self._settings.provider_governance_mode != "enforce"
                or self._before_io is None
            ):
                raise ProviderError(
                    ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                    self.provider_id,
                    self.model,
                    False,
                    "generate",
                    "image admission is unavailable",
                )
            maximum_input += bound
        return await self._run_attempt(
            lambda: self._model_provider.generate(request),
            maximum_input,
            request.maximum_output_tokens,
            role,
            ordinal,
        )


class GovernedTranscriptionProvider(_GovernedProvider):
    def __init__(
        self,
        provider: TranscriptionProvider,
        route: ResolvedProviderRoute,
        source: ProviderWorkSource,
        repository: SqlAlchemyProviderGovernanceRepository,
        settings: Settings,
        rate_limiter: RateLimiter | None,
        concurrency_limiter: ConcurrencyLimiter | None,
        before_io: Callable[[], Awaitable[bool]],
        telemetry: MetricsRecorder | None = None,
    ) -> None:
        super().__init__(
            provider,
            route,
            source,
            ProviderOperation.MEDIA_TRANSCRIPTION,
            repository,
            settings,
            rate_limiter,
            concurrency_limiter,
            telemetry,
            workload=WorkloadClass.TRANSCRIPTION,
            before_io=before_io,
        )
        self._transcription_provider = provider

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        if (
            self._settings.provider_governance_mode != "enforce"
            or self._rate_limiter is None
            or self._concurrency_limiter is None
            or not capability_matches(
                self._route,
                WorkloadClass.TRANSCRIPTION,
                {
                    "speech_to_text": True,
                    "audio_format": request.media.mime_type,
                    "maximum_audio_bytes": len(request.media.data),
                    "maximum_audio_duration_seconds": max(1, request.duration_seconds),
                },
            ).eligible
        ):
            raise ProviderError(
                ProviderErrorCategory.GOVERNANCE_UNAVAILABLE,
                self.provider_id,
                self.model,
                False,
                "transcribe",
                "transcription admission is unavailable",
            )
        # Stable operation ordinal: a new planning lease must not create a new call.
        return await self._run_attempt(
            lambda: self._transcription_provider.transcribe(request),
            None,
            None,
            RouteRole.PRIMARY,
            1,
        )


class GovernedEmbeddingProvider:
    """Apply the same durable admission boundary to one embedding call."""

    governed = True

    def __init__(
        self,
        provider: EmbeddingProvider,
        route: ResolvedProviderRoute,
        source: ProviderWorkSource,
        operation: ProviderOperation,
        repository: SqlAlchemyProviderGovernanceRepository,
        settings: Settings,
        rate_limiter: RateLimiter | None,
        concurrency_limiter: ConcurrencyLimiter | None,
        telemetry: MetricsRecorder | None = None,
        *,
        before_io: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._provider = provider
        self._route = route
        self._source = source
        self._operation = operation
        self._repository = repository
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._concurrency_limiter = concurrency_limiter
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self._before_io = before_io
        self.provider_id = provider.provider_id
        self.model = provider.model
        self.dimension = provider.dimension

    async def embed_text(self, text: str) -> EmbeddingVector:
        admission = await self._repository.reserve_attempt(
            self._source,
            self._route,
            WorkloadClass.EMBEDDING,
            self._operation,
            RouteRole.PRIMARY,
            self._source.execution_ordinal,
            len(text.encode("utf-8")),
            0,
        )
        for event in admission.budget_events:
            self._telemetry.increment(
                "january_provider_budget_decisions_total",
                workload="embedding",
                scope=event.scope.value,
                mode=event.mode.value,
                outcome=event.decision.value,
            )
            if event.reserved:
                self._telemetry.increment(
                    "january_provider_budget_reservations_total",
                    workload="embedding",
                    scope=event.scope.value,
                    outcome="reserved",
                )
        if not admission.allowed:
            self._telemetry.increment(
                "january_provider_routing_decisions_total",
                workload="embedding",
                operation=self._operation.value,
                route_role="primary",
                outcome="denied",
                reason=(
                    "budget_denied"
                    if admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
                    else "no_route"
                ),
            )
            raise EmbeddingError(
                (
                    self._budget_error_category()
                    if admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
                    else self._unavailable_error_category()
                ),
                self.provider_id,
                False,
            )
        self._telemetry.increment(
            "january_provider_routing_decisions_total",
            workload="embedding",
            operation=self._operation.value,
            route_role="primary",
            outcome="selected",
            reason="eligible",
        )
        if self._rate_limiter is not None:
            try:
                decision = await self._rate_limiter.check(
                    RateLimitOperation.EMBEDDING,
                    (embedding_provider_rule(self._settings, self.provider_id),),
                )
            except RateLimitUnavailable as exc:
                decision = RateLimitDecision(
                    False,
                    retry_after_seconds=(
                        self._settings.rate_limit_redis_failure_retry_seconds
                    ),
                )
                await self._repository.record_rate_decision(
                    self._source,
                    RateLimitOperation.EMBEDDING,
                    self._route.provider_id,
                    decision,
                )
                await self._repository.finish_no_io(
                    admission.attempt_id, ProviderAttemptOutcome.RATE_LIMITED
                )
                self._record_embedding_budget_state(admission, "released")
                self._record_embedding_route_denial("rate_limited")
                raise EmbeddingError(
                    self._rate_error_category(), self.provider_id, True
                ) from exc
            await self._repository.record_rate_decision(
                self._source,
                RateLimitOperation.EMBEDDING,
                self._route.provider_id,
                decision,
            )
            if not decision.allowed:
                await self._repository.finish_no_io(
                    admission.attempt_id, ProviderAttemptOutcome.RATE_LIMITED
                )
                self._record_embedding_budget_state(admission, "released")
                self._record_embedding_route_denial("rate_limited")
                raise EmbeddingError(
                    self._rate_error_category(), self.provider_id, True
                )
        lease = None
        provider_enum = self._route.provider_id
        if self._concurrency_limiter is not None:
            try:
                lease = await self._concurrency_limiter.acquire(provider_enum)
            except ConcurrencyUnavailable as exc:
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.CONCURRENCY_LIMITED,
                )
                self._record_embedding_budget_state(admission, "released")
                self._record_embedding_route_denial("concurrency_limited")
                raise EmbeddingError(
                    self._unavailable_error_category(), self.provider_id, True
                ) from exc
            if lease is None:
                await self._repository.finish_no_io(
                    admission.attempt_id,
                    ProviderAttemptOutcome.CONCURRENCY_LIMITED,
                )
                self._record_embedding_budget_state(admission, "released")
                self._record_embedding_route_denial("concurrency_limited")
                raise EmbeddingError(
                    self._unavailable_error_category(), self.provider_id, True
                )
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id,
                outcome="acquired",
            )
        try:
            authority_current = self._before_io is None or await self._before_io()
        except BaseException:
            if lease is not None:
                await self._safe_embedding_release(lease)
            raise
        if not authority_current:
            if lease is not None:
                await self._safe_embedding_release(lease)
            await self._repository.finish_no_io(
                admission.attempt_id, ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
            )
            self._record_embedding_budget_state(admission, "released")
            raise EmbeddingError(
                self._unavailable_error_category(), self.provider_id, False
            )
        if not await self._repository.mark_io_started(
            admission.attempt_id,
            self._source.execution_owner or self._source.source_key,
        ):
            if lease is not None:
                await self._safe_embedding_release(lease)
            self._record_embedding_route_denial("invalid_policy")
            raise EmbeddingError(
                self._unavailable_error_category(), self.provider_id, False
            )
        io_started = perf_counter()
        try:
            vector = await self._provider.embed_text(text)
        except EmbeddingError as error:
            self._record_embedding_attempt(
                "provider_error", perf_counter() - io_started
            )
            completion = await self._repository.finish_io(
                admission.attempt_id,
                outcome=ProviderAttemptOutcome.PROVIDER_ERROR,
                input_tokens=None,
                output_tokens=None,
                total_tokens=None,
                provider_request_id=None,
                retryable=error.retryable,
                error_category=error.category.value,
            )
            if completion is None:
                raise EmbeddingError(
                    self._unavailable_error_category(), self.provider_id, False
                ) from error
            self._record_embedding_completion(completion)
            self._record_embedding_budget_state(admission, "consumed")
            raise
        except Exception:
            self._record_embedding_attempt(
                "unexpected_error", perf_counter() - io_started
            )
            raise
        finally:
            if lease is not None:
                await self._safe_embedding_release(lease)
        self._record_embedding_attempt("success", perf_counter() - io_started)
        completion = await self._repository.finish_io(
            admission.attempt_id,
            outcome=ProviderAttemptOutcome.SUCCESS,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_request_id=None,
            retryable=False,
            error_category=None,
        )
        if completion is None:
            raise EmbeddingError(
                self._unavailable_error_category(), self.provider_id, False
            )
        await self._repository.set_application_outcome(admission.attempt_id, "accepted")
        self._record_embedding_completion(completion)
        self._record_embedding_budget_state(admission, "consumed")
        return vector

    def _record_embedding_completion(self, completion: ProviderUsageCompletion) -> None:
        self._telemetry.increment(
            "january_provider_usage_quality_total",
            provider=self.provider_id,
            workload="embedding",
            usage_quality=completion.usage_quality.value,
        )
        self._telemetry.increment(
            "january_provider_estimate_outcomes_total",
            provider=self.provider_id,
            workload="embedding",
            estimate_quality=completion.estimate_quality.value,
        )
        if completion.estimated_cost_microusd is not None:
            self._telemetry.increment(
                "january_provider_estimated_cost_microusd_total",
                completion.estimated_cost_microusd,
                provider=self.provider_id,
                workload="embedding",
            )
        if completion.health_reason is not None:
            self._telemetry.increment(
                "january_provider_health_transitions_total",
                provider=self.provider_id,
                from_state=(
                    completion.health_from.value
                    if completion.health_from is not None
                    else "unknown"
                ),
                to_state=(
                    completion.health_to.value
                    if completion.health_to is not None
                    else "unknown"
                ),
                reason=completion.health_reason,
            )

    def _record_embedding_attempt(self, outcome: str, duration: float) -> None:
        labels = {
            "provider": self.provider_id,
            "workload": "embedding",
            "operation": self._operation.value,
            "route_role": "primary",
            "outcome": outcome,
        }
        self._telemetry.increment("january_provider_attempts_total", **labels)
        self._telemetry.observe(
            "january_provider_attempt_duration_seconds", duration, **labels
        )

    def _record_embedding_budget_state(
        self, admission: ProviderAdmission, outcome: str
    ) -> None:
        for event in admission.budget_events:
            if event.reserved:
                self._telemetry.increment(
                    "january_provider_budget_reservations_total",
                    workload="embedding",
                    scope=event.scope.value,
                    outcome=outcome,
                )

    def _record_embedding_route_denial(self, reason: str) -> None:
        self._telemetry.increment(
            "january_provider_routing_decisions_total",
            workload="embedding",
            operation=self._operation.value,
            route_role="primary",
            outcome="denied",
            reason=reason,
        )

    async def _safe_embedding_release(self, lease: ConcurrencyLease) -> None:
        limiter = self._concurrency_limiter
        if limiter is None:
            return
        try:
            await limiter.release(lease)
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id,
                outcome="released",
            )
        except ConcurrencyUnavailable:
            self._telemetry.increment(
                "january_provider_concurrency_events_total",
                provider=self.provider_id,
                outcome="unavailable",
            )

    @staticmethod
    def _budget_error_category() -> EmbeddingErrorCategory:
        return EmbeddingErrorCategory.BUDGET_EXHAUSTED

    @staticmethod
    def _unavailable_error_category() -> EmbeddingErrorCategory:
        return EmbeddingErrorCategory.PROVIDER_UNAVAILABLE

    @staticmethod
    def _rate_error_category() -> EmbeddingErrorCategory:
        return EmbeddingErrorCategory.RATE_LIMITED

    async def aclose(self) -> None:
        await self._provider.aclose()
