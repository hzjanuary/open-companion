# Production Promotion Checklist

Use the [promotion runbook](production-promotion.md) and
manifest (private execution record omitted from this snapshot). Unknown or unchecked
mandatory item means NO-GO. Local PASS never authorizes production.

## AUTHORIZATION

- [ ] Explicit scoped approval names target/environment/source/digest/config,
  actions/expiry and deploy/migration/rollback/privacy/incident/on-call owners.
- [ ] Separate publication, read-only DB, Telegram live, provider billing/TTS
  and restore scopes cover every intended action; flags are not approval.

## PRE-PROMOTION

- [ ] Independent audit, exact-SHA green Quality, immutable digest, source/
  build/lock provenance, full local matrix/static/secret/VCS-free proof pass.
- [ ] Offline and injected production config pass without values; approved
  revision/scoped fingerprint/protected secret versions recorded; no defaults,
  placeholders, debug/echo/demo, product/migration/workflow/selector drift.
- [ ] Safety/auth/privacy/provider enforcement/rate/concurrency enabled;
  optional capability/worker/profile/provider topology agrees.

## BACKUP

- [ ] Verified encrypted authoritative production backup has opaque ID/time/
  completion/checksum/catalog/destination class; synthetic restore separately PASS.
- [ ] Approved retention/RPO/RTO/restore owner and post-backup erasure ledger/
  reconciliation exist; no backup credentials/content retained.

## MIGRATION

- [ ] Authorized read-only DB and metadata schema/constraint preflight pass;
  one known current revision, target `0026_conversation_feedback`.
- [ ] At head NOT REQUIRED; supported older revision has bounded single-owner
  approved upgrade/backup/post-check; unknown/newer/multiple/diverged blocks.
- [ ] No manual ALTER, forced downgrade or constraint weakening.

## DEPLOYMENT

- [ ] Reviewed target controller commands deploy approved digest/config;
  actual digest/time/owner recorded; staging Compose not silently production.
- [ ] Ingress closed; backlog activation covered by approval. Dependencies,
  schema, API, dispatcher/conversation/planning/commands/outbound/provider
  recovery/governance/retention and enabled scheduler/optional roles start.

## READINESS

- [ ] Approved HTTPS/TLS `/live` and exact-head/Redis `/ready` PASS.
- [ ] Every required worker has current loop/lifecycle/lease/backlog/failure
  evidence, not just a running container. Disabled Qdrant safely non-blocking.
- [ ] Synthetic auth-overreach/safety/privacy/voice/feedback/memory/derived
  cleanup prove authority; no destructive real-data smoke.

## INGRESS

- [ ] Approved bot/connection inspected only with authorized token use;
  webhook HTTPS/secret/update set verified; exactly one ingress owner.
- [ ] Drain/transition/inverse rollback reviewed; preserve pending updates;
  explicit GO before traffic, never implicit registration or ownership overlap.

## LIVE TELEGRAM

- [ ] Dedicated approved bot/chat and harmless bounded scope; at most ten
  outbound API calls including lifecycle/presence/reaction/retry overhead.
- [ ] Reserve worst-case calls before each stimulus; actual call ledger checked.
- [ ] Durable ingress/idempotency/authority/response/reply/safe ordering/
  deterministic acknowledgement/terminal mapping/no duplicate or foreign scope
  verified; ambiguous result is not PASS; no unrelated user or harmful content.

## LIVE PROVIDER

- [ ] Account/data eligibility/credential/model/route/pricing/hard budget/rate/
  concurrency and explicit finite call/spend approval verified.
- [ ] Minimum harmless prompt; actual paid attempts/usage/terminal metadata
  recorded; no repeated possible-I/O for success.
- [ ] Optional one TTS generation has both approvals, enablement, governed
  artifact/send/retention and purge eligibility; delivery retry never repeats TTS.

## OBSERVABILITY

- [ ] Metrics/log ingestion/dashboard visible for readiness/workers/inbox,
  planning/provider/outbound unknown/pool/Redis/privacy failures.
- [ ] Active alert destination/ratified thresholds/on-call/team escalation
  verified; repository alert files are not live backend evidence.

## OBSERVATION WINDOW

- [ ] Finite duration/cadence/observer/abort thresholds explicitly approved.
- [ ] Actual start/end/samples cover readiness/worker lag/errors/unknown/
  DB/Redis/privacy throughout interval; no inferred stability.

## GO / NO-GO

- [ ] All mandatory approval/artifact/backup/config/schema/workers/readiness/
  safety/auth/privacy/provider/monitoring/owner/ingress gates green.
- [ ] Immediate NO-GO for security/privacy/tenant/auth defect, secret leak,
  mismatch, missing backup/worker, duplicate owner or unintended recipient.
- [ ] Approved sustained-error/backlog/unknown thresholds applied; explicit
  acceptance or abort recorded.

## ROLLBACK

- [ ] Previous approved immutable digest/config/schema compatibility proved:
  ROLLBACK SAFE / ROLLBACK REQUIRES FORWARD FIX / RESTORE REQUIRED.
- [ ] Covered traffic/worker stop and compatible rollback only; preserve data/
  ambiguity, no routine token revocation or blind DB downgrade; reverify ready.

## RESTORE ESCALATION

- [ ] Real restore separately authorized; never automatic production overwrite.
- [ ] Reapply erasures, verify schema/authority/voice, recreate Redis, rebuild/
  revalidate Qdrant before reopening traffic.

## EVIDENCE

- [ ] Manifest binds source/CI/digest/config/head/approval/backup/deploy/live/
  readiness/monitoring/window/rollback to actual count/time/opaque outcome.
- [ ] No secret/user/chat/content/prompt/memory/knowledge/audio; restricted
  collector IDs sanitized, evidence retention/access approved.
- [ ] NOT AUTHORIZED/NOT ACCESSED/NOT EXECUTED truthful; synthetic not production.
- [ ] Clean only identified owned resources; preserve unrelated stacks.
- [ ] Independent OpenCode audit next. DO NOT COMMIT. DO NOT PUSH.
  DO NOT START SPEC-043. Global Quality remains green.
