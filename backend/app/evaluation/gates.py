"""Objective hard-gate evaluation, isolated from execution and scoring."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pydantic import JsonValue

from app.evaluation.models import (
    EvalHardGateResult,
    EvalObservation,
    EvalStatus,
    HardExpectation,
    HardGate,
)

type Observed = bool | int | str | tuple[str, ...] | None


def evaluate_hard_gates(
    expectations: tuple[HardExpectation, ...], observation: EvalObservation
) -> tuple[EvalHardGateResult, ...]:
    """Evaluate every declared contract in stable fixture order."""
    return tuple(_evaluate(expectation, observation) for expectation in expectations)


def _evaluate(
    expectation: HardExpectation, observation: EvalObservation
) -> EvalHardGateResult:
    gate = expectation.gate
    expected = expectation.expected
    observed: Observed
    passed: bool

    exact: dict[HardGate, Callable[[EvalObservation], Observed]] = {
        HardGate.DECISION: lambda item: item.decision,
        HardGate.ORIGIN: lambda item: item.origin,
        HardGate.SAFETY_OUTCOME: lambda item: item.safety_outcome,
        HardGate.PROVENANCE: lambda item: item.provenance,
        HardGate.RESPONSE_PLAN_VALID: lambda item: item.response_plan_valid,
        HardGate.PROVIDER_CALLS: lambda item: item.external_provider_calls,
        HardGate.TELEGRAM_CALLS: lambda item: item.telegram_calls,
        HardGate.MEMORY_WRITES: lambda item: item.memory_writes,
        HardGate.SEMANTIC_INDEX_WRITES: lambda item: item.semantic_index_writes,
        HardGate.SCHEDULE_WRITES: lambda item: item.schedule_writes,
        HardGate.ROUTING_MUTATIONS: lambda item: item.routing_mutations,
        HardGate.KNOWLEDGE_WRITES: lambda item: item.knowledge_writes,
        HardGate.QDRANT_CALLS: lambda item: item.qdrant_calls,
        HardGate.EMBEDDING_CALLS: lambda item: item.embedding_calls,
        HardGate.KNOWLEDGE_AS_INSTRUCTION: (lambda item: item.knowledge_as_instruction),
        HardGate.RAW_MEDIA_PERSISTED: lambda item: item.raw_media_persisted,
        HardGate.TELEGRAM_CREDENTIAL_REQUIRED: (
            lambda item: item.telegram_credential_required
        ),
        HardGate.LIVE_PROVIDER_REQUESTED: lambda item: item.live_provider_requested,
        HardGate.FOREIGN_DATA_SELECTED: lambda item: item.foreign_data_selected,
        HardGate.TENANT_SCOPE: lambda item: str(item.tenant_id),
        HardGate.ASSISTANT_SCOPE: lambda item: str(item.assistant_id),
        HardGate.REPLY_TARGET: lambda item: item.reply_target,
        HardGate.CHUNK_COUNT: lambda item: item.chunk_count,
        HardGate.CHUNK_ORDER_PRESERVED: lambda item: item.chunk_order_preserved,
        HardGate.TAIL_BLOCKED: lambda item: item.tail_blocked,
        HardGate.PRESENCE_ATTEMPTS: lambda item: item.presence_attempts,
        HardGate.PRESENCE_AFTER_TERMINAL: lambda item: item.presence_after_terminal,
        HardGate.PRESENCE_FOR_SILENT_FLOW: (lambda item: item.presence_for_silent_flow),
        HardGate.PRESENCE_FOR_PROACTIVE_FLOW: (
            lambda item: item.presence_for_proactive_flow
        ),
        HardGate.HEARTBEAT_BOUND: lambda item: item.heartbeat_bound,
        HardGate.REGENERATION_AUTHORIZED: lambda item: item.regeneration_authorized,
        HardGate.GOVERNED_PROVIDER_ATTEMPTS: (
            lambda item: item.governed_provider_attempts
        ),
        HardGate.ROOT_RESPONSE_ID: lambda item: item.root_response_id,
        HardGate.REGENERATION_ORDINAL: lambda item: item.regeneration_ordinal,
        HardGate.PRESENTATION_MODE: lambda item: item.presentation_mode,
        HardGate.EDIT_CALLS: lambda item: item.edit_calls,
        HardGate.SEND_CALLS: lambda item: item.send_calls,
        HardGate.FALLBACK_CREATED: lambda item: item.fallback_created,
        HardGate.STALE_MEMORY_INCLUDED: lambda item: item.stale_memory_included,
        HardGate.STALE_KNOWLEDGE_INCLUDED: lambda item: item.stale_knowledge_included,
        HardGate.FOREIGN_TARGET_USED: lambda item: item.foreign_target_used,
        HardGate.REACTION_ALLOWED: lambda item: item.reaction_allowed,
        HardGate.REACTION_KIND: lambda item: item.reaction_kind,
        HardGate.REACTION_ATTEMPTS: lambda item: item.reaction_attempts,
        HardGate.REACTION_RETRIES: lambda item: item.reaction_retries,
        HardGate.PROVIDER_CALLS_FROM_REACTION: (
            lambda item: item.provider_calls_from_reaction
        ),
        HardGate.RESPONSE_CONTINUES: lambda item: item.response_continues,
        HardGate.REACTION_ON_FORBIDDEN_FLOW: (
            lambda item: item.reaction_on_forbidden_flow
        ),
        HardGate.REACTION_LOOP_CREATED: lambda item: item.reaction_loop_created,
        HardGate.VOICE_TARGET_AUTHORIZED: (lambda item: item.voice_target_authorized),
        HardGate.TTS_PROVIDER_CALLS: lambda item: item.tts_provider_calls,
        HardGate.TTS_ADMITTED: lambda item: item.tts_admitted,
        HardGate.VOICE_ARTIFACT_COUNT: lambda item: item.voice_artifact_count,
        HardGate.VOICE_ARTIFACT_VALID: lambda item: item.voice_artifact_valid,
        HardGate.SEND_VOICE_ACTIONS: lambda item: item.send_voice_actions,
        HardGate.DUPLICATE_VOICE_ACTIONS: lambda item: item.duplicate_voice_actions,
        HardGate.VOICE_SOURCE: lambda item: item.voice_source,
        HardGate.WHOLE_LOGICAL_RESPONSE: (lambda item: item.whole_logical_response),
        HardGate.SOURCE_TEXT_REWRITTEN: lambda item: item.source_text_rewritten,
        HardGate.TELEGRAM_VOICE_ATTEMPTS: (lambda item: item.telegram_voice_attempts),
        HardGate.AMBIGUOUS_DUPLICATE_SEND: (lambda item: item.ambiguous_duplicate_send),
        HardGate.NORMAL_GENERATION_CALLS: lambda item: item.normal_generation_calls,
        HardGate.SUMMARY_WRITES: lambda item: item.summary_writes,
        HardGate.MEDIA_DOWNLOADS: lambda item: item.media_downloads,
        HardGate.TRANSCRIPTION_CALLS: lambda item: item.transcription_calls,
        HardGate.VISION_CALLS: lambda item: item.vision_calls,
        HardGate.FEEDBACK_TARGET_AUTHORIZED: (
            lambda item: item.feedback_target_authorized
        ),
        HardGate.FEEDBACK_VALUE: lambda item: item.feedback_value,
        HardGate.FEEDBACK_CURRENT_STATE: lambda item: item.feedback_current_state,
        HardGate.FEEDBACK_EVENT_DELTA: lambda item: item.feedback_event_delta,
        HardGate.FEEDBACK_REVISION: lambda item: item.feedback_revision,
        HardGate.FEEDBACK_NO_CHANGE: lambda item: item.feedback_no_change,
        HardGate.FEEDBACK_IN_PROMPT: lambda item: item.feedback_in_prompt,
    }
    if gate == HardGate.MUST_RESPOND:
        observed = observation.should_respond
        passed = observed is True
    elif gate == HardGate.MUST_NOT_RESPOND:
        observed = observation.should_respond
        passed = observed is False
    elif gate == HardGate.MAX_RESPONSE_LENGTH:
        observed = observation.response_length
        limit = cast(int, expected)
        passed = observed is not None and observed <= limit
    elif gate == HardGate.FORBIDDEN_PHRASE:
        phrase = cast(str, expected)
        observed = (
            "absent"
            if phrase.casefold() not in (observation.response_text or "").casefold()
            else "present"
        )
        passed = observed == "absent"
    elif gate in {
        HardGate.INCLUDED_CONTEXT,
        HardGate.EXCLUDED_CONTEXT,
        HardGate.INCLUDED_MEMORY,
        HardGate.EXCLUDED_MEMORY,
        HardGate.INCLUDED_KNOWLEDGE,
        HardGate.EXCLUDED_KNOWLEDGE,
        HardGate.KNOWLEDGE_PROVENANCE,
    }:
        expected_items = tuple(cast(list[str], expected))
        selected = observation.selected_context
        if gate in {HardGate.INCLUDED_MEMORY, HardGate.EXCLUDED_MEMORY}:
            selected = observation.selected_memory
        elif gate in {
            HardGate.INCLUDED_KNOWLEDGE,
            HardGate.EXCLUDED_KNOWLEDGE,
        }:
            selected = observation.selected_knowledge
        elif gate == HardGate.KNOWLEDGE_PROVENANCE:
            selected = observation.knowledge_provenance
        observed = selected
        passed = (
            selected == expected_items
            if gate == HardGate.KNOWLEDGE_PROVENANCE
            else all(item in selected for item in expected_items)
            if gate
            in {
                HardGate.INCLUDED_CONTEXT,
                HardGate.INCLUDED_MEMORY,
                HardGate.INCLUDED_KNOWLEDGE,
                HardGate.KNOWLEDGE_PROVENANCE,
            }
            else all(item not in selected for item in expected_items)
        )
    else:
        observed = exact[gate](observation)
        passed = observed == expected

    return EvalHardGateResult(
        gate=gate,
        status=EvalStatus.PASS if passed else EvalStatus.FAIL,
        expected=_expected_summary(gate, expected),
        observed=_bounded(observed),
    )


def _expected_summary(gate: HardGate, expected: JsonValue) -> str:
    if gate == HardGate.FORBIDDEN_PHRASE:
        return "configured phrase absent"
    if gate == HardGate.MAX_RESPONSE_LENGTH:
        return f"at most {expected}"
    if gate == HardGate.MUST_RESPOND:
        return "respond"
    if gate == HardGate.MUST_NOT_RESPOND:
        return "silence"
    return _bounded(expected)


def _bounded(value: object) -> str:
    if value is None:
        return "not observed"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, tuple | list):
        rendered = ",".join(str(item) for item in value) or "none"
    else:
        rendered = str(value)
    return rendered[:200]
