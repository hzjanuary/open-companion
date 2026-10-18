# 0005 Conversation Processing Ledger

Date: 2026-07-29

## Status

Accepted

## Decision

Use PostgreSQL as the business-processing idempotency authority with one
`conversation_processing_records` row per durable incoming update. Normalize
Telegram input at the infrastructure boundary, commit conversation state and
the ledger in one transaction, then acknowledge the Redis Streams reference.

## Consequences

Redis remains at-least-once transport and contains references only. A duplicate
Stream delivery returns the existing ledger outcome and is acknowledged. A
transient database or queue failure remains pending for reclaim. Context is
assembled from normalized persisted messages with deterministic limits; it is
not a memory or model prompt execution mechanism.
