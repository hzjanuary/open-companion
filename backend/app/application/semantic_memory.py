"""Typed, provider-neutral semantic explicit-memory contracts."""

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from typing import Protocol
from uuid import UUID

from app.domain.persistence import MemoryScope

EMBEDDING_SCHEMA_VERSION = "explicit-memory-embedding-v1"


class EmbeddingErrorCategory(StrEnum):
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INVALID_INPUT = "invalid_input"
    INVALID_VECTOR = "invalid_vector"
    AUTHENTICATION = "authentication"
    RATE_LIMITED = "rate_limited"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TRANSPORT = "transport"
    BUDGET_EXHAUSTED = "budget_exhausted"
    GOVERNANCE_UNAVAILABLE = "governance_unavailable"


@dataclass(frozen=True, slots=True)
class EmbeddingError(Exception):
    category: EmbeddingErrorCategory
    provider_id: str
    retryable: bool

    def __str__(self) -> str:
        return f"embedding {self.provider_id}: {self.category.value}"


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    values: tuple[float, ...]

    @classmethod
    def validated(cls, values: tuple[float, ...], dimension: int) -> "EmbeddingVector":
        if len(values) != dimension or not all(isfinite(value) for value in values):
            raise EmbeddingError(
                EmbeddingErrorCategory.INVALID_VECTOR, "unknown", False
            )
        return cls(values)


class EmbeddingProvider(Protocol):
    provider_id: str
    model: str
    dimension: int

    async def embed_text(self, text: str) -> EmbeddingVector: ...

    async def aclose(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SemanticMemoryPoint:
    memory_id: UUID
    assistant_id: UUID
    platform_connection_id: UUID
    conversation_id: UUID
    scope: MemoryScope
    embedding_version: str

    def payload(self) -> dict[str, str]:
        """The complete permitted Qdrant payload; never include memory text."""
        return {
            "memory_id": str(self.memory_id),
            "assistant_id": str(self.assistant_id),
            "platform_connection_id": str(self.platform_connection_id),
            "conversation_id": str(self.conversation_id),
            "scope": self.scope.value,
            "embedding_version": self.embedding_version,
        }


@dataclass(frozen=True, slots=True)
class SemanticMemoryMatch:
    memory_id: UUID
    score: float


class SemanticMemoryIndex(Protocol):
    async def ensure_collection(self, collection: str, dimension: int) -> None: ...

    async def health(self) -> bool: ...

    async def upsert(
        self, collection: str, point: SemanticMemoryPoint, vector: EmbeddingVector
    ) -> None: ...

    async def delete(self, collection: str, memory_id: UUID) -> None: ...

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
    ) -> tuple[SemanticMemoryMatch, ...]: ...

    async def count(self, collection: str) -> int | None: ...

    async def list_memory_ids(self, collection: str) -> tuple[UUID, ...]: ...

    async def aclose(self) -> None: ...


def embedding_version(provider_id: str, model: str, dimension: int) -> str:
    payload = f"{EMBEDDING_SCHEMA_VERSION}|{provider_id}|{model}|{dimension}"
    return sha256(payload.encode("ascii")).hexdigest()[:16]


def collection_name(prefix: str, version: str) -> str:
    return f"{prefix}_{version}"
