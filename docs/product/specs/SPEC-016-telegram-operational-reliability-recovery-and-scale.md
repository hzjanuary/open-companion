# SPEC-016 Telegram Operational Reliability, Recovery, and Scale

SPEC-016 completes the Telegram MVP reliability track without a Zalo runtime or
SPEC-017 work. Durable work is classified content-free as either a replayable
dead letter (known no ambiguous external effect) or a quarantine (an external
effect may have occurred). `delivery_unknown` is always quarantine.

Recovery is local-operator-only: `uv run python -m app.runtime.operations
inspect`, `show <opaque-id>`, and `replay --kind <planning|outbound> --id
<opaque-id> --confirm`. Replay handles one dead letter, rechecks durable state
in its transaction, preserves business identity/idempotency, and never makes
external I/O. Quarantined, completed, and leased work is refused.

Conversation processing is serialized across processes with a PostgreSQL
transaction advisory lock keyed by January conversation identity. Provider
concurrency uses Redis TTL leases scoped to provider and is distinct from the
existing throughput rate limiter.
