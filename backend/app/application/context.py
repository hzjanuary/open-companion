"""Pure bounded conversation-context selection."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.application.conversation import TokenEstimator
from app.application.knowledge import ContextKnowledge


@dataclass(frozen=True, slots=True)
class ContextMessage:
    id: UUID
    conversation_id: UUID
    participant_id: UUID | None
    platform_thread_id: str | None
    text: str | None
    sent_at: datetime
    reply_to_message_id: UUID | None
    sender_display_name: str
    mention_allowed: bool
    teasing_allowed: bool
    privacy_deleted: bool = False
    protected: bool = False
    content_provenance: str | None = None
    media_caption: str | None = None


@dataclass(frozen=True, slots=True)
class ContextReply:
    """One locally authoritative, bounded conversational reference."""

    target_message_id: UUID
    participant_id: UUID | None
    sender_role: str
    sender_display_name: str
    text: str
    sent_at: datetime
    related_message_ids: tuple[UUID, ...] = ()
    response_plan_id: UUID | None = None
    truncated: bool = False
    content_provenance: str | None = None


class ReplyContextResolver(Protocol):
    async def resolve(
        self, current_message_id: UUID, *, now: datetime
    ) -> ContextReply | None: ...


@dataclass(frozen=True, slots=True)
class ContextMemory:
    """An explicitly stored fact safe to include as untrusted model context."""

    public_id: str
    content: str
    created_at: datetime
    creator_label: str


@dataclass(frozen=True, slots=True)
class ContextPersonalContext:
    """Explicit creator-private context for the current participant only."""

    public_id: str
    key: str
    content: str
    revision: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ContextSummary:
    """Derived, same-conversation history that remains untrusted context."""

    summary: str
    schema_version: str
    prompt_version: str
    source_ended_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationContext:
    current: ContextMessage
    reply_chain: tuple[ContextMessage, ...]
    recent_history: tuple[ContextMessage, ...]
    explicit_memories: tuple[ContextMemory, ...] = ()
    personal_context: tuple[ContextPersonalContext, ...] = ()
    historical_summary: ContextSummary | None = None
    knowledge: tuple[ContextKnowledge, ...] = ()
    reply_reference: ContextReply | None = None


def build_context(
    *,
    current: ContextMessage,
    candidates: tuple[ContextMessage, ...],
    now: datetime,
    recent_limit: int,
    reply_chain_depth: int,
    token_budget: int,
    character_limit: int,
    max_age_days: int,
    estimator: TokenEstimator,
    explicit_memories: tuple[ContextMemory, ...] = (),
    personal_context: tuple[ContextPersonalContext, ...] = (),
    memory_character_budget: int = 1200,
    personal_context_limit: int = 5,
    personal_context_character_budget: int = 600,
    historical_summary: ContextSummary | None = None,
    knowledge: tuple[ContextKnowledge, ...] = (),
    reply_reference: ContextReply | None = None,
) -> ConversationContext:
    """Select current, one typed reply reference, then bounded recent history."""

    allowed_after = now - timedelta(days=max_age_days)
    accepted: list[ContextMessage] = [current]
    used = _cost(current, character_limit, estimator)
    del reply_chain_depth  # Retained as a compatibility input; v1 is direct-only.

    selected_reply = reply_reference
    if selected_reply is not None:
        reply_cost = estimator.estimate(selected_reply.text[:character_limit])
        if selected_reply.sent_at < allowed_after or used + reply_cost > token_budget:
            selected_reply = None
        else:
            used += reply_cost

    summary = historical_summary
    if summary is not None:
        summary_cost = estimator.estimate(summary.summary[:character_limit])
        if used + summary_cost <= token_budget:
            used += summary_cost
        else:
            summary = None

    history: list[ContextMessage] = []
    excluded = {item.id for item in accepted}
    if selected_reply is not None:
        excluded.add(selected_reply.target_message_id)
        excluded.update(selected_reply.related_message_ids)
    for candidate in sorted(
        candidates, key=lambda item: (item.sent_at, str(item.id)), reverse=True
    ):
        if len(history) >= recent_limit:
            break
        if candidate.id in excluded or candidate.sent_at < allowed_after:
            continue
        if candidate.conversation_id != current.conversation_id:
            continue
        if candidate.platform_thread_id != current.platform_thread_id:
            continue
        if summary is not None and candidate.sent_at <= summary.source_ended_at:
            continue
        cost = _cost(candidate, character_limit, estimator)
        if used + cost > token_budget:
            continue
        history.append(candidate)
        used += cost
    selected_personal = _select_personal_context(
        personal_context,
        limit=personal_context_limit,
        character_budget=min(
            personal_context_character_budget, memory_character_budget
        ),
    )
    remaining_memory_budget = max(
        0,
        memory_character_budget - sum(len(item.content) for item in selected_personal),
    )
    return ConversationContext(
        current=current,
        reply_chain=(),
        recent_history=tuple(history),
        explicit_memories=_select_memories(explicit_memories, remaining_memory_budget),
        personal_context=selected_personal,
        historical_summary=summary,
        knowledge=knowledge,
        reply_reference=selected_reply,
    )


def _cost(
    message: ContextMessage, character_limit: int, estimator: TokenEstimator
) -> int:
    return estimator.estimate((message.text or "")[:character_limit]) + (
        estimator.estimate(message.media_caption) if message.media_caption else 0
    )


def _select_memories(
    memories: tuple[ContextMemory, ...], character_budget: int
) -> tuple[ContextMemory, ...]:
    """Keep a deterministic bounded prefix without consuming message-token budget."""

    selected: list[ContextMemory] = []
    used = 0
    for memory in memories:
        if not memory.content:
            continue
        cost = len(memory.content)
        if used + cost > character_budget:
            continue
        selected.append(memory)
        used += cost
    return tuple(selected)


def _select_personal_context(
    values: tuple[ContextPersonalContext, ...], *, limit: int, character_budget: int
) -> tuple[ContextPersonalContext, ...]:
    selected: list[ContextPersonalContext] = []
    used = 0
    for value in values:
        if len(selected) >= limit or not value.content:
            break
        cost = len(value.content)
        if used + cost > character_budget:
            continue
        selected.append(value)
        used += cost
    return tuple(selected)
