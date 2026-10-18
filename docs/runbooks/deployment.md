# Deployment

SPEC-020 adds the target-neutral deployment lifecycle and staging-shaped
Compose artifact. Use `docs/runbooks/production-operations.md` for startup,
drain, secret rotation, failure recovery, rollback, and evidence requirements.
`compose.staging.yaml` requires externally supplied values and contains no
production secret defaults; it is not a production orchestrator contract.

Before deployment run the canonical validators, take a PostgreSQL backup, check
schema compatibility, and verify required secret *presence* without printing
values. Preflight that Telegram uses exactly one of polling or webhook mode.
Apply `0021_multi_assistant_tenancy` before starting SPEC-030 binaries. The
migration preserves consistent legacy ownership, refuses contradictory tenant
signals, and may refuse downgrade when canonical tenant, slug, revision, or
lifecycle state would be lost. Do not bypass its guard or manually reparent
Assistants/connections.

Start PostgreSQL, Redis, API, dispatcher, conversation worker, command worker,
planning worker, outbound worker, enabled proactive scheduler, then governance
and retention workers. The scheduler is required only when both SPEC-029 feature
and worker flags are enabled; it depends on the migration and the outbound role,
does no external I/O, and recovers expired occurrence leases. Configure rate
limits and provider concurrency independently. Before restarting after an
incident, inspect dead letters and quarantines. Roll back application code when
possible; database downgrade is an exceptional, explicitly scoped recovery
action.

Bootstrap now requires `JANUARY_TELEGRAM_TENANT_ID` when more than one active
tenant exists; otherwise exactly one active tenant may be selected. A
connection, Assistant, and tenant must all be active before ingress, provider,
scheduling, media, command authorization, or outbound external I/O. Disable is
therefore an immediate operational fence, not just control-plane metadata.

The optional conversation-summary worker starts only when both summary flags are
enabled. It can be stopped independently without interrupting raw-history
planning. To roll back summary behavior, disable both flags; do not delete the
stored summaries because retention and privacy cleanup still apply.

The optional semantic-memory index worker starts separately. PostgreSQL remains
authoritative; stop semantic query use by disabling both semantic flags, then
continue deletion/reconciliation work from canonical PostgreSQL state as needed.
