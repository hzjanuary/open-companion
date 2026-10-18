"""Ports and bounded values for the derived Assistant knowledge index."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.application.semantic_memory import EmbeddingVector


@dataclass(frozen=True, slots=True)
class KnowledgePoint:
    tenant_id: UUID
    assistant_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    revision_id: UUID
    chunk_id: UUID
    embedding_version: str
    index_schema_version: str

    def payload(self) -> dict[str, str]:
        return {
            "tenant_id": str(self.tenant_id),
            "assistant_id": str(self.assistant_id),
            "knowledge_base_id": str(self.knowledge_base_id),
            "document_id": str(self.document_id),
            "document_revision_id": str(self.revision_id),
            "chunk_id": str(self.chunk_id),
            "embedding_version": self.embedding_version,
            "index_schema_version": self.index_schema_version,
        }


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    chunk_id: UUID
    score: float


@dataclass(frozen=True, slots=True)
class ContextKnowledge:
    knowledge_base_id: UUID
    document_id: UUID
    revision_id: UUID
    chunk_id: UUID
    content: str
    score: float
    title: str | None = None
    source_label: str | None = None

    def provenance(self) -> dict[str, str]:
        return {
            "knowledge_base_id": str(self.knowledge_base_id),
            "document_id": str(self.document_id),
            "revision_id": str(self.revision_id),
            "chunk_id": str(self.chunk_id),
        }


class KnowledgeVectorIndex(Protocol):
    async def health(self) -> bool: ...

    async def ensure_collection(self, collection: str, dimension: int) -> None: ...

    async def upsert(
        self, collection: str, point: KnowledgePoint, vector: EmbeddingVector
    ) -> None: ...

    async def delete(self, collection: str, chunk_id: UUID) -> None: ...

    async def count(self, collection: str) -> int | None: ...

    async def list_chunk_ids(self, collection: str) -> tuple[UUID, ...]: ...

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
    ) -> tuple[KnowledgeCandidate, ...]: ...

    async def aclose(self) -> None: ...


def knowledge_collection_name(prefix: str, embedding_version: str) -> str:
    import hashlib

    digest = hashlib.sha256(embedding_version.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"
