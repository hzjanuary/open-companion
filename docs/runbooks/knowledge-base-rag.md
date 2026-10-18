# Knowledge Base / RAG operations

SPEC-033 adds optional Assistant-scoped reference knowledge. PostgreSQL is the
only authority for content, lifecycle, ownership, current revisions, and index
work. Qdrant is disposable derived state and must never be backed up as an
authoritative content store.

## Deploy and enable

1. Back up PostgreSQL and apply `0022_knowledge_base_rag`.
2. Configure the existing governed local embedding route, model, dimension, and
   budgets. Set `JANUARY_KNOWLEDGE_RAG_ENABLED=true`; run the `knowledge-index`
   service with `JANUARY_KNOWLEDGE_INDEX_WORKER_ENABLED=true` (the staging
   Compose profile is `knowledge-rag`).
3. As `tenant_owner` or `tenant_admin`, create a draft knowledge base and
   documents through `/control/v1`. Submit a positive document revision and
   wait for the revision to become `ready`. Submitting the same checksum at the
   same expected revision is idempotent; a competing revision returns 409.
4. Set the Assistant knowledge flag using optimistic revision control, then
   activate the knowledge base. Both gates are required before query embedding
   or Qdrant search occurs.

Only JSON Unicode `text/plain` and `text/markdown` content is accepted. There
is no upload, PDF/DOCX/OCR, crawler, URL fetch, or source-reference resolution.
Source references are inert provenance strings. Owners/admins mutate and see
bounded metadata; content is write-only. Auditors see content-free lifecycle,
counts and index state. Operator, viewer, deployment-only and foreign-tenant
access is denied.

Keep the feature and every Assistant flag off during initial migration. Turning
off either gate is an immediate fail-closed rollback that needs no Qdrant
operation. Draft and disabled bases can be edited/reindexed; retired is
terminal.

## Status, reindex, and recovery

The Assistant-scoped status and reindex routes are content-free. Deployment
commands also return content-free JSON:

```bash
PYTHONPATH=backend .tools/uv run python -m app.runtime.knowledge_operations status
PYTHONPATH=backend .tools/uv run python -m app.runtime.knowledge_operations backfill --confirm
PYTHONPATH=backend .tools/uv run python -m app.runtime.knowledge_operations reconcile --confirm
PYTHONPATH=backend .tools/uv run python -m app.runtime.knowledge_operations rebuild --confirm
```

`backfill` coalesces UPSERT work for authoritative current chunks. `reconcile`
also deletes derived IDs that PostgreSQL no longer accepts. `rebuild` creates a
fresh versioned collection, replays canonical PostgreSQL chunks through
governed embeddings, proves exact ID parity, and only then switches the active
collection row. Failure leaves the old route active. Do not copy text into
Qdrant payloads or manually promote a collection.

When Qdrant or embeddings are unavailable, Telegram planning continues without
knowledge. Durable work uses bounded retries and stale-lease reclamation; it is
not exactly once. Investigate `january_knowledge_queries_total`,
`january_knowledge_fallback_total`, `january_knowledge_index_jobs_total`, the
content-free index status endpoint, and durable job failure categories. Do not
log prompts, chunk text, vectors, IDs as metric labels, or Qdrant request bodies.

## Delete, backup, and restore

Document deletion commits first in PostgreSQL: the document is tombstoned,
revision and chunk text/checksums are redacted, and durable delete jobs are
scheduled for every known collection. Deleting the last activation-ready
document disables its active base. A retired base becomes non-retrievable
immediately and schedules derived cleanup. Stale Qdrant points are harmless
because query results are revalidated against the current PostgreSQL chain.
Retry or reconcile cleanup after Qdrant recovers.

Back up PostgreSQL with the normal database procedure. After restore, discard
the knowledge Qdrant collection and run `rebuild --confirm`; never restore
Qdrant as a substitute for PostgreSQL. A populated downgrade is intentionally
refused with `SPEC-033 knowledge state blocks downgrade`. Disable retrieval and
the worker for rollback, preserve the database at 0022, and restore the prior
binary only if it tolerates the additive schema. Empty 0022→0021 reversal is
validated by `scripts/validate-knowledge-rag.sh`.

## Knowledge is not memory

Knowledge is tenant-operator reference material for one Assistant. Explicit
memory and personal context remain user-controlled conversation data. No
knowledge ingest, retrieval, deletion, reindex or rebuild creates memory rows or
semantic-memory points; memory workflows create no knowledge rows. The two
workers, collections, payload types, context fields, budgets and deletion paths
remain separate.
