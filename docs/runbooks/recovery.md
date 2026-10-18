# Recovery

Recovery is a local privileged operation. It never exposes content, Telegram
identifiers, command arguments, prompts, or credentials.

Use `uv run python -m app.runtime.operations inspect` for aggregate work-state,
oldest-pending-age, active/stale-lease, dead-letter, and quarantine counts;
`show <opaque-id>` returns one content-safe durable item. A dead letter is known-safe work
that exhausted a bounded retry budget without an ambiguous external effect. A
quarantine is non-replayable work: notably `delivery_unknown`, where Telegram
may already have sent a message. Quarantine is never automatically retried.

Replay only one confirmed dead letter with `replay --kind planning --id <id>
--confirm` (or `outbound`). The transaction rechecks the item, rejects active
leases/completed/quarantine items, retains attempts and identity, and appends a
content-free audit event. No provider or Telegram I/O occurs in that transaction.

For an incident, stop planning and outbound before freezing external effects;
inspect recovery state; restore PostgreSQL/Redis; then resume normal workers.
Do not routinely downgrade a production database as rollback.

Conversation-summary jobs have no Telegram side effect and are not delivery
quarantines. Any retry or replay must re-check feature gates, source-window
identity, privacy state, and retention before provider I/O; invalid/expired
source windows are terminal and never replayed from stored summary text.

`./scripts/validate-scalability.sh` runs the local two-worker ingress burst and
prints its observed item count, duplicate-effect count, and elapsed time. These
are repeatable local observations, not production latency or SLO claims.
