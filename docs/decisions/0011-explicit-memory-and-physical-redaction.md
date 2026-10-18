# ADR 0011: Explicit Memory and Physical Redaction

## Decision

January persists only user-commanded explicit facts with exact
same-conversation visibility. Deleted content is physically cleared while small
technical tombstones and content-free memory events remain. A dedicated
PostgreSQL worker enforces the 30-day raw-content limit.

## Consequences

The system does not infer memory subjects, create memory automatically, or
retrieve across conversations. Audit and operational logs use IDs, codes,
counts, and durations rather than content. Privacy changes invalidate future
use of affected content but cannot retract already completed/in-flight external
requests. Retention is bounded and idempotent and does not delete volumes or
backups.
