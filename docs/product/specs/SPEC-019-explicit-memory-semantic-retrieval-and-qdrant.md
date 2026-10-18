# SPEC-019 Explicit Memory Semantic Retrieval And Qdrant Derived Index

Semantic retrieval is optional and disabled by default. It applies only to
active user-created explicit memories. PostgreSQL remains the source of truth;
Qdrant is a disposable derived index.

Only canonical active explicit-memory text is embedded. Raw messages,
conversation summaries, generated responses, prompts, provider bodies, and
deleted or redacted memories are never embedded. Qdrant stores vectors and
opaque internal scope metadata only, never memory text or previews.

Every query uses only the current incoming message as its embedding input. The
Qdrant query filters exact Assistant, platform connection, conversation, scope,
and embedding version. Returned IDs are reloaded from PostgreSQL and rechecked
for exact scope, active state, visibility, expiry, and canonical content before
anything reaches model context. Therefore stale points cannot resurrect a
forgotten memory.

Creation schedules an idempotent derived-index UPSERT after canonical memory
commit. `/forget`, group reset, and `/forget_me` make PostgreSQL deletion
authoritative immediately and schedule DELETE work. A separate optional worker
uses leases and retries. Qdrant or embedding failures fall back to the existing
bounded explicit-memory selection and do not make response planning fail.

Embedding capability is separate from chat generation. The initial production
adapter is local Ollama with an operator-selected model and dimension; tests use
deterministic fakes. A collection is versioned from provider, model, dimension,
and the embedding schema version, so incompatible dimensions never mix.

PostgreSQL backups contain canonical memories and index jobs. Qdrant backup is
optional acceleration only; an empty index can be backfilled from active
PostgreSQL memories. See `docs/runbooks/semantic-memory.md`.
