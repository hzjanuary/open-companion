"""Provider retry, correction, fallback, and local response-plan validation."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from time import perf_counter

from app.application.model_provider import (
    AttemptGovernedModelProvider,
    GenerationRequest,
    ModelProvider,
    ProviderError,
)
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.response_plan import ResponsePlanCandidate, ResponsePlanPolicy
from app.application.telemetry import record_provider_usage
from app.domain.planning import ProviderErrorCategory
from app.domain.provider_governance import RouteRole


@dataclass(frozen=True, slots=True)
class PlanningGeneration:
    candidate: ResponsePlanCandidate | None
    provider_error: ProviderError | None
    provider: ModelProvider | None


async def generate_validated_plan(
    request: GenerationRequest,
    policy: ResponsePlanPolicy,
    primary: ModelProvider,
    fallback: ModelProvider | Sequence[ModelProvider] | None,
    transport_attempts: int,
    correction_attempts: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_attempt: Callable[
        [ModelProvider, bool, ProviderError | None, int], Awaitable[None]
    ]
    | None = None,
    before_provider: Callable[[ModelProvider], Awaitable[ProviderError | None]]
    | None = None,
    telemetry: MetricsRecorder | None = None,
    pricing: dict[str, dict[str, int]] | None = None,
) -> PlanningGeneration:
    recorder = telemetry or NoOpMetricsRecorder()
    configured_pricing = pricing or {}
    terminal_provider_error: ProviderError | None = None
    fallback_providers = (
        ()
        if fallback is None
        else tuple(fallback)
        if isinstance(fallback, Sequence)
        else (fallback,)
    )
    providers = (primary, *fallback_providers)
    ordinal = 0
    for provider_index, provider in enumerate(providers):
        errors: tuple[str, ...] = ()
        for correction in range(correction_attempts + 1):
            if before_provider is not None:
                limit_error = await before_provider(provider)
                if limit_error is not None:
                    return PlanningGeneration(None, limit_error, provider)
            current = replace(
                request,
                correction_attempt=correction,
                correction_errors=errors,
            )
            for attempt in range(transport_attempts):
                ordinal += 1
                role = (
                    RouteRole.RETRY
                    if attempt > 0
                    else RouteRole.CORRECTION
                    if correction > 0
                    else RouteRole.FALLBACK
                    if provider_index > 0
                    else RouteRole.PRIMARY
                )
                try:
                    started = perf_counter()
                    result = (
                        await provider.generate_attempt(current, role, ordinal)
                        if isinstance(provider, AttemptGovernedModelProvider)
                        else await provider.generate(current)
                    )
                except ProviderError as error:
                    duration = perf_counter() - started
                    recorder.increment(
                        "january_model_requests_total",
                        provider=provider.provider_id.value,
                        outcome=error.category.value,
                    )
                    recorder.observe(
                        "january_model_request_duration_seconds",
                        duration,
                        provider=provider.provider_id.value,
                        outcome=error.category.value,
                    )
                    if on_attempt is not None:
                        await on_attempt(provider, False, error, correction)
                    if error.category == ProviderErrorCategory.SAFETY_REFUSAL:
                        return PlanningGeneration(None, error, provider)
                    if error.retryable and attempt + 1 < transport_attempts:
                        await sleep(min(2.0, 0.25 * (2**attempt)))
                        continue
                    terminal_provider_error = error
                    break
                recorder.increment(
                    "january_model_requests_total",
                    provider=result.provider.value,
                    outcome="success",
                )
                recorder.observe(
                    "january_model_request_duration_seconds",
                    result.latency.total_seconds(),
                    provider=result.provider.value,
                    outcome="success",
                )
                record_provider_usage(
                    recorder,
                    provider=result.provider.value,
                    model=result.model,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    total_tokens=result.usage.total_tokens,
                    pricing=configured_pricing,
                )
                if result.refused or result.safety_blocked:
                    refusal = ProviderError(
                        ProviderErrorCategory.SAFETY_REFUSAL,
                        result.provider,
                        result.model,
                        False,
                        "generate",
                        "model refused",
                    )
                    if on_attempt is not None:
                        await on_attempt(provider, False, refusal, correction)
                    if isinstance(provider, AttemptGovernedModelProvider):
                        await provider.record_application_outcome("refused")
                    recorder.increment(
                        "january_response_plan_validation_total",
                        outcome="safe_fallback",
                    )
                    return PlanningGeneration(
                        None,
                        refusal,
                        provider,
                    )
                try:
                    parsed = ResponsePlanCandidate.model_validate_json(
                        result.structured_text
                    )
                    if on_attempt is not None:
                        await on_attempt(provider, True, None, correction)
                    if isinstance(provider, AttemptGovernedModelProvider):
                        await provider.record_application_outcome("accepted")
                    recorder.increment(
                        "january_response_plan_validation_total", outcome="valid"
                    )
                    return PlanningGeneration(
                        policy.apply(parsed, request.context), None, provider
                    )
                except ValueError:
                    invalid = ProviderError(
                        ProviderErrorCategory.STRUCTURED_OUTPUT,
                        provider.provider_id,
                        provider.model,
                        False,
                        "generate",
                        "invalid structured output",
                    )
                    if on_attempt is not None:
                        await on_attempt(provider, False, invalid, correction)
                    if isinstance(provider, AttemptGovernedModelProvider):
                        await provider.record_application_outcome("invalid_output")
                    recorder.increment(
                        "january_response_plan_validation_total",
                        outcome="correction_requested"
                        if correction < correction_attempts
                        else "invalid_terminal",
                    )
                    errors = ("response plan failed local schema or policy validation",)
                    if correction >= correction_attempts:
                        terminal_provider_error = invalid
                        break
            else:
                continue
            if errors:
                continue
        if provider_index + 1 >= len(providers):
            break
        if (
            isinstance(provider, AttemptGovernedModelProvider)
            and terminal_provider_error is not None
            and not provider.fallback_allowed(terminal_provider_error.category)
        ):
            return PlanningGeneration(None, terminal_provider_error, provider)
    if terminal_provider_error is not None:
        return PlanningGeneration(None, terminal_provider_error, provider)
    return PlanningGeneration(
        None,
        ProviderError(
            ProviderErrorCategory.STRUCTURED_OUTPUT,
            primary.provider_id,
            primary.model,
            False,
            "generate",
            "no valid response plan",
        ),
        primary,
    )
