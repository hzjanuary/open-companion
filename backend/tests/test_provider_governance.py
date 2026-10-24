import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.context import ConversationContext
from app.application.model_provider import (
    GenerationRequest,
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from app.application.ports.provider_governance import (
    ProviderAdmission,
    ProviderUsageCompletion,
    ProviderWorkSource,
    ResolvedProviderRoute,
)
from app.application.provider_governance import (
    capability_matches,
    conservative_utf8_input_bound,
    validate_requirements,
)
from app.application.semantic_memory import EmbeddingVector
from app.core.config import Settings
from app.domain.planning import ProviderErrorCategory, ProviderId
from app.domain.provider_governance import (
    MAX_BIGINT,
    BudgetWindowKind,
    EstimateQuality,
    GenerationPrice,
    ProviderAttemptOutcome,
    ProviderDataClass,
    ProviderHealth,
    ProviderOperation,
    RouteRole,
    UsageObservation,
    UsageQuality,
    WorkloadClass,
    budget_window,
    estimate_generation_cost,
    reserve_generation_cost,
)
from app.domain.rate_limit import RateLimitDecision
from app.infrastructure.concurrency import ConcurrencyUnavailable
from app.infrastructure.governed_provider import (
    GovernedEmbeddingProvider,
    GovernedModelProvider,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.interface.http.dependencies import database_session
from app.interface.http.provider_governance_control import (
    BudgetInput,
    CapabilityInput,
    PriceInput,
    RoutingInput,
)
from app.main import create_app
from app.runtime.conversation_summary_worker import _generate_governed_summary
from tests.conftest import AppClient


@pytest.mark.parametrize(
    ("values", "quality", "expected"),
    [
        ((4, 6, 10), UsageQuality.COMPLETE, (4, 6, 10)),
        ((4, None, None), UsageQuality.PARTIAL, (4, None, None)),
        ((None, None, None), UsageQuality.MISSING, (None, None, None)),
        ((-1, None, None), UsageQuality.INVALID, (None, None, None)),
        ((4, 6, 9), UsageQuality.INVALID, (None, None, None)),
        ((True, None, None), UsageQuality.INVALID, (None, None, None)),
    ],
)
def test_usage_quality_never_zero_fills(
    values: tuple[object, object, object],
    quality: UsageQuality,
    expected: tuple[int | None, int | None, int | None],
) -> None:
    observed = UsageObservation.classify(*values)
    assert observed.quality == quality
    assert (
        observed.input_tokens,
        observed.output_tokens,
        observed.total_tokens,
    ) == expected


def test_fixed_point_estimate_and_conservative_reservation() -> None:
    price = GenerationPrice(1_250_000, 2_500_000)
    assert estimate_generation_cost(3, 2, price) == 9
    assert reserve_generation_cost(3, 2, price) >= 9
    with pytest.raises(ValueError):
        reserve_generation_cost(
            MAX_BIGINT, MAX_BIGINT, GenerationPrice(MAX_BIGINT, MAX_BIGINT)
        )


def test_utc_budget_windows_cover_month_boundary() -> None:
    at = datetime(2028, 2, 29, 23, 59, tzinfo=UTC)
    daily = budget_window(BudgetWindowKind.DAILY_UTC, at)
    monthly = budget_window(BudgetWindowKind.MONTHLY_UTC, at)
    assert daily == (
        datetime(2028, 2, 29, tzinfo=UTC),
        datetime(2028, 3, 1, tzinfo=UTC),
    )
    assert monthly == (
        datetime(2028, 2, 1, tzinfo=UTC),
        datetime(2028, 3, 1, tzinfo=UTC),
    )


def _route(metadata: dict[str, object]) -> ResolvedProviderRoute:
    return ResolvedProviderRoute(
        snapshot_id=uuid4(),
        policy_revision_id=uuid4(),
        capability_id=uuid4(),
        provider_id=ProviderId.OPENAI,
        model="approved-model",
        adapter_key=ProviderId.OPENAI,
        position=0,
        data_class=ProviderDataClass.APPROVED_EXTERNAL,
        credential_slot="openai",
        reservation_strategy="utf8_byte_upper_bound",
        capability_metadata=metadata,
        allowed_fallback_reasons=frozenset({"timeout"}),
    )


def test_capability_matching_is_exact_and_data_class_is_enforced() -> None:
    requirements = {
        "json_schema": True,
        "maximum_output_tokens": 300,
        "allowed_data_classes": ["approved_external"],
        "require_current_health": True,
    }
    assert capability_matches(
        _route({"json_schema": True, "maximum_output_tokens": 300}),
        WorkloadClass.CHAT_GENERATION,
        requirements,
    ).eligible
    assert not capability_matches(
        _route({"json_schema": False, "maximum_output_tokens": 300}),
        WorkloadClass.CHAT_GENERATION,
        requirements,
    ).eligible
    with pytest.raises(ValueError):
        validate_requirements({**requirements, "semantic_quality": "best"})


def test_input_bound_is_utf8_safe_and_nonzero() -> None:
    assert conservative_utf8_input_bound("xin chào", "🙂") >= len("xin chào🙂".encode())


def test_control_contract_rejects_unknown_schema_and_invalid_price_shape() -> None:
    with pytest.raises(ValidationError):
        RoutingInput(
            schema_version="future",  # type: ignore[arg-type]
            requirements={},
            capability_ids=[uuid4()],
            effective_at=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        PriceInput(
            capability_id=uuid4(),
            unit_basis="generation_tokens",
            input_rate=1,
            effective_from=datetime.now(UTC),
        )
    with pytest.raises(ValidationError):
        CapabilityInput(
            provider_id=ProviderId.OPENAI,
            adapter_key=ProviderId.GEMINI,
            workload_class=WorkloadClass.CHAT_GENERATION,
            model="mismatch",
            capability_metadata={"maximum_output_tokens": 10},
            data_class=ProviderDataClass.APPROVED_EXTERNAL,
            credential_slot="gemini",
            credential_configured=True,
            reservation_strategy="utf8_byte_upper_bound",
        )
    with pytest.raises(ValidationError):
        CapabilityInput(
            provider_id=ProviderId.OLLAMA,
            adapter_key=ProviderId.OLLAMA,
            workload_class=WorkloadClass.EMBEDDING,
            model="embedding",
            capability_metadata={
                "embedding_dimension": 768,
                "embedding_version": "v1",
            },
            data_class=ProviderDataClass.APPROVED_EXTERNAL,
            credential_slot="ollama",
            credential_configured=True,
            reservation_strategy="request_count",
        )
    disabled = BudgetInput(
        workload_class=WorkloadClass.CHAT_GENERATION,
        measurement="requests",  # type: ignore[arg-type]
        window_kind="daily_utc",  # type: ignore[arg-type]
        enabled=False,
        amount=100,
        mode="hard",  # type: ignore[arg-type]
        alert_threshold_bps=8000,
        effective_at=datetime.now(UTC),
    )
    assert disabled.enabled is False


def test_control_routes_exist_only_behind_existing_control_plane() -> None:
    disabled_app = create_app(Settings())
    disabled = disabled_app.openapi()["paths"]
    budget_path = "/control/v1/deployment/provider-budgets"
    usage_path = (
        "/control/v1/tenants/{tenant_id}/connections/{resource_id}"
        "/provider-usage-summary"
    )
    assert budget_path not in disabled
    assert usage_path not in disabled
    settings = Settings(
        control_plane_enabled=True,
        control_plane_jwt_secret="x" * 32,
        control_plane_jwt_issuer="issuer",
        control_plane_jwt_audience="audience",
    )
    enabled_app = create_app(settings)
    enabled = enabled_app.openapi()["paths"]
    assert budget_path in enabled
    assert usage_path in enabled

    async def session_override():
        yield AsyncMock()

    enabled_app.dependency_overrides[database_session] = session_override
    concrete_usage = usage_path.format(tenant_id=uuid4(), resource_id=uuid4())
    for path in (budget_path, concrete_usage):
        assert AppClient(disabled_app).get(path).status_code == 404
        assert AppClient(enabled_app).get(path).status_code == 401


def test_governed_modes_require_control_plane_and_recovery_worker() -> None:
    common = {
        "control_plane_enabled": True,
        "control_plane_jwt_secret": "x" * 32,
        "control_plane_jwt_issuer": "issuer",
        "control_plane_jwt_audience": "audience",
    }
    with pytest.raises(ValidationError):
        Settings(provider_governance_mode="enforce", **common)
    with pytest.raises(ValidationError):
        Settings(
            provider_governance_mode="enforce",
            provider_governance_worker_enabled=True,
            provider_reservation_lease_seconds=20,
            **common,
        )
    settings = Settings(
        provider_governance_mode="enforce",
        provider_governance_worker_enabled=True,
        **common,
    )
    assert settings.provider_governance_mode == "enforce"


def test_provider_metrics_are_closed_and_reject_prohibited_labels() -> None:
    recorder = InMemoryMetricsRecorder()
    recorder.increment(
        "january_provider_usage_quality_total",
        provider="openai",
        workload="chat_generation",
        usage_quality="missing",
    )
    recorder.increment(
        "january_provider_estimate_outcomes_total",
        provider="openai",
        workload="chat_generation",
        estimate_quality=EstimateQuality.UNAVAILABLE.value,
    )
    with pytest.raises(ValueError):
        recorder.increment(
            "january_provider_usage_quality_total",
            provider="user-provided-model",
            workload="chat_generation",
            usage_quality="complete",
        )
    with pytest.raises(ValueError):
        recorder.increment(
            "january_provider_usage_quality_total",
            provider="openai",
            workload="chat_generation",
            usage_quality="complete",
            user_id="forbidden",
        )


class _Provider:
    provider_id = ProviderId.OPENAI
    model = "approved-model"
    capabilities = ProviderCapabilities(True, True, "max_tokens", True, True)

    def __init__(self, events: list[str], structured_text: str = "{}") -> None:
        self.events = events
        self.calls = 0
        self.structured_text = structured_text

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        del request
        self.events.append("provider_io")
        self.calls += 1
        return ProviderResult(
            self.provider_id,
            self.model,
            self.structured_text,
            "opaque",
            ProviderUsage(2, 3, 5),
            timedelta(milliseconds=1),
            "stop",
        )

    async def aclose(self) -> None:
        return None


class _Repository:
    def __init__(self, events: list[str], allowed: bool = True) -> None:
        self.events = events
        self.allowed = allowed

    async def reserve_attempt(
        self, *args: object, **kwargs: object
    ) -> ProviderAdmission:
        del args, kwargs
        self.events.append("budget")
        return ProviderAdmission(
            self.allowed,
            uuid4(),
            "attempt",
            ProviderAttemptOutcome.PENDING
            if self.allowed
            else ProviderAttemptOutcome.BUDGET_DENIED,
        )

    async def mark_io_started(self, attempt_id: object, owner: str) -> bool:
        del attempt_id, owner
        self.events.append("io_started")
        return True

    async def record_rate_decision(self, *args: object) -> None:
        del args
        self.events.append("rate_audit")

    async def finish_no_io(self, *args: object) -> bool:
        del args
        self.events.append("released")
        return True

    async def finish_io(
        self, *args: object, **kwargs: object
    ) -> ProviderUsageCompletion:
        del args, kwargs
        self.events.append("reconciled")
        return ProviderUsageCompletion(
            UsageQuality.COMPLETE,
            EstimateQuality.ESTIMATED,
            1,
            ProviderHealth.DEGRADED,
            ProviderHealth.READY,
            "success_threshold",
        )

    async def set_application_outcome(self, *args: object) -> bool:
        del args
        self.events.append("application")
        return True


class _Limiter:
    def __init__(self, events: list[str], allowed: bool = True) -> None:
        self.events = events
        self.allowed = allowed

    async def check(self, *args: object) -> RateLimitDecision:
        del args
        self.events.append("rate")
        return RateLimitDecision(self.allowed)


class _Lease:
    provider = ProviderId.OPENAI
    token = "must-not-be-persisted"


class _Concurrency:
    def __init__(
        self,
        events: list[str],
        release_fails: bool = False,
        provider: ProviderId = ProviderId.OPENAI,
    ) -> None:
        self.events = events
        self.release_fails = release_fails
        self.provider = provider

    async def acquire(self, provider: ProviderId) -> _Lease:
        assert provider == self.provider
        self.events.append("concurrency")
        return _Lease()

    async def release(self, lease: _Lease) -> None:
        del lease
        self.events.append("release_concurrency")
        if self.release_fails:
            raise ConcurrencyUnavailable("coordination unavailable")


def _generation_request() -> GenerationRequest:
    return GenerationRequest(
        uuid4(),
        cast(ConversationContext, object()),
        "prompt-v1",
        "schema-v1",
        "en",
        32,
        "system",
        "user",
        {},
    )


def _governed(
    events: list[str],
    *,
    budget_allowed: bool = True,
    rate_allowed: bool = True,
    release_fails: bool = False,
    telemetry: InMemoryMetricsRecorder | None = None,
) -> tuple[GovernedModelProvider, _Provider]:
    provider = _Provider(events)
    governed = GovernedModelProvider(
        provider,
        _route({"json_schema": True, "maximum_output_tokens": 300}),
        ProviderWorkSource(
            "planning:test",
            execution_owner="worker-a",
            planning_job_id=uuid4(),
        ),
        ProviderOperation.RESPONSE_PLANNING,
        cast(object, _Repository(events, budget_allowed)),
        Settings(),
        cast(object, _Limiter(events, rate_allowed)),
        cast(object, _Concurrency(events, release_fails)),
        telemetry or InMemoryMetricsRecorder(),
    )
    return governed, provider


def test_governed_provider_orders_every_pre_io_gate_and_reconciles() -> None:
    events: list[str] = []
    telemetry = InMemoryMetricsRecorder()
    governed, provider = _governed(events, release_fails=True, telemetry=telemetry)
    result = asyncio.run(
        governed.generate_attempt(_generation_request(), RouteRole.PRIMARY, 1)
    )
    assert result.provider == ProviderId.OPENAI
    assert provider.calls == 1
    assert events == [
        "budget",
        "rate",
        "rate_audit",
        "concurrency",
        "io_started",
        "provider_io",
        "release_concurrency",
        "reconciled",
    ]
    labels = {
        "provider": "openai",
        "workload": "chat_generation",
        "operation": "response_planning",
        "route_role": "primary",
        "outcome": "success",
    }
    assert telemetry.counter_value("january_provider_attempts_total", **labels) == 1
    assert (
        len(
            telemetry.histogram_values(
                "january_provider_attempt_duration_seconds", **labels
            )
        )
        == 1
    )


def test_governed_presence_hook_runs_only_after_admission_and_io_start() -> None:
    events: list[str] = []
    provider = _Provider(events)

    async def on_io_start() -> None:
        events.append("presence")

    governed = GovernedModelProvider(
        provider,
        _route({"json_schema": True, "maximum_output_tokens": 300}),
        ProviderWorkSource(
            "planning:presence",
            execution_owner="worker-a",
            planning_job_id=uuid4(),
        ),
        ProviderOperation.RESPONSE_PLANNING,
        cast(object, _Repository(events)),
        Settings(),
        cast(object, _Limiter(events)),
        cast(object, _Concurrency(events)),
        InMemoryMetricsRecorder(),
        on_io_start=on_io_start,
    )
    asyncio.run(governed.generate_attempt(_generation_request(), RouteRole.PRIMARY, 1))
    assert events[:6] == [
        "budget",
        "rate",
        "rate_audit",
        "concurrency",
        "io_started",
        "presence",
    ]
    assert events[6] == "provider_io"

    denied_events: list[str] = []
    denied_provider = _Provider(denied_events)
    denied = GovernedModelProvider(
        denied_provider,
        _route({"json_schema": True, "maximum_output_tokens": 300}),
        ProviderWorkSource(
            "planning:presence-denied",
            execution_owner="worker-a",
            planning_job_id=uuid4(),
        ),
        ProviderOperation.RESPONSE_PLANNING,
        cast(object, _Repository(denied_events, False)),
        Settings(),
        cast(object, _Limiter(denied_events)),
        cast(object, _Concurrency(denied_events)),
        InMemoryMetricsRecorder(),
        on_io_start=on_io_start,
    )
    with pytest.raises(ProviderError) as captured:
        asyncio.run(
            denied.generate_attempt(_generation_request(), RouteRole.PRIMARY, 1)
        )
    assert captured.value.category == ProviderErrorCategory.BUDGET_EXHAUSTED
    assert denied_events == ["budget"]
    assert denied_provider.calls == 0


def test_governed_presence_hook_failure_releases_concurrency_lease() -> None:
    events: list[str] = []
    provider = _Provider(events)

    async def failing_io_start() -> None:
        events.append("presence")
        raise RuntimeError("hook failed")

    governed = GovernedModelProvider(
        provider,
        _route({"json_schema": True, "maximum_output_tokens": 300}),
        ProviderWorkSource(
            "planning:presence-failure",
            execution_owner="worker-a",
            planning_job_id=uuid4(),
        ),
        ProviderOperation.RESPONSE_PLANNING,
        cast(object, _Repository(events)),
        Settings(),
        cast(object, _Limiter(events)),
        cast(object, _Concurrency(events)),
        InMemoryMetricsRecorder(),
        on_io_start=failing_io_start,
    )
    with pytest.raises(RuntimeError, match="hook failed"):
        asyncio.run(
            governed.generate_attempt(_generation_request(), RouteRole.PRIMARY, 1)
        )
    assert events == [
        "budget",
        "rate",
        "rate_audit",
        "concurrency",
        "io_started",
        "presence",
        "release_concurrency",
    ]
    assert provider.calls == 0


def test_summary_generation_uses_the_governed_attempt_boundary() -> None:
    events: list[str] = []
    provider = _Provider(events, '{"summary":"bounded summary"}')
    recorder = InMemoryMetricsRecorder()
    result, candidate = asyncio.run(
        _generate_governed_summary(
            Settings(),
            _generation_request(),
            (_route({"json_schema": True, "maximum_output_tokens": 300}),),
            ProviderWorkSource(
                "summary:test",
                execution_owner="summary-worker",
                summary_job_id=uuid4(),
            ),
            cast(object, _Repository(events)),
            cast(object, _Limiter(events)),
            cast(object, _Concurrency(events)),
            recorder,
            provider,
        )
    )
    assert result.provider == ProviderId.OPENAI
    assert candidate.summary == "bounded summary"
    assert events == [
        "budget",
        "rate",
        "rate_audit",
        "concurrency",
        "io_started",
        "provider_io",
        "release_concurrency",
        "reconciled",
        "application",
    ]
    assert (
        recorder.counter_value(
            "january_provider_attempts_total",
            provider="openai",
            workload="chat_generation",
            operation="summary_generation",
            route_role="primary",
            outcome="success",
        )
        == 1
    )


def test_embedding_uses_independent_governed_attempt_boundary() -> None:
    events: list[str] = []

    class EmbeddingProvider:
        provider_id = "ollama"
        model = "embedding-model"
        dimension = 2

        async def embed_text(self, text: str) -> EmbeddingVector:
            assert text == "bounded input"
            events.append("provider_io")
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    recorder = InMemoryMetricsRecorder()
    route = ResolvedProviderRoute(
        snapshot_id=uuid4(),
        policy_revision_id=uuid4(),
        capability_id=uuid4(),
        provider_id=ProviderId.OLLAMA,
        model="embedding-model",
        adapter_key=ProviderId.OLLAMA,
        position=0,
        data_class=ProviderDataClass.LOCAL,
        credential_slot="ollama",
        reservation_strategy="request_count",
        capability_metadata={
            "embedding_dimension": 2,
            "embedding_version": "v1",
        },
        allowed_fallback_reasons=frozenset(),
    )
    governed = GovernedEmbeddingProvider(
        EmbeddingProvider(),
        route,
        ProviderWorkSource(
            "semantic:test",
            execution_owner="semantic-worker",
            semantic_index_job_id=uuid4(),
        ),
        ProviderOperation.SEMANTIC_INDEX,
        cast(object, _Repository(events)),
        Settings(),
        cast(object, _Limiter(events)),
        cast(object, _Concurrency(events, provider=ProviderId.OLLAMA)),
        recorder,
    )
    vector = asyncio.run(governed.embed_text("bounded input"))
    assert vector.values == (0.1, 0.2)
    assert events == [
        "budget",
        "rate",
        "rate_audit",
        "concurrency",
        "io_started",
        "provider_io",
        "release_concurrency",
        "reconciled",
        "application",
    ]
    assert (
        recorder.counter_value(
            "january_provider_attempts_total",
            provider="ollama",
            workload="embedding",
            operation="semantic_index",
            route_role="primary",
            outcome="success",
        )
        == 1
    )


@pytest.mark.parametrize(
    ("budget_allowed", "rate_allowed", "expected"),
    [
        (False, True, ["budget"]),
        (True, False, ["budget", "rate", "rate_audit", "released"]),
    ],
)
def test_governed_provider_denials_never_reach_external_io(
    budget_allowed: bool, rate_allowed: bool, expected: list[str]
) -> None:
    events: list[str] = []
    governed, provider = _governed(
        events, budget_allowed=budget_allowed, rate_allowed=rate_allowed
    )
    with pytest.raises(ProviderError) as raised:
        asyncio.run(
            governed.generate_attempt(_generation_request(), RouteRole.PRIMARY, 1)
        )
    expected_category = (
        ProviderErrorCategory.BUDGET_EXHAUSTED
        if not budget_allowed
        else ProviderErrorCategory.RATE_LIMITED
    )
    assert raised.value.category == expected_category
    assert provider.calls == 0
    assert events == expected
