"""PostgreSQL atomicity and recovery proof for SPEC-026."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, select, text, update

from app.application.context import ConversationContext
from app.application.model_provider import (
    GenerationRequest,
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from app.core.config import Settings
from app.domain.conversation import ProcessingOutcome
from app.domain.persistence import (
    AssistantStatus,
    ConversationType,
    IngressSource,
    MessageDirection,
    MessageType,
    Platform,
    PlatformConnectionStatus,
)
from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    BudgetWindowKind,
    GovernanceMode,
    ProviderAttemptOutcome,
    ProviderAttemptState,
    ProviderDataClass,
    ProviderHealth,
    ProviderLifecycle,
    ProviderOperation,
    ReservationState,
    RouteRole,
    UsageQuality,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitDecision
from app.domain.tenancy import LEGACY_TENANT_ID
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import (
    AssistantModel,
    ControlAssistantBindingModel,
    ControlAuditEventModel,
    ControlConnectionBindingModel,
    ControlDeploymentAuthorityModel,
    ControlOperatorIdentityModel,
    ControlOperatorMembershipModel,
    ControlTenantModel,
    ConversationModel,
    ConversationProcessingRecordModel,
    IncomingPlatformUpdateModel,
    MessageModel,
    PlatformConnectionModel,
    ProviderBudgetEvaluationModel,
    ProviderBudgetHeadModel,
    ProviderBudgetModel,
    ProviderBudgetReservationModel,
    ProviderBudgetRevisionModel,
    ProviderBudgetWindowModel,
    ProviderCapabilityModel,
    ProviderCapabilityStateModel,
    ProviderHealthPolicyRevisionModel,
    ProviderPriceRevisionModel,
    ProviderRoutingPolicyHeadModel,
    ProviderRoutingPolicyRevisionModel,
    ProviderRoutingPolicyRouteModel,
    ProviderUsageAttemptModel,
    RateLimitEventModel,
    ResponsePlanningJobModel,
)
from app.infrastructure.database.provider_governance import (
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.governed_provider import GovernedModelProvider
from app.interface.http.control_plane import Principal, principal_for
from app.main import create_app


class _BlockingProvider:
    provider_id = ProviderId.OPENAI
    model = "spec026-model"
    capabilities = ProviderCapabilities(True, True, "max_tokens", True, True)

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release_call = asyncio.Event()

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        del request
        self.entered.set()
        await self.release_call.wait()
        return ProviderResult(
            self.provider_id,
            self.model,
            "{}",
            "opaque-request-reference",
            ProviderUsage(10, 20, 30),
            timedelta(milliseconds=1),
            "stop",
        )

    async def aclose(self) -> None:
        return None


class _AllowedRateLimiter:
    async def check(self, *args: object) -> RateLimitDecision:
        del args
        return RateLimitDecision(True)


class _Lease:
    provider = ProviderId.OPENAI
    token = "redis-only"


class _AvailableConcurrency:
    async def acquire(self, provider: ProviderId) -> _Lease:
        assert provider == ProviderId.OPENAI
        return _Lease()

    async def release(self, lease: _Lease) -> None:
        del lease


async def _seed(database: Database) -> tuple[UUID, dict[str, object]]:
    now = datetime.now(UTC)
    async with database.session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "TRUNCATE control_operator_identities, control_tenants, "
                    "assistants CASCADE"
                )
            )
            actor = ControlOperatorIdentityModel(issuer="spec026", subject="operator")
            tenant = ControlTenantModel(
                id=LEGACY_TENANT_ID, slug="spec026", name="SPEC 026"
            )
            session.add(tenant)
            await session.flush()
            assistant = AssistantModel(
                tenant_id=tenant.id,
                slug="provider-january",
                name="January",
                status=AssistantStatus.ACTIVE,
            )
            session.add_all([actor, assistant])
            await session.flush()
            connection = PlatformConnectionModel(
                tenant_id=tenant.id,
                assistant_id=assistant.id,
                platform=Platform.TELEGRAM,
                external_bot_id="spec026-bot",
                status=PlatformConnectionStatus.ACTIVE,
            )
            session.add(connection)
            await session.flush()
            session.add_all(
                [
                    ControlAssistantBindingModel(
                        tenant_id=tenant.id, assistant_id=assistant.id
                    ),
                    ControlConnectionBindingModel(
                        tenant_id=tenant.id, connection_id=connection.id
                    ),
                ]
            )
            conversation = ConversationModel(
                platform_connection_id=connection.id,
                platform_conversation_id="spec026-conversation",
                conversation_type=ConversationType.PRIVATE,
            )
            session.add(conversation)
            await session.flush()
            message = MessageModel(
                conversation_id=conversation.id,
                platform_message_id="spec026-message",
                direction=MessageDirection.INCOMING,
                message_type=MessageType.TEXT,
                text="content is deliberately absent from governance rows",
            )
            incoming = IncomingPlatformUpdateModel(
                platform_connection_id=connection.id,
                platform=Platform.TELEGRAM,
                platform_update_id="spec026-update",
                update_type="message",
                ingress_source=IngressSource.WEBHOOK,
                raw_payload={},
                received_at=now,
            )
            session.add_all([message, incoming])
            await session.flush()
            record = ConversationProcessingRecordModel(
                incoming_update_id=incoming.id,
                outcome=ProcessingOutcome.MESSAGE_CREATED,
                conversation_id=conversation.id,
                message_id=message.id,
            )
            session.add(record)
            await session.flush()
            job = ResponsePlanningJobModel(
                conversation_processing_record_id=record.id,
                conversation_id=conversation.id,
                message_id=message.id,
                prompt_version="spec026",
                response_schema_version="response-plan-v2",
                attempt_count=1,
                lease_owner="spec026-worker-a",
            )
            capability = ProviderCapabilityModel(
                provider_id=ProviderId.OPENAI,
                adapter_key=ProviderId.OPENAI,
                workload_class=WorkloadClass.CHAT_GENERATION,
                model="spec026-model",
                capability_metadata={
                    "json_schema": True,
                    "maximum_output_tokens": 300,
                },
                data_class=ProviderDataClass.APPROVED_EXTERNAL,
                credential_slot="openai",
                credential_configured=True,
                reservation_strategy="utf8_byte_upper_bound",
                created_by_identity_id=actor.id,
            )
            session.add_all([job, capability])
            await session.flush()
            health_policy = ProviderHealthPolicyRevisionModel(
                capability_id=capability.id,
                version=1,
                observation_window_seconds=300,
                degraded_threshold=2,
                unavailable_threshold=3,
                recovery_success_threshold=2,
                stale_after_seconds=300,
                effective_at=now,
                created_by_identity_id=actor.id,
            )
            session.add(health_policy)
            await session.flush()
            session.add(
                ProviderCapabilityStateModel(
                    capability_id=capability.id,
                    lifecycle=ProviderLifecycle.ENABLED,
                    health=ProviderHealth.READY,
                    health_policy_revision_id=health_policy.id,
                    last_evaluated_at=now,
                )
            )
            requirements: dict[str, object] = {
                "json_schema": True,
                "maximum_output_tokens": 300,
                "allowed_data_classes": ["local", "approved_external"],
                "require_current_health": True,
            }
            policy = ProviderRoutingPolicyRevisionModel(
                scope_type=BudgetScope.DEPLOYMENT,
                scope_key="deployment",
                workload_class=WorkloadClass.CHAT_GENERATION,
                schema_version="provider-routing-v1",
                version=1,
                requirements=requirements,
                effective_at=now,
                created_by_identity_id=actor.id,
            )
            session.add(policy)
            await session.flush()
            session.add_all(
                [
                    ProviderRoutingPolicyRouteModel(
                        policy_revision_id=policy.id,
                        capability_id=capability.id,
                        position=0,
                    ),
                    ProviderRoutingPolicyHeadModel(
                        scope_key="deployment",
                        workload_class=WorkloadClass.CHAT_GENERATION,
                        policy_revision_id=policy.id,
                    ),
                    ProviderPriceRevisionModel(
                        capability_id=capability.id,
                        currency="USD",
                        unit_basis="generation_tokens",
                        input_rate=1_000_000,
                        output_rate=1_000_000,
                        effective_from=now - timedelta(seconds=1),
                        created_by_identity_id=actor.id,
                    ),
                ]
            )
            for scope, scope_key, scoped_tenant, assistant_id, connection_id in (
                (BudgetScope.DEPLOYMENT, "deployment", None, None, None),
                (
                    BudgetScope.ASSISTANT,
                    f"assistant:{assistant.id}",
                    tenant.id,
                    assistant.id,
                    None,
                ),
                (
                    BudgetScope.PLATFORM_CONNECTION,
                    f"platform_connection:{connection.id}",
                    tenant.id,
                    None,
                    connection.id,
                ),
            ):
                budget = ProviderBudgetModel(
                    scope_type=scope,
                    scope_key=scope_key,
                    tenant_id=scoped_tenant,
                    assistant_id=assistant_id,
                    connection_id=connection_id,
                    workload_class=WorkloadClass.CHAT_GENERATION,
                    measurement=BudgetMeasurement.ESTIMATED_COST_MICROUSD,
                    window_kind=BudgetWindowKind.DAILY_UTC,
                )
                session.add(budget)
                await session.flush()
                revision = ProviderBudgetRevisionModel(
                    budget_id=budget.id,
                    version=1,
                    amount=10_000,
                    mode=BudgetMode.HARD,
                    alert_threshold_bps=8000,
                    effective_at=now,
                    created_by_identity_id=actor.id,
                )
                session.add(revision)
                await session.flush()
                session.add(
                    ProviderBudgetHeadModel(
                        budget_id=budget.id, budget_revision_id=revision.id
                    )
                )
            return job.id, requirements


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_atomic_admission_replay_usage_and_lease_recovery() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            async with database.session_factory() as _sess:
                async with _sess.begin():
                    await _sess.execute(
                        text("TRUNCATE provider_usage_attempts CASCADE")
                    )
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            await repository.validate_prerequisites(WorkloadClass.CHAT_GENERATION)
            source = await repository.planning_source(job_id)
            assert source.execution_owner == "spec026-worker-a"
            routes = await repository.resolve_routes(
                source,
                WorkloadClass.CHAT_GENERATION,
                requirements,
            )
            assert len(routes) == 1

            async def reserve(ordinal: int = 1):  # type: ignore[no-untyped-def]
                return await repository.reserve_attempt(
                    source,
                    routes[0],
                    WorkloadClass.CHAT_GENERATION,
                    ProviderOperation.RESPONSE_PLANNING,
                    RouteRole.PRIMARY,
                    ordinal,
                    100,
                    300,
                )

            # Two concurrent equivalent admission requests with the SAME durable
            # idempotency identity must converge to exactly one canonical attempt:
            # same attempt_id, no duplicate row, no double reservation, and the
            # non-winner is fenced from starting I/O with a stale owner.
            first, replay = await asyncio.gather(reserve(), reserve())
            assert first.allowed and replay.allowed
            assert first.attempt_id == replay.attempt_id
            assert not await repository.mark_io_started(
                first.attempt_id, "stale-worker"
            )
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ProviderUsageAttemptModel)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ProviderBudgetReservationModel)
                    )
                    == 3
                )
            assert (
                sum(
                    await asyncio.gather(
                        repository.mark_io_started(
                            first.attempt_id, "spec026-worker-a"
                        ),
                        repository.mark_io_started(
                            replay.attempt_id, "spec026-worker-a"
                        ),
                    )
                )
                == 1
            )
            completion = await repository.finish_io(
                first.attempt_id,
                outcome=ProviderAttemptOutcome.SUCCESS,
                input_tokens=10,
                output_tokens=None,
                total_tokens=None,
                provider_request_id="opaque-provider-reference",
                retryable=False,
                error_category=None,
            )
            assert completion is not None
            assert completion.usage_quality == UsageQuality.PARTIAL
            assert completion.estimated_cost_microusd == 10
            mismatched_replay = await repository.reserve_attempt(
                source,
                routes[0],
                WorkloadClass.CHAT_GENERATION,
                ProviderOperation.RESPONSE_PLANNING,
                RouteRole.FALLBACK,
                1,
                100,
                300,
            )
            assert not mismatched_replay.allowed
            assert (
                mismatched_replay.outcome
                == ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
            )

            stale = await reserve(2)
            active = await reserve(3)
            ambiguous = await reserve(4)
            assert await repository.mark_io_started(
                ambiguous.attempt_id, "spec026-worker-a"
            )
            async with database.session_factory() as session:
                async with session.begin():
                    await session.execute(
                        update(ProviderUsageAttemptModel)
                        .where(
                            ProviderUsageAttemptModel.id.in_(
                                [stale.attempt_id, ambiguous.attempt_id]
                            )
                        )
                        .values(
                            reservation_expires_at=datetime.now(UTC)
                            - timedelta(seconds=1)
                        )
                    )
            recovered = await repository.recover_stale(10)
            assert (recovered.released, recovered.ambiguous) == (1, 1)
            async with database.session_factory() as session:
                stale_row = await session.get(
                    ProviderUsageAttemptModel, stale.attempt_id
                )
                active_row = await session.get(
                    ProviderUsageAttemptModel, active.attempt_id
                )
                ambiguous_row = await session.get(
                    ProviderUsageAttemptModel, ambiguous.attempt_id
                )
                assert (
                    stale_row is not None
                    and stale_row.state == ProviderAttemptState.NO_IO
                )
                assert (
                    active_row is not None
                    and active_row.state == ProviderAttemptState.RESERVED
                )
                assert (
                    ambiguous_row is not None
                    and ambiguous_row.state == ProviderAttemptState.IO_POSSIBLE
                )
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ProviderUsageAttemptModel)
                    )
                    == 4
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProviderBudgetReservationModel)
                        .where(
                            ProviderBudgetReservationModel.state
                            == ReservationState.AMBIGUOUS
                        )
                    )
                    == 3
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_concurrent_admission_converges_repeatedly() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            await repository.validate_prerequisites(WorkloadClass.CHAT_GENERATION)
            source = await repository.planning_source(job_id)
            routes = await repository.resolve_routes(
                source,
                WorkloadClass.CHAT_GENERATION,
                requirements,
            )
            for ordinal in range(1, 16):
                first, replay = await asyncio.gather(
                    repository.reserve_attempt(
                        source,
                        routes[0],
                        WorkloadClass.CHAT_GENERATION,
                        ProviderOperation.RESPONSE_PLANNING,
                        RouteRole.PRIMARY,
                        ordinal,
                        100,
                        300,
                    ),
                    repository.reserve_attempt(
                        source,
                        routes[0],
                        WorkloadClass.CHAT_GENERATION,
                        ProviderOperation.RESPONSE_PLANNING,
                        RouteRole.PRIMARY,
                        ordinal,
                        100,
                        300,
                    ),
                )
                assert first.allowed and replay.allowed
                assert first.attempt_id == replay.attempt_id
                assert first.attempt_key == replay.attempt_key
            async with database.session_factory() as session:
                attempts = (
                    await session.scalars(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.source_key == source.source_key
                        )
                    )
                ).all()
                assert len(attempts) == 15
                assert len({item.attempt_key for item in attempts}) == 15
                assert all(
                    item.state == ProviderAttemptState.RESERVED for item in attempts
                )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_cumulative_scope_denial_is_all_or_none() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            source = await repository.planning_source(job_id)
            routes = await repository.resolve_routes(
                source,
                WorkloadClass.CHAT_GENERATION,
                requirements,
            )
            async with database.session_factory() as session:
                async with session.begin():
                    budget = await session.scalar(
                        select(ProviderBudgetModel).where(
                            ProviderBudgetModel.scope_type
                            == BudgetScope.PLATFORM_CONNECTION
                        )
                    )
                    assert budget is not None
                    head = await session.scalar(
                        select(ProviderBudgetHeadModel).where(
                            ProviderBudgetHeadModel.budget_id == budget.id
                        )
                    )
                    assert head is not None
                    revision = ProviderBudgetRevisionModel(
                        budget_id=budget.id,
                        version=2,
                        amount=1,
                        mode=BudgetMode.HARD,
                        alert_threshold_bps=8000,
                        effective_at=datetime.now(UTC),
                        created_by_identity_id=(
                            await session.scalar(
                                select(ControlOperatorIdentityModel.id).limit(1)
                            )
                        ),
                    )
                    session.add(revision)
                    await session.flush()
                    head.budget_revision_id = revision.id
                    head.lock_version += 1
            admission = await repository.reserve_attempt(
                source,
                routes[0],
                WorkloadClass.CHAT_GENERATION,
                ProviderOperation.RESPONSE_PLANNING,
                RouteRole.PRIMARY,
                1,
                100,
                300,
            )
            assert not admission.allowed
            assert admission.outcome == ProviderAttemptOutcome.BUDGET_DENIED
            async with database.session_factory() as session:
                denied_attempt = await session.get(
                    ProviderUsageAttemptModel, admission.attempt_id
                )
                assert denied_attempt is not None
                assert denied_attempt.estimated_cost_microusd is None
                assert denied_attempt.request_count == 0
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProviderBudgetEvaluationModel)
                        .where(
                            ProviderBudgetEvaluationModel.attempt_id
                            == admission.attempt_id
                        )
                    )
                    == 3
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ProviderBudgetReservationModel)
                        .where(
                            ProviderBudgetReservationModel.attempt_id
                            == admission.attempt_id
                        )
                    )
                    == 0
                )
                assert all(
                    value == 0
                    for value in await session.scalars(
                        select(ProviderBudgetWindowModel.reserved_amount)
                    )
                )
            async with database.session_factory() as session:
                async with session.begin():
                    deployment_budget = await session.scalar(
                        select(ProviderBudgetModel).where(
                            ProviderBudgetModel.scope_type == BudgetScope.DEPLOYMENT
                        )
                    )
                    actor_id = await session.scalar(
                        select(ControlOperatorIdentityModel.id).limit(1)
                    )
                    assert deployment_budget is not None and actor_id is not None
                    disabled = ProviderBudgetRevisionModel(
                        budget_id=deployment_budget.id,
                        version=2,
                        enabled=False,
                        amount=10_000,
                        mode=BudgetMode.HARD,
                        alert_threshold_bps=8000,
                        effective_at=datetime.now(UTC),
                        created_by_identity_id=actor_id,
                    )
                    session.add(disabled)
                    await session.flush()
                    deployment_head = await session.scalar(
                        select(ProviderBudgetHeadModel).where(
                            ProviderBudgetHeadModel.budget_id == deployment_budget.id
                        )
                    )
                    assert deployment_head is not None
                    deployment_head.budget_revision_id = disabled.id
                    deployment_head.lock_version += 1
            disabled_admission = await repository.reserve_attempt(
                source,
                routes[0],
                WorkloadClass.CHAT_GENERATION,
                ProviderOperation.RESPONSE_PLANNING,
                RouteRole.PRIMARY,
                2,
                100,
                300,
            )
            assert not disabled_admission.allowed
            assert (
                disabled_admission.outcome
                == ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
            )
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_concurrent_attempts_cannot_overspend_last_deployment_remainder() -> None:
    async def scenario() -> None:
        database = Database(Settings(_env_file=None, environment="test"))
        await database.start()
        try:
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            source = await repository.planning_source(job_id)
            routes = await repository.resolve_routes(
                source, WorkloadClass.CHAT_GENERATION, requirements
            )
            async with database.session_factory() as session:
                async with session.begin():
                    budget = await session.scalar(
                        select(ProviderBudgetModel).where(
                            ProviderBudgetModel.scope_type == BudgetScope.DEPLOYMENT
                        )
                    )
                    actor_id = await session.scalar(
                        select(ControlOperatorIdentityModel.id).limit(1)
                    )
                    assert budget is not None and actor_id is not None
                    revision = ProviderBudgetRevisionModel(
                        budget_id=budget.id,
                        version=2,
                        amount=400,
                        mode=BudgetMode.HARD,
                        alert_threshold_bps=8000,
                        effective_at=datetime.now(UTC),
                        created_by_identity_id=actor_id,
                    )
                    session.add(revision)
                    await session.flush()
                    head = await session.scalar(
                        select(ProviderBudgetHeadModel).where(
                            ProviderBudgetHeadModel.budget_id == budget.id
                        )
                    )
                    assert head is not None
                    head.budget_revision_id = revision.id
                    head.lock_version += 1

            async def reserve(ordinal: int):
                return await repository.reserve_attempt(
                    source,
                    routes[0],
                    WorkloadClass.CHAT_GENERATION,
                    ProviderOperation.RESPONSE_PLANNING,
                    RouteRole.PRIMARY,
                    ordinal,
                    100,
                    300,
                )

            admissions = await asyncio.gather(reserve(1), reserve(2))
            assert sum(item.allowed for item in admissions) == 1
            assert {item.outcome for item in admissions} == {
                ProviderAttemptOutcome.PENDING,
                ProviderAttemptOutcome.BUDGET_DENIED,
            }
            async with database.session_factory() as session:
                assert (
                    await session.scalar(
                        select(func.count()).select_from(ProviderBudgetReservationModel)
                    )
                    == 3
                )
                deployment_window = await session.scalar(
                    select(ProviderBudgetWindowModel)
                    .join(
                        ProviderBudgetModel,
                        ProviderBudgetModel.id == ProviderBudgetWindowModel.budget_id,
                    )
                    .where(ProviderBudgetModel.scope_type == BudgetScope.DEPLOYMENT)
                )
                assert deployment_window is not None
                assert deployment_window.reserved_amount == 400
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_real_admission_commits_before_blocking_provider_io() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            source = await repository.planning_source(job_id)
            routes = await repository.resolve_routes(
                source,
                WorkloadClass.CHAT_GENERATION,
                requirements,
            )
            raw = _BlockingProvider()
            provider = GovernedModelProvider(
                raw,
                routes[0],
                source,
                ProviderOperation.RESPONSE_PLANNING,
                repository,
                settings,
                cast(object, _AllowedRateLimiter()),
                cast(object, _AvailableConcurrency()),
            )
            request = GenerationRequest(
                planning_job_id=job_id,
                context=cast(ConversationContext, object()),
                prompt_version="spec026",
                response_schema_version="response-plan-v2",
                locale_hint="en",
                maximum_output_tokens=300,
                system_instructions="bounded test",
                user_content="bounded test",
                response_schema={},
            )
            task = asyncio.create_task(
                provider.generate_attempt(request, RouteRole.PRIMARY, 1)
            )
            await asyncio.wait_for(raw.entered.wait(), timeout=5)
            async with database.session_factory() as session:
                state = await session.scalar(
                    select(ProviderUsageAttemptModel.state).where(
                        ProviderUsageAttemptModel.source_key == source.source_key
                    )
                )
                assert state == ProviderAttemptState.IO_STARTED
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(RateLimitEventModel)
                        .where(
                            RateLimitEventModel.configuration_version
                            == "provider-governance-v1"
                        )
                    )
                    == 1
                )
            raw.release_call.set()
            result = await asyncio.wait_for(task, timeout=5)
            assert result.usage.total_tokens == 30
            async with database.session_factory() as session:
                state = await session.scalar(
                    select(ProviderUsageAttemptModel.state).where(
                        ProviderUsageAttemptModel.source_key == source.source_key
                    )
                )
                assert state == ProviderAttemptState.IO_COMPLETE
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_disabled_assistant_after_route_resolution_makes_zero_provider_calls() -> None:
    async def scenario() -> None:
        settings = Settings(_env_file=None, environment="test")
        database = Database(settings)
        await database.start()
        try:
            job_id, requirements = await _seed(database)
            repository = SqlAlchemyProviderGovernanceRepository(
                database.session_factory,
                mode=GovernanceMode.ENFORCE,
                reservation_lease_seconds=60,
            )
            source = await repository.planning_source(job_id)
            routes = await repository.resolve_routes(
                source, WorkloadClass.CHAT_GENERATION, requirements
            )
            assert source.assistant_id is not None
            async with database.session_factory() as session, session.begin():
                assistant = await session.get(AssistantModel, source.assistant_id)
                assert assistant is not None
                assistant.status = AssistantStatus.DISABLED
                assistant.revision += 1
            raw = _BlockingProvider()
            provider = GovernedModelProvider(
                raw,
                routes[0],
                source,
                ProviderOperation.RESPONSE_PLANNING,
                repository,
                settings,
                cast(object, _AllowedRateLimiter()),
                cast(object, _AvailableConcurrency()),
            )
            request = GenerationRequest(
                planning_job_id=job_id,
                context=cast(ConversationContext, object()),
                prompt_version="spec030",
                response_schema_version="response-plan-v2",
                locale_hint="en",
                maximum_output_tokens=300,
                system_instructions="bounded test",
                user_content="bounded test",
                response_schema={},
            )
            with pytest.raises(ProviderError):
                await provider.generate_attempt(request, RouteRole.PRIMARY, 1)
            assert not raw.entered.is_set()
        finally:
            await database.stop()

    asyncio.run(scenario())


@pytest.mark.integration
@pytest.mark.provider_governance_integration
def test_control_authorization_idempotency_conflict_and_redaction() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            environment="test",
            control_plane_enabled=True,
            control_plane_jwt_secret="x" * 32,
            control_plane_jwt_issuer="issuer",
            control_plane_jwt_audience="audience",
        )
        database = Database(settings)
        await database.start()
        try:
            await _seed(database)
            async with database.session_factory() as session:
                async with session.begin():
                    tenant = await session.scalar(select(ControlTenantModel).limit(1))
                    assistant = await session.scalar(select(AssistantModel).limit(1))
                    connection = await session.scalar(
                        select(PlatformConnectionModel).limit(1)
                    )
                    deployment = await session.scalar(
                        select(ControlOperatorIdentityModel).where(
                            ControlOperatorIdentityModel.subject == "operator"
                        )
                    )
                    assert all(
                        item is not None
                        for item in (tenant, assistant, connection, deployment)
                    )
                    owner = ControlOperatorIdentityModel(
                        issuer="spec026", subject="owner"
                    )
                    auditor = ControlOperatorIdentityModel(
                        issuer="spec026", subject="auditor"
                    )
                    viewer = ControlOperatorIdentityModel(
                        issuer="spec026", subject="viewer"
                    )
                    operator = ControlOperatorIdentityModel(
                        issuer="spec026", subject="tenant-operator"
                    )
                    session.add_all([owner, auditor, viewer, operator])
                    await session.flush()
                    assert tenant is not None and deployment is not None
                    session.add_all(
                        [
                            ControlOperatorMembershipModel(
                                tenant_id=tenant.id,
                                identity_id=owner.id,
                                role="tenant_owner",
                            ),
                            ControlOperatorMembershipModel(
                                tenant_id=tenant.id,
                                identity_id=auditor.id,
                                role="auditor",
                            ),
                            ControlOperatorMembershipModel(
                                tenant_id=tenant.id,
                                identity_id=viewer.id,
                                role="viewer",
                            ),
                            ControlOperatorMembershipModel(
                                tenant_id=tenant.id,
                                identity_id=operator.id,
                                role="operator",
                            ),
                            ControlDeploymentAuthorityModel(
                                identity_id=deployment.id,
                                authority="deployment_operator",
                                granted_by_identity_id=deployment.id,
                            ),
                        ]
                    )
            assert (
                tenant is not None and assistant is not None and connection is not None
            )
            assert deployment is not None
            principals = {
                item.subject: Principal(item, {})
                for item in (deployment, owner, auditor, viewer, operator)
            }
            selected = {"principal": principals["owner"]}

            async def current_principal() -> Principal:
                return selected["principal"]

            app = create_app(settings)
            app.state.database = database
            app.dependency_overrides[principal_for] = current_principal
            transport = httpx.ASGITransport(app=app)
            assistant_path = (
                f"/control/v1/tenants/{tenant.id}/assistants/{assistant.id}"
            )
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                assert (
                    await client.get("/control/v1/deployment/provider-budgets")
                ).status_code == 403
                selected["principal"] = principals["tenant-operator"]
                assert (
                    await client.get(f"{assistant_path}/provider-budgets")
                ).status_code == 403
                selected["principal"] = principals["viewer"]
                assert (
                    await client.get(f"{assistant_path}/provider-budgets")
                ).status_code == 403
                selected["principal"] = principals["auditor"]
                read = await client.get(f"{assistant_path}/provider-budgets")
                assert read.status_code == 200
                assert "credential" not in read.text.lower()
                denied = await client.post(
                    f"{assistant_path}/provider-budgets",
                    headers={"If-Match": "0", "X-Request-ID": "auditor-denied"},
                    json={
                        "workload_class": "chat_generation",
                        "measurement": "input_tokens",
                        "window_kind": "daily_utc",
                        "amount": 1000,
                        "mode": "hard",
                        "alert_threshold_bps": 8000,
                        "effective_at": datetime.now(UTC).isoformat(),
                    },
                )
                assert denied.status_code == 403
                selected["principal"] = principals["owner"]
                payload = {
                    "workload_class": "chat_generation",
                    "measurement": "input_tokens",
                    "window_kind": "daily_utc",
                    "amount": 1000,
                    "mode": "hard",
                    "alert_threshold_bps": 8000,
                    "effective_at": datetime.now(UTC).isoformat(),
                }
                headers = {"If-Match": "0", "X-Request-ID": "budget-create"}
                created = await client.post(
                    f"{assistant_path}/provider-budgets",
                    headers=headers,
                    json=payload,
                )
                replay = await client.post(
                    f"{assistant_path}/provider-budgets",
                    headers=headers,
                    json=payload,
                )
                assert created.status_code == replay.status_code == 201
                assert created.json() == replay.json()
                conflict = await client.post(
                    f"{assistant_path}/provider-budgets",
                    headers=headers,
                    json={**payload, "amount": 1001},
                )
                assert conflict.status_code == 409
                cross_scope = await client.get(
                    "/control/v1/tenants/"
                    f"{tenant.id}/connections/{uuid4()}/provider-budgets"
                )
                assert cross_scope.status_code == 404
                selected["principal"] = principals["operator"]
                assert (
                    await client.get("/control/v1/deployment/provider-budgets")
                ).status_code == 200
                # SPEC-021 membership isolation: a principal with no tenant
                # membership is masked as 404 (Not found) before any RBAC role
                # decision; a non-admin membership would instead yield 403.
                # This fixture's deployment principal has no membership, so the
                # assistant-scoped read is deterministically 404.
                assert (
                    await client.get(f"{assistant_path}/provider-budgets")
                ).status_code == 404
            async with database.session_factory() as session:
                outcomes = set(
                    await session.scalars(
                        select(ControlAuditEventModel.outcome).where(
                            ControlAuditEventModel.action == "provider_budget.publish"
                        )
                    )
                )
                assert {"success", "failed", "denied"} <= outcomes
        finally:
            await database.stop()

    asyncio.run(scenario())
