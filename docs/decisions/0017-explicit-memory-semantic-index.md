# 0017 Explicit Memory Semantic Index

Status: Accepted

## Decision

PostgreSQL is the authoritative source for explicit-memory text, active/deleted
state, and exact Assistant/platform-connection/conversation scope. Qdrant is a
rebuildable derived index only. It stores vectors plus content-free opaque
metadata, never memory text or source conversation content.

Only active user-created explicit-memory text may be embedded. Raw messages,
conversation summaries, generated responses, prompts, and deleted/redacted
memories are excluded. Qdrant query IDs are mandatory PostgreSQL-revalidation
candidates, not memory truth.

Collections are versioned from embedding provider, configured model, dimension,
and application schema version. Index updates use deterministic memory UUID
point IDs and durable PostgreSQL jobs. Semantic retrieval is optional and falls
back to existing explicit-memory selection when embedding or Qdrant is absent.
An operator rebuild writes a fresh physical collection, validates its opaque
point IDs against active canonical rows, then records that collection as active
for the compatible embedding version. Older collections are retained until a
separately authorized cleanup.

## Consequences

Canonical PostgreSQL backups can rebuild Qdrant. Privacy deletion becomes
immediately safe from PostgreSQL state even while asynchronous point cleanup is
pending. Embeddings remain privacy-sensitive derived data and must not be
logged, exported, or treated as anonymous.
