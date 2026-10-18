"""Content-free persistence for deterministic safety and limiter outcomes."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.rate_limit import RateLimitDecision, RateLimitOperation
from app.domain.safety import SafetyDecision
from app.infrastructure.database.models import (
    RateLimitEventModel,
    SafetyPolicyDecisionModel,
)


class SqlAlchemySafetyRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record_decision(
        self,
        *,
        planning_job_id: UUID | None,
        response_plan_id: UUID | None,
        conversation_id: UUID,
        decision: SafetyDecision,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    SafetyPolicyDecisionModel(
                        planning_job_id=planning_job_id,
                        response_plan_id=response_plan_id,
                        conversation_id=conversation_id,
                        policy_version=decision.policy_version,
                        stage=decision.stage,
                        outcome=decision.outcome,
                        reason_code=decision.reason_code,
                        transformed=decision.transformed,
                    )
                )

    async def record_rate_limit(
        self,
        *,
        planning_job_id: UUID | None,
        outbound_action_id: UUID | None,
        operation: RateLimitOperation,
        decision: RateLimitDecision,
        provider_id: str | None,
        configuration_version: str,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(
                    RateLimitEventModel(
                        planning_job_id=planning_job_id,
                        outbound_action_id=outbound_action_id,
                        operation=operation,
                        limiting_scope=decision.limiting_scope,
                        provider_id=provider_id,
                        allowed=decision.allowed,
                        retry_after_seconds=decision.retry_after_seconds,
                        configuration_version=configuration_version,
                    )
                )
