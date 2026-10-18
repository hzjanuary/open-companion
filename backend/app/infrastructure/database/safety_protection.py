"""Content-free SPEC-024 protection state, signal aggregation, and review queue."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.safety import ReviewItemRecord
from app.domain.outbound import OutboundActionStatus
from app.domain.safety import (
    AggregatedSignals,
    ProtectionAction,
    ProtectionState,
    ReviewAction,
    ReviewItemStatus,
    SafetyOutcome,
    SafetyReasonCode,
    SafetySignalType,
    SafetyStage,
)
from app.infrastructure.database.models import (
    MessageModel,
    OutboundActionModel,
    ParticipantModel,
    RateLimitEventModel,
    ResponsePlanModel,
    ResponsePlanningJobModel,
    SafetyPolicyDecisionModel,
    SafetyReviewItemModel,
)

_PROMPT_INJECTION_REASONS = frozenset(
    {
        SafetyReasonCode.PROMPT_INJECTION_ACTION_ATTEMPT,
        SafetyReasonCode.UNSUPPORTED_ACTION,
    }
)


class SafetyModerationUnavailable(ConnectionError):
    """Fail-closed surface for a safety repository outage (NFR-02)."""


class SqlAlchemySafetyModerationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def aggregate_signals(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
    ) -> AggregatedSignals:
        """Count content-free signals over the durable decision/limiter tables.

        Attribution is derivable through existing foreign keys; unattributable
        decisions are excluded from per-participant aggregation and included
        only conversation-wide. No message content is read.
        """

        try:
            async with self._session_factory() as session:
                refusal_count = await self._decision_count(
                    session,
                    conversation_id,
                    participant_id,
                    since,
                    outcomes=(SafetyOutcome.REFUSE, SafetyOutcome.TRANSFORM),
                )
                memory_count = await self._decision_count(
                    session,
                    conversation_id,
                    participant_id,
                    since,
                    reasons=(SafetyReasonCode.PRIVATE_MEMORY_EXTRACTION_ATTEMPT,),
                )
                dangerous_count = await self._decision_count(
                    session,
                    conversation_id,
                    participant_id,
                    since,
                    reasons=(SafetyReasonCode.DANGEROUS_INSTRUCTION_REQUEST,),
                )
                injection_count = await self._decision_count(
                    session,
                    conversation_id,
                    participant_id,
                    since,
                    reasons=tuple(_PROMPT_INJECTION_REASONS),
                )
                manipulation_count = await self._decision_count(
                    session,
                    conversation_id,
                    participant_id,
                    since,
                    reasons=(SafetyReasonCode.MANIPULATION_ATTEMPT,),
                )
                rate_limit_count = await self._rate_limit_violation_count(
                    session, conversation_id, participant_id, since
                )
                mention_count, teasing_count = await self._targeting_counts(
                    session, conversation_id, participant_id, since
                )
        except Exception as exc:
            raise SafetyModerationUnavailable("safety aggregation unavailable") from exc
        counts = {
            SafetySignalType.SAFETY_DECISION_REFUSAL: refusal_count,
            SafetySignalType.MENTION_FREQUENCY: mention_count,
            SafetySignalType.TEASING_FREQUENCY: teasing_count,
            SafetySignalType.RATE_LIMIT_VIOLATION: rate_limit_count,
            SafetySignalType.MEMORY_EXTRACTION_ATTEMPT: memory_count,
            SafetySignalType.DANGEROUS_INSTRUCTION_REQUEST: dangerous_count,
            SafetySignalType.PROMPT_INJECTION_ATTEMPT: injection_count,
            SafetySignalType.MANIPULATION_ATTEMPT: manipulation_count,
        }
        return AggregatedSignals(
            conversation_id=conversation_id,
            participant_id=participant_id,
            affected_target_participant_id=(
                participant_id if mention_count or teasing_count else None
            ),
            since=since,
            counts=counts,
        )

    async def protection_state(self, participant_id: UUID) -> ProtectionState | None:
        async with self._session_factory() as session:
            participant = await session.get(ParticipantModel, participant_id)
            if participant is None:
                return None
            latest = await session.scalar(
                select(SafetyReviewItemModel)
                .where(
                    SafetyReviewItemModel.participant_id == participant_id,
                    SafetyReviewItemModel.status != ReviewItemStatus.RESOLVED,
                    SafetyReviewItemModel.protection_action.is_not(None),
                )
                .order_by(SafetyReviewItemModel.created_at.desc())
                .limit(1)
            )
        protected = participant.protected_at is not None
        mode = None
        pause_until = None
        if latest is not None and latest.protection_action is not None:
            mode = latest.protection_action.value
            state = latest.protection_state or {}
            raw_until = state.get("pause_until")
            if isinstance(raw_until, str):
                try:
                    pause_until = datetime.fromisoformat(raw_until)
                except ValueError:
                    pause_until = None
        return ProtectionState(
            protected=protected,
            interaction_mode=mode,
            pause_until=pause_until,
        )

    async def protective_action_count(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        since: datetime,
    ) -> int:
        async with self._session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(SafetyReviewItemModel)
                .where(
                    SafetyReviewItemModel.conversation_id == conversation_id,
                    SafetyReviewItemModel.participant_id == participant_id,
                    SafetyReviewItemModel.protection_action.is_not(None),
                    SafetyReviewItemModel.created_at >= since,
                )
            )
        return int(count or 0)

    async def protect(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                participant = await session.get(
                    ParticipantModel, participant_id, with_for_update=True
                )
                if (
                    participant is None
                    or participant.conversation_id != conversation_id
                ):
                    raise SafetyModerationUnavailable("participant not in conversation")
                participant.protected_at = datetime.now(UTC)

    async def restore_targeting(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                participant = await session.get(
                    ParticipantModel, participant_id, with_for_update=True
                )
                if (
                    participant is None
                    or participant.conversation_id != conversation_id
                ):
                    raise SafetyModerationUnavailable("participant not in conversation")
                participant.protected_at = None

    async def record_protective_action(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        affected_target_participant_id: UUID | None,
        signals: AggregatedSignals,
        action: ProtectionAction,
    ) -> UUID:
        now = datetime.now(UTC)
        protection_state: dict[str, object] = {
            "action": action.value,
            "applied_at": now.isoformat(),
        }
        if action == ProtectionAction.PAUSE_INTERACTION:
            protection_state["pause_until"] = now.isoformat()
        async with self._session_factory() as session:
            async with session.begin():
                item = SafetyReviewItemModel(
                    conversation_id=conversation_id,
                    participant_id=participant_id,
                    category=SafetySignalType.PROTECTIVE_ACTION,
                    stage=SafetyStage.PRE_DELIVERY,
                    outcome_counts={
                        str(signal_type.value): count
                        for signal_type, count in signals.counts.items()
                        if count
                    },
                    protection_state=protection_state,
                    status=ReviewItemStatus.OPEN,
                    protection_action=action,
                )
                session.add(item)
                await session.flush()
                item_id = item.id
        return item_id

    async def apply_review_action(
        self,
        *,
        item_id: UUID,
        action: ReviewAction,
        actor_participant_id: UUID | None,
        source: str,
    ) -> bool:
        """Apply one of the four bounded review actions with idempotency (FR-08).

        Returns True when the item state changed; False when the action was
        already current or the item is resolved (idempotent no-op).
        """

        now = datetime.now(UTC)
        async with self._session_factory() as session:
            async with session.begin():
                item = await session.get(
                    SafetyReviewItemModel, item_id, with_for_update=True
                )
                if item is None:
                    raise SafetyModerationUnavailable("review item not found")
                if item.status == ReviewItemStatus.RESOLVED:
                    return False
                changed = False
                if action == ReviewAction.ACKNOWLEDGE:
                    if item.status != ReviewItemStatus.ACKNOWLEDGED:
                        item.status = ReviewItemStatus.ACKNOWLEDGED
                        item.acknowledged_at = now
                        changed = True
                elif action == ReviewAction.ESCALATE:
                    if item.status != ReviewItemStatus.ESCALATED:
                        item.status = ReviewItemStatus.ESCALATED
                        item.escalated_at = now
                        changed = True
                elif action == ReviewAction.RESTORE_TARGETING:
                    if item.participant_id is not None:
                        participant = await session.get(
                            ParticipantModel, item.participant_id, with_for_update=True
                        )
                        if participant is not None:
                            participant.protected_at = None
                    item.status = ReviewItemStatus.RESOLVED
                    item.resolved_at = now
                    item.protection_action = ProtectionAction.RESTORE_TARGETING
                    changed = True
                elif action == ReviewAction.PAUSE_OR_RESTRICT:
                    if item.participant_id is not None:
                        participant = await session.get(
                            ParticipantModel, item.participant_id, with_for_update=True
                        )
                        if participant is not None:
                            participant.protected_at = now
                    item.protection_action = ProtectionAction.PAUSE_INTERACTION
                    item.protection_state = {
                        **(item.protection_state or {}),
                        "action": ProtectionAction.PAUSE_INTERACTION.value,
                        "applied_at": now.isoformat(),
                    }
                    if item.status == ReviewItemStatus.OPEN:
                        item.status = ReviewItemStatus.ACKNOWLEDGED
                        item.acknowledged_at = now
                    changed = True
                if changed:
                    item.action = action
                    item.actioned_at = now
                    item.actor_participant_id = actor_participant_id
                    item.source = source
                return changed

    async def list_review_items(
        self, *, conversation_id: UUID
    ) -> list[ReviewItemRecord]:
        async with self._session_factory() as session:
            items = (
                await session.scalars(
                    select(SafetyReviewItemModel)
                    .where(SafetyReviewItemModel.conversation_id == conversation_id)
                    .order_by(SafetyReviewItemModel.created_at.desc())
                    .limit(50)
                )
            ).all()
            return [
                ReviewItemRecord(
                    item_id=item.id,
                    category=SafetySignalType(str(item.category)),
                    stage=str(item.stage),
                    status=ReviewItemStatus(str(item.status)),
                    outcome_counts=dict(item.outcome_counts or {}),
                    protection_state=dict(item.protection_state or {}),
                    created_at=item.created_at,
                )
                for item in items
            ]

    async def _decision_count(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
        *,
        outcomes: tuple[SafetyOutcome, ...] = (),
        reasons: tuple[SafetyReasonCode, ...] = (),
    ) -> int:
        query = select(func.count()).select_from(SafetyPolicyDecisionModel)
        conditions = [
            SafetyPolicyDecisionModel.conversation_id == conversation_id,
            SafetyPolicyDecisionModel.created_at >= since,
        ]
        if outcomes:
            conditions.append(SafetyPolicyDecisionModel.outcome.in_(outcomes))
        if reasons:
            conditions.append(SafetyPolicyDecisionModel.reason_code.in_(reasons))
        if participant_id is not None:
            conditions.append(MessageModel.participant_id == participant_id)
            query = query.join(
                ResponsePlanningJobModel,
                SafetyPolicyDecisionModel.planning_job_id
                == ResponsePlanningJobModel.id,
            ).join(
                MessageModel,
                ResponsePlanningJobModel.message_id == MessageModel.id,
            )
        query = query.where(and_(*conditions))
        value = await session.scalar(query)
        return int(value or 0)

    async def _rate_limit_violation_count(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
    ) -> int:
        query = select(func.count()).select_from(RateLimitEventModel)
        conditions = [
            RateLimitEventModel.allowed.is_(False),
            RateLimitEventModel.created_at >= since,
        ]
        if participant_id is not None:
            conditions.append(MessageModel.participant_id == participant_id)
            query = query.join(
                ResponsePlanningJobModel,
                RateLimitEventModel.planning_job_id == ResponsePlanningJobModel.id,
            ).join(
                MessageModel,
                ResponsePlanningJobModel.message_id == MessageModel.id,
            )
        query = query.where(and_(*conditions))
        value = await session.scalar(query)
        return int(value or 0)

    async def _targeting_counts(
        self,
        session: AsyncSession,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
    ) -> tuple[int, int]:
        if participant_id is None:
            return 0, 0
        identifier = str(participant_id)
        mention = await session.scalar(
            select(func.count())
            .select_from(OutboundActionModel)
            .where(
                OutboundActionModel.conversation_id == conversation_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
                OutboundActionModel.created_at >= since,
                OutboundActionModel.mention_participant_ids.contains([identifier]),
            )
        )
        teasing = await session.scalar(
            select(func.count())
            .select_from(OutboundActionModel)
            .join(
                ResponsePlanModel,
                OutboundActionModel.response_plan_id == ResponsePlanModel.id,
            )
            .where(
                OutboundActionModel.conversation_id == conversation_id,
                OutboundActionModel.status == OutboundActionStatus.DELIVERED,
                OutboundActionModel.created_at >= since,
                ResponsePlanModel.teasing_target_participant_ids.contains([identifier]),
            )
        )
        return int(mention or 0), int(teasing or 0)
