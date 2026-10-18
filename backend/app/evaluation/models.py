"""Strict fixture, observation, and result models for SPEC-032."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)

SUITE_SCHEMA_VERSION = "ai-eval-suite-v1"
SCENARIO_SCHEMA_VERSION = "ai-eval-scenario-v1"
RUN_SCHEMA_VERSION = "ai-eval-run-v1"
MAX_TURNS = 6

StableId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=96,
        pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)+$",
    ),
]


class EvalStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"
    ERROR = "ERROR"


class EvaluatorKind(StrEnum):
    PLANNING = "planning_contract"
    CONTEXT = "context_contract"
    AMBIENT = "ambient_contract"
    SCHEDULING = "scheduling_contract"
    MEDIA = "media_contract"
    KNOWLEDGE = "knowledge_contract"
    TELEGRAM_UX = "telegram_ux_contract"
    PRESENCE = "presence_contract"
    REGENERATION = "regeneration_contract"
    REACTION = "reaction_contract"
    VOICE = "voice_contract"
    FEEDBACK = "feedback_contract"


class EvalCategory(StrEnum):
    PERSONALITY = "personality"
    CONTEXT = "context"
    MEMORY = "memory"
    SAFETY = "safety"
    AMBIENT = "ambient"
    SCHEDULING = "scheduling"
    MEDIA = "media"
    MULTI_TENANT = "multi_tenant"
    PLANNING = "planning"
    KNOWLEDGE = "knowledge"
    REACTION = "reaction"
    VOICE = "voice"
    FEEDBACK = "feedback"


class QualityDimension(StrEnum):
    RELEVANCE = "relevance"
    INSTRUCTION_FOLLOWING = "instruction_following"
    PERSONALITY_ADHERENCE = "personality_adherence"
    CONTEXT_USE = "context_use"
    CLARITY = "clarity"
    CONCISION = "concision"
    NON_REPETITION = "non_repetition"
    SOCIAL_APPROPRIATENESS = "social_appropriateness"


class HardGate(StrEnum):
    MUST_RESPOND = "must_respond"
    MUST_NOT_RESPOND = "must_not_respond"
    DECISION = "decision"
    ORIGIN = "origin"
    SAFETY_OUTCOME = "safety_outcome"
    PROVENANCE = "provenance"
    RESPONSE_PLAN_VALID = "response_plan_valid"
    MAX_RESPONSE_LENGTH = "max_response_length"
    FORBIDDEN_PHRASE = "forbidden_phrase"
    PROVIDER_CALLS = "external_provider_calls"
    TELEGRAM_CALLS = "telegram_calls"
    MEMORY_WRITES = "memory_writes"
    SEMANTIC_INDEX_WRITES = "semantic_index_writes"
    SCHEDULE_WRITES = "schedule_writes"
    ROUTING_MUTATIONS = "routing_mutations"
    RAW_MEDIA_PERSISTED = "raw_media_persisted"
    TELEGRAM_CREDENTIAL_REQUIRED = "telegram_credential_required"
    LIVE_PROVIDER_REQUESTED = "live_provider_requested"
    FOREIGN_DATA_SELECTED = "foreign_data_selected"
    TENANT_SCOPE = "tenant_scope"
    ASSISTANT_SCOPE = "assistant_scope"
    INCLUDED_CONTEXT = "included_context"
    EXCLUDED_CONTEXT = "excluded_context"
    INCLUDED_MEMORY = "included_memory"
    EXCLUDED_MEMORY = "excluded_memory"
    INCLUDED_KNOWLEDGE = "included_knowledge"
    EXCLUDED_KNOWLEDGE = "excluded_knowledge"
    KNOWLEDGE_WRITES = "knowledge_writes"
    QDRANT_CALLS = "qdrant_calls"
    EMBEDDING_CALLS = "embedding_calls"
    KNOWLEDGE_AS_INSTRUCTION = "knowledge_as_instruction"
    KNOWLEDGE_PROVENANCE = "knowledge_provenance"
    REPLY_TARGET = "reply_target"
    CHUNK_COUNT = "chunk_count"
    CHUNK_ORDER_PRESERVED = "chunk_order_preserved"
    TAIL_BLOCKED = "tail_blocked"
    PRESENCE_ATTEMPTS = "presence_attempts"
    PRESENCE_AFTER_TERMINAL = "presence_after_terminal"
    PRESENCE_FOR_SILENT_FLOW = "presence_for_silent_flow"
    PRESENCE_FOR_PROACTIVE_FLOW = "presence_for_proactive_flow"
    HEARTBEAT_BOUND = "heartbeat_bound"
    REGENERATION_AUTHORIZED = "regeneration_authorized"
    GOVERNED_PROVIDER_ATTEMPTS = "governed_provider_attempts"
    ROOT_RESPONSE_ID = "root_response_id"
    REGENERATION_ORDINAL = "regeneration_ordinal"
    PRESENTATION_MODE = "presentation_mode"
    EDIT_CALLS = "edit_calls"
    SEND_CALLS = "send_calls"
    FALLBACK_CREATED = "fallback_created"
    STALE_MEMORY_INCLUDED = "stale_memory_included"
    STALE_KNOWLEDGE_INCLUDED = "stale_knowledge_included"
    FOREIGN_TARGET_USED = "foreign_target_used"
    REACTION_ALLOWED = "reaction_allowed"
    REACTION_KIND = "reaction_kind"
    REACTION_ATTEMPTS = "reaction_attempts"
    REACTION_RETRIES = "reaction_retries"
    PROVIDER_CALLS_FROM_REACTION = "provider_calls_from_reaction"
    RESPONSE_CONTINUES = "response_continues"
    REACTION_ON_FORBIDDEN_FLOW = "reaction_on_forbidden_flow"
    REACTION_LOOP_CREATED = "reaction_loop_created"
    VOICE_TARGET_AUTHORIZED = "voice_target_authorized"
    TTS_PROVIDER_CALLS = "tts_provider_calls"
    TTS_ADMITTED = "tts_admitted"
    VOICE_ARTIFACT_COUNT = "voice_artifact_count"
    VOICE_ARTIFACT_VALID = "voice_artifact_valid"
    SEND_VOICE_ACTIONS = "send_voice_actions"
    DUPLICATE_VOICE_ACTIONS = "duplicate_voice_actions"
    VOICE_SOURCE = "voice_source"
    WHOLE_LOGICAL_RESPONSE = "whole_logical_response"
    SOURCE_TEXT_REWRITTEN = "source_text_rewritten"
    TELEGRAM_VOICE_ATTEMPTS = "telegram_voice_attempts"
    AMBIGUOUS_DUPLICATE_SEND = "ambiguous_duplicate_send"
    NORMAL_GENERATION_CALLS = "normal_generation_calls"
    SUMMARY_WRITES = "summary_writes"
    MEDIA_DOWNLOADS = "media_downloads"
    TRANSCRIPTION_CALLS = "transcription_calls"
    VISION_CALLS = "vision_calls"
    FEEDBACK_TARGET_AUTHORIZED = "feedback_target_authorized"
    FEEDBACK_VALUE = "feedback_value"
    FEEDBACK_CURRENT_STATE = "feedback_current_state"
    FEEDBACK_EVENT_DELTA = "feedback_event_delta"
    FEEDBACK_REVISION = "feedback_revision"
    FEEDBACK_NO_CHANGE = "feedback_no_change"
    FEEDBACK_IN_PROMPT = "feedback_in_prompt"


class FixtureProvenanceKind(StrEnum):
    REPOSITORY_SYNTHETIC = "repository_synthetic"
    MANUALLY_SANITIZED = "manually_sanitized"


class SyntheticScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tenant_id: UUID
    assistant_id: UUID
    connection_id: UUID
    conversation_id: UUID
    participant_id: UUID


class FixtureProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: FixtureProvenanceKind
    source: str = Field(min_length=3, max_length=200)


class EvalTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: Literal["user", "assistant", "system_fixture"]
    content: str = Field(min_length=1, max_length=1000)


class HardExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    gate: HardGate
    expected: JsonValue

    @model_validator(mode="after")
    def expected_matches_gate(self) -> HardExpectation:
        boolean_gates = {
            HardGate.MUST_RESPOND,
            HardGate.MUST_NOT_RESPOND,
            HardGate.RESPONSE_PLAN_VALID,
            HardGate.RAW_MEDIA_PERSISTED,
            HardGate.TELEGRAM_CREDENTIAL_REQUIRED,
            HardGate.LIVE_PROVIDER_REQUESTED,
            HardGate.FOREIGN_DATA_SELECTED,
            HardGate.KNOWLEDGE_AS_INSTRUCTION,
            HardGate.CHUNK_ORDER_PRESERVED,
            HardGate.TAIL_BLOCKED,
            HardGate.HEARTBEAT_BOUND,
            HardGate.REGENERATION_AUTHORIZED,
            HardGate.FALLBACK_CREATED,
            HardGate.STALE_MEMORY_INCLUDED,
            HardGate.STALE_KNOWLEDGE_INCLUDED,
            HardGate.FOREIGN_TARGET_USED,
            HardGate.REACTION_ALLOWED,
            HardGate.RESPONSE_CONTINUES,
            HardGate.REACTION_ON_FORBIDDEN_FLOW,
            HardGate.REACTION_LOOP_CREATED,
            HardGate.VOICE_TARGET_AUTHORIZED,
            HardGate.TTS_ADMITTED,
            HardGate.VOICE_ARTIFACT_VALID,
            HardGate.WHOLE_LOGICAL_RESPONSE,
            HardGate.SOURCE_TEXT_REWRITTEN,
            HardGate.AMBIGUOUS_DUPLICATE_SEND,
            HardGate.FEEDBACK_TARGET_AUTHORIZED,
            HardGate.FEEDBACK_NO_CHANGE,
            HardGate.FEEDBACK_IN_PROMPT,
        }
        count_gates = {
            HardGate.MAX_RESPONSE_LENGTH,
            HardGate.PROVIDER_CALLS,
            HardGate.TELEGRAM_CALLS,
            HardGate.MEMORY_WRITES,
            HardGate.SEMANTIC_INDEX_WRITES,
            HardGate.SCHEDULE_WRITES,
            HardGate.ROUTING_MUTATIONS,
            HardGate.KNOWLEDGE_WRITES,
            HardGate.QDRANT_CALLS,
            HardGate.EMBEDDING_CALLS,
            HardGate.CHUNK_COUNT,
            HardGate.PRESENCE_ATTEMPTS,
            HardGate.PRESENCE_AFTER_TERMINAL,
            HardGate.PRESENCE_FOR_SILENT_FLOW,
            HardGate.PRESENCE_FOR_PROACTIVE_FLOW,
            HardGate.GOVERNED_PROVIDER_ATTEMPTS,
            HardGate.REGENERATION_ORDINAL,
            HardGate.EDIT_CALLS,
            HardGate.SEND_CALLS,
            HardGate.REACTION_ATTEMPTS,
            HardGate.REACTION_RETRIES,
            HardGate.PROVIDER_CALLS_FROM_REACTION,
            HardGate.TTS_PROVIDER_CALLS,
            HardGate.VOICE_ARTIFACT_COUNT,
            HardGate.SEND_VOICE_ACTIONS,
            HardGate.DUPLICATE_VOICE_ACTIONS,
            HardGate.TELEGRAM_VOICE_ATTEMPTS,
            HardGate.NORMAL_GENERATION_CALLS,
            HardGate.SUMMARY_WRITES,
            HardGate.MEDIA_DOWNLOADS,
            HardGate.TRANSCRIPTION_CALLS,
            HardGate.VISION_CALLS,
            HardGate.FEEDBACK_EVENT_DELTA,
            HardGate.FEEDBACK_REVISION,
        }
        list_gates = {
            HardGate.INCLUDED_CONTEXT,
            HardGate.EXCLUDED_CONTEXT,
            HardGate.INCLUDED_MEMORY,
            HardGate.EXCLUDED_MEMORY,
            HardGate.INCLUDED_KNOWLEDGE,
            HardGate.EXCLUDED_KNOWLEDGE,
            HardGate.KNOWLEDGE_PROVENANCE,
        }
        if self.gate in boolean_gates and type(self.expected) is not bool:
            raise ValueError(f"{self.gate.value} expects a boolean")
        if (
            self.gate
            in {
                HardGate.MUST_RESPOND,
                HardGate.MUST_NOT_RESPOND,
            }
            and self.expected is not True
        ):
            raise ValueError(f"{self.gate.value} must be asserted as true")
        if self.gate in count_gates and (
            type(self.expected) is not int or self.expected < 0
        ):
            raise ValueError(f"{self.gate.value} expects a non-negative integer")
        if self.gate in list_gates and not (
            isinstance(self.expected, list)
            and all(
                isinstance(item, str) and 1 <= len(item) <= 64 for item in self.expected
            )
            and len(self.expected) == len(set(self.expected))
        ):
            raise ValueError(f"{self.gate.value} expects unique bounded strings")
        if self.gate not in boolean_gates | count_gates | list_gates and not (
            isinstance(self.expected, str) and 1 <= len(self.expected) <= 200
        ):
            raise ValueError(f"{self.gate.value} expects a bounded string")
        return self


class RubricDimension(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    dimension: QualityDimension
    definition: str = Field(min_length=8, max_length=400)
    weight: int = Field(default=1, ge=1, le=4)


class EvalRubric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    threshold: float = Field(ge=0, le=4)
    dimensions: tuple[RubricDimension, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> EvalRubric:
        values = [item.dimension for item in self.dimensions]
        if len(values) != len(set(values)):
            raise ValueError("rubric dimensions must be unique")
        return self


class EvalExecutionCase(BaseModel):
    """Expectation-free input handed to deterministic scenario drivers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: StableId
    scope: SyntheticScope
    provider_mode: Literal["disabled", "mock"]
    turns: tuple[EvalTurn, ...]
    input: dict[str, JsonValue]


class EvalScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["ai-eval-scenario-v1"]
    id: StableId
    category: EvalCategory
    capability: StableId
    tags: tuple[StableId, ...] = Field(default=(), max_length=12)
    scope: SyntheticScope
    provenance: FixtureProvenance
    evaluator: EvaluatorKind
    provider_mode: Literal["disabled", "mock"] = "disabled"
    turns: tuple[EvalTurn, ...] = Field(min_length=1, max_length=MAX_TURNS)
    input: dict[str, JsonValue]
    hard_expectations: tuple[HardExpectation, ...] = Field(min_length=1, max_length=24)
    rubric: EvalRubric | None = None

    @field_validator("tags")
    @classmethod
    def tags_are_unique(cls, value: tuple[StableId, ...]) -> tuple[StableId, ...]:
        if len(value) != len(set(value)):
            raise ValueError("scenario tags must be unique")
        return value

    @model_validator(mode="after")
    def expectations_are_consistent(self) -> EvalScenario:
        gates = [item.gate for item in self.hard_expectations]
        if len(gates) != len(set(gates)):
            raise ValueError("hard expectation gates must be unique")
        if {
            HardGate.MUST_RESPOND,
            HardGate.MUST_NOT_RESPOND,
        }.issubset(gates):
            raise ValueError("scenario cannot both require response and silence")
        return self

    def execution_case(self) -> EvalExecutionCase:
        return EvalExecutionCase(
            id=self.id,
            scope=self.scope,
            provider_mode=self.provider_mode,
            turns=self.turns,
            input=self.input,
        )


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["ai-eval-suite-v1"]
    suite_id: StableId
    suite_version: int = Field(ge=1)
    default_soft_threshold: float = Field(ge=0, le=4)
    scenarios: tuple[EvalScenario, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def scenario_ids_are_unique(self) -> EvalSuite:
        values = [scenario.id for scenario in self.scenarios]
        if len(values) != len(set(values)):
            raise ValueError("scenario IDs must be unique")
        return self


class EvalObservation(BaseModel):
    """Objective driver output. Expectations are never passed to drivers."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    should_respond: bool | None = None
    decision: str | None = Field(default=None, max_length=96)
    origin: str | None = Field(default=None, max_length=64)
    safety_outcome: str | None = Field(default=None, max_length=64)
    provenance: str | None = Field(default=None, max_length=96)
    response_plan_valid: bool | None = None
    response_length: int | None = Field(default=None, ge=0)
    response_text: str | None = Field(default=None, exclude=True, repr=False)
    external_provider_calls: int = Field(default=0, ge=0)
    mock_provider_calls: int = Field(default=0, ge=0)
    telegram_calls: int = Field(default=0, ge=0)
    memory_writes: int = Field(default=0, ge=0)
    semantic_index_writes: int = Field(default=0, ge=0)
    schedule_writes: int = Field(default=0, ge=0)
    routing_mutations: int = Field(default=0, ge=0)
    knowledge_writes: int = Field(default=0, ge=0)
    qdrant_calls: int = Field(default=0, ge=0)
    embedding_calls: int = Field(default=0, ge=0)
    knowledge_as_instruction: bool = False
    raw_media_persisted: bool = False
    telegram_credential_required: bool = False
    live_provider_requested: bool = False
    foreign_data_selected: bool = False
    tenant_id: UUID
    assistant_id: UUID
    selected_context: tuple[str, ...] = ()
    selected_memory: tuple[str, ...] = ()
    selected_knowledge: tuple[str, ...] = ()
    knowledge_provenance: tuple[str, ...] = ()
    reply_target: str | None = Field(default=None, max_length=64)
    chunk_count: int | None = Field(default=None, ge=0, le=5)
    chunk_order_preserved: bool | None = None
    tail_blocked: bool | None = None
    presence_attempts: int = Field(default=0, ge=0)
    presence_after_terminal: int = Field(default=0, ge=0)
    presence_for_silent_flow: int = Field(default=0, ge=0)
    presence_for_proactive_flow: int = Field(default=0, ge=0)
    heartbeat_bound: bool | None = None
    regeneration_authorized: bool | None = None
    governed_provider_attempts: int = Field(default=0, ge=0)
    root_response_id: str | None = Field(default=None, max_length=96)
    regeneration_ordinal: int | None = Field(default=None, ge=1, le=3)
    presentation_mode: str | None = Field(default=None, max_length=32)
    edit_calls: int = Field(default=0, ge=0)
    send_calls: int = Field(default=0, ge=0)
    fallback_created: bool = False
    stale_memory_included: bool = False
    stale_knowledge_included: bool = False
    foreign_target_used: bool = False
    reaction_allowed: bool = False
    reaction_kind: str = Field(default="none", max_length=32)
    reaction_attempts: int = Field(default=0, ge=0, le=1)
    reaction_retries: int = Field(default=0, ge=0)
    provider_calls_from_reaction: int = Field(default=0, ge=0)
    response_continues: bool = True
    reaction_on_forbidden_flow: bool = False
    reaction_loop_created: bool = False
    voice_target_authorized: bool = False
    tts_provider_calls: int = Field(default=0, ge=0, le=1)
    tts_admitted: bool = False
    voice_artifact_count: int = Field(default=0, ge=0, le=1)
    voice_artifact_valid: bool = False
    send_voice_actions: int = Field(default=0, ge=0, le=1)
    duplicate_voice_actions: int = Field(default=0, ge=0)
    voice_source: str = Field(default="none", max_length=64)
    whole_logical_response: bool = False
    source_text_rewritten: bool = False
    telegram_voice_attempts: int = Field(default=0, ge=0, le=2)
    ambiguous_duplicate_send: bool = False
    normal_generation_calls: int = Field(default=0, ge=0)
    summary_writes: int = Field(default=0, ge=0)
    media_downloads: int = Field(default=0, ge=0)
    transcription_calls: int = Field(default=0, ge=0)
    vision_calls: int = Field(default=0, ge=0)
    feedback_target_authorized: bool = False
    feedback_value: str = Field(default="none", max_length=16)
    feedback_current_state: str = Field(default="none", max_length=16)
    feedback_event_delta: int = Field(default=0, ge=0, le=1)
    feedback_revision: int = Field(default=0, ge=0, le=10)
    feedback_no_change: bool = False
    feedback_in_prompt: bool = False


class EvalHardGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    gate: HardGate
    status: Literal[EvalStatus.PASS, EvalStatus.FAIL]
    expected: str = Field(max_length=200)
    observed: str = Field(max_length=200)


class EvalDimensionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    dimension: QualityDimension
    status: EvalStatus
    score: float | None = Field(default=None, ge=0, le=4)
    reason: str = Field(min_length=1, max_length=240)


class JudgeScore(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    dimension: QualityDimension
    score: float = Field(ge=0, le=4)
    reason: str = Field(min_length=1, max_length=240)


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    judge_version: StableId
    scores: tuple[JudgeScore, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> JudgeOutput:
        dimensions = [item.dimension for item in self.scores]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("judge dimensions must be unique")
        return self


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    suite_id: StableId
    suite_version: int = Field(ge=1)
    scenario_id: StableId
    category: EvalCategory
    evaluator: EvaluatorKind
    status: EvalStatus
    hard_gates: tuple[EvalHardGateResult, ...]
    dimensions: tuple[EvalDimensionResult, ...]
    normalized_score: float | None = Field(default=None, ge=0, le=4)
    soft_threshold: float | None = Field(default=None, ge=0, le=4)
    failure_reason: str | None = Field(default=None, max_length=240)
    duration: Literal["not_measured"] = "not_measured"


class EvalRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal["ai-eval-run-v1"] = "ai-eval-run-v1"
    suite_id: StableId
    suite_version: int
    status: EvalStatus
    results: tuple[EvalResult, ...]
    counts: dict[EvalStatus, int]
    judge: str = Field(default="disabled", min_length=3, max_length=96)
