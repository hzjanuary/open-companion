# Telegram-first Release Checklist

Use this checklist only with an independently approved candidate. Completing
repository checks does not authorize production deployment.

## Pre-deploy

- [ ] Record the exact approved SHA and immutable image digest; confirm they
  correspond to the independently reviewed candidate.
- [ ] Confirm GitHub Quality is green for that exact SHA. SPEC-041 continuity
  starts from baseline `private-source-checkpoint-omitted` and run
  `36405527959`.
- [ ] Confirm source/worktree integrity and no unreviewed product, API, command,
  migration, or workflow change.
- [ ] Run `./scripts/validate-production-readiness.sh` offline.
- [ ] Run `--production-config` from the production secret/config injection
  context; retain only redacted pass/fail evidence.
- [ ] Verify no unresolved placeholder, local default, `.env`, real credential,
  debug logging, database echo, or demo-live flag.
- [ ] Confirm one Alembic source head: `0026_conversation_feedback` and run the
  read-only `--database-preflight` against the selected database.
- [ ] Confirm backup destination, retention, checksum/catalog verification,
  restore authority, RPO/RTO, and post-backup erasure-reapplication record.
- [ ] Confirm Telegram bot/connection, mode, token, webhook secret and DNS/TLS
  for webhook mode, or exclusive polling ownership.
- [ ] Confirm provider routes/capabilities, data eligibility, prices, hard/soft
  budgets, rate/concurrency limits, credentials, account credit, and ownership.
- [ ] Confirm optional TTS, media, semantic-memory, knowledge, summary, and
  scheduling features are either fully configured or explicitly disabled.
- [ ] Confirm safety, control-plane auth/bootstrap subjects, governance,
  retention, command, outbound, provider-recovery, and metrics controls.
- [ ] Confirm metrics backend/dashboards, alert thresholds/destinations,
  on-call, incident commander, deployment, rollback, restore, and privacy owners.
- [ ] Confirm PostgreSQL/Redis readiness and optional Qdrant degradation/rebuild
  procedure; verify pool/call/lease timeouts remain bounded and coherent.
- [ ] Confirm external acceptance scope, test chat, spend bound, traffic window,
  abort criteria, and operator approval. Never infer it from local proof.

## Deploy

- [ ] Disable external ingress/traffic and ensure one migration owner.
- [ ] Create and verify the authoritative PostgreSQL backup immediately before
  migration. Do not treat Redis/Qdrant snapshots as authoritative backup.
- [ ] Run the approved single-owner upgrade to
  `0026_conversation_feedback`; stop on any failure.
- [ ] Repeat database preflight and confirm the exact current revision.
- [ ] Start API, verify `/live`, then require `/ready` before worker rollout.
- [ ] Start dispatcher, conversation, planning, command, outbound, scheduler,
  governance, retention, provider-governance, and only enabled optional workers.
- [ ] Verify worker start/drain evidence, leases, backlogs, Redis coordination,
  and no unexpected retry/unknown spike.
- [ ] Register webhook or start polling, never both. Enable traffic gradually.

## Post-deploy

- [ ] Verify `/live`, `/ready`, component health, schema revision, database pool,
  Redis, and optional Qdrant degradation status.
- [ ] Verify dispatcher/conversation/planning/command/outbound and privacy/
  retention/recovery worker liveness and bounded backlog.
- [ ] Exercise one bounded authorized inbox-to-outbox Telegram text flow and
  confirm idempotent update acceptance.
- [ ] Verify provider admission, route, budget/rate/concurrency accounting, and
  no unexpected fallback or ambiguous possible-I/O.
- [ ] If approved, exercise bounded reply/order, edit/regeneration, presence,
  reaction, voice/TTS, and feedback smoke only within the accepted test scope.
- [ ] Confirm no error, retry, `delivery_unknown`, provider ambiguity, DB pool,
  Redis, privacy-worker, or lease-recovery spike.
- [ ] Inspect content-safe metrics/logs: no prompt, response, memory, knowledge,
  audio bytes, token, secret, provider body, or prohibited identity label.
- [ ] Confirm retention, governance, provider recovery, scheduled work, export,
  erasure, derived cleanup, and voice-artifact purge status.
- [ ] Record live evidence as fresh, historical, or blocked on an exact external
  prerequisite. Never write “production deployed” before promotion is complete.

## Rollback or incident

- [ ] Stop/limit external ingress first when authority, privacy, duplicate-send,
  or uncontrolled-cost risk exists.
- [ ] Disable the affected provider/capability without weakening safety,
  privacy, tenant authority, or durable evidence.
- [ ] Classify provider possible-I/O and Telegram delivery-unknown; do not
  automatically repeat ambiguous external calls.
- [ ] Decide whether the prior application is compatible with the current
  schema. If yes, roll back image/config and reverify readiness/workers.
- [ ] Treat database downgrade as a separate exceptional decision. Never force
  a guarded downgrade or use manual `ALTER` as routine rollback.
- [ ] If downgrade is unsafe, keep current schema and forward-fix.
- [ ] Restore PostgreSQL only for authorized data loss/corruption. Reapply
  post-backup erasures, recreate Redis, rebuild/revalidate Qdrant, and rerun
  tenant/governance/memory authority checks before traffic.
- [ ] Escalate through the named incident/on-call/privacy/provider owners and
  preserve timestamps, image/config identifiers, bounded failure classes, and
  operator actions without content/secrets.
- [ ] Reopen traffic only after exact schema, `/ready`, worker recovery,
  backlog, safety/privacy, provider admission, and bounded Telegram smoke pass.
