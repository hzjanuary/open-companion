"""SPEC-024 service-layer tests over a deterministic in-memory repository."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.safety import ReviewItemRecord, SafetyModerationService
from app.core.config import Settings
from app.domain.safety import (
    AggregatedSignals,
    ProtectionAction,
    ProtectionState,
    ReviewAction,
    SafetyLevel,
    SafetySignalType,
)


class FakeSafetyModerationRepository:
    """Minimal in-memory repository recording service interactions."""

    def __init__(
        self,
        *,
        signals: AggregatedSignals | None = None,
        prior_actions: int = 0,
        state: ProtectionState | None = None,
    ) -> None:
        self.signals = signals
        self.prior_actions = prior_actions
        self.state = state
        self.protective_actions: list[ProtectionAction] = []
        self.protected: list[tuple[UUID, UUID | None, str]] = []
        self.restored: list[tuple[UUID, UUID | None, str]] = []
        self.review_results: dict[tuple[UUID, ReviewAction], bool] = {}

    async def aggregate_signals(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
    ) -> AggregatedSignals:
        assert self.signals is not None
        return self.signals

    async def protection_state(self, participant_id: UUID) -> ProtectionState | None:
        return self.state

    async def protective_action_count(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        since: datetime,
    ) -> int:
        return self.prior_actions

    async def protect(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None:
        self.protected.append((participant_id, actor_participant_id, source))

    async def restore_targeting(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None:
        self.restored.append((participant_id, actor_participant_id, source))

    async def record_protective_action(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        affected_target_participant_id: UUID | None,
        signals: AggregatedSignals,
        action: ProtectionAction,
    ) -> UUID:
        self.protective_actions.append(action)
        return uuid4()

    async def apply_review_action(
        self,
        *,
        item_id: UUID,
        action: ReviewAction,
        actor_participant_id: UUID | None,
        source: str,
    ) -> bool:
        return self.review_results.get((item_id, action), True)

    async def list_review_items(
        self, *, conversation_id: UUID
    ) -> list[ReviewItemRecord]:
        return []


def _signals(
    counts: dict[SafetySignalType, int], *, affected_target: UUID | None = None
) -> AggregatedSignals:
    return AggregatedSignals(
        conversation_id=uuid4(),
        participant_id=uuid4(),
        affected_target_participant_id=affected_target,
        since=datetime(2026, 1, 1, tzinfo=UTC),
        counts=counts,
    )


def _service(
    repository: FakeSafetyModerationRepository,
    *,
    enabled: bool = True,
) -> SafetyModerationService:
    return SafetyModerationService(
        Settings(_env_file=None, safety_moderation_enabled=enabled),
        repository,
    )


def test_disabled_or_unknown_participant_takes_no_action() -> None:
    conversation_id = uuid4()
    for repository in (
        FakeSafetyModerationRepository(),
        FakeSafetyModerationRepository(signals=_signals({})),
    ):
        service = _service(repository, enabled=False)
        result = asyncio.run(
            service.evaluate_and_enforce(
                conversation_id=conversation_id, participant_id=None
            )
        )
        assert result is None
    repository = FakeSafetyModerationRepository(signals=_signals({}))
    service = _service(repository, enabled=True)
    assert (
        asyncio.run(
            service.evaluate_and_enforce(
                conversation_id=conversation_id, participant_id=None
            )
        )
        is None
    )


def test_no_threshold_exceeded_means_no_protective_action() -> None:
    repository = FakeSafetyModerationRepository(
        signals=_signals({SafetySignalType.MENTION_FREQUENCY: 3})
    )
    service = _service(repository)
    result = asyncio.run(
        service.evaluate_and_enforce(conversation_id=uuid4(), participant_id=uuid4())
    )
    assert result is None
    assert repository.protective_actions == []
    assert repository.protected == []


def test_escalation_ladder_stop_then_reduce_then_pause() -> None:
    conversation_id = uuid4()
    participant_id = uuid4()
    for prior, expected in (
        (0, ProtectionAction.STOP_TARGETING),
        (1, ProtectionAction.REDUCE_INTERACTION),
        (2, ProtectionAction.PAUSE_INTERACTION),
    ):
        repository = FakeSafetyModerationRepository(
            signals=_signals({SafetySignalType.DANGEROUS_INSTRUCTION_REQUEST: 2}),
            prior_actions=prior,
        )
        service = _service(repository)
        result = asyncio.run(
            service.evaluate_and_enforce(
                conversation_id=conversation_id, participant_id=participant_id
            )
        )
        assert result == expected
        assert repository.protective_actions == [expected]


def test_targeting_surge_protects_affected_target() -> None:
    conversation_id = uuid4()
    participant_id = uuid4()
    target = uuid4()
    repository = FakeSafetyModerationRepository(
        signals=_signals(
            {
                SafetySignalType.MENTION_FREQUENCY: 20,
                SafetySignalType.TEASING_FREQUENCY: 1,
            },
            affected_target=target,
        )
    )
    service = _service(repository)
    result = asyncio.run(
        service.evaluate_and_enforce(
            conversation_id=conversation_id, participant_id=participant_id
        )
    )
    assert result is not None
    assert repository.protected == [(target, participant_id, "protective_enforcement")]


def test_sustained_non_targeting_signals_do_not_protect_any_target() -> None:
    repository = FakeSafetyModerationRepository(
        signals=_signals({SafetySignalType.MANIPULATION_ATTEMPT: 5})
    )
    service = _service(repository)
    result = asyncio.run(
        service.evaluate_and_enforce(conversation_id=uuid4(), participant_id=uuid4())
    )
    assert result is not None
    assert repository.protected == []


def test_review_actions_delegate_to_repository() -> None:
    service = _service(FakeSafetyModerationRepository())
    item_id = uuid4()
    assert asyncio.run(service.acknowledge(item_id=item_id)) is True
    assert asyncio.run(service.escalate(item_id=item_id)) is True
    assert (
        asyncio.run(service.restore(item_id=item_id, actor_participant_id=None)) is True
    )
    assert (
        asyncio.run(service.pause(item_id=item_id, actor_participant_id=None)) is True
    )
    repository = FakeSafetyModerationRepository()
    repository.review_results[(item_id, ReviewAction.ACKNOWLEDGE)] = False
    service = _service(repository)
    assert asyncio.run(service.acknowledge(item_id=item_id)) is False


def test_pause_or_restrict_protects_participant() -> None:
    conversation_id = uuid4()
    participant_id = uuid4()
    repository = FakeSafetyModerationRepository()
    service = _service(repository)
    asyncio.run(
        service.pause_or_restrict(
            conversation_id=conversation_id,
            participant_id=participant_id,
            actor_participant_id=None,
            source="review_pause_or_restrict",
        )
    )
    assert repository.protected == [(participant_id, None, "review_pause_or_restrict")]


def test_strict_and_relaxed_levels_change_trigger_sensitivity() -> None:
    conversation_id = uuid4()
    participant_id = uuid4()

    def service_with_level(level: SafetyLevel) -> SafetyModerationService:
        return SafetyModerationService(
            Settings(
                _env_file=None,
                safety_moderation_enabled=True,
                safety_threshold_mention_frequency=12,
            ),
            FakeSafetyModerationRepository(
                signals=_signals({SafetySignalType.MENTION_FREQUENCY: 7})
            ),
        )

    relaxed = asyncio.run(
        service_with_level(SafetyLevel.RELAXED).evaluate_and_enforce(
            conversation_id=conversation_id,
            participant_id=participant_id,
            safety_level=SafetyLevel.RELAXED,
        )
    )
    assert relaxed is None
    strict = asyncio.run(
        service_with_level(SafetyLevel.STRICT).evaluate_and_enforce(
            conversation_id=conversation_id,
            participant_id=participant_id,
            safety_level=SafetyLevel.STRICT,
        )
    )
    assert strict is not None


def test_protection_state_is_surfaced() -> None:
    repository = FakeSafetyModerationRepository(
        state=ProtectionState(
            protected=True,
            interaction_mode=ProtectionAction.PAUSE_INTERACTION.value,
            pause_until=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    service = _service(repository)
    state = asyncio.run(service.protection_state(uuid4()))
    assert state is not None
    assert state.interaction_mode == ProtectionAction.PAUSE_INTERACTION.value
    assert state.protected is True
