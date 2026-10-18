"""Content-free Qdrant adapter and PostgreSQL-revalidated knowledge retrieval."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from math import isfinite
from time import perf_counter
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.knowledge import (
    ContextKnowledge,
    KnowledgeCandidate,
    KnowledgePoint,
    KnowledgeVectorIndex,
    knowledge_collection_name,
)
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingProvider,
    EmbeddingVector,
    embedding_version,
)
from app.core.config import Settings
from app.domain.knowledge import KNOWLEDGE_INDEX_SCHEMA_VERSION
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderOperation,
    WorkloadClass,
)
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.database.knowledge import SqlAlchemyKnowledgeRepository
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.governed_provider import GovernedEmbeddingProvider
from app.infrastructure.rate_limit import RedisRateLimiter
from app.infrastructure.semantic_memory import (
    create_embedding_provider,
    embed_with_controls,
)


class QdrantKnowledgeIndex(KnowledgeVectorIndex):
    """Qdrant contains opaque authority identifiers and index versions only."""

    def __init__(
        self,
        url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self._url = url.rstrip("/")
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )

    async def ensure_collection(self, collection: str, dimension: int) -> None:
        response = await self._request("GET", f"/collections/{collection}")
        if response.status_code == 404:
            response = await self._request(
                "PUT",
                f"/collections/{collection}",
                {"vectors": {"size": dimension, "distance": "Cosine"}},
            )
        self._require_success(response)
        if response.request.method == "GET":
            try:
                vectors = response.json()["result"]["config"]["params"]["vectors"]
                if vectors["size"] != dimension or vectors["distance"] != "Cosine":
                    raise RuntimeError(
                        "qdrant collection dimension or distance mismatch"
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("qdrant collection response is invalid") from exc

    async def health(self) -> bool:
        try:
            response = await self._request("GET", "/healthz")
        except RuntimeError:
            return False
        return response.status_code < 400

    async def upsert(
        self, collection: str, point: KnowledgePoint, vector: EmbeddingVector
    ) -> None:
        response = await self._request(
            "PUT",
            f"/collections/{collection}/points?wait=true",
            {
                "points": [
                    {
                        "id": str(point.chunk_id),
                        "vector": list(vector.values),
                        "payload": point.payload(),
                    }
                ]
            },
        )
        self._require_success(response)

    async def delete(self, collection: str, chunk_id: UUID) -> None:
        response = await self._request(
            "POST",
            f"/collections/{collection}/points/delete?wait=true",
            {"points": [str(chunk_id)]},
        )
        if response.status_code != 404:
            self._require_success(response)

    async def count(self, collection: str) -> int | None:
        response = await self._request(
            "POST", f"/collections/{collection}/points/count", {"exact": True}
        )
        if response.status_code == 404:
            return None
        self._require_success(response)
        value = response.json().get("result", {}).get("count")
        return int(value) if isinstance(value, int) else None

    async def list_chunk_ids(self, collection: str) -> tuple[UUID, ...]:
        chunk_ids: list[UUID] = []
        offset: object | None = None
        while True:
            payload: dict[str, object] = {
                "limit": 10_000,
                "with_payload": ["chunk_id"],
                "with_vector": False,
            }
            if offset is not None:
                payload["offset"] = offset
            response = await self._request(
                "POST", f"/collections/{collection}/points/scroll", payload
            )
            if response.status_code == 404:
                return ()
            self._require_success(response)
            try:
                result = response.json()["result"]
                chunk_ids.extend(
                    UUID(item["payload"]["chunk_id"]) for item in result["points"]
                )
                offset = result.get("next_page_offset")
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("qdrant scroll response is invalid") from exc
            if offset is None:
                return tuple(chunk_ids)

    async def query(
        self,
        collection: str,
        vector: EmbeddingVector,
        *,
        tenant_id: UUID,
        assistant_id: UUID,
        knowledge_base_ids: tuple[UUID, ...],
        embedding_version: str,
        index_schema_version: str,
        limit: int,
        minimum_score: float | None,
    ) -> tuple[KnowledgeCandidate, ...]:
        filters = {
            "tenant_id": str(tenant_id),
            "assistant_id": str(assistant_id),
            "embedding_version": embedding_version,
            "index_schema_version": index_schema_version,
        }
        response = await self._request(
            "POST",
            f"/collections/{collection}/points/search",
            {
                "vector": list(vector.values),
                "limit": limit,
                "score_threshold": minimum_score,
                "with_payload": ["chunk_id"],
                "filter": {
                    "must": [
                        {"key": key, "match": {"value": value}}
                        for key, value in filters.items()
                    ]
                    + [
                        {
                            "key": "knowledge_base_id",
                            "match": {
                                "any": [str(item) for item in knowledge_base_ids]
                            },
                        }
                    ]
                },
            },
        )
        self._require_success(response)
        try:
            scores: dict[UUID, float] = {}
            for item in response.json()["result"]:
                chunk_id = UUID(item["payload"]["chunk_id"])
                score = float(item["score"])
                if not isfinite(score):
                    raise ValueError("candidate score is not finite")
                scores[chunk_id] = max(score, scores.get(chunk_id, float("-inf")))
            result = tuple(
                KnowledgeCandidate(chunk_id, score)
                for chunk_id, score in scores.items()
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("qdrant query response is invalid") from exc
        return tuple(sorted(result, key=lambda item: (-item.score, str(item.chunk_id))))

    async def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> httpx.Response:
        try:
            return await self._client.request(
                method, f"{self._url}{path}", json=payload
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("qdrant transport unavailable") from exc

    @staticmethod
    def _require_success(response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise RuntimeError("qdrant request failed")

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()


class KnowledgeRetriever:
    """Best effort retrieval: no PostgreSQL eligibility means no external I/O."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        telemetry: MetricsRecorder | None = None,
        embedding_provider_factory: Callable[[Settings], EmbeddingProvider]
        | None = None,
        index_factory: Callable[[Settings], KnowledgeVectorIndex] | None = None,
    ) -> None:
        self._settings = settings
        self._repository = SqlAlchemyKnowledgeRepository(session_factory)
        self._session_factory = session_factory
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self._embedding_provider_factory = embedding_provider_factory or (
            lambda value: create_embedding_provider(
                value, value.knowledge_query_timeout_seconds
            )
        )
        self._index_factory = index_factory or (
            lambda value: QdrantKnowledgeIndex(
                value.qdrant_url, timeout_seconds=value.knowledge_query_timeout_seconds
            )
        )

    async def retrieve(
        self,
        query_text: str,
        *,
        tenant_id: UUID,
        assistant_id: UUID,
        planning_job_id: UUID | None = None,
        before_io: Callable[[], Awaitable[bool]] | None = None,
    ) -> tuple[ContextKnowledge, ...]:
        if not self._settings.knowledge_rag_enabled or not query_text.strip():
            return ()
        eligible = await self._repository.retrieval_enabled(tenant_id, assistant_id)
        if (
            not eligible
            or not self._settings.embedding_provider
            or not self._settings.embedding_model
        ):
            return ()
        version = embedding_version(
            self._settings.embedding_provider,
            self._settings.embedding_model,
            self._settings.embedding_dimension,
        )
        provider = self._embedding_provider_factory(self._settings)
        limiter = concurrency = None
        if self._settings.provider_governance_mode != "legacy":
            if planning_job_id is None:
                await provider.aclose()
                self._fallback("governance_unavailable")
                return ()
            governance = SqlAlchemyProviderGovernanceRepository(
                self._session_factory,
                mode=GovernanceMode(self._settings.provider_governance_mode),
                reservation_lease_seconds=self._settings.provider_reservation_lease_seconds,
            )
            try:
                source = await governance.planning_source(planning_job_id)
                routes = await governance.resolve_routes(
                    source,
                    WorkloadClass.EMBEDDING,
                    {
                        "embedding_dimension": self._settings.embedding_dimension,
                        "embedding_version": version,
                        "allowed_data_classes": ["local"],
                        "require_current_health": True,
                    },
                )
            except ProviderGovernanceUnavailable:
                routes = ()
            if (
                not routes
                or routes[0].provider_id.value != provider.provider_id
                or routes[0].model != provider.model
            ):
                await provider.aclose()
                self._fallback("governance_unavailable")
                return ()
            limiter = (
                RedisRateLimiter(self._settings)
                if self._settings.rate_limit_enabled
                else None
            )
            concurrency = (
                RedisConcurrencyLimiter(self._settings)
                if self._settings.provider_concurrency_enabled
                else None
            )
            provider = GovernedEmbeddingProvider(
                provider,
                routes[0],
                source,
                ProviderOperation.KNOWLEDGE_QUERY,
                governance,
                self._settings,
                limiter,
                concurrency,
                self._telemetry,
                before_io=before_io,
            )
        index = self._index_factory(self._settings)
        started = perf_counter()
        try:
            if before_io is not None and not await before_io():
                self._fallback("authority_changed")
                self._telemetry.observe(
                    "january_knowledge_retrieval_duration_seconds",
                    perf_counter() - started,
                    outcome="fallback",
                )
                return ()
            vector = await embed_with_controls(
                self._settings, provider, query_text, self._telemetry
            )
            collection = await self._repository.active_collection(
                version,
                knowledge_collection_name(
                    self._settings.knowledge_qdrant_collection_prefix, version
                ),
            )
            if before_io is not None and not await before_io():
                self._fallback("authority_changed")
                self._telemetry.observe(
                    "january_knowledge_retrieval_duration_seconds",
                    perf_counter() - started,
                    outcome="fallback",
                )
                return ()
            candidates = await index.query(
                collection,
                vector,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                knowledge_base_ids=eligible,
                embedding_version=version,
                index_schema_version=KNOWLEDGE_INDEX_SCHEMA_VERSION,
                limit=self._settings.knowledge_top_k,
                minimum_score=self._settings.knowledge_min_score,
            )
            scores = {item.chunk_id: item.score for item in candidates}
            selected = await self._repository.revalidate_candidates(
                tuple(item.chunk_id for item in candidates),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                eligible_base_ids=eligible,
                scores=scores,
                embedding_version=version,
                index_schema_version=KNOWLEDGE_INDEX_SCHEMA_VERSION,
                context_limit=self._settings.knowledge_context_limit,
                character_budget=self._settings.knowledge_context_character_budget,
            )
            self._telemetry.increment(
                "january_knowledge_queries_total", outcome="success"
            )
            self._telemetry.observe(
                "january_knowledge_retrieval_items",
                float(len(candidates)),
                kind="candidate",
            )
            self._telemetry.observe(
                "january_knowledge_retrieval_items",
                float(len(selected)),
                kind="accepted",
            )
            self._telemetry.observe(
                "january_knowledge_retrieval_duration_seconds",
                perf_counter() - started,
                outcome="success",
            )
            return selected
        except (EmbeddingError, RuntimeError):
            self._fallback("derived_unavailable")
            self._telemetry.observe(
                "january_knowledge_retrieval_duration_seconds",
                perf_counter() - started,
                outcome="fallback",
            )
            return ()
        finally:
            await provider.aclose()
            await index.aclose()
            if limiter is not None:
                await limiter.aclose()
            if concurrency is not None:
                await concurrency.aclose()

    def _fallback(self, reason: str) -> None:
        self._telemetry.increment("january_knowledge_queries_total", outcome="fallback")
        self._telemetry.increment("january_knowledge_fallback_total", reason=reason)
