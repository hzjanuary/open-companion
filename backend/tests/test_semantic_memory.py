import asyncio
import json
from datetime import UTC, datetime
from math import inf, nan
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest

from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingErrorCategory,
    EmbeddingVector,
    SemanticMemoryMatch,
    SemanticMemoryPoint,
    collection_name,
    embedding_version,
)
from app.core.config import Settings
from app.domain.persistence import MemoryScope
from app.infrastructure.semantic_memory import (
    QdrantSemanticMemoryIndex,
    SemanticMemoryRetriever,
    embed_with_controls,
)
from app.infrastructure.telemetry import InMemoryMetricsRecorder
from app.runtime.semantic_memory_index_worker import _retry_delay, _retryable


def test_semantic_worker_does_not_publish_vector_for_superseded_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.persistence import SemanticMemoryIndexOperation
    from app.runtime import semantic_memory_index_worker as worker

    settings = Settings(
        _env_file=None,
        semantic_memory_enabled=True,
        semantic_memory_worker_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    version = embedding_version("ollama", "fake", 2)
    repository = AsyncMock()
    repository.claim.return_value = [
        SimpleNamespace(
            id=uuid4(),
            memory_id=uuid4(),
            embedding_version=version,
            target_collection="synthetic",
            operation=SemanticMemoryIndexOperation.UPSERT,
        )
    ]
    repository.point_for_upsert.side_effect = [
        (object(), "old"),
        (object(), "corrected"),
    ]
    repository.complete.return_value = False  # correction reopened the durable job
    monkeypatch.setattr(
        worker, "SqlAlchemySemanticMemoryRepository", lambda _: repository
    )
    provider = AsyncMock()
    provider.embed_text.return_value = EmbeddingVector.validated((0.1, 0.2), 2)
    index = AsyncMock()
    assert (
        asyncio.run(
            worker.consume_once(
                settings,
                SimpleNamespace(session_factory=None),
                owner="old-lease",
                provider=provider,
                index=index,
            )
        )
        == 0
    )
    provider.embed_text.assert_awaited_once_with("old")
    index.upsert.assert_not_awaited()
    index.delete.assert_not_awaited()
    repository.release.assert_not_awaited()


def test_correction_reopens_known_index_targets_without_losing_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.persistence import SemanticMemoryIndexOperation
    from app.infrastructure.database.semantic_memory import (
        SqlAlchemySemanticMemoryRepository,
    )

    session = AsyncMock()
    rows = Mock()
    rows.all.return_value = [("v1", "rebuild_target")]
    session.execute.return_value = rows
    schedule = AsyncMock()
    monkeypatch.setattr(SqlAlchemySemanticMemoryRepository, "schedule", schedule)
    memory_id = uuid4()
    asyncio.run(
        SqlAlchemySemanticMemoryRepository.schedule_upserts_for_memory(
            session, memory_id, "v2"
        )
    )
    assert [call.args for call in schedule.await_args_list] == [
        (
            session,
            memory_id,
            SemanticMemoryIndexOperation.UPSERT,
            "v1",
            "rebuild_target",
        ),
        (session, memory_id, SemanticMemoryIndexOperation.UPSERT, "v2", None),
    ]


def test_embedding_vector_requires_exact_finite_dimension() -> None:
    assert EmbeddingVector.validated((0.1, 0.2), 2).values == (0.1, 0.2)
    for values in ((0.1,), (nan, 0.2), (inf, 0.2)):
        with pytest.raises(EmbeddingError):
            EmbeddingVector.validated(values, 2)


def test_qdrant_payload_is_opaque_and_content_free() -> None:
    point = SemanticMemoryPoint(
        uuid4(), uuid4(), uuid4(), uuid4(), MemoryScope.GROUP_CONVERSATION, "v1"
    )
    payload = point.payload()
    assert set(payload) == {
        "memory_id",
        "assistant_id",
        "platform_connection_id",
        "conversation_id",
        "scope",
        "embedding_version",
    }
    assert "content" not in payload
    assert "text" not in payload


def test_embedding_version_changes_with_configuration() -> None:
    first = embedding_version("ollama", "model-a", 768)
    assert first == embedding_version("ollama", "model-a", 768)
    assert first != embedding_version("ollama", "model-b", 768)
    assert collection_name("january_explicit_memory", first).endswith(first)


def test_qdrant_adapter_sends_only_opaque_payload_and_exact_scope_filter() -> None:
    point = SemanticMemoryPoint(
        uuid4(), uuid4(), uuid4(), uuid4(), MemoryScope.GROUP_CONVERSATION, "v1"
    )
    observed: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/healthz":
            return httpx.Response(200, json={"title": "qdrant"})
        body = json.loads(request.content)
        observed.append(body)
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json={"result": []})
        if request.url.path.endswith("/scroll"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [{"payload": {"memory_id": str(point.memory_id)}}]
                    }
                },
            )
        return httpx.Response(200, json={"result": {"status": "ok"}})

    async def scenario() -> None:
        index = QdrantSemanticMemoryIndex(
            "http://qdrant.invalid",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        vector = EmbeddingVector.validated((0.1, 0.2), 2)
        assert await index.health()
        await index.upsert("collection", point, vector)
        await index.query(
            "collection",
            vector,
            assistant_id=point.assistant_id,
            platform_connection_id=point.platform_connection_id,
            conversation_id=point.conversation_id,
            scope=point.scope,
            embedding_version="v1",
            limit=6,
            minimum_score=None,
        )
        assert await index.list_memory_ids("collection") == (point.memory_id,)
        await index.aclose()

    asyncio.run(scenario())
    payload = observed[0]["points"][0]["payload"]  # type: ignore[index]
    assert set(payload) == set(point.payload())  # type: ignore[arg-type]
    assert "content" not in payload  # type: ignore[operator]
    filters = observed[1]["filter"]["must"]  # type: ignore[index]
    assert len(filters) == 5  # type: ignore[arg-type]
    assert observed[2]["with_vector"] is False
    assert observed[2]["with_payload"] == ["memory_id"]


def test_qdrant_health_is_false_when_transport_is_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    async def scenario() -> bool:
        index = QdrantSemanticMemoryIndex(
            "http://qdrant.invalid",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            return await index.health()
        finally:
            await index.aclose()

    assert asyncio.run(scenario()) is False


def test_qdrant_delete_treats_missing_collection_as_already_clean() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status": {"error": "not found"}})

    async def scenario() -> None:
        index = QdrantSemanticMemoryIndex(
            "http://qdrant.invalid",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            await index.delete("missing", uuid4())
        finally:
            await index.aclose()

    asyncio.run(scenario())


def test_qdrant_reconciliation_scrolls_all_opaque_id_pages() -> None:
    first, second = uuid4(), uuid4()
    offsets: list[object | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        offsets.append(payload.get("offset"))
        if payload.get("offset") is None:
            return httpx.Response(
                200,
                json={
                    "result": {
                        "points": [{"payload": {"memory_id": str(first)}}],
                        "next_page_offset": "next",
                    }
                },
            )
        return httpx.Response(
            200,
            json={"result": {"points": [{"payload": {"memory_id": str(second)}}]}},
        )

    async def scenario() -> tuple[UUID, ...]:
        index = QdrantSemanticMemoryIndex(
            "http://qdrant.invalid",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        try:
            return await index.list_memory_ids("collection")
        finally:
            await index.aclose()

    assert asyncio.run(scenario()) == (first, second)
    assert offsets == [None, "next"]


def test_embedding_telemetry_is_content_free_and_only_records_real_io() -> None:
    class FakeEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        async def embed_text(self, text: str) -> EmbeddingVector:
            assert text == "current incoming message"
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    async def scenario() -> None:
        recorder = InMemoryMetricsRecorder()
        result = await embed_with_controls(
            Settings(_env_file=None, environment="test"),
            FakeEmbeddingProvider(),
            "current incoming message",
            recorder,
        )
        assert result.values == (0.1, 0.2)
        assert (
            recorder.counter_value(
                "january_embedding_requests_total", provider="ollama", outcome="success"
            )
            == 1
        )
        assert recorder.histogram_values(
            "january_embedding_request_duration_seconds",
            provider="ollama",
            outcome="success",
        )
        exposition = recorder.exposition()
        assert "current incoming message" not in exposition
        assert "vector" not in exposition

    asyncio.run(scenario())


def test_retrieval_uses_only_current_text_and_revalidates_qdrant_ids() -> None:
    class FakeEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        def __init__(self) -> None:
            self.inputs: list[str] = []

        async def embed_text(self, text: str) -> EmbeddingVector:
            self.inputs.append(text)
            return EmbeddingVector.validated((0.1, 0.2), 2)

        async def aclose(self) -> None:
            return None

    class FakeIndex:
        def __init__(self, active_id: UUID, stale_id: UUID) -> None:
            self.active_id = active_id
            self.stale_id = stale_id
            self.queries: list[dict[str, object]] = []

        async def query(
            self, *args: object, **kwargs: object
        ) -> tuple[SemanticMemoryMatch, ...]:
            self.queries.append(kwargs)
            return (
                SemanticMemoryMatch(self.stale_id, 0.99),
                SemanticMemoryMatch(self.active_id, 0.90),
            )

        async def aclose(self) -> None:
            return None

    class FakeRepository:
        def __init__(self, active_id: UUID) -> None:
            self.active_id = active_id

        async def active_collection(self, version: str, fallback: str) -> str:
            return fallback

        async def revalidate_matches(
            self, memory_ids: tuple[UUID, ...], **kwargs: object
        ) -> dict[UUID, tuple[str, str, datetime, str]]:
            assert self.active_id in memory_ids
            assert kwargs["scope"] == MemoryScope.GROUP_CONVERSATION
            return {
                self.active_id: (
                    "memory-1",
                    "canonical saved memory",
                    datetime(2026, 1, 1, tzinfo=UTC),
                    "Memory",
                )
            }

    async def scenario() -> None:
        assistant_id, connection_id, conversation_id = uuid4(), uuid4(), uuid4()
        active_id, stale_id = uuid4(), uuid4()
        provider = FakeEmbeddingProvider()
        index = FakeIndex(active_id, stale_id)
        retriever = SemanticMemoryRetriever(
            Settings(
                _env_file=None,
                environment="test",
                semantic_memory_enabled=True,
                embedding_provider="ollama",
                embedding_model="fake",
                embedding_dimension=2,
            ),
            object(),  # type: ignore[arg-type]
            embedding_provider_factory=lambda _: provider,
            index_factory=lambda _: index,  # type: ignore[return-value]
        )
        retriever._repository = FakeRepository(active_id)  # type: ignore[assignment]
        result = await retriever.retrieve(
            "only current input",
            assistant_id=assistant_id,
            platform_connection_id=connection_id,
            conversation_id=conversation_id,
            scope=MemoryScope.GROUP_CONVERSATION,
        )
        assert [item.public_id for item in result] == ["memory-1"]
        assert provider.inputs == ["only current input"]
        assert index.queries[0]["assistant_id"] == assistant_id
        assert index.queries[0]["platform_connection_id"] == connection_id
        assert index.queries[0]["conversation_id"] == conversation_id
        assert index.queries[0]["scope"] == MemoryScope.GROUP_CONVERSATION

    asyncio.run(scenario())


def test_embedding_outage_falls_back_without_qdrant_query() -> None:
    class UnavailableEmbeddingProvider:
        provider_id = "ollama"
        model = "fake"
        dimension = 2

        async def embed_text(self, text: str) -> EmbeddingVector:
            raise EmbeddingError(
                EmbeddingErrorCategory.PROVIDER_UNAVAILABLE,
                self.provider_id,
                True,
            )

        async def aclose(self) -> None:
            return None

    class FailingIfQueriedIndex:
        async def aclose(self) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"unexpected Qdrant operation: {name}")

    async def scenario() -> None:
        recorder = InMemoryMetricsRecorder()
        retriever = SemanticMemoryRetriever(
            Settings(
                _env_file=None,
                environment="test",
                semantic_memory_enabled=True,
                embedding_provider="ollama",
                embedding_model="fake",
                embedding_dimension=2,
            ),
            object(),  # type: ignore[arg-type]
            telemetry=recorder,
            embedding_provider_factory=lambda _: UnavailableEmbeddingProvider(),
            index_factory=lambda _: FailingIfQueriedIndex(),  # type: ignore[return-value]
        )
        assert (
            await retriever.retrieve(
                "current input",
                assistant_id=uuid4(),
                platform_connection_id=uuid4(),
                conversation_id=uuid4(),
                scope=MemoryScope.GROUP_CONVERSATION,
            )
            == ()
        )
        assert (
            recorder.counter_value(
                "january_semantic_memory_fallback_total", reason="provider_unavailable"
            )
            == 1
        )

    asyncio.run(scenario())


def test_semantic_worker_retry_policy_is_bounded_and_respects_error_category() -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        semantic_memory_retry_min_delay_seconds=1,
        semantic_memory_retry_max_delay_seconds=4,
    )
    assert [_retry_delay(settings, attempt) for attempt in (1, 2, 3, 4)] == [
        1,
        2,
        4,
        4,
    ]
    assert (
        _retryable(
            EmbeddingError(EmbeddingErrorCategory.INVALID_VECTOR, "ollama", False)
        )
        is False
    )
    assert (
        _retryable(
            EmbeddingError(EmbeddingErrorCategory.PROVIDER_UNAVAILABLE, "ollama", True)
        )
        is True
    )
