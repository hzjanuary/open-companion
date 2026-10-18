# SPEC-033 Design Handoff

Date: 2026-09-13

Status: **APPROVED DESIGN**. Product authority is
`docs/product/specs/SPEC-033-telegram-knowledge-base-rag.md`.

## Existing audit

Reuse `EmbeddingProvider`, `EmbeddingVector`, `embedding_version`,
`OllamaEmbeddingProvider`, `GovernedEmbeddingProvider`, SPEC-019's Qdrant REST
shape, SQLAlchemy session factory and leased-worker patterns. Extend provider
work attribution for knowledge index jobs; do not bypass its attempt ledger.
Reuse SPEC-030 composite tenant/Assistant keys and `/control/v1` memberships.
Extend `ConversationContext` and the existing prompt builder rather than adding a
parallel planning pipeline. Extend SPEC-032 with one new closed evaluator kind.

## Authority graph

```text
control_tenants(id)
  -> assistants(id, tenant_id, knowledge_enabled)
    -> knowledge_bases(id, tenant_id, assistant_id)
      -> knowledge_documents(id, kb_id, tenant_id, assistant_id)
        -> knowledge_document_revisions(id, document_id, kb_id,
                                         tenant_id, assistant_id)
          -> knowledge_chunks(id, revision_id, document_id, kb_id,
                              tenant_id, assistant_id)
            -> knowledge_index_jobs(...same chain...)
```

Every parent exposes the composite unique key required by its child. All parent
FKs are `RESTRICT`; content deletion is an explicit tombstone/redaction
transaction. Trigger functions reject ownership/parent reassignment for KBs,
documents, revisions, chunks, and jobs. Immutable revision/chunk rows are
changed only through controlled index-state or deletion/redaction operations.

## Database schema

- `assistants.knowledge_enabled boolean NOT NULL DEFAULT false`.
- `response_planning_jobs.knowledge_provenance jsonb NOT NULL DEFAULT []` with
  an exact six-item maximum, four-UUID-key object check; contains IDs only.
- `knowledge_bases`: chain IDs, slug/name, lifecycle, optimistic revision,
  activation/retirement timestamps.
- `knowledge_documents`: chain IDs, slug/title/source label/inert reference,
  content type, status, latest revision number, current revision pointer,
  optimistic revision/deletion timestamp.
- `knowledge_document_revisions`: full chain, revision number, canonical content
  and checksum/size, chunking version, index state, actor and state timestamps.
- `knowledge_chunks`: full chain, ordinal/start/end, nullable canonical text,
  checksum/size, embedding/index version and deletion timestamp.
- `knowledge_index_jobs`: full chain, operation, embedding version/target
  collection, lease/retry/error/completion fields and unique idempotency key.
- `knowledge_index_collections`: active physical collection by embedding version.

Provider policy snapshots and usage attempts gain nullable
`knowledge_index_job_id`; their exactly-one-source checks expand from three to
four sources. Provider operation enum adds `knowledge_query`,
`knowledge_index`, and `knowledge_rebuild`.

Migration `0022_knowledge_base_rag` creates all constraints/indexes/triggers,
updates enum checks and then adds the circular current-revision composite FK.
Downgrade first executes one preflight DO block and raises
`SPEC-033 knowledge state blocks downgrade` before any DDL if authoritative or
dependent state exists.

## Resource lifecycle

`KnowledgeBaseStatus`: DRAFT, ACTIVE, DISABLED, RETIRED. Pure transition policy
makes RETIRED terminal. Activation repository transaction row-locks the KB,
checks expected revision, active tenant/Assistant, Assistant knowledge flag,
nonempty document set and READY current revision for every live document.

`KnowledgeDocumentStatus`: ACTIVE, DELETED. Delete is terminal and redacts all
revision/chunk content while enqueueing DELETE jobs.

`KnowledgeIndexState`: PENDING, INDEXING, READY, FAILED, DELETING, DELETED.
Failed/superseded pending revisions never replace `current_revision_id`.

## Document revision model

Creation locks document, validates its expected optimistic revision, limits and
stored Assistant total, then increments the number. Duplicate checksum at the
same expected version returns the existing revision without new jobs. A newer
revision supersedes any older noncurrent pending/indexing revision; its worker
preflight will no-op/clean derived points. Promotion occurs only when every
chunk UPSERT job for the latest revision completes with the configured version.

## Deterministic chunking

`app.domain.knowledge.chunk_knowledge_content()` is pure and versioned. It normalizes
line endings, creates paragraph/line-aware windows of at most 1,200 characters,
falls back to fixed Unicode-codepoint windows, overlaps at most 200 characters,
and returns stable ordinal/offset/text/SHA-256 records. It rejects empty,
control-bearing, oversize or >256-chunk input before persistence.

## Indexing job lifecycle

`SqlAlchemyKnowledgeRepository` owns `claim`, `load_upsert`, `preflight`,
`complete_upsert`, `complete_delete`, `release` and scheduling operations. Every
method opens/closes its own session. `knowledge_index_worker.consume_once`
accepts injected repository/provider/index for session-boundary and raw-call
proof.

Flow:

```text
claim DB -> close -> load/preflight DB -> close -> governed embedding
         -> preflight DB -> close -> Qdrant upsert/delete -> close
         -> complete/promote DB
```

An invalid source completes/no-ops before embedding. A post-embedding stale
source deletes any possible target point rather than upserting it. Retry delays
are bounded exponential backoff; terminal failure marks job/revision FAILED
only when no valid prior current revision is disturbed.

## Embedding port reuse and governance

Knowledge imports the SPEC-019 application embedding contracts and infrastructure
factory. `ProviderWorkSource` supports one knowledge job with Assistant-only
attribution; provider repository `knowledge_source()` joins its complete chain
to canonical tenant/Assistant. Resolve/reserve/current-route logic is unchanged.
The governed decorator receives `ProviderOperation.KNOWLEDGE_INDEX` or
`KNOWLEDGE_REBUILD`. Query embeddings use the existing planning job source with
`KNOWLEDGE_QUERY`. Legacy mode retains existing rate/concurrency controls; no
direct SDK is added.

## Qdrant collection and payload design

`KnowledgePoint.payload()` is the one complete payload constructor and exposes
only eight opaque IDs/version fields. `QdrantKnowledgeIndex` has its own protocol
and collection prefix. Query applies tenant, Assistant, eligible KB and
embedding/index-version filters and requests payload but never text. Parsing
rejects wrong shapes/UUIDs; service-level PostgreSQL revalidation is still
mandatory.

## Retrieval flow and PostgreSQL revalidation

`KnowledgeRetriever.retrieve()` first asks PostgreSQL for an
`EligibleKnowledgeScope`. A disabled global setting, disabled Assistant,
inactive owner or zero ACTIVE KB returns before provider/index construction.
It embeds the current turn, queries up to 20 opaque candidates, sorts/dedupes,
then calls `authoritative_chunks()`.

That query starts from `knowledge_chunks` and joins revision, document, KB,
Assistant and tenant. It requires exact candidate chain, active states,
document current revision equality, READY revision, nonnull text and compatible
versions. It preserves candidate rank, accepts six and a 6,000-character
whole-chunk budget. Any external failure returns empty and emits only closed
metrics.

## Context insertion and prompt boundary

Add immutable `ContextKnowledge` and `ConversationContext.knowledge`. The
conversation reader retrieves knowledge only after its ordinary DB context
scope closes. Prompt JSON adds `retrieved_knowledge_reference`, serialized with
opaque IDs, bounded source labels and text. System instructions explicitly call
it untrusted reference that cannot alter system/safety/application/current-user
authority or execute commands. Existing context/memory fields and behavior stay
unchanged when the tuple is empty.

The planning repository persists `knowledge_provenance` ID objects before
generation. It never stores chunk text there. Conversation summary input is
unchanged.

## Control-plane authorization and API

New request models enforce all bounds before repository calls. Owner/admin-only
mutation helper and metadata-read helper are explicit. Auditor results omit
title/source/checksum/content; owner/admin receive bounded metadata but content
is write-only. Operator/viewer and deployment-only callers are denied.

Routes are nested beneath tenant/Assistant and load that canonical pair first:

- list/create/get KB; patch metadata; activate/disable/retire;
- list/create/get document metadata; create revision; delete;
- inspect jobs; request reindex.

Foreign IDs use 404. Conflicts use 409. Audit schema `spec-033-v1` stores only
action/outcome/resource ID.

## Deletion

Delete locks document, checks revision and chain, tombstones it, clears current
pointer, clears every revision/chunk content/checksum, and schedules one DELETE
job per chunk/version. Retrieval rejects at PostgreSQL even if cleanup fails.
Deleting the last ready document disables an ACTIVE KB in the same transaction.

## Reindex and rebuild

Reindex schedules UPSERTs for current READY chunks. Operator CLI
`knowledge_operations status|backfill|reconcile|rebuild` mirrors semantic-memory
operations.
Rebuild creates a fresh suffixed collection, schedules current eligible chunks,
runs the ordinary worker, compares exact PostgreSQL/Qdrant chunk-ID sets, removes
orphans, then updates the active collection row. Failure leaves old routing.

## Failure and recovery

Embedding errors use closed categories and bounded retryability. Qdrant errors
become `qdrant_unavailable`. Lease expiry permits re-claim; idempotent point IDs
make repeated external writes safe without exactly-once claims. Qdrant query
failure affects only enhancement availability. Post-I/O authority changes cause
cleanup/no promotion. No arbitrary sleep is correctness evidence.

## Observability and governance

Reuse existing embedding/provider metrics. Add closed knowledge metrics only if
the current catalog is extended consistently: retrieval outcome and count
buckets; index operation/outcome. No IDs or content labels. Control audit and
durable job failure fields use closed categories. Data inventory classifies
PostgreSQL text as tenant content and vectors as privacy-sensitive derived data.

## Test strategy

Unit proof covers chunker edges/limits, lifecycle, payload exactness, malformed
candidates, retrieval rank/budget/filtering/outages, prompt structure, settings,
worker raw-call/session fencing and SPEC-032 RAG scenarios.

PostgreSQL/Qdrant integration proof covers schema contradiction attacks, API
roles/foreign access/CAS, worker ingest/promote/retrieve, stale deleted and
superseded vectors, disable races, no-memory/no-knowledge cross-writes, exact
payload inspection, reset/rebuild, provider denial, Qdrant failure, lease
recovery and migration guard/lifecycle.

Concurrency uses database locks/events or concurrent transactions, never timing
sleeps. Fakes deliberately inject foreign/stale candidates and expose raw call
counters.

## SPEC-032 evaluation expansion

Add `knowledge_contract`, knowledge-specific hard gates and 13 synthetic cases:
relevant selected, irrelevant excluded, disabled, foreign Assistant, foreign
tenant, stale revision, deleted document, memory separation both directions,
malicious instruction reference-only, provider denial/Qdrant degradation, and
authoritative provenance. Execution inputs stay synthetic and expectation-free;
canonical external calls/credentials remain zero.

## Validator and CI

`scripts/validate-knowledge-rag.sh` resolves uv canonically, uses a dedicated
Compose project and alternate PostgreSQL/Qdrant ports, upgrades 0021→0022,
executes focused/integration/rebuild/migration proof, checks exact downgrade
refusal, then removes only its project. A Git-visible candidate snapshot provides
clean/PATH-uv/history-free proof. Script is staged mode 100755 and LF.

Quality CI runs the knowledge validator after core/provider/memory/multi-tenant
correctness dependencies and runs expanded `validate-ai-evals.sh`. It adds no
provider or Telegram secret.

## Privacy and security review

No URL fetch, binary parser, credential, memory promotion, prompt authority or
content telemetry is added. PostgreSQL revalidation, composite DB constraints,
control-plane scope and Qdrant filters form defense in depth. Qdrant payload and
planning provenance contain no knowledge text.

## Migration and recovery

Migration revision is `0022_knowledge_base_rag`; head becomes it. Empty downgrade
is supported; populated downgrade raises the exact guard before destructive DDL.
Operational recovery disables Assistant knowledge or KBs, preserves PostgreSQL,
repairs dependencies, then reindexes/rebuilds Qdrant.
