# Semantic Memory

Semantic memory is disabled by default. It retrieves only explicit memories
saved through `/memory remember`; it never creates memory from raw messages or
conversation summaries.

Configure a local Ollama embedding capability and Qdrant only when enabling it:

```bash
JANUARY_SEMANTIC_MEMORY_ENABLED=true
JANUARY_SEMANTIC_MEMORY_WORKER_ENABLED=true
JANUARY_EMBEDDING_PROVIDER=ollama
JANUARY_EMBEDDING_MODEL=<operator-selected-model>
JANUARY_EMBEDDING_DIMENSION=<model-dimension>
uv run python -m app.runtime.semantic_memory_index_worker --once
```

## Capability Boundary

| Capability | Current support | Notes |
| --- | --- | --- |
| Ollama embeddings | Supported | Local `/api/embed`; the operator selects model and dimension. |
| OpenAI, Gemini, Groq, OpenRouter chat adapters | Not embedding-capable in January | Their configured chat capability does not imply embedding support. |
| Qdrant | Supported derived index | Local Compose service only; it never owns canonical memory text. |

Canonical validation uses deterministic fake embeddings. It neither pulls an
Ollama model nor makes a provider request.

Qdrant is derived data. It stores no memory text, previews, raw Telegram IDs,
queries, prompts, or provider bodies. PostgreSQL revalidates every returned
memory ID before canonical text enters context. A Qdrant or embedding outage
falls back to normal explicit-memory selection.

Use content-free local operations with explicit confirmation:

```bash
uv run python -m app.runtime.semantic_memory_operations status
uv run python -m app.runtime.semantic_memory_operations backfill --confirm
uv run python -m app.runtime.semantic_memory_operations reconcile --confirm
uv run python -m app.runtime.semantic_memory_operations rebuild --confirm
```

`backfill` schedules idempotent UPSERT work for the active compatible
collection. `reconcile` also removes point IDs absent from canonical active
PostgreSQL rows. `rebuild` creates a fresh physical collection, drains durable
jobs using the configured embedding capability, verifies its opaque ID set
against active PostgreSQL rows, and then atomically records it as the active
collection for that embedding version. Existing collections remain untouched;
a failed rebuild does not switch query routing. Do not use database downgrade
as semantic rollback. Set both semantic flags to `false` to restore existing
explicit-memory context behavior immediately; status, cleanup, and rebuild
operations remain available whenever an embedding configuration is supplied.

The API's `/ready` endpoint does not depend on Ollama, Qdrant, or the optional
semantic worker. A semantic outage therefore degrades only semantic selection;
normal bounded explicit-memory fallback and response planning continue.
`status` reports only content-free configuration, job counts, point count, and
an optional opaque-ID drift count when Qdrant is reachable.
`JANUARY_SEMANTIC_MEMORY_QUERY_TIMEOUT_SECONDS` defaults to one second and
applies only to response-path embedding/Qdrant requests; worker indexing keeps
its separate longer adapter timeout and durable retry behavior.

The worker claims jobs under a PostgreSQL lease. Transient embedding or Qdrant
failures are rescheduled with bounded exponential delay; invalid vectors and
exhausted attempts become content-free terminal `failed` jobs visible through
`status`. Repair configuration before scheduling a new backfill or rebuild.
When an operator changes embedding configuration, deletion schedules cleanup
for every known historical embedding version of the memory; the worker routes
each DELETE to that version's active derived collection. A missing collection
or point is already-clean cleanup, not an error.

PostgreSQL backups are sufficient for recovery. Restore PostgreSQL, start an
empty local Qdrant instance, then backfill. Deleted memory remains absent
because deletion is rechecked from PostgreSQL before every upsert and query.

Run local deterministic proof with:

```bash
./scripts/validate-semantic-memory.sh
```
