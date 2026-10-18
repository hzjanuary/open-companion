"""SPEC-024 content-free signal aggregation, protective enforcement, and review.

This layer owns the deterministic policy over persisted content-free state.
It never stores content, never sanctions a participant, never weakens the
SPEC-012 hard boundaries, and is invoked out of band or inside the bounded
planning/delivery targeting paths -- never inside the webhook acknowledgement
path.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.core.config import Settings
from app.domain.safety import (
    AggregatedSignals,
    ProtectionAction,
    ProtectionState,
    ReviewAction,
    ReviewItemStatus,
    SafetyLevel,
    SafetySignalType,
    SignalThresholds,
    evaluate_protection,
    interaction_escalation,
)


@dataclass(frozen=True)
class ReviewItemRecord:
    """Content-free projection of a persisted review item."""

    item_id: UUID
    category: SafetySignalType
    stage: str
    status: ReviewItemStatus
    outcome_counts: dict[str, int]
    protection_state: dict[str, object]
    created_at: datetime


class SafetyModerationRepository(Protocol):
    async def aggregate_signals(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID | None,
        since: datetime,
    ) -> AggregatedSignals: ...

    async def protection_state(
        self, participant_id: UUID
    ) -> ProtectionState | None: ...

    async def protective_action_count(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        since: datetime,
    ) -> int: ...

    async def protect(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None: ...

    async def restore_targeting(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None: ...

    async def record_protective_action(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        affected_target_participant_id: UUID | None,
        signals: AggregatedSignals,
        action: ProtectionAction,
    ) -> UUID: ...

    async def apply_review_action(
        self,
        *,
        item_id: UUID,
        action: ReviewAction,
        actor_participant_id: UUID | None,
        source: str,
    ) -> bool: ...

    async def list_review_items(
        self, *, conversation_id: UUID
    ) -> list[ReviewItemRecord]: ...


def thresholds_from_settings(
    settings: Settings, safety_level: SafetyLevel | str = SafetyLevel.STANDARD
) -> SignalThresholds:
    """Scale operating-owner thresholds by the per-group safety level.

    Safety level never disables the hard boundaries; it only changes the
    sensitivity of content-free signal counting. RELAXED raises thresholds
    (fewer protections), STRICT lowers them (earlier protection).
    """

    level = SafetyLevel(str(safety_level))
    multiplier = {"strict": 0.5, "standard": 1.0, "relaxed": 1.5}[level.value]

    def scaled(value: int) -> int:
        return max(1, round(value * multiplier))

    return SignalThresholds(
        participant_refusals=scaled(settings.safety_threshold_participant_refusals),
        mention_frequency=scaled(settings.safety_threshold_mention_frequency),
        teasing_frequency=scaled(settings.safety_threshold_teasing_frequency),
        rate_limit_violations=scaled(settings.safety_threshold_rate_limit_violations),
        memory_extraction=scaled(settings.safety_threshold_memory_extraction),
        dangerous_instruction=scaled(settings.safety_threshold_dangerous_instruction),
        prompt_injection=scaled(settings.safety_threshold_prompt_injection),
        manipulation=scaled(settings.safety_threshold_manipulation),
    )


class SafetyModerationService:
    def __init__(
        self,
        settings: Settings,
        repository: SafetyModerationRepository,
    ) -> None:
        self._settings = settings
        self._repository = repository

    async def aggregate(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID | None,
        now: datetime | None = None,
    ) -> AggregatedSignals:
        since = (now or datetime.now(UTC)) - timedelta(
            seconds=self._settings.safety_signal_window_seconds
        )
        return await self._repository.aggregate_signals(
            conversation_id=conversation_id,
            participant_id=participant_id,
            since=since,
        )

    async def protection_state(self, participant_id: UUID) -> ProtectionState | None:
        return await self._repository.protection_state(participant_id)

    async def evaluate_and_enforce(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID | None,
        safety_level: SafetyLevel | str = SafetyLevel.STANDARD,
        now: datetime | None = None,
    ) -> ProtectionAction | None:
        """Run protective enforcement for one participant (FR-07).

        Deterministic and idempotent on repeated evaluation: protection is
        recorded once per sustained-signal window and reversed only through the
        review path. Returns the applied action, or None when no threshold is
        exceeded. Fail closed: repository errors surface rather than silently
        degrading the structural guard.
        """

        if not self._settings.safety_moderation_enabled or participant_id is None:
            return None
        signals = await self.aggregate(
            conversation_id=conversation_id,
            participant_id=participant_id,
            now=now,
        )
        thresholds = thresholds_from_settings(self._settings, safety_level)
        if evaluate_protection(signals, thresholds) is None:
            return None
        affected_target = signals.affected_target_participant_id
        if affected_target is not None and (
            signals.count(SafetySignalType.MENTION_FREQUENCY)
            >= thresholds.mention_frequency
            or signals.count(SafetySignalType.TEASING_FREQUENCY)
            >= thresholds.teasing_frequency
        ):
            await self._repository.protect(
                conversation_id=conversation_id,
                participant_id=affected_target,
                actor_participant_id=participant_id,
                source="protective_enforcement",
            )
        prior = await self._repository.protective_action_count(
            conversation_id=conversation_id,
            participant_id=participant_id,
            since=signals.since,
        )
        action = interaction_escalation(
            prior, self._settings.safety_pause_after_actions
        )
        await self._repository.record_protective_action(
            conversation_id=conversation_id,
            participant_id=participant_id,
            affected_target_participant_id=affected_target,
            signals=signals,
            action=action,
        )
        return action

    async def pause_or_restrict(
        self,
        *,
        conversation_id: UUID,
        participant_id: UUID,
        actor_participant_id: UUID | None,
        source: str,
    ) -> None:
        """Administrator/review request to pause or restrict behavior (FR-08)."""

        await self._repository.protect(
            conversation_id=conversation_id,
            participant_id=participant_id,
            actor_participant_id=actor_participant_id,
            source=source,
        )

    async def acknowledge(self, *, item_id: UUID) -> bool:
        return await self._repository.apply_review_action(
            item_id=item_id,
            action=ReviewAction.ACKNOWLEDGE,
            actor_participant_id=None,
            source="review_acknowledge",
        )

    async def escalate(self, *, item_id: UUID) -> bool:
        return await self._repository.apply_review_action(
            item_id=item_id,
            action=ReviewAction.ESCALATE,
            actor_participant_id=None,
            source="review_escalate",
        )

    async def restore(
        self, *, item_id: UUID, actor_participant_id: UUID | None
    ) -> bool:
        return await self._repository.apply_review_action(
            item_id=item_id,
            action=ReviewAction.RESTORE_TARGETING,
            actor_participant_id=actor_participant_id,
            source="review_restore_targeting",
        )

    async def pause(self, *, item_id: UUID, actor_participant_id: UUID | None) -> bool:
        return await self._repository.apply_review_action(
            item_id=item_id,
            action=ReviewAction.PAUSE_OR_RESTRICT,
            actor_participant_id=actor_participant_id,
            source="review_pause_or_restrict",
        )


def render_review_item_view(
    item_id: UUID,
    category: SafetySignalType,
    stage: str,
    status: ReviewItemStatus,
    outcome_counts: dict[str, int],
    protection_state: dict[str, object],
    created_at: datetime,
) -> dict[str, object]:
    """Content-free rendering of a review item (NFR-01/FR-08/FR-12).

    Opaque identifiers and counts only; never text, prompts, memories,
    usernames, or raw platform identifiers.
    """

    return {
        "id": str(item_id),
        "category": category.value,
        "stage": stage,
        "status": status.value,
        "outcome_counts": outcome_counts,
        "protection_state": protection_state,
        "created_at": created_at.isoformat(),
    }


def signal_counts_view(signals: AggregatedSignals) -> dict[str, object]:
    """Content-free aggregate rendering; never participant identifiers."""

    return {
        "conversation": str(signals.conversation_id),
        "since": signals.since.isoformat(),
        "counts": {
            signal_type.value: count
            for signal_type, count in sorted(signals.counts.items())
        },
    }
