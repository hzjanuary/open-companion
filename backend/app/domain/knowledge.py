"""Pure lifecycle and deterministic chunking policy for Assistant knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from unicodedata import category

KNOWLEDGE_CHUNK_SIZE = 1200
KNOWLEDGE_CHUNK_OVERLAP = 200
KNOWLEDGE_CHUNKING_VERSION = "knowledge-chunk-v1"
KNOWLEDGE_INDEX_SCHEMA_VERSION = "knowledge-index-v1"
MAX_KNOWLEDGE_BASES_PER_ASSISTANT = 20
MAX_DOCUMENTS_PER_KNOWLEDGE_BASE = 100
MAX_REVISIONS_PER_DOCUMENT = 20
MAX_DOCUMENT_CHARACTERS = 200_000
MAX_DOCUMENT_BYTES = 262_144
MAX_CHUNKS_PER_REVISION = 256
MAX_STORED_REVISION_CHARACTERS_PER_ASSISTANT = 5_000_000
MAX_OPEN_INDEX_JOBS_PER_ASSISTANT = 2_000
MAX_KNOWLEDGE_CANDIDATES = 20
MAX_KNOWLEDGE_CONTEXT_CHUNKS = 6
MAX_KNOWLEDGE_CONTEXT_CHARACTERS = 6_000


class KnowledgeBaseStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DISABLED = "disabled"
    RETIRED = "retired"


class KnowledgeDocumentStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class KnowledgeIndexState(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class KnowledgeIndexOperation(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


class KnowledgeIndexJobStatus(StrEnum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


class KnowledgeContentType(StrEnum):
    TEXT = "text/plain"
    MARKDOWN = "text/markdown"


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    ordinal: int
    start_offset: int
    end_offset: int
    content: str
    checksum: str


def normalize_knowledge_content(content: str) -> str:
    """Normalize line endings and validate bounded operator-authored text."""

    if not isinstance(content, str):
        raise ValueError("knowledge content must be text")
    value = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise ValueError("knowledge content must be valid UTF-8") from exc
    if not value.strip():
        raise ValueError("knowledge content must not be blank")
    if any(
        category(character) == "Cc" and character not in {"\n", "\t"}
        for character in value
    ):
        raise ValueError("knowledge content contains unsupported control characters")
    if len(value) > MAX_DOCUMENT_CHARACTERS or len(encoded) > MAX_DOCUMENT_BYTES:
        raise ValueError("knowledge content exceeds the document limit")
    return value


def chunk_knowledge_content(content: str) -> tuple[KnowledgeChunk, ...]:
    """Split text by stable character offsets; the algorithm is deliberately dull."""

    value = normalize_knowledge_content(content)
    chunks: list[KnowledgeChunk] = []
    start = 0
    while start < len(value):
        end = min(len(value), start + KNOWLEDGE_CHUNK_SIZE)
        if end < len(value):
            minimum_break = start + KNOWLEDGE_CHUNK_OVERLAP + 1
            paragraph_break = value.rfind("\n\n", minimum_break, end)
            line_break = value.rfind("\n", minimum_break, end)
            if paragraph_break >= minimum_break:
                end = paragraph_break + 2
            elif line_break >= minimum_break:
                end = line_break + 1
        text = value[start:end]
        ordinal = len(chunks)
        chunks.append(
            KnowledgeChunk(
                ordinal=ordinal,
                start_offset=start,
                end_offset=end,
                content=text,
                checksum=sha256(text.encode("utf-8")).hexdigest(),
            )
        )
        if end == len(value):
            break
        start = end - min(KNOWLEDGE_CHUNK_OVERLAP, end - start - 1)
    if len(chunks) > MAX_CHUNKS_PER_REVISION:
        raise ValueError("knowledge content exceeds the chunk limit")
    return tuple(chunks)


def knowledge_base_transition_allowed(
    current: KnowledgeBaseStatus, target: KnowledgeBaseStatus
) -> bool:
    return (
        target
        in {
            KnowledgeBaseStatus.DRAFT: {
                KnowledgeBaseStatus.DRAFT,
                KnowledgeBaseStatus.ACTIVE,
                KnowledgeBaseStatus.DISABLED,
                KnowledgeBaseStatus.RETIRED,
            },
            KnowledgeBaseStatus.ACTIVE: {
                KnowledgeBaseStatus.ACTIVE,
                KnowledgeBaseStatus.DISABLED,
                KnowledgeBaseStatus.RETIRED,
            },
            KnowledgeBaseStatus.DISABLED: {
                KnowledgeBaseStatus.DISABLED,
                KnowledgeBaseStatus.ACTIVE,
                KnowledgeBaseStatus.RETIRED,
            },
            KnowledgeBaseStatus.RETIRED: {KnowledgeBaseStatus.RETIRED},
        }[current]
    )
