"""PostgreSQL authority for SPEC-026 routing, usage, and budget admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.provider_governance import (
    BudgetAdmissionEvent,
    ProviderAdmission,
    ProviderHealthTransition,
    ProviderRecoveryResult,
    ProviderUsageCompletion,
    ProviderWorkSource,
    ResolvedProviderRoute,
)
from app.application.provider_governance import (
    capability_matches,
    work_requirements_match,
)
from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    MAX_BIGINT,
    BudgetDecision,
    BudgetMeasurement,
    BudgetMode,
    BudgetScope,
    EstimateQuality,
    GenerationPrice,
    GovernanceMode,
    ProviderAttemptOutcome,
    ProviderAttemptState,
    ProviderHealth,
    ProviderLifecycle,
    ProviderOperation,
    ReservationState,
    RouteRole,
    UsageObservation,
    UsageQuality,
    WorkloadClass,
    budget_window,
    estimate_generation_cost,
    reserve_generation_cost,
)
from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.domain.voice import VoiceGenerationStatus
from app.infrastructure.database.models import (
    AssistantModel,
    ControlTenantModel,
    ConversationModel,
    ConversationSummaryJobModel,
    ExplicitMemorySemanticIndexJobModel,
    KnowledgeIndexJobModel,
    MemoryItemModel,
    PlatformConnectionModel,
    ProviderBudgetEvaluationModel,
    ProviderBudgetModel,
    ProviderBudgetReservationModel,
    ProviderBudgetRevisionModel,
    ProviderBudgetWindowModel,
    ProviderCapabilityModel,
    ProviderCapabilityStateModel,
    ProviderHealthEventModel,
    ProviderHealthPolicyRevisionModel,
    ProviderPriceRevisionModel,
    ProviderRoutingFallbackReasonModel,
    ProviderRoutingPolicyRevisionModel,
    ProviderRoutingPolicyRouteModel,
    ProviderUsageAttemptModel,
    ProviderWorkPolicySnapshotModel,
    RateLimitEventModel,
    ResponsePlanningJobModel,
    TelegramVoiceGenerationJobModel,
)


class ProviderGovernanceUnavailable(RuntimeError):
    """Durable governance cannot safely authorize provider I/O."""


class SqlAlchemyProviderGovernanceRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        mode: GovernanceMode,
        reservation_lease_seconds: int,
    ) -> None:
        self._session_factory = session_factory
        self._mode = mode
        self._reservation_lease_seconds = reservation_lease_seconds

    async def validate_prerequisites(self, workload: WorkloadClass) -> None:
        """Fail enforced worker startup when its deployment authority is absent."""

        if self._mode != GovernanceMode.ENFORCE:
            return
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            revision = await session.scalar(
                select(ProviderRoutingPolicyRevisionModel)
                .where(
                    ProviderRoutingPolicyRevisionModel.scope_key == "deployment",
                    ProviderRoutingPolicyRevisionModel.workload_class == workload,
                    ProviderRoutingPolicyRevisionModel.effective_at <= now,
                )
                .order_by(ProviderRoutingPolicyRevisionModel.version.desc())
                .limit(1)
            )
            if revision is None or revision.schema_version != "provider-routing-v1":
                raise ProviderGovernanceUnavailable(
                    f"active deployment {workload.value} route is unavailable"
                )
            rows = (
                await session.execute(
                    select(
                        ProviderRoutingPolicyRouteModel,
                        ProviderCapabilityModel,
                        ProviderCapabilityStateModel,
                    )
                    .join(
                        ProviderCapabilityModel,
                        ProviderCapabilityModel.id
                        == ProviderRoutingPolicyRouteModel.capability_id,
                    )
                    .outerjoin(
                        ProviderCapabilityStateModel,
                        ProviderCapabilityStateModel.capability_id
                        == ProviderCapabilityModel.id,
                    )
                    .where(
                        ProviderRoutingPolicyRouteModel.policy_revision_id
                        == revision.id
                    )
                )
            ).all()
            eligible = False
            for route, capability, state in rows:
                candidate = ResolvedProviderRoute(
                    snapshot_id=revision.id,
                    policy_revision_id=revision.id,
                    capability_id=capability.id,
                    provider_id=capability.provider_id,
                    model=capability.model,
                    adapter_key=capability.adapter_key,
                    position=route.position,
                    data_class=capability.data_class,
                    credential_slot=capability.credential_slot,
                    reservation_strategy=capability.reservation_strategy,
                    capability_metadata=dict(capability.capability_metadata),
                    allowed_fallback_reasons=frozenset(),
                )
                if (
                    await self._health_eligible(session, state, now)
                    and capability.credential_configured
                    and capability_matches(
                        candidate, workload, dict(revision.requirements)
                    ).eligible
                ):
                    eligible = True
                    break
            if not eligible:
                raise ProviderGovernanceUnavailable(
                    f"deployment {workload.value} route has no eligible capability"
                )
            active_budget_revisions = (
                select(
                    ProviderBudgetRevisionModel.budget_id.label("budget_id"),
                    func.max(ProviderBudgetRevisionModel.version).label("version"),
                )
                .where(ProviderBudgetRevisionModel.effective_at <= now)
                .group_by(ProviderBudgetRevisionModel.budget_id)
                .subquery()
            )
            budget = await session.scalar(
                select(ProviderBudgetModel.id)
                .join(
                    active_budget_revisions,
                    active_budget_revisions.c.budget_id == ProviderBudgetModel.id,
                )
                .join(
                    ProviderBudgetRevisionModel,
                    (
                        ProviderBudgetRevisionModel.budget_id
                        == active_budget_revisions.c.budget_id
                    )
                    & (
                        ProviderBudgetRevisionModel.version
                        == active_budget_revisions.c.version
                    ),
                )
                .where(
                    ProviderBudgetModel.scope_type == BudgetScope.DEPLOYMENT,
                    ProviderBudgetModel.workload_class == workload,
                    ProviderBudgetRevisionModel.enabled.is_(True),
                )
                .limit(1)
            )
            if budget is None:
                raise ProviderGovernanceUnavailable(
                    f"active deployment {workload.value} budget is unavailable"
                )

    async def planning_source(self, job_id: UUID) -> ProviderWorkSource:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ResponsePlanningJobModel,
                        ConversationModel,
                        PlatformConnectionModel,
                        PlatformConnectionModel.tenant_id,
                    )
                    .join(
                        ConversationModel,
                        ConversationModel.id
                        == ResponsePlanningJobModel.conversation_id,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == ConversationModel.platform_connection_id,
                    )
                    .where(ResponsePlanningJobModel.id == job_id)
                )
            ).one_or_none()
        if row is None:
            raise ProviderGovernanceUnavailable("planning source is unavailable")
        job, conversation, connection, tenant_id = row
        return ProviderWorkSource(
            source_key=f"planning:{job.id}",
            execution_ordinal=job.attempt_count,
            execution_owner=job.lease_owner,
            planning_job_id=job.id,
            tenant_id=tenant_id,
            assistant_id=connection.assistant_id,
            connection_id=conversation.platform_connection_id,
        )

    async def summary_source(self, job_id: UUID) -> ProviderWorkSource:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ConversationSummaryJobModel,
                        ConversationModel,
                        PlatformConnectionModel,
                        PlatformConnectionModel.tenant_id,
                    )
                    .join(
                        ConversationModel,
                        ConversationModel.id
                        == ConversationSummaryJobModel.conversation_id,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == ConversationModel.platform_connection_id,
                    )
                    .where(ConversationSummaryJobModel.id == job_id)
                )
            ).one_or_none()
        if row is None:
            raise ProviderGovernanceUnavailable("summary source is unavailable")
        job, conversation, connection, tenant_id = row
        return ProviderWorkSource(
            source_key=f"summary:{job.id}",
            execution_ordinal=job.attempt_count,
            execution_owner=job.lease_owner,
            summary_job_id=job.id,
            tenant_id=tenant_id,
            assistant_id=connection.assistant_id,
            connection_id=conversation.platform_connection_id,
        )

    async def semantic_source(self, job_id: UUID) -> ProviderWorkSource:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        ExplicitMemorySemanticIndexJobModel,
                        MemoryItemModel,
                        PlatformConnectionModel.tenant_id,
                    )
                    .join(
                        MemoryItemModel,
                        MemoryItemModel.id
                        == ExplicitMemorySemanticIndexJobModel.memory_id,
                    )
                    .join(
                        PlatformConnectionModel,
                        PlatformConnectionModel.id
                        == MemoryItemModel.platform_connection_id,
                    )
                    .where(ExplicitMemorySemanticIndexJobModel.id == job_id)
                )
            ).one_or_none()
        if row is None:
            raise ProviderGovernanceUnavailable("semantic source is unavailable")
        job, memory, tenant_id = row
        return ProviderWorkSource(
            source_key=f"semantic:{job.id}",
            execution_ordinal=job.attempt_count,
            execution_owner=job.lease_owner,
            semantic_index_job_id=job.id,
            tenant_id=tenant_id,
            assistant_id=memory.assistant_id,
            connection_id=memory.platform_connection_id,
        )

    async def knowledge_source(self, job_id: UUID) -> ProviderWorkSource:
        async with self._session_factory() as session:
            job = await session.scalar(
                select(KnowledgeIndexJobModel).where(
                    KnowledgeIndexJobModel.id == job_id
                )
            )
        if job is None:
            raise ProviderGovernanceUnavailable("knowledge source is unavailable")
        return ProviderWorkSource(
            source_key=f"knowledge:{job.id}",
            execution_ordinal=max(1, job.attempt_count),
            execution_owner=job.lease_owner,
            knowledge_index_job_id=job.id,
            tenant_id=job.tenant_id,
            assistant_id=job.assistant_id,
        )

    async def voice_source(self, job_id: UUID) -> ProviderWorkSource:
        async with self._session_factory() as session:
            job = await session.scalar(
                select(TelegramVoiceGenerationJobModel).where(
                    TelegramVoiceGenerationJobModel.id == job_id
                )
            )
        if job is None:
            raise ProviderGovernanceUnavailable("voice source is unavailable")
        return ProviderWorkSource(
            source_key=f"voice:{job.id}",
            execution_ordinal=max(1, job.attempt_count),
            execution_owner=job.lease_owner,
            voice_generation_job_id=job.id,
            tenant_id=job.tenant_id,
            assistant_id=job.assistant_id,
            connection_id=job.connection_id,
        )

    async def resolve_routes(
        self,
        source: ProviderWorkSource,
        workload: WorkloadClass,
        requirements: dict[str, object],
    ) -> tuple[ResolvedProviderRoute, ...]:
        if self._mode == GovernanceMode.LEGACY:
            raise ProviderGovernanceUnavailable("routing requested in legacy mode")
        async with self._session_factory() as session:
            async with session.begin():
                await self._verify_attribution(session, source)
                snapshot = await session.scalar(
                    select(ProviderWorkPolicySnapshotModel).where(
                        ProviderWorkPolicySnapshotModel.source_key == source.source_key,
                        ProviderWorkPolicySnapshotModel.workload_class == workload,
                    )
                )
                if snapshot is None:
                    revision = await self._resolve_revision(session, source, workload)
                    if revision is None:
                        raise ProviderGovernanceUnavailable("no active routing policy")
                    snapshot = ProviderWorkPolicySnapshotModel(
                        source_key=source.source_key,
                        planning_job_id=source.planning_job_id,
                        summary_job_id=source.summary_job_id,
                        semantic_index_job_id=source.semantic_index_job_id,
                        knowledge_index_job_id=source.knowledge_index_job_id,
                        voice_generation_job_id=source.voice_generation_job_id,
                        workload_class=workload,
                        policy_revision_id=revision.id,
                        tenant_id=source.tenant_id,
                        assistant_id=source.assistant_id,
                        connection_id=source.connection_id,
                    )
                    session.add(snapshot)
                    await session.flush()
                else:
                    revision = await session.get(
                        ProviderRoutingPolicyRevisionModel,
                        snapshot.policy_revision_id,
                    )
                    if revision is None:
                        raise ProviderGovernanceUnavailable(
                            "routing snapshot is invalid"
                        )
                if revision.schema_version != "provider-routing-v1":
                    raise ProviderGovernanceUnavailable("unknown routing schema")
                if not work_requirements_match(
                    revision.requirements, requirements, workload
                ):
                    raise ProviderGovernanceUnavailable(
                        "work requirements do not match the published policy"
                    )
                reasons = frozenset(
                    await session.scalars(
                        select(ProviderRoutingFallbackReasonModel.reason).where(
                            ProviderRoutingFallbackReasonModel.policy_revision_id
                            == revision.id
                        )
                    )
                )
                rows = (
                    await session.execute(
                        select(
                            ProviderRoutingPolicyRouteModel,
                            ProviderCapabilityModel,
                            ProviderCapabilityStateModel,
                        )
                        .join(
                            ProviderCapabilityModel,
                            ProviderCapabilityModel.id
                            == ProviderRoutingPolicyRouteModel.capability_id,
                        )
                        .outerjoin(
                            ProviderCapabilityStateModel,
                            ProviderCapabilityStateModel.capability_id
                            == ProviderCapabilityModel.id,
                        )
                        .where(
                            ProviderRoutingPolicyRouteModel.policy_revision_id
                            == revision.id,
                            ProviderCapabilityModel.workload_class == workload,
                        )
                        .order_by(ProviderRoutingPolicyRouteModel.position)
                    )
                ).all()
                resolved: list[ResolvedProviderRoute] = []
                for route, capability, state in rows:
                    if (
                        not await self._health_eligible(
                            session, state, datetime.now(UTC)
                        )
                        or not capability.credential_configured
                    ):
                        continue
                    item = ResolvedProviderRoute(
                        snapshot_id=snapshot.id,
                        policy_revision_id=revision.id,
                        capability_id=capability.id,
                        provider_id=capability.provider_id,
                        model=capability.model,
                        adapter_key=capability.adapter_key,
                        position=route.position,
                        data_class=capability.data_class,
                        credential_slot=capability.credential_slot,
                        reservation_strategy=capability.reservation_strategy,
                        capability_metadata=dict(capability.capability_metadata),
                        allowed_fallback_reasons=reasons,
                    )
                    if capability_matches(item, workload, requirements).eligible:
                        resolved.append(item)
                return tuple(resolved)

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
    ) -> ProviderAdmission:
        now = datetime.now(UTC)
        attempt_key = _attempt_key(
            source.source_key,
            workload,
            operation,
            route.position,
            role,
            attempt_ordinal,
        )
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(ProviderUsageAttemptModel)
                    .where(ProviderUsageAttemptModel.attempt_key == attempt_key)
                    .with_for_update()
                )
                if existing is not None:
                    if not _attempt_identity_matches(
                        existing,
                        route,
                        workload,
                        operation,
                        role,
                        attempt_ordinal,
                    ):
                        return ProviderAdmission(
                            False,
                            existing.id,
                            existing.attempt_key,
                            ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE,
                        )
                    if existing.state != ProviderAttemptState.RESERVED:
                        return ProviderAdmission(
                            False,
                            existing.id,
                            existing.attempt_key,
                            existing.provider_outcome,
                        )
                    await self._verify_attribution(session, source)
                    state = await session.scalar(
                        select(ProviderCapabilityStateModel).where(
                            ProviderCapabilityStateModel.capability_id
                            == route.capability_id
                        )
                    )
                    still_allowed = await self._current_route_allowed(
                        session, source, route, workload
                    ) and await self._health_eligible(session, state, now)
                    if not still_allowed:
                        await self._release_reservations(session, existing.id)
                        existing.state = ProviderAttemptState.NO_IO
                        existing.provider_outcome = (
                            ProviderAttemptOutcome.NO_ELIGIBLE_ROUTE
                        )
                        existing.estimate_quality = EstimateQuality.UNAVAILABLE
                        existing.estimated_cost_microusd = None
                        existing.finalized_at = now
                    else:
                        # RESERVED proves request_count=0 and no provider I/O.
                        # A newly claimed durable source lease may therefore
                        # transfer this reservation and fence the stale owner
                        # without creating a second provider attempt.
                        existing.reservation_owner = (
                            source.execution_owner or source.source_key
                        )
                        existing.reservation_expires_at = now + timedelta(
                            seconds=self._reservation_lease_seconds
                        )
                    return ProviderAdmission(
                        still_allowed,
                        existing.id,
                        existing.attempt_key,
                        existing.provider_outcome,
                    )
                await self._verify_attribution(session, source)
                if not await self._current_route_allowed(
                    session, source, route, workload
                ):
                    return await self._denied_attempt(
                        session,
                        source,
                        route,
                        workload,
                        operation,
                        role,
                        attempt_ordinal,
                        attempt_key,
                        ProviderAttemptOutcome.NO_ELIGIBLE_ROUTE,
                        now,
                    )
                state = await session.scalar(
                    select(ProviderCapabilityStateModel).where(
                        ProviderCapabilityStateModel.capability_id
                        == route.capability_id
                    )
                )
                if not await self._health_eligible(session, state, now):
                    return await self._denied_attempt(
                        session,
                        source,
                        route,
                        workload,
                        operation,
                        role,
                        attempt_ordinal,
                        attempt_key,
                        ProviderAttemptOutcome.NO_ELIGIBLE_ROUTE,
                        now,
                    )
                assert state is not None
                price = await session.scalar(
                    select(ProviderPriceRevisionModel)
                    .where(
                        ProviderPriceRevisionModel.capability_id == route.capability_id,
                        ProviderPriceRevisionModel.effective_from <= now,
                        or_(
                            ProviderPriceRevisionModel.effective_to.is_(None),
                            ProviderPriceRevisionModel.effective_to > now,
                        ),
                    )
                    .order_by(ProviderPriceRevisionModel.effective_from.desc())
                    .limit(1)
                )
                amounts = _reservation_amounts(
                    maximum_input_tokens, maximum_output_tokens, price
                )
                attempt = ProviderUsageAttemptModel(
                    attempt_key=attempt_key,
                    source_key=source.source_key,
                    record_origin="governed",
                    planning_job_id=source.planning_job_id,
                    summary_job_id=source.summary_job_id,
                    semantic_index_job_id=source.semantic_index_job_id,
                    knowledge_index_job_id=source.knowledge_index_job_id,
                    voice_generation_job_id=source.voice_generation_job_id,
                    workload_class=workload,
                    operation=operation,
                    attempt_ordinal=attempt_ordinal,
                    route_role=role,
                    capability_id=route.capability_id,
                    policy_snapshot_id=route.snapshot_id,
                    price_revision_id=price.id if price is not None else None,
                    health_policy_revision_id=state.health_policy_revision_id,
                    provider_id=route.provider_id,
                    model=route.model,
                    tenant_id=source.tenant_id,
                    assistant_id=source.assistant_id,
                    connection_id=source.connection_id,
                    state=ProviderAttemptState.RESERVED,
                    provider_outcome=ProviderAttemptOutcome.PENDING,
                    request_count=0,
                    usage_quality=UsageQuality.MISSING,
                    estimate_quality=(
                        EstimateQuality.RESERVATION_ESTIMATE
                        if amounts[BudgetMeasurement.ESTIMATED_COST_MICROUSD]
                        is not None
                        else EstimateQuality.UNAVAILABLE
                    ),
                    estimated_cost_microusd=amounts[
                        BudgetMeasurement.ESTIMATED_COST_MICROUSD
                    ],
                    reserved_at=now,
                    reservation_owner=source.execution_owner or source.source_key,
                    reservation_expires_at=now
                    + timedelta(seconds=self._reservation_lease_seconds),
                )
                try:
                    async with session.begin_nested():
                        session.add(attempt)
                        await session.flush()
                except IntegrityError:
                    raced = await session.scalar(
                        select(ProviderUsageAttemptModel).where(
                            ProviderUsageAttemptModel.attempt_key == attempt_key
                        )
                    )
                    if raced is None:
                        raced = await session.scalar(
                            select(ProviderUsageAttemptModel).where(
                                ProviderUsageAttemptModel.source_key
                                == source.source_key,
                                ProviderUsageAttemptModel.operation == operation,
                                ProviderUsageAttemptModel.attempt_ordinal
                                == attempt_ordinal,
                            )
                        )
                    if raced is None:
                        raise ProviderGovernanceUnavailable(
                            "attempt identity race could not be resolved"
                        ) from None
                    if not _attempt_identity_matches(
                        raced,
                        route,
                        workload,
                        operation,
                        role,
                        attempt_ordinal,
                    ):
                        return ProviderAdmission(
                            False,
                            raced.id,
                            raced.attempt_key,
                            ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE,
                        )
                    return ProviderAdmission(
                        raced.state
                        in {
                            ProviderAttemptState.RESERVED,
                            ProviderAttemptState.IO_STARTED,
                            ProviderAttemptState.IO_COMPLETE,
                        },
                        raced.id,
                        raced.attempt_key,
                        raced.provider_outcome,
                    )
                active_budget_revisions = (
                    select(
                        ProviderBudgetRevisionModel.budget_id.label("budget_id"),
                        func.max(ProviderBudgetRevisionModel.version).label("version"),
                    )
                    .where(ProviderBudgetRevisionModel.effective_at <= now)
                    .group_by(ProviderBudgetRevisionModel.budget_id)
                    .subquery()
                )
                budgets = list(
                    (
                        await session.execute(
                            select(
                                ProviderBudgetModel,
                                ProviderBudgetRevisionModel,
                            )
                            .join(
                                active_budget_revisions,
                                active_budget_revisions.c.budget_id
                                == ProviderBudgetModel.id,
                            )
                            .join(
                                ProviderBudgetRevisionModel,
                                (
                                    ProviderBudgetRevisionModel.budget_id
                                    == active_budget_revisions.c.budget_id
                                )
                                & (
                                    ProviderBudgetRevisionModel.version
                                    == active_budget_revisions.c.version
                                ),
                            )
                            .where(
                                ProviderBudgetModel.scope_key.in_(_scope_keys(source)),
                                ProviderBudgetModel.workload_class == workload,
                                ProviderBudgetRevisionModel.enabled.is_(True),
                            )
                        )
                    ).all()
                )
                budgets.sort(
                    key=lambda item: (
                        _scope_order(item[0].scope_type),
                        str(item[0].id),
                    )
                )
                has_deployment = any(
                    budget.scope_type == BudgetScope.DEPLOYMENT for budget, _ in budgets
                )
                if self._mode == GovernanceMode.ENFORCE and not has_deployment:
                    attempt.state = ProviderAttemptState.NO_IO
                    attempt.provider_outcome = (
                        ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE
                    )
                    attempt.estimate_quality = EstimateQuality.UNAVAILABLE
                    attempt.estimated_cost_microusd = None
                    attempt.finalized_at = now
                    return ProviderAdmission(
                        False,
                        attempt.id,
                        attempt_key,
                        ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE,
                    )
                evaluated: list[
                    tuple[
                        ProviderBudgetModel,
                        ProviderBudgetRevisionModel,
                        ProviderBudgetWindowModel,
                        int | None,
                        BudgetDecision,
                    ]
                ] = []
                denied = False
                reset_at: datetime | None = None
                for budget, revision in budgets:
                    start, end = budget_window(budget.window_kind, now)
                    await session.execute(
                        insert(ProviderBudgetWindowModel)
                        .values(
                            budget_id=budget.id,
                            window_start=start,
                            window_end=end,
                            reserved_amount=0,
                            consumed_amount=0,
                            lock_version=1,
                        )
                        .on_conflict_do_nothing(
                            index_elements=("budget_id", "window_start")
                        )
                    )
                    window = await session.scalar(
                        select(ProviderBudgetWindowModel)
                        .where(
                            ProviderBudgetWindowModel.budget_id == budget.id,
                            ProviderBudgetWindowModel.window_start == start,
                        )
                        .with_for_update()
                    )
                    if window is None:
                        raise ProviderGovernanceUnavailable(
                            "budget window could not be locked"
                        )
                    requested = amounts.get(budget.measurement)
                    unavailable = requested is None
                    exhausted = (
                        requested is not None
                        and window.reserved_amount + window.consumed_amount + requested
                        > revision.amount
                    )
                    hard = revision.mode == BudgetMode.HARD
                    if unavailable:
                        decision = BudgetDecision.UNAVAILABLE
                    elif exhausted:
                        decision = (
                            BudgetDecision.DENIED
                            if hard and self._mode == GovernanceMode.ENFORCE
                            else BudgetDecision.EXCEEDED
                        )
                    else:
                        decision = BudgetDecision.WITHIN
                    if (
                        hard
                        and self._mode == GovernanceMode.ENFORCE
                        and (unavailable or exhausted)
                    ):
                        denied = True
                        reset_at = end if reset_at is None else min(reset_at, end)
                    evaluated.append((budget, revision, window, requested, decision))
                for budget, revision, window, requested, decision in evaluated:
                    session.add(
                        ProviderBudgetEvaluationModel(
                            attempt_id=attempt.id,
                            budget_id=budget.id,
                            budget_revision_id=revision.id,
                            window_id=window.id,
                            decision=decision,
                            limit_amount=revision.amount,
                            reserved_before=window.reserved_amount,
                            consumed_before=window.consumed_amount,
                            requested_amount=requested,
                        )
                    )
                if denied:
                    attempt.state = ProviderAttemptState.NO_IO
                    attempt.provider_outcome = ProviderAttemptOutcome.BUDGET_DENIED
                    attempt.estimate_quality = EstimateQuality.UNAVAILABLE
                    attempt.estimated_cost_microusd = None
                    attempt.finalized_at = now
                    return ProviderAdmission(
                        False,
                        attempt.id,
                        attempt_key,
                        ProviderAttemptOutcome.BUDGET_DENIED,
                        reset_at,
                        tuple(
                            BudgetAdmissionEvent(
                                budget.scope_type,
                                revision.mode,
                                decision,
                                False,
                            )
                            for budget, revision, _, _, decision in evaluated
                        ),
                    )
                for budget, _, window, requested, _ in evaluated:
                    if requested is None:
                        continue
                    window.reserved_amount += requested
                    window.lock_version += 1
                    session.add(
                        ProviderBudgetReservationModel(
                            attempt_id=attempt.id,
                            budget_id=budget.id,
                            window_id=window.id,
                            state=ReservationState.RESERVED,
                            reserved_amount=requested,
                            reconciled_amount=0,
                        )
                    )
                return ProviderAdmission(
                    True,
                    attempt.id,
                    attempt_key,
                    ProviderAttemptOutcome.PENDING,
                    budget_events=tuple(
                        BudgetAdmissionEvent(
                            budget.scope_type,
                            revision.mode,
                            decision,
                            requested is not None,
                        )
                        for budget, revision, _, requested, decision in evaluated
                    ),
                )

    async def mark_io_started(self, attempt_id: UUID, owner: str) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                attempt = await session.get(
                    ProviderUsageAttemptModel, attempt_id, with_for_update=True
                )
                if (
                    attempt is None
                    or attempt.state != ProviderAttemptState.RESERVED
                    or attempt.reservation_owner != owner
                    or attempt.reservation_expires_at is None
                    or attempt.reservation_expires_at <= now
                ):
                    return False
                attempt.state = ProviderAttemptState.IO_STARTED
                attempt.request_count = 1
                attempt.io_started_at = now
                return True

    async def record_rate_decision(
        self,
        source: ProviderWorkSource,
        operation: RateLimitOperation,
        provider_id: ProviderId,
        decision: RateLimitDecision,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    RateLimitEventModel(
                        planning_job_id=source.planning_job_id,
                        outbound_action_id=None,
                        voice_generation_job_id=source.voice_generation_job_id,
                        operation=operation,
                        limiting_scope=decision.limiting_scope,
                        provider_id=provider_id.value,
                        allowed=decision.allowed,
                        retry_after_seconds=decision.retry_after_seconds,
                        configuration_version="provider-governance-v1",
                    )
                )

    async def finish_no_io(
        self, attempt_id: UUID, outcome: ProviderAttemptOutcome
    ) -> bool:
        async with self._session_factory() as session:
            async with session.begin():
                attempt = await session.get(
                    ProviderUsageAttemptModel, attempt_id, with_for_update=True
                )
                if attempt is None or attempt.state != ProviderAttemptState.RESERVED:
                    return False
                await self._release_reservations(session, attempt.id)
                attempt.state = ProviderAttemptState.NO_IO
                attempt.provider_outcome = outcome
                attempt.estimate_quality = EstimateQuality.UNAVAILABLE
                attempt.estimated_cost_microusd = None
                attempt.finalized_at = datetime.now(UTC)
                return True

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
    ) -> ProviderUsageCompletion | None:
        observation = UsageObservation.classify(
            input_tokens, output_tokens, total_tokens
        )
        async with self._session_factory() as session:
            async with session.begin():
                attempt = await session.get(
                    ProviderUsageAttemptModel, attempt_id, with_for_update=True
                )
                if attempt is None or attempt.state != ProviderAttemptState.IO_STARTED:
                    return None
                price = (
                    await session.get(
                        ProviderPriceRevisionModel, attempt.price_revision_id
                    )
                    if attempt.price_revision_id is not None
                    else None
                )
                estimate, estimate_quality = _actual_estimate(observation, price)
                if (
                    estimate is None
                    and estimate_quality == EstimateQuality.RESERVATION_ESTIMATE
                ):
                    estimate = attempt.estimated_cost_microusd
                attempt.state = ProviderAttemptState.IO_COMPLETE
                attempt.provider_outcome = outcome
                attempt.error_category = error_category
                attempt.retryable = retryable
                attempt.provider_request_id = _provider_request_reference(
                    provider_request_id
                )
                attempt.input_tokens = observation.input_tokens
                attempt.output_tokens = observation.output_tokens
                attempt.total_tokens = observation.total_tokens
                attempt.usage_quality = observation.quality
                attempt.estimate_quality = estimate_quality
                attempt.estimated_cost_microusd = estimate
                attempt.io_completed_at = datetime.now(UTC)
                attempt.finalized_at = attempt.io_completed_at
                await self._consume_reservations(
                    session, attempt, observation, estimate
                )
                health_transition = await self._record_health(
                    session,
                    attempt.capability_id,
                    outcome,
                    error_category,
                    attempt.io_completed_at,
                )
                return ProviderUsageCompletion(
                    observation.quality,
                    estimate_quality,
                    estimate,
                    *(health_transition if health_transition is not None else ()),
                )

    async def set_application_outcome(self, attempt_id: UUID, outcome: str) -> bool:
        if outcome not in {"accepted", "refused", "invalid_output"}:
            raise ValueError("application outcome must be a closed value")
        async with self._session_factory() as session:
            async with session.begin():
                attempt = await session.get(
                    ProviderUsageAttemptModel, attempt_id, with_for_update=True
                )
                if attempt is None or attempt.state != ProviderAttemptState.IO_COMPLETE:
                    return False
                attempt.application_outcome = outcome
                return True

    async def recover_stale(self, limit: int) -> ProviderRecoveryResult:
        now = datetime.now(UTC)
        released = ambiguous = 0
        health_transitions: list[ProviderHealthTransition] = []
        async with self._session_factory() as session:
            async with session.begin():
                attempts = list(
                    await session.scalars(
                        select(ProviderUsageAttemptModel)
                        .where(
                            ProviderUsageAttemptModel.state.in_(
                                (
                                    ProviderAttemptState.RESERVED,
                                    ProviderAttemptState.IO_STARTED,
                                )
                            ),
                            ProviderUsageAttemptModel.reservation_expires_at < now,
                        )
                        .order_by(
                            ProviderUsageAttemptModel.reservation_expires_at,
                            ProviderUsageAttemptModel.created_at,
                            ProviderUsageAttemptModel.id,
                        )
                        .limit(limit)
                        .with_for_update(skip_locked=True)
                    )
                )
                for attempt in attempts:
                    if attempt.state == ProviderAttemptState.RESERVED:
                        await self._release_reservations(session, attempt.id)
                        attempt.state = ProviderAttemptState.NO_IO
                        attempt.provider_outcome = (
                            ProviderAttemptOutcome.RECOVERED_NO_IO
                        )
                        attempt.estimate_quality = EstimateQuality.UNAVAILABLE
                        attempt.estimated_cost_microusd = None
                        attempt.recovery_reason = "reservation_expired"
                        released += 1
                    else:
                        await self._ambiguate_reservations(session, attempt.id)
                        attempt.state = ProviderAttemptState.IO_POSSIBLE
                        attempt.provider_outcome = (
                            ProviderAttemptOutcome.RECOVERED_IO_POSSIBLE
                        )
                        attempt.usage_quality = UsageQuality.MISSING
                        attempt.estimate_quality = EstimateQuality.RESERVATION_ESTIMATE
                        attempt.recovery_reason = "worker_restart"
                        ambiguous += 1
                    attempt.finalized_at = now
                stale_states = list(
                    await session.scalars(
                        select(ProviderCapabilityStateModel)
                        .where(
                            ProviderCapabilityStateModel.health.is_not(None),
                            ProviderCapabilityStateModel.health_policy_revision_id.is_not(
                                None
                            ),
                        )
                        .order_by(ProviderCapabilityStateModel.updated_at)
                        .limit(max(0, limit - len(attempts)))
                        .with_for_update(skip_locked=True)
                    )
                )
                for state in stale_states:
                    policy = await session.get(
                        ProviderHealthPolicyRevisionModel,
                        state.health_policy_revision_id,
                    )
                    if (
                        policy is not None
                        and state.last_evaluated_at is not None
                        and state.last_evaluated_at
                        + timedelta(seconds=policy.stale_after_seconds)
                        < now
                    ):
                        previous = state.health
                        session.add(
                            ProviderHealthEventModel(
                                capability_id=state.capability_id,
                                from_state=state.health,
                                to_state=None,
                                reason="stale",
                                source="recovery_worker",
                            )
                        )
                        state.health = None
                        state.lock_version += 1
                        capability = await session.get(
                            ProviderCapabilityModel, state.capability_id
                        )
                        if capability is not None:
                            health_transitions.append(
                                ProviderHealthTransition(
                                    capability.provider_id,
                                    previous,
                                    None,
                                    "stale",
                                )
                            )
        return ProviderRecoveryResult(released, ambiguous, tuple(health_transitions))

    async def _record_health(
        self,
        session: AsyncSession,
        capability_id: UUID | None,
        outcome: ProviderAttemptOutcome,
        error_category: str | None,
        at: datetime,
    ) -> tuple[ProviderHealth | None, ProviderHealth, str] | None:
        if capability_id is None:
            return None
        state = await session.scalar(
            select(ProviderCapabilityStateModel)
            .where(ProviderCapabilityStateModel.capability_id == capability_id)
            .with_for_update()
        )
        if state is None or state.health_policy_revision_id is None:
            return None
        policy = await session.get(
            ProviderHealthPolicyRevisionModel, state.health_policy_revision_id
        )
        if policy is None:
            return None
        previous = state.health
        reason: str | None = None
        if (
            state.last_evaluated_at is None
            or state.last_evaluated_at
            + timedelta(seconds=policy.observation_window_seconds)
            < at
        ):
            state.consecutive_successes = 0
            state.consecutive_failures = 0
        if outcome in {ProviderAttemptOutcome.SUCCESS, ProviderAttemptOutcome.REFUSED}:
            state.consecutive_successes += 1
            state.consecutive_failures = 0
            state.last_success_at = at
            if (
                state.health != ProviderHealth.READY
                and state.consecutive_successes >= policy.recovery_success_threshold
            ):
                state.health = ProviderHealth.READY
                reason = "success_threshold"
        elif error_category in {"timeout", "transport", "provider_unavailable"}:
            state.consecutive_failures += 1
            state.consecutive_successes = 0
            state.last_failure_at = at
            if state.consecutive_failures >= policy.unavailable_threshold:
                state.health = ProviderHealth.UNAVAILABLE
                reason = "failure_threshold"
            elif state.consecutive_failures >= policy.degraded_threshold:
                state.health = ProviderHealth.DEGRADED
                reason = "failure_threshold"
        elif error_category in {
            "authentication",
            "permission",
            "invalid_configuration",
        }:
            state.health = ProviderHealth.UNAVAILABLE
            state.last_failure_at = at
            reason = "configuration"
        else:
            return None
        state.last_evaluated_at = at
        state.lock_version += 1
        if state.health != previous:
            assert state.health is not None
            transition_reason = reason or "failure_threshold"
            session.add(
                ProviderHealthEventModel(
                    capability_id=capability_id,
                    from_state=previous,
                    to_state=state.health,
                    reason=transition_reason,
                    source="provider_attempt",
                )
            )
            return previous, state.health, transition_reason
        return None

    async def _resolve_revision(
        self,
        session: AsyncSession,
        source: ProviderWorkSource,
        workload: WorkloadClass,
    ) -> ProviderRoutingPolicyRevisionModel | None:
        now = datetime.now(UTC)
        keys = []
        if source.connection_id is not None:
            keys.append(f"platform_connection:{source.connection_id}")
        if source.assistant_id is not None:
            keys.append(f"assistant:{source.assistant_id}")
        keys.append("deployment")
        for key in keys:
            revision = await session.scalar(
                select(ProviderRoutingPolicyRevisionModel)
                .where(
                    ProviderRoutingPolicyRevisionModel.scope_key == key,
                    ProviderRoutingPolicyRevisionModel.workload_class == workload,
                    ProviderRoutingPolicyRevisionModel.effective_at <= now,
                )
                .order_by(ProviderRoutingPolicyRevisionModel.version.desc())
                .limit(1)
            )
            if revision is not None:
                return revision
        return None

    async def _current_route_allowed(
        self,
        session: AsyncSession,
        source: ProviderWorkSource,
        route: ResolvedProviderRoute,
        workload: WorkloadClass,
    ) -> bool:
        if source.assistant_id is not None:
            assistant = await session.get(AssistantModel, source.assistant_id)
            if (
                assistant is None
                or assistant.tenant_id != source.tenant_id
                or assistant.status.value != "active"
            ):
                return False
            tenant = await session.get(ControlTenantModel, assistant.tenant_id)
            if tenant is None or tenant.status.value != "active":
                return False
        if source.connection_id is not None:
            connection = await session.get(
                PlatformConnectionModel, source.connection_id
            )
            if (
                connection is None
                or connection.tenant_id != source.tenant_id
                or connection.assistant_id != source.assistant_id
                or connection.status.value != "active"
            ):
                return False
        revision = await self._resolve_revision(session, source, workload)
        if revision is None or revision.schema_version != "provider-routing-v1":
            return False
        present = await session.scalar(
            select(ProviderRoutingPolicyRouteModel.id).where(
                ProviderRoutingPolicyRouteModel.policy_revision_id == revision.id,
                ProviderRoutingPolicyRouteModel.capability_id == route.capability_id,
            )
        )
        if present is None:
            return False
        capability = await session.get(ProviderCapabilityModel, route.capability_id)
        if capability is None or not capability.credential_configured:
            return False
        current = ResolvedProviderRoute(
            snapshot_id=route.snapshot_id,
            policy_revision_id=revision.id,
            capability_id=capability.id,
            provider_id=capability.provider_id,
            model=capability.model,
            adapter_key=capability.adapter_key,
            position=route.position,
            data_class=capability.data_class,
            credential_slot=capability.credential_slot,
            reservation_strategy=capability.reservation_strategy,
            capability_metadata=dict(capability.capability_metadata),
            allowed_fallback_reasons=frozenset(),
        )
        try:
            return capability_matches(
                current, workload, dict(revision.requirements)
            ).eligible
        except ValueError:
            return False

    async def _verify_attribution(
        self, session: AsyncSession, source: ProviderWorkSource
    ) -> None:
        if source.tenant_id is None or source.assistant_id is None:
            raise ProviderGovernanceUnavailable("resource attribution is unavailable")
        if source.knowledge_index_job_id is not None:
            bound = await session.scalar(
                select(KnowledgeIndexJobModel.id)
                .join(
                    AssistantModel,
                    (AssistantModel.id == KnowledgeIndexJobModel.assistant_id)
                    & (AssistantModel.tenant_id == KnowledgeIndexJobModel.tenant_id),
                )
                .where(
                    KnowledgeIndexJobModel.id == source.knowledge_index_job_id,
                    KnowledgeIndexJobModel.tenant_id == source.tenant_id,
                    KnowledgeIndexJobModel.assistant_id == source.assistant_id,
                )
            )
            if bound is None or source.connection_id is not None:
                raise ProviderGovernanceUnavailable("resource attribution denied")
            return
        if source.voice_generation_job_id is not None:
            bound = await session.scalar(
                select(TelegramVoiceGenerationJobModel.id)
                .join(
                    AssistantModel,
                    (AssistantModel.id == TelegramVoiceGenerationJobModel.assistant_id)
                    & (
                        AssistantModel.tenant_id
                        == TelegramVoiceGenerationJobModel.tenant_id
                    ),
                )
                .where(
                    TelegramVoiceGenerationJobModel.id
                    == source.voice_generation_job_id,
                    TelegramVoiceGenerationJobModel.tenant_id == source.tenant_id,
                    TelegramVoiceGenerationJobModel.assistant_id == source.assistant_id,
                    TelegramVoiceGenerationJobModel.connection_id
                    == source.connection_id,
                    TelegramVoiceGenerationJobModel.status
                    == VoiceGenerationStatus.LEASED,
                    TelegramVoiceGenerationJobModel.lease_owner
                    == source.execution_owner,
                    TelegramVoiceGenerationJobModel.lease_expires_at
                    > datetime.now(UTC),
                )
            )
            if bound is None:
                raise ProviderGovernanceUnavailable("resource attribution denied")
            return
        if source.connection_id is None:
            raise ProviderGovernanceUnavailable("resource attribution is unavailable")
        bound = await session.scalar(
            select(PlatformConnectionModel.id)
            .join(
                AssistantModel,
                (AssistantModel.id == PlatformConnectionModel.assistant_id)
                & (AssistantModel.tenant_id == PlatformConnectionModel.tenant_id),
            )
            .where(
                PlatformConnectionModel.id == source.connection_id,
                PlatformConnectionModel.tenant_id == source.tenant_id,
                PlatformConnectionModel.assistant_id == source.assistant_id,
            )
        )
        if bound is None:
            raise ProviderGovernanceUnavailable("resource attribution denied")

    async def _health_eligible(
        self,
        session: AsyncSession,
        state: ProviderCapabilityStateModel | None,
        now: datetime,
    ) -> bool:
        if (
            state is None
            or state.lifecycle != ProviderLifecycle.ENABLED
            or state.health not in {ProviderHealth.READY, ProviderHealth.DEGRADED}
            or state.health_policy_revision_id is None
            or state.last_evaluated_at is None
        ):
            return False
        policy = await session.get(
            ProviderHealthPolicyRevisionModel, state.health_policy_revision_id
        )
        return bool(
            policy is not None
            and policy.effective_at <= now
            and state.last_evaluated_at + timedelta(seconds=policy.stale_after_seconds)
            >= now
        )

    async def _denied_attempt(
        self,
        session: AsyncSession,
        source: ProviderWorkSource,
        route: ResolvedProviderRoute,
        workload: WorkloadClass,
        operation: ProviderOperation,
        role: RouteRole,
        ordinal: int,
        attempt_key: str,
        outcome: ProviderAttemptOutcome,
        now: datetime,
    ) -> ProviderAdmission:
        row = ProviderUsageAttemptModel(
            attempt_key=attempt_key,
            source_key=source.source_key,
            record_origin="governed",
            planning_job_id=source.planning_job_id,
            summary_job_id=source.summary_job_id,
            semantic_index_job_id=source.semantic_index_job_id,
            knowledge_index_job_id=source.knowledge_index_job_id,
            voice_generation_job_id=source.voice_generation_job_id,
            workload_class=workload,
            operation=operation,
            attempt_ordinal=ordinal,
            route_role=role,
            capability_id=route.capability_id,
            policy_snapshot_id=route.snapshot_id,
            provider_id=route.provider_id,
            model=route.model,
            tenant_id=source.tenant_id,
            assistant_id=source.assistant_id,
            connection_id=source.connection_id,
            state=ProviderAttemptState.NO_IO,
            provider_outcome=outcome,
            request_count=0,
            usage_quality=UsageQuality.MISSING,
            estimate_quality=EstimateQuality.UNAVAILABLE,
            finalized_at=now,
        )
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
        except IntegrityError:
            raced = await session.scalar(
                select(ProviderUsageAttemptModel).where(
                    ProviderUsageAttemptModel.attempt_key == attempt_key
                )
            )
            if raced is None:
                raced = await session.scalar(
                    select(ProviderUsageAttemptModel).where(
                        ProviderUsageAttemptModel.source_key == source.source_key,
                        ProviderUsageAttemptModel.operation == operation,
                        ProviderUsageAttemptModel.attempt_ordinal == ordinal,
                    )
                )
            if raced is None:
                raise ProviderGovernanceUnavailable(
                    "denied attempt identity race could not be resolved"
                ) from None
            if not _attempt_identity_matches(
                raced, route, workload, operation, role, ordinal
            ):
                return ProviderAdmission(
                    False,
                    raced.id,
                    raced.attempt_key,
                    ProviderAttemptOutcome.GOVERNANCE_UNAVAILABLE,
                )
            return ProviderAdmission(
                raced.state
                in {
                    ProviderAttemptState.RESERVED,
                    ProviderAttemptState.IO_STARTED,
                    ProviderAttemptState.IO_COMPLETE,
                },
                raced.id,
                raced.attempt_key,
                raced.provider_outcome,
            )
        return ProviderAdmission(False, row.id, attempt_key, outcome)

    async def _release_reservations(
        self, session: AsyncSession, attempt_id: UUID
    ) -> None:
        rows = list(
            await session.scalars(
                select(ProviderBudgetReservationModel)
                .where(
                    ProviderBudgetReservationModel.attempt_id == attempt_id,
                    ProviderBudgetReservationModel.state == ReservationState.RESERVED,
                )
                .order_by(ProviderBudgetReservationModel.budget_id)
                .with_for_update()
            )
        )
        for reservation in rows:
            window = await session.get(
                ProviderBudgetWindowModel,
                reservation.window_id,
                with_for_update=True,
            )
            if window is None or window.reserved_amount < reservation.reserved_amount:
                raise ProviderGovernanceUnavailable("reservation counter is invalid")
            window.reserved_amount -= reservation.reserved_amount
            window.lock_version += 1
            reservation.state = ReservationState.RELEASED

    async def _consume_reservations(
        self,
        session: AsyncSession,
        attempt: ProviderUsageAttemptModel,
        usage: UsageObservation,
        estimate: int | None,
    ) -> None:
        rows = list(
            await session.scalars(
                select(ProviderBudgetReservationModel)
                .where(
                    ProviderBudgetReservationModel.attempt_id == attempt.id,
                    ProviderBudgetReservationModel.state == ReservationState.RESERVED,
                )
                .order_by(ProviderBudgetReservationModel.budget_id)
                .with_for_update()
            )
        )
        for reservation in rows:
            budget = await session.get(ProviderBudgetModel, reservation.budget_id)
            window = await session.get(
                ProviderBudgetWindowModel,
                reservation.window_id,
                with_for_update=True,
            )
            if budget is None or window is None:
                raise ProviderGovernanceUnavailable(
                    "reservation references are invalid"
                )
            actual = _actual_amount(budget.measurement, attempt, usage, estimate)
            reconciled = (
                actual
                if usage.quality == UsageQuality.COMPLETE
                or budget.measurement == BudgetMeasurement.REQUESTS
                else reservation.reserved_amount
            )
            if reconciled is None:
                reconciled = reservation.reserved_amount
            if window.reserved_amount < reservation.reserved_amount:
                raise ProviderGovernanceUnavailable("reservation counter is invalid")
            window.reserved_amount -= reservation.reserved_amount
            window.consumed_amount += reconciled
            window.lock_version += 1
            reservation.reconciled_amount = reconciled
            reservation.state = ReservationState.CONSUMED

    async def _ambiguate_reservations(
        self, session: AsyncSession, attempt_id: UUID
    ) -> None:
        rows = list(
            await session.scalars(
                select(ProviderBudgetReservationModel)
                .where(
                    ProviderBudgetReservationModel.attempt_id == attempt_id,
                    ProviderBudgetReservationModel.state == ReservationState.RESERVED,
                )
                .order_by(ProviderBudgetReservationModel.budget_id)
                .with_for_update()
            )
        )
        for reservation in rows:
            window = await session.get(
                ProviderBudgetWindowModel,
                reservation.window_id,
                with_for_update=True,
            )
            if window is None or window.reserved_amount < reservation.reserved_amount:
                raise ProviderGovernanceUnavailable("reservation counter is invalid")
            window.reserved_amount -= reservation.reserved_amount
            window.consumed_amount += reservation.reserved_amount
            window.lock_version += 1
            reservation.reconciled_amount = reservation.reserved_amount
            reservation.state = ReservationState.AMBIGUOUS


def _attempt_key(
    source_key: str,
    workload: WorkloadClass,
    operation: ProviderOperation,
    route_position: int,
    role: RouteRole,
    attempt_ordinal: int,
) -> str:
    return sha256(
        (
            "provider-attempt-v1|"
            f"{source_key}|{workload.value}|{operation.value}|{route_position}|"
            f"{role.value}|{attempt_ordinal}"
        ).encode()
    ).hexdigest()


def _attempt_identity_matches(
    attempt: ProviderUsageAttemptModel,
    route: ResolvedProviderRoute,
    workload: WorkloadClass,
    operation: ProviderOperation,
    role: RouteRole,
    attempt_ordinal: int,
) -> bool:
    return bool(
        attempt.workload_class == workload
        and attempt.operation == operation
        and attempt.route_role == role
        and attempt.attempt_ordinal == attempt_ordinal
        and attempt.capability_id == route.capability_id
        and attempt.policy_snapshot_id == route.snapshot_id
    )


def _provider_request_reference(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= 255:
        return value
    return f"sha256:{sha256(value.encode()).hexdigest()}"


def _scope_keys(source: ProviderWorkSource) -> tuple[str, ...]:
    values = ["deployment"]
    if source.assistant_id is not None:
        values.append(f"assistant:{source.assistant_id}")
    if source.connection_id is not None:
        values.append(f"platform_connection:{source.connection_id}")
    return tuple(values)


def _scope_order(scope: BudgetScope) -> int:
    return {
        BudgetScope.DEPLOYMENT: 0,
        BudgetScope.ASSISTANT: 1,
        BudgetScope.PLATFORM_CONNECTION: 2,
    }[scope]


def _reservation_amounts(
    maximum_input_tokens: int | None,
    maximum_output_tokens: int | None,
    price: ProviderPriceRevisionModel | None,
) -> dict[BudgetMeasurement, int | None]:
    total = (
        maximum_input_tokens + maximum_output_tokens
        if maximum_input_tokens is not None and maximum_output_tokens is not None
        else None
    )
    if total is not None and total > MAX_BIGINT:
        raise ValueError("total token reservation exceeds durable integer range")
    cost: int | None = None
    if price is not None and price.unit_basis in {
        "embedding_request",
        "transcription_request",
        "tts_request",
    }:
        cost = price.request_rate
    elif (
        price is not None
        and price.unit_basis == "generation_tokens"
        and price.input_rate is not None
        and price.output_rate is not None
        and maximum_input_tokens is not None
        and maximum_output_tokens is not None
    ):
        cost = reserve_generation_cost(
            maximum_input_tokens,
            maximum_output_tokens,
            GenerationPrice(price.input_rate, price.output_rate),
        )
    return {
        BudgetMeasurement.REQUESTS: 1,
        BudgetMeasurement.INPUT_TOKENS: maximum_input_tokens,
        BudgetMeasurement.OUTPUT_TOKENS: maximum_output_tokens,
        BudgetMeasurement.TOTAL_TOKENS: total,
        BudgetMeasurement.ESTIMATED_COST_MICROUSD: cost,
    }


def _actual_estimate(
    usage: UsageObservation, price: ProviderPriceRevisionModel | None
) -> tuple[int | None, EstimateQuality]:
    if price is None:
        return None, EstimateQuality.UNAVAILABLE
    if (
        price.unit_basis
        in {"embedding_request", "transcription_request", "tts_request"}
        and price.request_rate is not None
    ):
        return price.request_rate, EstimateQuality.ESTIMATED
    if (
        usage.quality == UsageQuality.COMPLETE
        and usage.input_tokens is not None
        and usage.output_tokens is not None
        and price.input_rate is not None
        and price.output_rate is not None
    ):
        return (
            estimate_generation_cost(
                usage.input_tokens,
                usage.output_tokens,
                GenerationPrice(price.input_rate, price.output_rate),
            ),
            EstimateQuality.ESTIMATED,
        )
    if usage.quality == UsageQuality.PARTIAL:
        known = 0
        present = False
        generation_price = GenerationPrice(
            price.input_rate or 0, price.output_rate or 0
        )
        if usage.input_tokens is not None and price.input_rate is not None:
            known += estimate_generation_cost(usage.input_tokens, 0, generation_price)
            present = True
        if usage.output_tokens is not None and price.output_rate is not None:
            known += estimate_generation_cost(0, usage.output_tokens, generation_price)
            present = True
        if known > MAX_BIGINT:
            raise ValueError("partial estimate exceeds durable integer range")
        return (known if present else None), EstimateQuality.PARTIAL
    return None, EstimateQuality.RESERVATION_ESTIMATE


def _actual_amount(
    measurement: BudgetMeasurement,
    attempt: ProviderUsageAttemptModel,
    usage: UsageObservation,
    estimate: int | None,
) -> int | None:
    return {
        BudgetMeasurement.REQUESTS: attempt.request_count,
        BudgetMeasurement.INPUT_TOKENS: usage.input_tokens,
        BudgetMeasurement.OUTPUT_TOKENS: usage.output_tokens,
        BudgetMeasurement.TOTAL_TOKENS: usage.total_tokens,
        BudgetMeasurement.ESTIMATED_COST_MICROUSD: estimate,
    }[measurement]
