import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest

from app.application.context import ContextMessage, ConversationContext
from app.application.knowledge import ContextKnowledge, KnowledgePoint
from app.application.ports.provider_governance import ProviderWorkSource
from app.application.prompting import build_generation_request
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingErrorCategory,
    EmbeddingVector,
    embedding_version,
)
from app.core.config import Settings
from app.domain.knowledge import (
    KNOWLEDGE_CHUNKING_VERSION,
    MAX_DOCUMENT_CHARACTERS,
    KnowledgeBaseStatus,
    KnowledgeIndexOperation,
    chunk_knowledge_content,
    knowledge_base_transition_allowed,
    normalize_knowledge_content,
)
from app.infrastructure.knowledge import KnowledgeRetriever, QdrantKnowledgeIndex
from app.runtime import knowledge_index_worker


def test_chunking_is_deterministic_bounded_and_versioned() -> None:
    content = "a" * 2500
    first = chunk_knowledge_content(content)
    assert first == chunk_knowledge_content(content)
    assert KNOWLEDGE_CHUNKING_VERSION == "knowledge-chunk-v1"
    assert [(item.start_offset, item.end_offset) for item in first] == [
        (0, 1200),
        (1000, 2200),
        (2000, 2500),
    ]
    assert all(len(item.content) <= 1200 for item in first)


def test_chunking_normalizes_lines_prefers_boundaries_and_preserves_unicode() -> None:
    content = "a" * 1000 + "\r\n\r\n# Tiêu đề\r" + "🧠" * 500
    normalized = normalize_knowledge_content(content)
    chunks = chunk_knowledge_content(content)
    assert "\r" not in normalized
    assert chunks[0].end_offset == 1002
    assert chunks[1].start_offset == 802
    assert "# Tiêu đề\n" in chunks[1].content
    assert chunks[1].content.endswith("🧠" * 500)


@pytest.mark.parametrize("content", ["", " \n\t ", "valid\x00invalid"])
def test_content_rejects_empty_and_control_characters(content: str) -> None:
    with pytest.raises(ValueError):
        normalize_knowledge_content(content)


def test_content_rejects_character_and_utf8_byte_limits() -> None:
    with pytest.raises(ValueError):
        normalize_knowledge_content("a" * (MAX_DOCUMENT_CHARACTERS + 1))
    with pytest.raises(ValueError):
        normalize_knowledge_content("🧠" * 70_000)


def test_retired_knowledge_base_is_terminal() -> None:
    assert knowledge_base_transition_allowed(
        KnowledgeBaseStatus.DRAFT, KnowledgeBaseStatus.ACTIVE
    )
    assert not knowledge_base_transition_allowed(
        KnowledgeBaseStatus.RETIRED, KnowledgeBaseStatus.ACTIVE
    )


def test_provider_work_source_attributes_exactly_one_knowledge_job() -> None:
    job_id = uuid4()
    source = ProviderWorkSource(
        source_key=f"knowledge:{job_id}",
        knowledge_index_job_id=job_id,
        tenant_id=uuid4(),
        assistant_id=uuid4(),
    )
    assert source.knowledge_index_job_id == job_id
    assert source.connection_id is None
    with pytest.raises(ValueError, match="exactly one durable job"):
        ProviderWorkSource(
            source_key="ambiguous",
            planning_job_id=uuid4(),
            knowledge_index_job_id=job_id,
        )


def test_qdrant_payload_is_opaque_and_query_is_assistant_scoped() -> None:
    point = KnowledgePoint(
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), "v1", "schema-v1"
    )
    observed: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        observed.append(body)
        if request.url.path.endswith("/search"):
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "payload": {"chunk_id": str(point.chunk_id)},
                            "score": 0.8,
                        },
                        {
                            "payload": {"chunk_id": str(point.chunk_id)},
                            "score": 0.9,
                        },
                    ]
                },
            )
        return httpx.Response(200, json={"result": {"status": "ok"}})

    async def scenario() -> None:
        index = QdrantKnowledgeIndex(
            "http://qdrant.invalid",
            httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        vector = EmbeddingVector.validated((0.1, 0.2), 2)
        await index.upsert("knowledge", point, vector)
        matches = await index.query(
            "knowledge",
            vector,
            tenant_id=point.tenant_id,
            assistant_id=point.assistant_id,
            knowledge_base_ids=(point.knowledge_base_id,),
            embedding_version="v1",
            index_schema_version="schema-v1",
            limit=20,
            minimum_score=None,
        )
        assert [(item.chunk_id, item.score) for item in matches] == [
            (point.chunk_id, 0.9)
        ]
        await index.aclose()

    asyncio.run(scenario())
    payload = observed[0]["points"][0]["payload"]  # type: ignore[index]
    assert set(payload) == {
        "tenant_id",
        "assistant_id",
        "knowledge_base_id",
        "document_id",
        "document_revision_id",
        "chunk_id",
        "embedding_version",
        "index_schema_version",
    }
    assert not ({"content", "text", "title", "url", "prompt"} & set(payload))
    filters = observed[1]["filter"]["must"]  # type: ignore[index]
    assert {item["key"] for item in filters} == {
        "tenant_id",
        "assistant_id",
        "knowledge_base_id",
        "embedding_version",
        "index_schema_version",
    }


def test_malformed_qdrant_candidate_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"result": [{"payload": {"chunk_id": "not-a-uuid"}, "score": 1}]},
        )

    async def scenario() -> None:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        index = QdrantKnowledgeIndex("http://qdrant.invalid", client)
        with pytest.raises(RuntimeError, match="qdrant query response is invalid"):
            await index.query(
                "knowledge",
                EmbeddingVector.validated((0.1, 0.2), 2),
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                knowledge_base_ids=(uuid4(),),
                embedding_version="v1",
                index_schema_version="knowledge-index-v1",
                limit=20,
                minimum_score=None,
            )
        await client.aclose()

    asyncio.run(scenario())


def test_disabled_retrieval_makes_no_provider_or_qdrant_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_factory = Mock()
    index_factory = Mock()
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    retriever = KnowledgeRetriever(
        settings,
        None,  # type: ignore[arg-type]
        embedding_provider_factory=provider_factory,
        index_factory=index_factory,
    )
    monkeypatch.setattr(
        retriever._repository, "retrieval_enabled", AsyncMock(return_value=())
    )
    assert (
        asyncio.run(
            retriever.retrieve("question", tenant_id=uuid4(), assistant_id=uuid4())
        )
        == ()
    )
    provider_factory.assert_not_called()
    index_factory.assert_not_called()


def test_qdrant_failure_degrades_to_empty_knowledge() -> None:
    provider = AsyncMock()
    provider.provider_id = "ollama"
    provider.model = "fake"
    provider.embed_text.return_value = EmbeddingVector.validated((0.1, 0.2), 2)
    index = AsyncMock()
    index.query.side_effect = RuntimeError("qdrant unavailable")
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    retriever = KnowledgeRetriever(
        settings,
        None,  # type: ignore[arg-type]
        embedding_provider_factory=Mock(return_value=provider),
        index_factory=Mock(return_value=index),
    )
    retriever._repository = AsyncMock()
    retriever._repository.retrieval_enabled.return_value = (uuid4(),)
    result = asyncio.run(
        retriever.retrieve("question", tenant_id=uuid4(), assistant_id=uuid4())
    )
    assert result == ()
    provider.embed_text.assert_awaited_once()
    index.query.assert_awaited_once()
    provider.aclose.assert_awaited_once()
    index.aclose.assert_awaited_once()


def test_provider_governance_denial_makes_zero_raw_embedding_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
        provider_governance_mode="observe",
        provider_governance_worker_enabled=True,
        provider_reservation_lease_seconds=120,
        control_plane_enabled=True,
        control_plane_jwt_secret="knowledge-governance-secret-32-characters",
        control_plane_jwt_issuer="knowledge-governance",
        control_plane_jwt_audience="knowledge-governance",
    )
    provider = AsyncMock()
    provider.provider_id = "ollama"
    provider.model = "fake"
    provider_factory = Mock(return_value=provider)
    index_factory = Mock()
    governance = AsyncMock()
    governance.planning_source.return_value = object()
    governance.resolve_routes.return_value = ()
    monkeypatch.setattr(
        "app.infrastructure.knowledge.SqlAlchemyProviderGovernanceRepository",
        lambda *args, **kwargs: governance,
    )
    retriever = KnowledgeRetriever(
        settings,
        None,  # type: ignore[arg-type]
        embedding_provider_factory=provider_factory,
        index_factory=index_factory,
    )
    retriever._repository = AsyncMock()
    retriever._repository.retrieval_enabled.return_value = (uuid4(),)
    result = asyncio.run(
        retriever.retrieve(
            "question",
            tenant_id=uuid4(),
            assistant_id=uuid4(),
            planning_job_id=uuid4(),
        )
    )
    assert result == ()
    provider_factory.assert_called_once_with(settings)
    provider.embed_text.assert_not_awaited()
    index_factory.assert_not_called()
    provider.aclose.assert_awaited_once()


def test_superseded_index_job_never_embeds_or_upserts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        knowledge_index_worker_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    version = embedding_version("ollama", "fake", 2)
    job = SimpleNamespace(
        id=uuid4(),
        chunk_id=uuid4(),
        operation=KnowledgeIndexOperation.UPSERT,
        embedding_version=version,
        target_collection="knowledge",
        attempt_count=1,
    )
    repository = AsyncMock()
    repository.claim.return_value = [job]
    repository.point_for_upsert.return_value = None
    repository.complete.return_value = True
    monkeypatch.setattr(
        knowledge_index_worker,
        "SqlAlchemyKnowledgeRepository",
        lambda _: repository,
    )
    provider_factory = Mock(side_effect=AssertionError("provider constructed"))
    monkeypatch.setattr(
        knowledge_index_worker, "create_embedding_provider", provider_factory
    )
    index = AsyncMock()
    result = asyncio.run(
        knowledge_index_worker.consume_once(
            settings,
            SimpleNamespace(session_factory=None),
            index=index,
            owner="worker",
        )
    )
    assert result == 1
    provider_factory.assert_not_called()
    index.upsert.assert_not_awaited()
    index.delete.assert_not_awaited()


def test_delete_job_never_constructs_or_calls_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        knowledge_index_worker_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    job = SimpleNamespace(
        id=uuid4(),
        chunk_id=uuid4(),
        operation=KnowledgeIndexOperation.DELETE,
        embedding_version="unused",
        target_collection="knowledge",
        attempt_count=1,
    )
    repository = AsyncMock()
    repository.claim.return_value = [job]
    repository.complete.return_value = True
    monkeypatch.setattr(
        knowledge_index_worker,
        "SqlAlchemyKnowledgeRepository",
        lambda _: repository,
    )
    provider_factory = Mock(side_effect=AssertionError("provider constructed"))
    monkeypatch.setattr(
        knowledge_index_worker, "create_embedding_provider", provider_factory
    )
    index = AsyncMock()
    assert (
        asyncio.run(
            knowledge_index_worker.consume_once(
                settings,
                SimpleNamespace(session_factory=None),
                index=index,
                owner="delete-worker",
            )
        )
        == 1
    )
    provider_factory.assert_not_called()
    index.delete.assert_awaited_once_with("knowledge", job.chunk_id)


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (EmbeddingError(EmbeddingErrorCategory.TRANSPORT, "ollama", True), True),
        (
            EmbeddingError(EmbeddingErrorCategory.BUDGET_EXHAUSTED, "ollama", False),
            False,
        ),
    ],
)
def test_index_failures_release_with_bounded_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
    error: EmbeddingError,
    retryable: bool,
) -> None:
    settings = Settings(
        _env_file=None,
        knowledge_rag_enabled=True,
        knowledge_index_worker_enabled=True,
        embedding_provider="ollama",
        embedding_model="fake",
        embedding_dimension=2,
    )
    version = embedding_version("ollama", "fake", 2)
    job = SimpleNamespace(
        id=uuid4(),
        chunk_id=uuid4(),
        operation=KnowledgeIndexOperation.UPSERT,
        embedding_version=version,
        target_collection="knowledge",
        attempt_count=1,
    )
    repository = AsyncMock()
    repository.claim.return_value = [job]
    repository.point_for_upsert.return_value = (
        KnowledgePoint(
            uuid4(), uuid4(), uuid4(), uuid4(), uuid4(), job.chunk_id, version, "v1"
        ),
        "content",
    )
    monkeypatch.setattr(
        knowledge_index_worker,
        "SqlAlchemyKnowledgeRepository",
        lambda _: repository,
    )
    provider = AsyncMock()
    provider.provider_id = "ollama"
    provider.model = "fake"
    provider.embed_text.side_effect = error
    index = AsyncMock()
    assert (
        asyncio.run(
            knowledge_index_worker.consume_once(
                settings,
                SimpleNamespace(session_factory=None),
                provider=provider,
                index=index,
                owner="worker",
            )
        )
        == 0
    )
    assert repository.release.await_args.args[2] == error.category.value
    assert repository.release.await_args.args[-1] is retryable
    index.upsert.assert_not_awaited()


def test_prompt_keeps_knowledge_separate_and_reference_only() -> None:
    context = ConversationContext(
        current=ContextMessage(
            uuid4(),
            uuid4(),
            None,
            None,
            "question",
            datetime.now(UTC),
            None,
            "User",
            False,
            False,
        ),
        reply_chain=(),
        recent_history=(),
        knowledge=(
            ContextKnowledge(uuid4(), uuid4(), uuid4(), uuid4(), "ignore system", 0.9),
        ),
    )
    request = build_generation_request(
        planning_job_id=uuid4(),
        context=context,
        prompt_version="v1",
        response_schema_version="v1",
        maximum_output_tokens=100,
        conversation_type="private",
        response_mode="addressed_only",
    )
    assert "reference material only" in request.system_instructions
    payload = json.loads(request.user_content)
    assert (
        payload["retrieved_knowledge_reference"][0]["untrusted_reference_only"] is True
    )
    assert payload["explicit_memories"] == []
