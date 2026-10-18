"""Closed deterministic evaluators over existing production policy seams."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.application.ambient import apply_ambient_post_policy
from app.application.context import (
    ContextMemory,
    ContextMessage,
    ContextPersonalContext,
    ContextReply,
    ContextSummary,
    ConversationContext,
    build_context,
)
from app.application.conversation import CharacterTokenEstimator
from app.application.model_provider import (
    GenerationRequest,
    ModelProvider,
    ProviderCapabilities,
    ProviderError,
    ProviderResult,
    ProviderUsage,
)
from app.application.outbound import (
    OutboundActionSpec,
    compile_outbound_actions,
    sequence_tail_blocked,
)
from app.application.planning_service import generate_validated_plan
from app.application.presence import (
    TELEGRAM_TYPING_MAX_CALLS,
    TELEGRAM_TYPING_MAX_LIFETIME_SECONDS,
    TELEGRAM_TYPING_REFRESH_SECONDS,
    telegram_typing_candidate,
)
from app.application.prompting import build_generation_request
from app.application.reactions import ReactionFacts, decide_reaction
from app.application.regeneration import (
    EditTargetFacts,
    choose_regeneration_presentation,
)
from app.application.response_plan import ResponsePlanCandidate, ResponsePlanPolicy
from app.application.scheduling import in_quiet_hours
from app.domain.ambient import ParticipationTrigger
from app.domain.media import MediaLimits
from app.domain.outbound import OutboundActionStatus
from app.domain.persistence import MessageDirection, MessageType, Platform
from app.domain.planning import (
    PlanReasonCode,
    ProviderErrorCategory,
    ProviderId,
    StickerIntent,
)
from app.domain.scheduling import ScheduleKind, SchedulePreferences
from app.evaluation.models import (
    EvalExecutionCase,
    EvalObservation,
    EvaluatorKind,
    SyntheticScope,
)
from app.infrastructure.telegram.media import normalize_media


class ScenarioEvaluator(Protocol):
    kind: ClassVar[EvaluatorKind]

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation: ...


def _stable_uuid(scenario_id: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"january-eval:{scenario_id}:{key}")


def _current_context(scenario: EvalExecutionCase) -> ConversationContext:
    now = datetime(2026, 1, 1, 12, tzinfo=UTC)
    current = ContextMessage(
        id=_stable_uuid(scenario.id, "current-message"),
        conversation_id=scenario.scope.conversation_id,
        participant_id=scenario.scope.participant_id,
        platform_thread_id=None,
        text=scenario.turns[-1].content,
        sent_at=now,
        reply_to_message_id=None,
        sender_display_name="Synthetic user",
        mention_allowed=True,
        teasing_allowed=False,
    )
    recent_history = tuple(
        ContextMessage(
            id=_stable_uuid(scenario.id, f"prior-turn:{index}"),
            conversation_id=scenario.scope.conversation_id,
            participant_id=(
                scenario.scope.participant_id if turn.role == "user" else None
            ),
            platform_thread_id=None,
            text=turn.content,
            sent_at=now - timedelta(minutes=len(scenario.turns) - index),
            reply_to_message_id=None,
            sender_display_name=(
                "Synthetic user" if turn.role == "user" else "Synthetic assistant"
            ),
            mention_allowed=True,
            teasing_allowed=False,
        )
        for index, turn in enumerate(scenario.turns[:-1])
    )
    return ConversationContext(
        current=current,
        reply_chain=(),
        recent_history=tuple(reversed(recent_history)),
    )


class PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider_outcome: Literal["success", "denied", "malformed", "timeout", "fallback"]
    candidate: dict[str, JsonValue] | None = None
    fallback_candidate: dict[str, JsonValue] | None = None
    text_limit: int = Field(default=240, ge=1, le=1000)
    personality_assistant_id: UUID | None = None


class _ScriptedProvider:
    capabilities = ProviderCapabilities(True, False, "max_tokens", True, True)

    def __init__(self, provider_id: ProviderId, values: list[object]) -> None:
        self.provider_id = provider_id
        self.model = "synthetic-eval-model"
        self._values = values
        self.calls = 0

    async def generate(self, request: GenerationRequest) -> ProviderResult:
        value = self._values[self.calls]
        self.calls += 1
        if isinstance(value, ProviderError):
            raise value
        return ProviderResult(
            provider=self.provider_id,
            model=self.model,
            structured_text=str(value),
            provider_request_id=None,
            usage=ProviderUsage(None, None, None),
            latency=timedelta(),
            finish_reason="stop",
        )

    async def aclose(self) -> None:
        return None


def _provider_error(
    category: ProviderErrorCategory, *, retryable: bool
) -> ProviderError:
    return ProviderError(
        category=category,
        provider=ProviderId.OLLAMA,
        model="synthetic-eval-model",
        retryable=retryable,
        operation="generate",
        summary="bounded synthetic provider outcome",
    )


def _candidate_json(value: dict[str, JsonValue] | None) -> str:
    if value is None:
        raise ValueError("planning success/fallback requires a candidate")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class PlanningEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.PLANNING

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = PlanningInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        if scenario.provider_mode != "mock":
            raise ValueError(
                "planning evaluator requires controlled mock provider mode"
            )
        personality_id = value.personality_assistant_id or scenario.scope.assistant_id
        if personality_id != scenario.scope.assistant_id:
            return _observation(
                scenario,
                should_respond=False,
                decision="foreign_personality_rejected",
                safety_outcome="silent",
                response_plan_valid=False,
            )

        if value.provider_outcome == "success":
            primary_values: list[object] = [_candidate_json(value.candidate)]
            fallback: ModelProvider | None = None
            transport_attempts, correction_attempts = 1, 0
        elif value.provider_outcome == "denied":
            primary_values = [
                _provider_error(ProviderErrorCategory.BUDGET_EXHAUSTED, retryable=False)
            ]
            fallback = None
            transport_attempts, correction_attempts = 1, 0
        elif value.provider_outcome == "malformed":
            primary_values = ["{}", "{}"]
            fallback = None
            transport_attempts, correction_attempts = 1, 1
        elif value.provider_outcome == "timeout":
            timeout = _provider_error(ProviderErrorCategory.TIMEOUT, retryable=True)
            primary_values = [timeout, timeout]
            fallback = None
            transport_attempts, correction_attempts = 2, 0
        else:
            primary_values = [
                _provider_error(ProviderErrorCategory.TRANSPORT, retryable=True)
            ]
            fallback = _ScriptedProvider(
                ProviderId.GROQ,
                [_candidate_json(value.fallback_candidate or value.candidate)],
            )
            transport_attempts, correction_attempts = 1, 0

        primary = _ScriptedProvider(ProviderId.OLLAMA, primary_values)
        context = _current_context(scenario)
        request = build_generation_request(
            planning_job_id=_stable_uuid(scenario.id, "planning-job"),
            context=context,
            prompt_version="ai-eval-prompt-v1",
            response_schema_version="response-plan-v2",
            maximum_output_tokens=256,
            conversation_type="private",
            response_mode="mention_only",
            effective_personality={"assistant_id": str(personality_id)},
        )

        async def no_wait(_: float) -> None:
            return None

        result = await generate_validated_plan(
            request,
            ResponsePlanPolicy(value.text_limit, frozenset(StickerIntent)),
            primary,
            fallback,
            transport_attempts,
            correction_attempts,
            sleep=no_wait,
        )
        candidate = result.candidate
        fallback_calls = (
            fallback.calls if isinstance(fallback, _ScriptedProvider) else 0
        )
        if candidate is not None:
            source = value.fallback_candidate or value.candidate or {}
            interaction = source.get("interaction")
            transformed = (
                isinstance(interaction, dict)
                and interaction.get("kind") == "teasing"
                and candidate.interaction.kind.value != "teasing"
            )
            return _observation(
                scenario,
                should_respond=candidate.should_respond,
                decision="response" if candidate.should_respond else "silence",
                origin=ParticipationTrigger.ADDRESSED.value,
                safety_outcome="transform" if transformed else "allow",
                response_plan_valid=True,
                response_length=len(candidate.text or ""),
                response_text=candidate.text,
                mock_provider_calls=primary.calls + fallback_calls,
                selected_context=(
                    "current",
                    *(
                        f"prior-turn-{index}"
                        for index in reversed(range(len(scenario.turns) - 1))
                    ),
                ),
            )
        decision = (
            "provider_denied"
            if result.provider_error is not None
            and result.provider_error.category == ProviderErrorCategory.BUDGET_EXHAUSTED
            else "invalid_output"
            if result.provider_error is not None
            and result.provider_error.category
            == ProviderErrorCategory.STRUCTURED_OUTPUT
            else "provider_timeout"
        )
        return _observation(
            scenario,
            should_respond=False,
            decision=decision,
            safety_outcome="silent",
            response_plan_valid=False,
            mock_provider_calls=primary.calls + fallback_calls,
        )


class ContextCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=1000)
    scope: SyntheticScope
    minutes_ago: int = Field(default=1, ge=1, le=100_000)
    thread: str | None = Field(default=None, max_length=64)


class MemoryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    key: str = Field(min_length=1, max_length=64)
    content: str = Field(min_length=1, max_length=500)
    scope: SyntheticScope
    kind: Literal["explicit", "personal"] = "explicit"
    recall_enabled: bool = True


class SummaryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    content: str = Field(min_length=1, max_length=1000)
    scope: SyntheticScope


class ContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    history: tuple[ContextCandidate, ...] = Field(default=(), max_length=30)
    memories: tuple[MemoryCandidate, ...] = Field(default=(), max_length=20)
    summary: SummaryCandidate | None = None
    recent_limit: int = Field(default=10, ge=0, le=20)
    token_budget: int = Field(default=1000, ge=1, le=8000)
    memory_character_budget: int = Field(default=1200, ge=0, le=1200)

    @model_validator(mode="after")
    def candidate_keys_are_unique(self) -> ContextInput:
        history_keys = [item.key for item in self.history]
        memory_keys = [item.key for item in self.memories]
        if len(history_keys) != len(set(history_keys)):
            raise ValueError("context history keys must be unique")
        if len(memory_keys) != len(set(memory_keys)):
            raise ValueError("memory candidate keys must be unique")
        return self


def _same_scope(left: SyntheticScope, right: SyntheticScope) -> bool:
    return left == right


class ContextEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.CONTEXT

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = ContextInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        current = _current_context(scenario).current
        history: list[ContextMessage] = []
        history_keys: dict[UUID, str] = {}
        for item in value.history:
            if not _same_scope(item.scope, scenario.scope):
                continue
            identifier = _stable_uuid(scenario.id, f"history:{item.key}")
            history_keys[identifier] = item.key
            history.append(
                ContextMessage(
                    id=identifier,
                    conversation_id=item.scope.conversation_id,
                    participant_id=item.scope.participant_id,
                    platform_thread_id=item.thread,
                    text=item.content,
                    sent_at=now - timedelta(minutes=item.minutes_ago),
                    reply_to_message_id=None,
                    sender_display_name="Synthetic context",
                    mention_allowed=True,
                    teasing_allowed=False,
                )
            )
        allowed_memories = [
            item
            for item in value.memories
            if _same_scope(item.scope, scenario.scope) and item.recall_enabled
        ]
        explicit = tuple(
            ContextMemory(item.key, item.content, now, "Synthetic user")
            for item in allowed_memories
            if item.kind == "explicit"
        )
        personal = tuple(
            ContextPersonalContext(item.key, "personal_note", item.content, 1, now)
            for item in allowed_memories
            if item.kind == "personal"
        )
        summary = (
            ContextSummary(
                value.summary.content,
                "conversation-summary-v1",
                "ai-eval-summary-v1",
                now - timedelta(minutes=60),
            )
            if value.summary is not None
            and _same_scope(value.summary.scope, scenario.scope)
            else None
        )
        selected = build_context(
            current=current,
            candidates=tuple(history),
            now=now,
            recent_limit=value.recent_limit,
            reply_chain_depth=0,
            token_budget=value.token_budget,
            character_limit=1000,
            max_age_days=30,
            estimator=CharacterTokenEstimator(),
            explicit_memories=explicit,
            personal_context=personal,
            memory_character_budget=value.memory_character_budget,
            historical_summary=summary,
        )
        selected_history = tuple(
            history_keys[item.id] for item in selected.recent_history
        )
        selected_memory = tuple(
            item.public_id for item in selected.personal_context
        ) + tuple(item.public_id for item in selected.explicit_memories)
        scope_by_key = {item.key: item.scope for item in value.history}
        scope_by_key.update({item.key: item.scope for item in value.memories})
        foreign_selected = any(
            not _same_scope(scope_by_key[key], scenario.scope)
            for key in (*selected_history, *selected_memory)
        )
        return _observation(
            scenario,
            decision="context_built",
            provenance=(
                "current_over_memory"
                if selected_memory
                else "summary_and_raw"
                if selected.historical_summary is not None
                else "current_and_raw"
            ),
            selected_context=("current", *selected_history),
            selected_memory=selected_memory,
            foreign_data_selected=foreign_selected,
        )


class TelegramUXInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    reply_key: str | None = Field(default=None, min_length=1, max_length=64)
    reply_text: str | None = Field(default=None, min_length=1, max_length=2000)
    reply_scope: SyntheticScope | None = None
    reply_role: Literal["user", "assistant"] = "user"
    target_available: bool = True
    target_erased: bool = False
    already_recent: bool = False
    trigger: Literal["addressed", "ambient", "scheduled"] = "addressed"
    also_scheduled: bool = False
    response_text: str | None = Field(default=None, min_length=1, max_length=13600)
    response_characters: int = Field(default=0, ge=0, le=13600)
    predecessor_statuses: tuple[OutboundActionStatus, ...] = Field(
        default=(), max_length=4
    )


class TelegramUXEvaluator:
    """Exercise reply, split, and predecessor policy without external I/O."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.TELEGRAM_UX

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = TelegramUXInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        now = datetime(2026, 1, 1, 12, tzinfo=UTC)
        current = _current_context(scenario).current
        target_id = _stable_uuid(scenario.id, "reply-target")
        scope_matches = value.reply_scope is None or _same_scope(
            value.reply_scope, scenario.scope
        )
        reply = (
            ContextReply(
                target_message_id=target_id,
                participant_id=(
                    scenario.scope.participant_id
                    if value.reply_role == "user"
                    else None
                ),
                sender_role=value.reply_role,
                sender_display_name="Synthetic reply target",
                text=(value.reply_text or "reference")[:1200],
                sent_at=now - timedelta(minutes=1),
                truncated=len(value.reply_text or "reference") > 1200,
            )
            if value.reply_key is not None
            and value.target_available
            and not value.target_erased
            and scope_matches
            else None
        )
        recent = (
            (
                ContextMessage(
                    id=target_id,
                    conversation_id=scenario.scope.conversation_id,
                    participant_id=scenario.scope.participant_id,
                    platform_thread_id=None,
                    text=value.reply_text or "reference",
                    sent_at=now - timedelta(minutes=1),
                    reply_to_message_id=None,
                    sender_display_name="Synthetic reply target",
                    mention_allowed=True,
                    teasing_allowed=False,
                ),
            )
            if value.already_recent and scope_matches
            else ()
        )
        context = build_context(
            current=current,
            candidates=recent,
            now=now,
            recent_limit=10,
            reply_chain_depth=1,
            token_budget=8000,
            character_limit=2000,
            max_age_days=30,
            estimator=CharacterTokenEstimator(),
            reply_reference=reply,
        )
        selected_context = ["current"]
        if context.reply_reference is not None and value.reply_key is not None:
            selected_context.append(value.reply_key)
        if context.recent_history and value.reply_key is not None:
            selected_context.append(value.reply_key)

        response_text = value.response_text or (
            "x" * value.response_characters if value.response_characters else None
        )
        actions: tuple[OutboundActionSpec, ...] = ()
        reply_target: str | None = None
        if response_text is not None:
            candidate = ResponsePlanCandidate(
                should_respond=True,
                reason_code=PlanReasonCode.ANSWER,
                text=response_text,
                reply_to_message_id=current.id,
                confidence=1,
            )
            policy = ResponsePlanPolicy(
                13600,
                frozenset(),
                reply_to_current=value.trigger == "addressed",
            )
            approved = policy.apply(candidate, context)
            actions = compile_outbound_actions(
                _stable_uuid(scenario.id, "response-plan"), approved
            )
            reply_target = (
                "current_first_only"
                if len(actions) > 1
                and actions[0].reply_to_message_id == current.id
                and all(action.reply_to_message_id is None for action in actions[1:])
                else "current"
                if actions and actions[0].reply_to_message_id == current.id
                else "none"
            )

        tail_blocked = (
            sequence_tail_blocked(value.predecessor_statuses)
            if value.predecessor_statuses
            else None
        )
        if value.also_scheduled and response_text is not None:
            scheduled = ResponsePlanPolicy(
                13600, frozenset(), reply_to_current=False
            ).apply(candidate, context)
            scheduled_actions = compile_outbound_actions(
                _stable_uuid(scenario.id, "scheduled-plan"), scheduled
            )
            if any(
                action.reply_to_message_id is not None for action in scheduled_actions
            ):
                reply_target = "unexpected"
            decision = "ambient_proactive_replyless"
        elif value.predecessor_statuses:
            decision = "tail_blocked" if tail_blocked else "tail_ready"
        elif response_text is not None and len(actions) > 1:
            decision = "response_split"
        elif response_text is not None:
            decision = "reply_targeted" if reply_target == "current" else "replyless"
        else:
            decision = (
                "reply_deduplicated"
                if reply is not None
                and value.already_recent
                and selected_context.count(value.reply_key or "") == 1
                else "reply_resolved"
                if reply is not None
                else "reply_unresolved"
            )
        action_text = "".join(action.text or "" for action in actions)
        return _observation(
            scenario,
            should_respond=True if response_text is not None else None,
            decision=decision,
            origin=value.trigger,
            provenance=(value.reply_role if reply is not None else "none"),
            selected_context=tuple(selected_context),
            foreign_data_selected=False,
            reply_target=reply_target,
            chunk_count=len(actions) if response_text is not None else None,
            chunk_order_preserved=(
                action_text == response_text if response_text is not None else None
            ),
            tail_blocked=tail_blocked,
        )


class AmbientInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    candidate: dict[str, JsonValue]
    minimum_confidence: float = Field(ge=0, le=1)


class AmbientEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.AMBIENT

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = AmbientInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        candidate = ResponsePlanCandidate.model_validate_json(
            json.dumps(value.candidate), strict=True
        )
        result, reason = apply_ambient_post_policy(candidate, value.minimum_confidence)
        return _observation(
            scenario,
            should_respond=result.should_respond,
            decision=reason.value,
            origin=ParticipationTrigger.AMBIENT.value,
            safety_outcome="allow" if result.should_respond else "silent",
            response_plan_valid=True,
            response_length=len(result.text or ""),
            response_text=result.text,
        )


class SchedulingInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: ScheduleKind
    consent: bool = False
    authority_active: bool = True
    stale: bool = False
    inactivity_hours: int = Field(default=24, ge=0, le=10_000)
    required_inactivity_hours: int = Field(default=24, ge=1, le=168)
    quiet_hours_enabled: bool = False
    quiet_start_minute: int = Field(default=1320, ge=0, lt=1440)
    quiet_end_minute: int = Field(default=480, ge=0, lt=1440)
    current_minute: int = Field(default=720, ge=0, lt=1440)
    authority_scope: SyntheticScope | None = None
    preference_scope: SyntheticScope | None = None


class SchedulingEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.SCHEDULING

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = SchedulingInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        moment = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
            minutes=value.current_minute
        )
        preferences = SchedulePreferences(
            timezone_name="UTC",
            quiet_hours_enabled=value.quiet_hours_enabled,
            quiet_start_minute=value.quiet_start_minute,
            quiet_end_minute=value.quiet_end_minute,
            revision=1,
        )
        if value.authority_scope is not None and not _same_scope(
            value.authority_scope, scenario.scope
        ):
            decision = "foreign_schedule"
        elif value.preference_scope is not None and not _same_scope(
            value.preference_scope, scenario.scope
        ):
            decision = "foreign_preferences"
        elif not value.authority_active:
            decision = "inactive_authority"
        elif value.stale:
            decision = "stale"
        elif value.kind == ScheduleKind.CHECK_IN and not value.consent:
            decision = "no_consent"
        elif (
            value.kind == ScheduleKind.CHECK_IN
            and value.inactivity_hours < value.required_inactivity_hours
        ):
            decision = "recent_activity"
        elif value.kind == ScheduleKind.CHECK_IN and in_quiet_hours(
            moment, preferences
        ):
            decision = "quiet_hours"
        else:
            decision = "eligible"
        return _observation(
            scenario,
            should_respond=decision == "eligible",
            decision=decision,
            origin=ParticipationTrigger.SCHEDULED.value,
            safety_outcome="allow" if decision == "eligible" else "silent",
        )


class MediaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    payload: dict[str, Any]
    transcript_available: bool = False
    provider_capable: bool = True


class MediaEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.MEDIA

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = MediaInput.model_validate_json(json.dumps(scenario.input), strict=True)
        media_type, attachment, failure = normalize_media(value.payload, MediaLimits())
        if attachment is not None and not value.provider_capable:
            decision = "capability_denied"
            provenance = "media_metadata_only"
        elif failure is not None:
            decision = failure.value
            provenance = "unsupported_fallback"
        elif attachment is not None and media_type == "photo":
            decision = "accepted"
            provenance = "photo_current_turn"
        elif attachment is not None and media_type in {"voice", "audio"}:
            decision = (
                "accepted" if value.transcript_available else "transcript_missing"
            )
            provenance = (
                f"{media_type}_transcript"
                if value.transcript_available
                else "media_metadata_only"
            )
        else:
            decision = "no_media"
            provenance = "none"
        return _observation(
            scenario,
            should_respond=decision == "accepted",
            decision=decision,
            provenance=provenance,
            safety_outcome="allow" if decision == "accepted" else "silent",
            response_plan_valid=None,
            selected_context=(
                ("current_caption",)
                if media_type == "photo" and bool(scenario.turns[-1].content)
                else ()
            ),
        )


class KnowledgeCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    key: str = Field(min_length=1, max_length=64)
    tenant_id: UUID
    assistant_id: UUID
    score: float = Field(ge=-1, le=1)
    base_active: bool = True
    current_revision: bool = True
    revision_ready: bool = True
    deleted: bool = False
    content: str = Field(min_length=1, max_length=1200)


class KnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    assistant_enabled: bool = True
    active_base_available: bool = True
    provider_allowed: bool = True
    derived_index_available: bool = True
    minimum_score: float | None = Field(default=None, ge=-1, le=1)
    candidates: tuple[KnowledgeCandidateInput, ...] = Field(default=(), max_length=20)


class KnowledgeEvaluator:
    """Expectation-free simulation of the closed retrieval eligibility contract."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.KNOWLEDGE

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = KnowledgeInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        if not value.assistant_enabled:
            return _observation(scenario, decision="assistant_disabled")
        if not value.active_base_available:
            return _observation(scenario, decision="knowledge_base_disabled")
        if not value.provider_allowed:
            return _observation(scenario, decision="provider_denied")
        if not value.derived_index_available:
            return _observation(
                scenario,
                decision="derived_index_unavailable",
                embedding_calls=1,
                qdrant_calls=1,
            )
        eligible = [
            item
            for item in value.candidates
            if item.tenant_id == scenario.scope.tenant_id
            and item.assistant_id == scenario.scope.assistant_id
            and item.base_active
            and item.current_revision
            and item.revision_ready
            and not item.deleted
            and (value.minimum_score is None or item.score >= value.minimum_score)
        ]
        eligible.sort(key=lambda item: (-item.score, item.key))
        selected: list[KnowledgeCandidateInput] = []
        used = 0
        for item in eligible:
            if len(selected) >= 6 or used + len(item.content) > 6000:
                continue
            selected.append(item)
            used += len(item.content)
        keys = tuple(item.key for item in selected)
        return _observation(
            scenario,
            decision="knowledge_selected" if keys else "no_eligible_knowledge",
            embedding_calls=1,
            qdrant_calls=1,
            selected_knowledge=keys,
            knowledge_provenance=keys,
            foreign_data_selected=False,
            knowledge_as_instruction=False,
        )


class PresenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    platform: Literal["telegram", "zalo"] = "telegram"
    trigger: Literal["addressed", "ambient", "proactive", "command"] = "addressed"
    telegram_enabled: bool = True
    authority_active: bool = True
    safety_allowed: bool = True
    provider_admitted: bool = True
    provider_generation: bool = True
    recovered: bool = False
    terminal: bool = False
    provider_seconds: int = Field(default=1, ge=0, le=120)
    presence_failure: bool = False


class PresenceEvaluator:
    kind: ClassVar[EvaluatorKind] = EvaluatorKind.PRESENCE

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = PresenceInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        addressed = value.trigger == "addressed"
        candidate = telegram_typing_candidate(
            Platform(value.platform),
            ParticipationTrigger.ADDRESSED
            if addressed
            else ParticipationTrigger.AMBIENT,
            value.telegram_enabled,
        )
        eligible = (
            candidate
            and value.authority_active
            and value.safety_allowed
            and value.provider_admitted
            and value.provider_generation
            and not value.recovered
            and not value.terminal
        )
        attempts = 0
        if eligible:
            if value.presence_failure:
                attempts = 1
            else:
                refresh_window = min(
                    value.provider_seconds,
                    int(TELEGRAM_TYPING_MAX_LIFETIME_SECONDS) - 1,
                )
                attempts = min(
                    TELEGRAM_TYPING_MAX_CALLS,
                    1 + int(refresh_window // TELEGRAM_TYPING_REFRESH_SECONDS),
                )
        decision = (
            "presence_failed"
            if eligible and value.presence_failure
            else "presence_active"
            if eligible
            else "presence_absent"
        )
        return _observation(
            scenario,
            decision=decision,
            presence_attempts=attempts,
            presence_after_terminal=0,
            presence_for_silent_flow=(
                attempts
                if not value.provider_generation or not value.safety_allowed
                else 0
            ),
            presence_for_proactive_flow=(
                attempts if value.trigger == "proactive" else 0
            ),
            heartbeat_bound=attempts <= TELEGRAM_TYPING_MAX_CALLS,
        )


class RegenerationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    target: Literal[
        "same_scope",
        "unknown",
        "foreign_tenant",
        "foreign_assistant",
        "foreign_conversation",
        "foreign_connection",
    ] = "same_scope"
    reply_based: bool = True
    target_erased: bool = False
    prior_regenerations: int = Field(default=0, ge=0, le=3)
    provider_admitted: bool = True
    old_memory_key: str | None = Field(default=None, min_length=1, max_length=64)
    old_memory_enabled: bool = True
    current_memory_key: str | None = Field(default=None, min_length=1, max_length=64)
    old_knowledge_key: str | None = Field(default=None, min_length=1, max_length=64)
    old_knowledge_enabled: bool = True
    current_knowledge_key: str | None = Field(default=None, min_length=1, max_length=64)
    original_action_count: int = Field(default=1, ge=1, le=5)
    original_kind: Literal["text", "sticker"] = "text"
    original_delivered: bool = True
    platform_message_id_known: bool = True
    ambiguous_prior_edit: bool = False
    deterministically_editable: bool = True
    regenerated_text_characters: int = Field(default=24, ge=1, le=13600)
    regenerated_sticker: bool = False
    edit_outcome: Literal["success", "rejected", "timeout", "not_modified"] = "success"
    presence_stopped_before_presentation: bool = True


class RegenerationEvaluator:
    """Offline regeneration authority and presentation state-machine contract."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.REGENERATION

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = RegenerationInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        same_scope = value.target == "same_scope"
        target_authorized = (
            value.reply_based
            and same_scope
            and not value.target_erased
            and value.prior_regenerations < 3
        )
        selected_memory = tuple(
            key
            for key, enabled in (
                (value.old_memory_key, value.old_memory_enabled),
                (value.current_memory_key, True),
            )
            if key is not None and enabled
        )
        selected_knowledge = tuple(
            key
            for key, enabled in (
                (value.old_knowledge_key, value.old_knowledge_enabled),
                (value.current_knowledge_key, True),
            )
            if key is not None and enabled
        )
        ordinal = value.prior_regenerations + 1 if target_authorized else None
        generated = target_authorized and value.provider_admitted
        provider_attempts = 1 if generated else 0
        presentation_mode: str | None = None
        edit_calls = 0
        send_calls = 0
        fallback_created = False
        if generated:
            candidate = ResponsePlanCandidate(
                should_respond=True,
                reason_code=PlanReasonCode.ANSWER,
                text="x" * value.regenerated_text_characters,
                reply_to_message_id=_stable_uuid(scenario.id, "source-message"),
                sticker_intent=(
                    StickerIntent.CELEBRATE if value.regenerated_sticker else None
                ),
                confidence=1,
            )
            presentation = choose_regeneration_presentation(
                candidate,
                EditTargetFacts(
                    exactly_one_delivered_text=(
                        value.original_action_count == 1
                        and value.original_kind == "text"
                        and value.original_delivered
                    ),
                    platform_message_id_known=value.platform_message_id_known,
                    same_authority=same_scope,
                    target_content_available=not value.target_erased,
                    ambiguous_prior_edit=value.ambiguous_prior_edit,
                    deterministically_editable=value.deterministically_editable,
                ),
            )
            presentation_mode = presentation.value
            if presentation_mode == "edit_existing":
                edit_calls = 1
                if value.edit_outcome == "rejected":
                    fallback_created = True
                    send_calls = 1
            else:
                send_calls = 1

        decision = (
            "target_unknown"
            if value.target == "unknown" or not value.reply_based
            else "foreign_target_rejected"
            if not same_scope
            else "source_erased"
            if value.target_erased
            else "limit_reached"
            if value.prior_regenerations >= 3
            else "provider_denied"
            if not value.provider_admitted
            else "regeneration_generated"
        )
        return _observation(
            scenario,
            should_respond=generated,
            decision=decision,
            provenance="current_authority" if target_authorized else "none",
            selected_memory=selected_memory if target_authorized else (),
            selected_knowledge=selected_knowledge if target_authorized else (),
            regeneration_authorized=target_authorized,
            governed_provider_attempts=provider_attempts,
            root_response_id=("root-source-response" if target_authorized else None),
            regeneration_ordinal=ordinal,
            presentation_mode=presentation_mode,
            edit_calls=edit_calls,
            send_calls=send_calls,
            fallback_created=fallback_created,
            stale_memory_included=(
                value.old_memory_key is not None
                and not value.old_memory_enabled
                and value.old_memory_key in selected_memory
            ),
            stale_knowledge_included=(
                value.old_knowledge_key is not None
                and not value.old_knowledge_enabled
                and value.old_knowledge_key in selected_knowledge
            ),
            foreign_target_used=not same_scope and target_authorized,
            presence_attempts=1 if generated else 0,
            presence_after_terminal=(
                0 if not generated or value.presence_stopped_before_presentation else 1
            ),
        )


class ReactionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    platform: Literal["telegram", "zalo"] = "telegram"
    trigger: Literal["addressed", "ambient", "scheduled"] = "addressed"
    flow: Literal[
        "ordinary", "command", "regeneration", "proactive", "reaction_update"
    ] = "ordinary"
    message_type: Literal["text", "photo", "voice"] = "text"
    text: str | None = Field(default=None, max_length=1000)
    authority: Literal[
        "active",
        "disabled_assistant_connection",
        "foreign_scope",
        "redacted",
    ] = "active"
    safety_allowed: bool = True
    api_outcome: Literal["success", "failure"] = "success"
    duplicate_update_count: int = Field(default=1, ge=1, le=2)
    response_ready: bool = True


class ReactionEvaluator:
    """Offline reaction policy, attempt bound, and failure-isolation contract."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.REACTION

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = ReactionInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        trigger = ParticipationTrigger(value.trigger)
        message_type = MessageType(value.message_type)
        ordinary = value.flow == "ordinary"
        active_authority = value.authority == "active"
        decision = decide_reaction(
            ReactionFacts(
                platform=Platform(value.platform),
                trigger=trigger,
                direction=MessageDirection.INCOMING,
                message_type=message_type,
                text=value.text,
                message_eligible=value.flow != "reaction_update",
                user_authored=value.flow != "reaction_update",
                content_available=value.authority != "redacted",
                ordinary_flow=ordinary,
                authority_active=active_authority,
                safety_allowed=value.safety_allowed,
            )
        )
        selected = decision.kind is not None
        attempts = 1 if selected else 0
        forbidden = (
            value.flow != "ordinary"
            or trigger != ParticipationTrigger.ADDRESSED
            or not active_authority
            or not value.safety_allowed
        )
        return _observation(
            scenario,
            decision="reaction_selected" if selected else "reaction_none",
            reaction_allowed=selected,
            reaction_kind=decision.kind.value if decision.kind is not None else "none",
            reaction_attempts=attempts,
            reaction_retries=0,
            provider_calls_from_reaction=0,
            response_continues=value.response_ready,
            reaction_on_forbidden_flow=selected and forbidden,
            reaction_loop_created=value.flow == "reaction_update" and attempts > 0,
        )


class VoiceInput(BaseModel):
    """Synthetic facts for the offline SPEC-038 presentation contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    target: Literal[
        "assistant_text",
        "no_reply",
        "user_message",
        "foreign_assistant",
        "foreign_tenant",
        "foreign_conversation",
        "erased",
    ]
    source: Literal["root_plan", "split_plan", "regenerated_plan"] = "root_plan"
    source_characters: int = Field(default=100, ge=1, le=5000)
    admission: Literal["allowed", "denied"] = "allowed"
    tts_result: Literal["success", "failure", "oversize", "uncertain"] = "success"
    telegram_result: Literal[
        "not_attempted", "success", "retryable_then_success", "ambiguous"
    ] = "success"
    duplicate_updates: int = Field(default=1, ge=1, le=2)


class VoiceEvaluator:
    """Expectation-independent arithmetic over synthetic voice workflow facts."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.VOICE

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = VoiceInput.model_validate_json(json.dumps(scenario.input), strict=True)
        target_authorized = value.target == "assistant_text"
        tts_admitted = (
            target_authorized
            and value.source_characters <= 4000
            and value.admission == "allowed"
        )
        tts_calls = int(tts_admitted)
        artifact_valid = tts_admitted and value.tts_result == "success"
        artifact_count = int(artifact_valid)
        voice_actions = artifact_count
        if not voice_actions or value.telegram_result == "not_attempted":
            telegram_attempts = 0
        elif value.telegram_result == "retryable_then_success":
            telegram_attempts = 2
        else:
            telegram_attempts = 1
        voice_source = (
            "whole_logical_response"
            if target_authorized and value.source == "split_plan"
            else "regenerated_plan"
            if target_authorized and value.source == "regenerated_plan"
            else "root_plan"
            if target_authorized
            else "none"
        )
        decision = (
            "target_denied"
            if not target_authorized
            else "source_too_long"
            if value.source_characters > 4000
            else "admission_denied"
            if value.admission == "denied"
            else "provider_uncertain"
            if value.tts_result == "uncertain"
            else "provider_failed"
            if value.tts_result in {"failure", "oversize"}
            else "voice_queued"
        )
        return _observation(
            scenario,
            decision=decision,
            voice_target_authorized=target_authorized,
            tts_provider_calls=tts_calls,
            tts_admitted=tts_admitted,
            voice_artifact_count=artifact_count,
            voice_artifact_valid=artifact_valid,
            send_voice_actions=voice_actions,
            duplicate_voice_actions=max(0, voice_actions - 1),
            voice_source=voice_source,
            whole_logical_response=(target_authorized and value.source == "split_plan"),
            source_text_rewritten=False,
            telegram_voice_attempts=telegram_attempts,
            ambiguous_duplicate_send=(
                value.telegram_result == "ambiguous" and telegram_attempts > 1
            ),
            normal_generation_calls=0,
            memory_writes=0,
            semantic_index_writes=0,
            knowledge_writes=0,
            summary_writes=0,
            media_downloads=0,
            transcription_calls=0,
            presence_attempts=0,
            reaction_attempts=0,
        )


class FeedbackInput(BaseModel):
    """Synthetic facts for the offline SPEC-039 feedback contract."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    target: Literal[
        "assistant_response",
        "split_response",
        "regenerated_response",
        "voice_presentation",
        "no_reply",
        "user_message",
        "foreign_tenant",
        "foreign_assistant",
        "foreign_conversation",
        "erased",
    ]
    value: Literal["helpful", "unhelpful"]
    current_value: Literal["none", "helpful", "unhelpful"] = "none"
    current_revision: int = Field(default=0, ge=0, le=10)
    duplicate_updates: int = Field(default=1, ge=1, le=2)

    @model_validator(mode="after")
    def current_shape(self) -> FeedbackInput:
        if (self.current_value == "none") != (self.current_revision == 0):
            raise ValueError("feedback current value/revision shape is invalid")
        return self


class FeedbackEvaluator:
    """Expectation-independent feedback authorization and revision arithmetic."""

    kind: ClassVar[EvaluatorKind] = EvaluatorKind.FEEDBACK

    async def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation:
        value = FeedbackInput.model_validate_json(
            json.dumps(scenario.input), strict=True
        )
        authorized = value.target in {
            "assistant_response",
            "split_response",
            "regenerated_response",
            "voice_presentation",
        }
        same = authorized and value.current_value == value.value
        limited = authorized and not same and value.current_revision >= 10
        changed = authorized and not same and not limited
        revision = value.current_revision + int(changed)
        state = value.value if changed else value.current_value
        decision = (
            "target_unavailable"
            if not authorized
            else "no_change"
            if same
            else "limit_reached"
            if limited
            else "saved"
        )
        return _observation(
            scenario,
            decision=decision,
            feedback_target_authorized=authorized,
            feedback_value=value.value,
            feedback_current_state=state,
            feedback_event_delta=int(changed),
            feedback_revision=revision,
            feedback_no_change=same,
            feedback_in_prompt=False,
            normal_generation_calls=0,
            tts_provider_calls=0,
            embedding_calls=0,
            transcription_calls=0,
            vision_calls=0,
            qdrant_calls=0,
            memory_writes=0,
            semantic_index_writes=0,
            knowledge_writes=0,
            summary_writes=0,
            voice_artifact_count=0,
            reaction_attempts=0,
            presence_attempts=0,
            external_provider_calls=0,
            telegram_calls=0,
        )


def _observation(
    scenario: EvalExecutionCase,
    **values: object,
) -> EvalObservation:
    base: dict[str, object] = {
        "tenant_id": scenario.scope.tenant_id,
        "assistant_id": scenario.scope.assistant_id,
    }
    base.update(values)
    return EvalObservation.model_validate(base, strict=True)


EvaluatorRegistry = dict[EvaluatorKind, ScenarioEvaluator]
Sleep = Callable[[float], Awaitable[None]]
