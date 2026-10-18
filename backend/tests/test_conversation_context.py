from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.application.context import (
    ContextMemory,
    ContextMessage,
    ContextPersonalContext,
    ContextReply,
    ContextSummary,
    build_context,
)
from app.application.conversation import CharacterTokenEstimator


def message(
    *,
    conversation_id: UUID,
    minutes: int,
    text: str = "hello",
    thread: str | None = None,
    reply_to: UUID | None = None,
) -> ContextMessage:
    identifier = uuid4()
    return ContextMessage(
        id=identifier,
        conversation_id=conversation_id,
        participant_id=uuid4(),
        platform_thread_id=thread,
        text=text,
        sent_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minutes),
        reply_to_message_id=reply_to,
        sender_display_name="Tester",
        mention_allowed=True,
        teasing_allowed=False,
    )


def test_context_keeps_one_direct_reply_and_bounded_thread_history() -> None:
    conversation_id = uuid4()
    root = message(conversation_id=conversation_id, minutes=1, text="root")
    reply = message(
        conversation_id=conversation_id, minutes=2, text="reply", reply_to=root.id
    )
    current = message(
        conversation_id=conversation_id, minutes=3, text="current", reply_to=reply.id
    )
    same_thread = message(conversation_id=conversation_id, minutes=4, text="recent")
    other_thread = message(
        conversation_id=conversation_id, minutes=5, text="other", thread="topic"
    )
    result = build_context(
        current=current,
        candidates=(root, reply, same_thread, other_thread),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=2,
        token_budget=20,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        reply_reference=ContextReply(
            target_message_id=reply.id,
            participant_id=reply.participant_id,
            sender_role="user",
            sender_display_name=reply.sender_display_name,
            text=reply.text or "",
            sent_at=reply.sent_at,
        ),
    )
    assert result.current == current
    assert result.reply_chain == ()
    assert result.reply_reference is not None
    assert result.reply_reference.target_message_id == reply.id
    assert result.recent_history == (same_thread, root)


def test_reply_reference_is_deduplicated_and_cannot_starve_current_turn() -> None:
    conversation_id = uuid4()
    target = message(conversation_id=conversation_id, minutes=1, text="target")
    current = message(conversation_id=conversation_id, minutes=2, text="current")
    reply = ContextReply(
        target_message_id=target.id,
        participant_id=target.participant_id,
        sender_role="user",
        sender_display_name="Tester",
        text="target",
        sent_at=target.sent_at,
    )
    included = build_context(
        current=current,
        candidates=(target,),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=1,
        token_budget=20,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        reply_reference=reply,
    )
    assert included.reply_reference == reply
    assert included.recent_history == ()
    starved = build_context(
        current=current,
        candidates=(target,),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=1,
        token_budget=2,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        reply_reference=reply,
    )
    assert starved.current == current
    assert starved.reply_reference is None


def test_context_does_not_include_cross_conversation_or_over_budget_content() -> None:
    conversation_id = uuid4()
    current = message(conversation_id=conversation_id, minutes=3, text="current")
    foreign = message(conversation_id=uuid4(), minutes=4, text="foreign")
    oversized = message(conversation_id=conversation_id, minutes=5, text="x" * 100)
    result = build_context(
        current=current,
        candidates=(foreign, oversized),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=0,
        token_budget=3,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
    )
    assert result.recent_history == ()


def test_context_keeps_explicit_memories_in_deterministic_separate_budget() -> None:
    conversation_id = uuid4()
    current = message(conversation_id=conversation_id, minutes=3, text="current")
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    result = build_context(
        current=current,
        candidates=(),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=0,
        token_budget=1,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        explicit_memories=(
            ContextMemory("later", "second", created_at + timedelta(minutes=1), "Mai"),
            ContextMemory("first", "first", created_at, "Nam"),
            ContextMemory("too-long", "x" * 10, created_at, "Lan"),
        ),
        memory_character_budget=11,
    )
    assert [item.public_id for item in result.explicit_memories] == ["later", "first"]


def test_personal_context_has_precedence_and_combined_bounded_budget() -> None:
    conversation_id = uuid4()
    current = message(conversation_id=conversation_id, minutes=3, text="current")
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    result = build_context(
        current=current,
        candidates=(),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=0,
        token_budget=1,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        personal_context=(
            ContextPersonalContext("Personal1", "preferred_name", "Mai", 2, created_at),
            ContextPersonalContext(
                "Personal2", "personal_note", "123456", 1, created_at
            ),
        ),
        explicit_memories=(
            ContextMemory("Explicit1", "1234", created_at, "Mai"),
            ContextMemory("Explicit2", "12345", created_at, "Mai"),
        ),
        personal_context_limit=1,
        personal_context_character_budget=6,
        memory_character_budget=8,
    )
    assert [item.public_id for item in result.personal_context] == ["Personal1"]
    assert [item.public_id for item in result.explicit_memories] == ["Explicit1"]
    assert (
        sum(len(item.content) for item in result.personal_context)
        + sum(len(item.content) for item in result.explicit_memories)
        <= 8
    )


def test_context_uses_one_summary_before_non_overlapping_raw_history() -> None:
    conversation_id = uuid4()
    older = message(conversation_id=conversation_id, minutes=1, text="older")
    recent = message(conversation_id=conversation_id, minutes=3, text="recent")
    current = message(conversation_id=conversation_id, minutes=4, text="current")
    result = build_context(
        current=current,
        candidates=(older, recent),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        recent_limit=2,
        reply_chain_depth=0,
        token_budget=20,
        character_limit=100,
        max_age_days=30,
        estimator=CharacterTokenEstimator(),
        historical_summary=ContextSummary(
            summary="compressed older history",
            schema_version="conversation-summary-v1",
            prompt_version="test",
            source_ended_at=older.sent_at,
        ),
    )
    assert result.historical_summary is not None
    assert result.recent_history == (recent,)
