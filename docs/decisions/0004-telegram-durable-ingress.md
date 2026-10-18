# 0004 Telegram Durable Ingress

Date: 2026-07-29

## Status

Accepted

## Decision

Use mutually exclusive Telegram webhook or polling delivery modes. Both feed a
shared PostgreSQL inbox/outbox transaction, then a Redis 7 Stream carries only
typed references with a stable internal incoming-update ID. Webhook lifecycle
changes are explicit operator commands. Polling and outbox dispatch are
separate runtimes, never API-instance background loops.

## Consequences

The database is the durable idempotency authority and Redis delivery is
at-least-once, not exactly-once. Downstream consumers must remain idempotent by
incoming update ID. Raw Telegram bodies stay in PostgreSQL infrastructure data
and are not placed in Stream events. The business consumer is deferred to
SPEC-005.
