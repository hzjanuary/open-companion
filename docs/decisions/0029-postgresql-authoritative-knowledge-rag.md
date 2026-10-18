# 0029 PostgreSQL-Authoritative Knowledge RAG

Date: 2026-09-13

## Status

Accepted under the Product Owner-authorized SPEC-033 implementation.

## Context

Assistant knowledge needs semantic retrieval, but vector indexes can be stale,
reset, malformed or incorrectly scoped. Knowledge content is tenant-provided
reference data and must remain distinct from user-controlled memory and from
system instruction authority.

## Decision

PostgreSQL is authoritative for knowledge ownership, content, lifecycle,
revision state and chunk text. Qdrant is a rebuildable, separate derived index
containing vectors plus opaque chain/version identifiers only. It contains no
document/chunk/title/source/URI text, prompts, responses, memory or participant
data.

Every Qdrant result is only a candidate. Before prompt inclusion, one bounded
PostgreSQL join must prove the exact tenant, Assistant, ACTIVE KB, nondeleted
document, current READY revision, live chunk and compatible index version.
Unknown, stale, deleted, disabled, superseded or foreign candidates are dropped.

Knowledge context is separately typed and serialized only as untrusted reference
material below system/safety/application/current-user authority. Knowledge
ingestion, retrieval, deletion, indexing and rebuild remain distinct from all
memory, personal-context and summary tables, jobs and Qdrant collections.

Embedding calls reuse SPEC-019's port/adapters and SPEC-026's governed attempt
boundary. Leased database work is loaded/revalidated in short transactions;
embedding and Qdrant I/O occur with no database session or lock.

## Consequences

- Stale Qdrant points cannot resurrect deleted or superseded content.
- Tenant/Assistant isolation is enforced in PostgreSQL and repeated in vector
  filters.
- Qdrant loss affects retrieval availability, not authoritative knowledge;
  rebuild restores derived state from PostgreSQL.
- Knowledge failure degrades to ordinary planning without KB context.
- Rich citations and general prompt-injection immunity are not claimed.
- Migration 0022 is guarded because populated authoritative knowledge cannot be
  silently removed by downgrade.

## Alternatives considered

1. Store chunk text in Qdrant: rejected because it bypasses authoritative
   lifecycle/revalidation and expands content copies.
2. Reuse explicit-memory points/collection: rejected because knowledge and user
   memory have different ownership, consent and deletion semantics.
3. Treat vector filters as sufficient authorization: rejected because derived
   indexes can be stale or malformed.
4. Fetch URLs/crawl sources: rejected because v1 needs no SSRF/remote ingestion
   surface.
5. Fail all planning when Qdrant fails: rejected because knowledge is optional
   enhancement, not a grounded-only response contract.

## Follow-up

Production enablement requires an approved embedding deployment and governance
configuration. User-visible verified citations or new ingestion formats require
separate product authority.
