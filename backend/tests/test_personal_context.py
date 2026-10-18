"""Pure SPEC-027 personal-context validation proof."""

import asyncio
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest

from app.application.memory import MemoryValidationError, normalize_personal_context
from app.domain.persistence import (
    MemoryKind,
    MemoryScope,
    MemoryVisibility,
    PersonalContextKey,
)


def test_personal_context_normalization_is_explicit_and_bounded() -> None:
    draft = normalize_personal_context("preferred_name", "  Mai\tNguyen  ")
    assert draft.context_key == PersonalContextKey.PREFERRED_NAME
    assert draft.content == "Mai Nguyen"
    assert draft.kind == MemoryKind.PERSONAL_CONTEXT
    assert draft.scope == MemoryScope.PRIVATE_CONVERSATION
    assert draft.visibility == MemoryVisibility.CREATOR_ONLY


@pytest.mark.parametrize(
    ("key", "content"),
    [
        ("unknown", "value"),
        ("preferred_name", ""),
        ("preferred_name", "x" * 301),
        ("personal_note", "hidden\x00value"),
    ],
)
def test_personal_context_rejects_unknown_unbounded_or_control_content(
    key: str, content: str
) -> None:
    with pytest.raises(MemoryValidationError):
        normalize_personal_context(key, content)


@pytest.mark.parametrize(
    ("arguments", "method", "outcome", "code"),
    [
        ("", "status_for_participant", "", "memory_summary"),
        ("list", "active_for_conversation", "", "memory_summary"),
        ("remember explicit fact", "create", "created", "memory_saved"),
        (
            "context add preferred_name Mai",
            "create_personal_context",
            "created",
            "memory_context_saved",
        ),
        ("update abcdefgh 1 corrected", "update_owned", "updated", "memory_updated"),
        ("delete abcdefgh 1", "delete_owned", "deleted", "memory_deleted"),
        ("clear_mine confirm", "clear_owned", "cleared", "memory_cleared"),
        ("recall status", "status_for_participant", "", "memory_summary"),
        ("recall on", "set_recall", "enabled", "memory_recall_enabled"),
        ("recall off", "set_recall", "disabled", "memory_recall_disabled"),
    ],
)
def test_memory_command_handler_is_deterministic_without_provider_io(
    monkeypatch: pytest.MonkeyPatch,
    arguments: str,
    method: str,
    outcome: str,
    code: str,
) -> None:
    from app.application.commands import parse_command
    from app.core.config import Settings
    from app.domain.persistence import ConversationType
    from app.infrastructure.database.memory import (
        MemoryMutationResult,
        MemoryStatusSummary,
        SqlAlchemyMemoryRepository,
    )
    from app.infrastructure.database.models import (
        AssistantModel,
        ConversationModel,
        MemoryItemModel,
        ParticipantModel,
        TelegramCommandJobModel,
    )
    from app.infrastructure.model_providers import (
        GeminiProvider,
        OllamaProvider,
        OpenAICompatibleProvider,
    )
    from app.infrastructure.telemetry import InMemoryMetricsRecorder
    from app.runtime.telegram_command_worker import _handle_memory_command

    # A provider/network call must fail, even if a future handler accidentally
    # catches the failure: the await count below detects that attempt as well.
    external_io = AsyncMock(
        side_effect=AssertionError("management invoked provider I/O")
    )
    for provider in (GeminiProvider, OllamaProvider, OpenAICompatibleProvider):
        monkeypatch.setattr(provider, "generate", external_io)
    monkeypatch.setattr(httpx.AsyncClient, "send", external_io)
    memories = AsyncMock(spec=SqlAlchemyMemoryRepository)
    result: object = MemoryMutationResult(
        outcome, "abcdefgh", 1, 2, recall_enabled=arguments != "recall off"
    )
    if method == "status_for_participant":
        result = MemoryStatusSummary(True, 0, 1, 0, 1)
    elif method == "active_for_conversation":
        result = ()
    elif method == "create":
        result = MemoryItemModel(public_id="abcdefgh", revision=1)
    getattr(memories, method).return_value = result
    commands = AsyncMock()
    assistant = AssistantModel(id=uuid4())
    conversation = ConversationModel(
        id=uuid4(),
        platform_connection_id=uuid4(),
        conversation_type=ConversationType.PRIVATE,
    )
    participant = ParticipantModel(id=uuid4())
    job = TelegramCommandJobModel(id=uuid4(), message_id=uuid4())
    asyncio.run(
        _handle_memory_command(
            None,
            commands,
            memories,
            job,
            "worker",
            parse_command("memory", arguments),
            "en",
            conversation,
            participant,
            assistant,
            Settings(_env_file=None),
            None,
            InMemoryMetricsRecorder(),
        )
    )
    getattr(memories, method).assert_awaited_once()
    commands.complete.assert_awaited_once()
    assert commands.complete.await_args.args[3] == code
    external_io.assert_not_awaited()


def test_memory_command_failure_does_not_expose_exception_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings
    from app.domain.persistence import ConversationType
    from app.infrastructure.database.models import (
        AssistantModel,
        ConversationModel,
        ParticipantModel,
        TelegramCommandJobModel,
    )
    from app.infrastructure.telemetry import InMemoryMetricsRecorder
    from app.runtime import telegram_command_worker as worker

    secret = "private-memory-value-never-log"
    command = TelegramCommandJobModel(
        id=uuid4(), command_name="memory", arguments="list"
    )
    commands = AsyncMock()
    commands.claim.return_value = [command]
    governance = AsyncMock()
    governance.fail_stale_erasure_requests.return_value = []
    monkeypatch.setattr(worker, "SqlAlchemyCommandRepository", lambda _: commands)
    monkeypatch.setattr(worker, "SqlAlchemyGovernanceRepository", lambda _: governance)
    monkeypatch.setattr(worker, "SqlAlchemyMemoryRepository", lambda *args: AsyncMock())
    monkeypatch.setattr(
        worker,
        "_load_state",
        AsyncMock(
            return_value=(
                "en",
                ConversationModel(conversation_type=ConversationType.PRIVATE),
                ParticipantModel(),
                AssistantModel(),
                None,
            )
        ),
    )
    monkeypatch.setattr(
        worker, "_handle_memory_command", AsyncMock(side_effect=RuntimeError(secret))
    )
    telemetry = InMemoryMetricsRecorder()
    with pytest.raises(RuntimeError, match="^memory command failed$") as caught:
        asyncio.run(
            worker.consume_once(
                Settings(_env_file=None, command_worker_enabled=True),
                SimpleNamespace(session_factory=None),
                owner="test",
                telemetry=telemetry,
            )
        )
    assert secret not in "".join(traceback.format_exception(caught.value))
    commands.complete.assert_not_awaited()
    assert (
        telemetry.counter_value(
            "january_memory_control_operations_total",
            operation="list",
            outcome="failed",
            record_kind="none",
            conversation_type="private",
        )
        == 1
    )


def test_database_engine_hides_bound_personal_context_parameters() -> None:
    from app.core.config import Settings
    from app.infrastructure.database.database import Database

    async def scenario() -> None:
        database = Database(Settings(_env_file=None, database_echo=True))
        await database.start()
        try:
            assert database.engine.sync_engine.hide_parameters is True
        finally:
            await database.stop()

    asyncio.run(scenario())
