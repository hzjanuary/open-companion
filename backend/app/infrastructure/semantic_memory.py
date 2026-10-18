"""HTTP adapters for optional embedding and Qdrant derived-index services."""

from collections.abc import Awaitable, Callable
from math import isfinite
from time import perf_counter
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.context import ContextMemory
from app.application.ports.telemetry import MetricsRecorder, NoOpMetricsRecorder
from app.application.rate_limit_rules import embedding_provider_rule
from app.application.semantic_memory import (
    EmbeddingError,
    EmbeddingErrorCategory,
    EmbeddingProvider,
    EmbeddingVector,
    SemanticMemoryIndex,
    SemanticMemoryMatch,
    SemanticMemoryPoint,
    collection_name,
    embedding_version,
)
from app.core.config import Settings
from app.domain.persistence import MemoryScope
from app.domain.planning import ProviderId
from app.domain.provider_governance import (
    GovernanceMode,
    ProviderOperation,
    WorkloadClass,
)
from app.domain.rate_limit import RateLimitOperation
from app.infrastructure.concurrency import RedisConcurrencyLimiter
from app.infrastructure.database.provider_governance import (
    ProviderGovernanceUnavailable,
    SqlAlchemyProviderGovernanceRepository,
)
from app.infrastructure.database.semantic_memory import (
    SqlAlchemySemanticMemoryRepository,
)
from app.infrastructure.rate_limit import RedisRateLimiter


class OllamaEmbeddingProvider(EmbeddingProvider):
    provider_id = "ollama"

    def __init__(
        self,
        model: str,
        dimension: int,
        base_url: str,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 20,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._base_url = base_url.rstrip("/")
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds)
        )

    async def embed_text(self, text: str) -> EmbeddingVector:
        if not text.strip():
            raise EmbeddingError(
                EmbeddingErrorCategory.INVALID_INPUT, self.provider_id, False
            )
        try:
            response = await self._client.post(
                f"{self._base_url}/api/embed",
                json={"model": self.model, "input": text},
            )
        except httpx.TimeoutException as exc:
            raise EmbeddingError(
                EmbeddingErrorCategory.PROVIDER_UNAVAILABLE, self.provider_id, True
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                EmbeddingErrorCategory.TRANSPORT, self.provider_id, True
            ) from exc
        if response.status_code >= 400:
            category = (
                EmbeddingErrorCategory.RATE_LIMITED
                if response.status_code == 429
                else EmbeddingErrorCategory.AUTHENTICATION
                if response.status_code in {401, 403}
                else EmbeddingErrorCategory.PROVIDER_UNAVAILABLE
                if response.status_code >= 500
                else EmbeddingErrorCategory.UNSUPPORTED_CAPABILITY
            )
            raise EmbeddingError(
                category,
                self.provider_id,
                category
                in {
                    EmbeddingErrorCategory.RATE_LIMITED,
                    EmbeddingErrorCategory.PROVIDER_UNAVAILABLE,
                },
            )
        try:
            parsed = response.json()
            raw = parsed["embeddings"][0]
            values = tuple(float(value) for value in raw)
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(
                EmbeddingErrorCategory.INVALID_VECTOR, self.provider_id, False
            ) from exc
        if not all(isfinite(value) for value in values):
            raise EmbeddingError(
                EmbeddingErrorCategory.INVALID_VECTOR, self.provider_id, False
            )
        try:
            return EmbeddingVector.validated(values, self.dimension)
        except EmbeddingError as exc:
            raise EmbeddingError(exc.category, self.provider_id, exc.retryable) from exc

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()


class QdrantSemanticMemoryIndex(SemanticMemoryIndex):
    """Minimal Qdrant REST adapter. It never logs query, vector, or payload bodies."""

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
            return
        self._require_success(response)
        try:
            size = response.json()["result"]["config"]["params"]["vectors"]["size"]
            distance = response.json()["result"]["config"]["params"]["vectors"][
                "distance"
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("qdrant collection response is invalid") from exc
        if size != dimension or distance != "Cosine":
            raise RuntimeError("qdrant collection dimension or distance mismatch")

    async def health(self) -> bool:
        try:
            response = await self._request("GET", "/healthz")
        except RuntimeError:
            return False
        return response.status_code < 400

    async def upsert(
        self, collection: str, point: SemanticMemoryPoint, vector: EmbeddingVector
    ) -> None:
        response = await self._request(
            "PUT",
            f"/collections/{collection}/points?wait=true",
            {
                "points": [
                    {
                        "id": str(point.memory_id),
                        "vector": list(vector.values),
                        "payload": point.payload(),
                    }
                ]
            },
        )
        self._require_success(response)

    async def delete(self, collection: str, memory_id: UUID) -> None:
        response = await self._request(
            "POST",
            f"/collections/{collection}/points/delete?wait=true",
            {"points": [str(memory_id)]},
        )
        if response.status_code != 404:
            self._require_success(response)

    async def query(
        self,
        collection: str,
        vector: EmbeddingVector,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        scope: MemoryScope,
        embedding_version: str,
        limit: int,
        minimum_score: float | None,
    ) -> tuple[SemanticMemoryMatch, ...]:
        filter_values = {
            "assistant_id": str(assistant_id),
            "platform_connection_id": str(platform_connection_id),
            "conversation_id": str(conversation_id),
            "scope": scope.value,
            "embedding_version": embedding_version,
        }
        response = await self._request(
            "POST",
            f"/collections/{collection}/points/search",
            {
                "vector": list(vector.values),
                "limit": limit,
                "score_threshold": minimum_score,
                "with_payload": ["memory_id"],
                "filter": {
                    "must": [
                        {"key": key, "match": {"value": value}}
                        for key, value in filter_values.items()
                    ]
                },
            },
        )
        self._require_success(response)
        try:
            points = response.json()["result"]
            matches = tuple(
                SemanticMemoryMatch(
                    UUID(item["payload"]["memory_id"]), float(item["score"])
                )
                for item in points
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("qdrant query response is invalid") from exc
        return tuple(
            sorted(matches, key=lambda item: (-item.score, str(item.memory_id)))
        )

    async def count(self, collection: str) -> int | None:
        response = await self._request(
            "POST", f"/collections/{collection}/points/count", {"exact": True}
        )
        if response.status_code == 404:
            return None
        self._require_success(response)
        value = response.json().get("result", {}).get("count")
        return int(value) if isinstance(value, int) else None

    async def list_memory_ids(self, collection: str) -> tuple[UUID, ...]:
        memory_ids: list[UUID] = []
        offset: object | None = None
        while True:
            payload: dict[str, object] = {
                "limit": 10_000,
                "with_payload": ["memory_id"],
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
                points = result["points"]
                memory_ids.extend(UUID(item["payload"]["memory_id"]) for item in points)
                offset = result.get("next_page_offset")
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("qdrant scroll response is invalid") from exc
            if offset is None:
                return tuple(memory_ids)

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


def create_embedding_provider(
    settings: Settings,
    timeout_seconds: float = 20,
    model_override: str | None = None,
    dimension_override: int | None = None,
) -> EmbeddingProvider:
    model = model_override or settings.embedding_model
    if settings.embedding_provider != "ollama" or not model:
        raise RuntimeError("semantic embedding provider is not configured")
    return OllamaEmbeddingProvider(
        model,
        dimension_override or settings.embedding_dimension,
        settings.llm_ollama_base_url,
        timeout_seconds=timeout_seconds,
    )


def create_semantic_index(
    settings: Settings, timeout_seconds: float = 10
) -> SemanticMemoryIndex:
    return QdrantSemanticMemoryIndex(
        settings.qdrant_url, timeout_seconds=timeout_seconds
    )


class SemanticMemoryRetriever:
    """Best-effort semantic selection; PostgreSQL remains the sole content source."""

    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        telemetry: MetricsRecorder | None = None,
        embedding_provider_factory: Callable[[Settings], EmbeddingProvider]
        | None = None,
        index_factory: Callable[[Settings], SemanticMemoryIndex] | None = None,
    ) -> None:
        self._settings = settings
        self._repository = SqlAlchemySemanticMemoryRepository(session_factory)
        self._telemetry = telemetry or NoOpMetricsRecorder()
        self._embedding_provider_factory = embedding_provider_factory or (
            lambda value: create_embedding_provider(
                value, value.semantic_memory_query_timeout_seconds
            )
        )
        self._index_factory = index_factory or (
            lambda value: create_semantic_index(
                value, value.semantic_memory_query_timeout_seconds
            )
        )

    async def retrieve(
        self,
        query_text: str,
        *,
        assistant_id: UUID,
        platform_connection_id: UUID,
        conversation_id: UUID,
        scope: MemoryScope,
        planning_job_id: UUID | None = None,
        before_io: Callable[[], Awaitable[bool]] | None = None,
    ) -> tuple[ContextMemory, ...]:
        if not self._settings.semantic_memory_enabled or not query_text.strip():
            return ()
        if not self._settings.embedding_provider or not self._settings.embedding_model:
            return ()
        version = embedding_version(
            self._settings.embedding_provider,
            self._settings.embedding_model,
            self._settings.embedding_dimension,
        )
        provider = self._embedding_provider_factory(self._settings)
        governance_limiter = None
        governance_concurrency = None
        if self._settings.provider_governance_mode != "legacy":
            from app.infrastructure.governed_provider import GovernedEmbeddingProvider

            if planning_job_id is None:
                self._record_fallback("governance_unavailable", provider.provider_id)
                await provider.aclose()
                return ()
            governance = SqlAlchemyProviderGovernanceRepository(
                self._repository.session_factory,
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
                self._telemetry.increment(
                    "january_provider_routing_decisions_total",
                    workload="embedding",
                    operation="semantic_query",
                    route_role="primary",
                    outcome="denied",
                    reason="invalid_policy",
                )
                self._record_fallback("governance_unavailable", provider.provider_id)
                await provider.aclose()
                return ()
            if not routes:
                self._telemetry.increment(
                    "january_provider_routing_decisions_total",
                    workload="embedding",
                    operation="semantic_query",
                    route_role="primary",
                    outcome="denied",
                    reason="no_route",
                )
                self._record_fallback("unsupported_capability", provider.provider_id)
                await provider.aclose()
                return ()
            route = routes[0]
            if (
                route.provider_id.value != provider.provider_id
                or route.model != provider.model
            ):
                self._record_fallback("unsupported_capability", provider.provider_id)
                await provider.aclose()
                return ()
            governance_limiter = (
                RedisRateLimiter(self._settings)
                if self._settings.rate_limit_enabled
                else None
            )
            governance_concurrency = (
                RedisConcurrencyLimiter(self._settings)
                if self._settings.provider_concurrency_enabled
                else None
            )
            provider = GovernedEmbeddingProvider(
                provider,
                route,
                source,
                ProviderOperation.SEMANTIC_QUERY,
                governance,
                self._settings,
                governance_limiter,
                governance_concurrency,
                self._telemetry,
                before_io=before_io,
            )
        index = self._index_factory(self._settings)
        try:
            if before_io is not None and not await before_io():
                return ()
            vector = await embed_with_controls(
                self._settings, provider, query_text, self._telemetry
            )
            collection = await self._repository.active_collection(
                version,
                collection_name(self._settings.qdrant_collection_prefix, version),
            )
            if before_io is not None and not await before_io():
                return ()
            matches = await index.query(
                collection,
                vector,
                assistant_id=assistant_id,
                platform_connection_id=platform_connection_id,
                conversation_id=conversation_id,
                scope=scope,
                embedding_version=version,
                limit=self._settings.semantic_memory_top_k,
                minimum_score=self._settings.semantic_memory_min_score,
            )
            canonical = await self._repository.revalidate_matches(
                tuple(item.memory_id for item in matches),
                assistant_id=assistant_id,
                platform_connection_id=platform_connection_id,
                conversation_id=conversation_id,
                scope=scope,
            )
            selected = tuple(
                ContextMemory(*canonical[match.memory_id])
                for match in matches
                if match.memory_id in canonical
            )
            self._telemetry.increment(
                "january_semantic_memory_queries_total",
                outcome="success",
                provider=provider.provider_id,
            )
            return selected
        except EmbeddingError as exc:
            self._record_fallback(exc.category.value, provider.provider_id)
            return ()
        except Exception:
            self._record_fallback("qdrant_unavailable", provider.provider_id)
            return ()
        finally:
            await provider.aclose()
            await index.aclose()
            if governance_limiter is not None:
                await governance_limiter.aclose()
            if governance_concurrency is not None:
                await governance_concurrency.aclose()

    def _record_fallback(self, reason: str, provider: str) -> None:
        self._telemetry.increment(
            "january_semantic_memory_queries_total",
            outcome="fallback",
            provider=provider,
        )
        self._telemetry.increment(
            "january_semantic_memory_fallback_total",
            reason=reason,
        )


async def embed_with_controls(
    settings: Settings,
    provider: EmbeddingProvider,
    text: str,
    telemetry: MetricsRecorder | None = None,
) -> EmbeddingVector:
    """Apply distributed limits immediately before real embedding I/O."""
    recorder = telemetry or NoOpMetricsRecorder()
    governed = bool(getattr(provider, "governed", False))
    limiter = (
        RedisRateLimiter(settings)
        if settings.rate_limit_enabled and not governed
        else None
    )
    concurrency = (
        RedisConcurrencyLimiter(settings)
        if settings.provider_concurrency_enabled and not governed
        else None
    )
    lease = None
    try:
        if limiter is not None:
            decision = await limiter.check(
                RateLimitOperation.EMBEDDING,
                (embedding_provider_rule(settings, provider.provider_id),),
            )
            if not decision.allowed:
                raise EmbeddingError(
                    EmbeddingErrorCategory.RATE_LIMITED, provider.provider_id, True
                )
        if concurrency is not None:
            lease = await concurrency.acquire(ProviderId(provider.provider_id))
            if lease is None:
                raise EmbeddingError(
                    EmbeddingErrorCategory.RATE_LIMITED, provider.provider_id, True
                )
        started = perf_counter()
        try:
            vector = await provider.embed_text(text)
        except EmbeddingError as exc:
            recorder.increment(
                "january_embedding_requests_total",
                provider=provider.provider_id,
                outcome=exc.category.value,
            )
            recorder.observe(
                "january_embedding_request_duration_seconds",
                perf_counter() - started,
                provider=provider.provider_id,
                outcome=exc.category.value,
            )
            raise
        except Exception:
            recorder.increment(
                "january_embedding_requests_total",
                provider=provider.provider_id,
                outcome="unexpected_error",
            )
            recorder.observe(
                "january_embedding_request_duration_seconds",
                perf_counter() - started,
                provider=provider.provider_id,
                outcome="unexpected_error",
            )
            raise
        recorder.increment(
            "january_embedding_requests_total",
            provider=provider.provider_id,
            outcome="success",
        )
        recorder.observe(
            "january_embedding_request_duration_seconds",
            perf_counter() - started,
            provider=provider.provider_id,
            outcome="success",
        )
        return vector
    finally:
        if lease is not None and concurrency is not None:
            await concurrency.release(lease)
        if limiter is not None:
            await limiter.aclose()
        if concurrency is not None:
            await concurrency.aclose()
