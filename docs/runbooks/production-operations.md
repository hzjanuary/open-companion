# Production Runtime Operations

This runbook covers the target-neutral lifecycle implemented by SPEC-020. It
does not select a cloud provider or replace the target-specific release
procedure that must be approved before production use.

## Preflight

1. Confirm the approved release image, environment, migration compatibility,
   maintenance window, and rollback owner.
2. Verify required secret references exist without printing values. Confirm
   staging and production namespaces are distinct.
3. Run the canonical validators, deployment validator, and offline release
   preflight:

   `./scripts/validate.sh`

   `./scripts/validate-deployment.sh`

   `./scripts/validate-production-readiness.sh`

   `./scripts/validate-telegram-conversation-ux.sh`

   `./scripts/validate-telegram-presence.sh`

   `./scripts/validate-telegram-reactions.sh`

   `./scripts/validate-telegram-voice-tts.sh`

   `./scripts/validate-conversation-feedback.sh`

   `./scripts/validate-reliability.sh`

   Follow the full [Telegram-first release-readiness contract](telegram-first-release-readiness.md)
   and [operator checklist](telegram-first-release-checklist.md). SPEC-040 remote
   closure is proven at baseline `0222704a…` by GitHub Quality run `36405527959`;
   every later candidate still needs green Quality on its own exact SHA.

4. Run `validate-production-readiness.sh --production-config` from the approved
   secret/config injection context. Retain only redacted pass/fail evidence.
   Then run `--database-preflight` against the selected database to record its
   current revision and verify the linear path to `0026_conversation_feedback`.

5. Take or verify the PostgreSQL backup and inspect dead letters, quarantines,
   stale leases, and pending work before changing external traffic.
6. Confirm Telegram uses exactly one of webhook or polling mode.
7. Verify bot identity against the approved connection record with the explicit
   SPEC-022 operation; see [`live-acceptance.md`](live-acceptance.md).

## Startup and rollout

SPEC-028 media remains opt-in. Apply 0019 and follow
[media enablement](telegram-media.md); the existing planning worker handles
downloads/transcription/current-turn images. Staging shares the bounded media
configuration across existing workers, with no new media service or volume.
Enable provider concurrency and enforce-mode media policies before activation.
SPEC-033 knowledge also remains opt-in: apply 0022, provision a governed local
embedding route/budget, run the separate knowledge-index role, ingest and index
draft content, then explicitly enable the Assistant and activate each ready KB.
See [knowledge-base operations](knowledge-base-rag.md).
SPEC-035 presence uses the existing planning role and Telegram credential; it
adds no service, setting, migration, or durable recovery state. Validate the
staging planning role with [Telegram presence operations](telegram-presence.md).
SPEC-037 reactions use that same planning role and Telegram adapter. They add
no service, setting, migration, durable recovery, or credential. Validate the
exact allowlist and current-authority fence with
[Telegram reaction operations](telegram-reactions.md).
SPEC-038 voice is opt-in: apply schema head `0026_conversation_feedback` (which
includes `0025_telegram_voice_tts`), provision an
enabled OpenAI `text_to_speech` capability/route with request pricing and hard
budget, enable provider governance/rate/concurrency, and keep command, outbound,
provider-governance, and retention roles running. Validate the staging command
and outbound roles with [Telegram voice operations](telegram-voice-tts.md)
before setting `JANUARY_TELEGRAM_VOICE_TTS_ENABLED=true`.
SPEC-039 feedback is always a local command-worker capability after schema head
`0026_conversation_feedback`; it adds no provider credential, route, service,
feature flag, or inspection endpoint. Validate its target/privacy boundaries
with [conversation feedback operations](conversation-feedback.md).

1. Start or verify PostgreSQL, Redis, and optional derived services.
2. Run the single-owner migration job and verify the expected Alembic head.
3. Start API replicas and verify `/live`, `/health`, `/ready`, and `/docs`.
4. Start dispatcher and enabled workers (poller, dispatcher, conversation,
   planning, command, outbound, scheduler, governance, retention,
   provider-governance, summary, semantic-memory, and knowledge-index roles).
   SPEC-029 requires the scheduler only when proactive scheduling is enabled;
   it runs no network I/O and still requires the outbound worker. Confirm each
   role reports healthy lifecycle state and no unexpected backlog growth.
5. Register or switch the Telegram webhook only after durable ingress is ready,
   using the explicit SPEC-022 lifecycle operation that verifies the resulting
   Telegram state. Never run polling for the same connection while the webhook
   is active.
6. Run the dedicated staging smoke interaction before accepting traffic.

API startup does not run migrations or start hidden worker loops. Optional
summary, semantic-index, Qdrant, Ollama, and provider capabilities may be
stopped when their documented fallback is safe.

## Graceful shutdown

Send termination to one role at a time where possible. The role must stop
claiming work, finish only work inside the drain budget, release or safely
expire leases, acknowledge only committed work, and close clients. Inspect
pending/reclaimed work after restart. A Telegram request that was already in
flight remains subject to `delivery_unknown`; do not automatically resend it.

## Secret rotation and revocation

Provision the replacement in the approved secret manager, validate it in
staging, restart the affected role through the deployment controller, and
verify the new credential. Revoke the old value only after the replacement is
known good. For suspected compromise, revoke first, fail closed for affected
external I/O, record a content-free incident reference, then replace and
revalidate. Never put the value in shell history, logs, tickets, images, or
health responses.

## Failure and recovery

- **PostgreSQL unavailable:** keep API readiness failed; restore canonical
  service before resuming workers.
- **Redis unavailable:** fail closed for configured external I/O; allow only
  documented database-only mutations; resume after coordination recovers.
- **Qdrant/Ollama unavailable:** keep API ready when semantic fallback is safe;
  knowledge and semantic-memory retrieval both fall back safely; rebuild or
  reconcile each separate derived collection from PostgreSQL later.
- **Worker stopped:** allow leases/consumer groups to reclaim work; inspect
  recovery state before replaying anything.
- **Scheduler stopped:** missed recurrence collapses to the latest eligible
  occurrence inside the configured catch-up window; never manually emit every
  missed time. Let expired occurrence leases recover normally.
- **Migration failure:** stop rollout, preserve logs without product content,
  restore the approved compatible image if safe, and use a forward corrective
  migration rather than routine production downgrade.
- **Ambiguous Telegram send:** quarantine and use the explicit possible-
  duplicate operator workflow; never use generic replay. A late-bound export
  credential action is not requeueable after ambiguous delivery; the subject
  must make a new export request so a new credential can be issued safely.
- **Ordered response tail blocked:** inspect the predecessor action and attempt
  state without message content. Retry only through the existing recovery
  classification; never regenerate or resend the delivered prefix. An
  ambiguous predecessor intentionally blocks all later ordinals.
- **Deleted reply target:** one replyless fallback is automatic only for the
  exact classified Telegram 400 missing-reply response. A timeout, reset, 429,
  5xx, malformed response or other 400 must never be manually converted into a
  second send.
- **Typing unavailable:** inspect only closed presence outcome/error metrics.
  Do not retry chat actions manually or alter provider/delivery policy; replies
  continue normally and the current Telegram indicator expires naturally.
- **Reaction unavailable:** inspect only bounded reaction outcome/error-class
  metrics. Do not retry 400/403/429/5xx/timeout/reset/malformed failures and do
  not send explanatory text; normal response delivery is already independent.
- **TTS denied or failed before output:** inspect only closed admission/result,
  route, budget, rate, concurrency, and provider health classes. Do not bypass
  governance, switch to chat generation, truncate text, or recover provider
  response bodies.
- **TTS outcome uncertain:** a timeout/reset after possible I/O may already have
  incurred provider work. Leave the job terminal uncertain and never synthesize
  it again automatically.
- **Voice delivery rejected:** let definitive no-send retries reuse the same
  artifact. Never invoke TTS again because Telegram failed.
- **Voice delivery ambiguous:** keep `delivery_unknown`; Telegram may already
  contain the voice. Do not resend or send explanatory text.
- **Voice artifact unavailable:** privacy erasure or expiry is terminal. Never
  restore bytes from backups, logs, Telegram quotes, or provider responses to
  satisfy pending delivery.
- **Feedback target unavailable:** do not recover from Telegram quoted text or
  write a row manually. Confirm the participant and exact local reply target are
  active, retained, delivered, and in the same authority scope.
- **Feedback revision limit:** revision 10 is final for state changes. A
  same-value repeat remains `NO_CHANGE`; never reset history to bypass the cap.
- **Regeneration edit rejected:** only the exact classified non-application
  errors activate the already-persisted send fallback. Let the normal outbound
  worker claim it; never issue an ad-hoc Telegram send.
- **Regeneration edit ambiguous:** timeout, reset, malformed post-I/O response,
  or 5xx leaves the edit `delivery_unknown` and the fallback blocked. Quarantine
  and investigate through the existing recovery workflow; never unblock the
  fallback merely because the visible Telegram state is unclear.

## Rollback and restore

Prefer configuration rollback, compatible image rollback, or disabling the
affected optional capability. Restore PostgreSQL only through the backup/restore
procedure. After restore, keep workers and Telegram ingress stopped while the
operating owner reapplies every erasure newer than the backup from its external
operating record. Then reconstruct Redis coordination and rebuild/reconcile
Qdrant from canonical active memories. Verify schema head, redaction,
idempotency, recovery dispositions, and privacy invariants before resuming
workers or ingress. The repository does not supply the external post-backup
erasure record.

Live voice artifacts are part of PostgreSQL backup consistency but not semantic
exports. After restore, reapply post-backup erasures before outbound resumes and
verify every ready artifact still has its scoped generation job/action pair.
Purged bytes must remain absent. Do not downgrade `0025` while any voice/TTS
state exists; the migration refuses that destructive operation.

Live feedback current/history rows also restore with PostgreSQL. Reapply every
post-backup subject erasure and response-retention deletion before ingress
resumes. Never downgrade `0026` while any feedback row/event exists; the
migration refuses that destructive operation.

Knowledge uses the same PostgreSQL-authority rule but its own collection and
rebuild command. After restore, keep knowledge retrieval disabled until
`app.runtime.knowledge_operations rebuild --confirm` proves exact current-chunk
ID parity and activates the fresh collection. Never restore Qdrant as knowledge
authority.

## Evidence and cleanup

Record release/configuration identifiers, lifecycle outcomes, dependency
failures, and operator identity without raw messages, prompts, memory text,
vectors, credentials, or provider bodies. Live acceptance runs produce the
content-safe SPEC-022 evidence bundle via
`uv run python -m app.runtime.acceptance_evidence collect --confirm-live-telegram`.
For local validation, run `docker compose down` for the project and verify
`docker compose ps` is empty.
