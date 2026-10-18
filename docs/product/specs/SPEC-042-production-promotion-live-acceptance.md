# SPEC-042 — Production Promotion and Live Acceptance

Date: 2026-09-30

Status: APPROVED PRODUCTION PROMOTION SPEC

## Outcome and authority

Promote only the exact SPEC-041 approved source when separately authorized;
otherwise prepare and validate its operator-gated promotion package. The
Product Owner's SPEC-042 request authorizes repository documentation, bounded
release tooling, local builds and isolated synthetic validation. It explicitly
does **not** authorize production access/mutation, registry publication,
DNS/webhook changes, live Telegram traffic, paid provider calls, secret
rotation, monitoring writes, production backup deletion, restore, or traffic
enablement. No configurable flag is evidence of that missing authorization.

Baseline: `private-source-checkpoint-omitted`.
Quality: `36721562006`, main/push/completed/success on that SHA.
Schema: one head `0026_conversation_feedback`. Migration NONE.
Product behavior/capability NONE. Zalo remains frozen. No commit, push or
SPEC-043. Existing SPEC-020/021/022/023/025/026/029/030/033–041 behavior remains
authority; historical deferred CI exceptions are closed by SPEC-040.

## Distinct release states

| State | Required evidence; never inferred from an earlier state |
| --- | --- |
| REPOSITORY READY | approved source and green exact-SHA Quality |
| PROMOTION PACKAGE READY | provenance, contracts, synthetic proof, complete local Quality and VCS-free proof |
| PRODUCTION PROMOTION AUTHORIZED | explicit Product Owner/operator approval of exact target, artifact, configuration and actions |
| PRODUCTION DEPLOYED | authorized controller reports exact deployed artifact/configuration and timestamp |
| LIVE ACCEPTANCE PASSED | separately authorized approved bot/chat and provider scope with fresh durable terminal evidence |
| POST-DEPLOY OBSERVATION PASSED | actual deployment observed for the approved bounded interval with no abort condition |

No earlier state implies a later one. Missing prerequisites are not synthetic
PASS. Package-only final status is
`PROMOTION PACKAGE READY — OPERATOR AUTHORIZATION REQUIRED`. Other allowed
outcomes are `BLOCKED_ON_EXTERNAL_PREREQUISITE`,
`BLOCKED — VERIFIED PRODUCTION BACKUP REQUIRED`,
`BLOCKED — PRODUCTION PROMOTION REQUIRES PRODUCT/ARCHITECTURE CHANGE`, or
`REQUIRES FIXES`. Actual deployment can be `PRODUCTION DEPLOYED — LIVE
ACCEPTANCE PENDING`; successful live proof remains independently audited before
`APPROVED PRODUCTION RELEASE CANDIDATE — INDEPENDENT AUDIT PENDING`.

## Immutable identity and provenance

The manifest records source SHA, exact-SHA Quality, OCI image/index digest,
platform manifest/config identity, build input and lock hashes, Python version,
source-export verification, schema head, non-secret configuration revision and
scoped fingerprint, environment, operator and deployed timestamp. Local
artifact availability is not registry publication or operator digest approval.
Mutable `latest` is never sole identity. Build from the approved commit archive,
not the promotion-document worktree. Changes to runtime/build inputs require a
new reviewed source and exact-SHA Quality, not an in-place promotion patch.

The offline fingerprint reuses `Settings.safe_configuration_fingerprint()` and
explicit secret-key injection presence. It never hashes secret values, URLs,
subjects or chat IDs. Its allowlisted scope is not full drift detection;
the separately approved non-secret configuration revision and secret-manager
version references remain mandatory. Do not publish those references if they
would reveal sensitive identifiers.

## Approval and external inventory

Every prerequisite is classified AVAILABLE, NOT AVAILABLE, UNKNOWN or NOT
REQUIRED with observed provenance, not inferred from documentation. The
manifest owns the actual inventory. Production authorization must specify
target/environment, source/digest/configuration, deployment/migration/traffic
scope, designated single migration owner, backup/restore/rollback scope,
incident/privacy/on-call owners, expiry/window and abort criteria. Telegram
testing and paid provider/TTS spend require separate explicit scope. Existing
`--confirm-live-telegram` is a necessary operation guard, not release approval.
There is no automatic deploy or permissive newly invented authorization gate.

Production DB access itself requires explicit read-only approval. Without it,
only synthetic preflight runs. No real content is read/dumped to prove readiness.
Missing deployment target/credentials/approval is reported without asking that
secrets be pasted into a chat, ticket or repository.

## Pre-mutation and traffic gates

Before any authorized production mutation require approved digest and
configuration, green Quality, verified encrypted authoritative PostgreSQL
backup, connectivity/current-revision/schema preflight, approved monitoring and
operating coverage. Backup evidence includes opaque ID, timestamp, success,
checksum/catalog verification, destination class, encryption, retention,
restore owner, RPO/RTO and post-backup erasure-reconciliation authority.
Synthetic restore is not a production backup. Redis/Qdrant are not backup truth.

At current head no migration is needed. A known supported older revision needs
explicit migration approval and backup, a single bounded canonical
`alembic upgrade 0026_conversation_feedback`, and post-check. Unknown, newer,
multiple or diverged revisions are NO-GO. Preflight failure stops rollout;
never force with manual ALTER, disable constraints, or blindly downgrade.

Deploy sequence: freeze approved inputs → exact-SHA Quality → approval → backup
verify → config preflight → DB preflight → migration if required → immutable
deployment with external ingress closed → API and required workers → readiness
and worker/backlog proof → explicit GO → single-owner ingress → bounded live
smoke → approved observation → acceptance/rollback decision.

Required topology is API/webhook, dispatcher, conversation, planning, commands,
outbound, governance, retention and provider-governance recovery. Scheduler is
required for enabled proactive scheduling. Summary, semantic-memory and
knowledge-index workers require paired configuration and corresponding enabled
capabilities. Qdrant is optional derived state; disabled absence does not block
core readiness. No API startup migration or hidden worker supervisor.
Container running alone is not worker health: require current loop/lifecycle,
bounded failures, backlog and lease recovery evidence.

`/live` is process-only. `/ready` requires exact PostgreSQL head and configured
Redis coordination. Public verification must use approved HTTPS and valid TLS;
synthetic failure injection never targets production. Safety, abuse/rate gates,
provider enforcement, authenticated control plane, privacy/governance/retention
and content-safe observability remain enabled.

## Live acceptance and observation

Telegram preconditions: approved bot and canonical connection, dedicated test
chat, explicit live scope, credential reference, public HTTPS/TLS and webhook
secret for webhook mode, and verified exclusive webhook/polling ownership.
Across one smoke run, at most **10 outbound Telegram API operations**, including
typing refreshes, reactions, lifecycle calls, retries, commands and voice;
operator scope may be stricter. Reserve the worst-case automatic budget before
each stimulus; do not submit another stimulus if it could exceed the total.
Use synthetic harmless text only; no unrelated users, intentionally abusive
content, destructive erasure tests, or forced live dependency failures.

Prove ingress/idempotency, current conversation authority, response/reply,
safe ordering only when bounded, deterministic command acknowledgement,
durable outbound terminal state, scoped message mapping and no duplicate or
cross-chat effect. Optional cosmetic operations count toward the same limit.
No provider-backed text turn without billing authorization. Otherwise use
synthetic/mock proof and report fresh provider/Telegram proof pending.

Paid calls require approved account/credential, capability/route/model,
pricing, hard budget, rate/concurrency admission, data eligibility, explicit
billing authorization and an operator-set maximum count/spend. No arbitrary
default budget. Minimum bounded synthetic prompt; verify governed usage and
terminal state without logging content. Possible-I/O is never repeated merely
to obtain success. TTS additionally requires enablement and Telegram authority;
one approved generation, one governed artifact/send path, retention metadata
and governed cleanup eligibility. Never synthesize again for delivery retry.

Before ingress, monitoring must demonstrate accessible metrics/logs, readiness,
worker failures/backlogs, DB/Redis pressure, provider failures/unknown usage,
outbound retry/delivery_unknown and privacy/retention failures; verified alert
destination, dashboards and named role/team escalation are required. Repository
SLO/alert contracts do not prove a live backend or ratified thresholds.

The owner must approve a finite observation duration, sampling cadence,
failure/budget thresholds, start/end and observer before GO. No source contract
selects a universal launch window; absent approval means NO-GO, not an invented
default. Observe HTTP readiness, worker liveness, inbox lag, planning/provider
errors, outbound/unknown, pool/Redis and privacy failures throughout that window.
Record actual start/end and samples, never claim stability without observation.

## Incident, rollback and evidence

Immediate NO-GO: red Quality/schema/backup/readiness, missing worker, unsafe
auth/safety/governance, secret leak, tenant/privacy defect, duplicate ingress,
unintended test recipient, or artifact mismatch. Approved sustained-error,
backlog and unknown-delivery thresholds also abort. Authority/privacy/security
failure stops traffic immediately under incident authority; preserve evidence.

The operator identifies the previous approved immutable artifact and proves
compatibility with current schema before marking ROLLBACK SAFE. If incompatible,
record ROLLBACK REQUIRES FORWARD FIX; authoritative loss may require RESTORE
REQUIRED with separate restore authorization. Unknown previous deployment means
rollback is not ready. Disable ingress and affected external-I/O workers without
deleting data or routine token revocation. Never bypass ambiguity quarantine.
Restore reconciles post-backup erasures and derived state before reopening.

Evidence is content-safe: operation/type/time, opaque correlation, status,
latency class, source/digest/config/schema/approval/backup/deploy/acceptance and
observation outcomes. No credentials, real user/chat IDs, message/prompt/body,
memory/knowledge text or audio. Existing live collector may contain scoped
identifiers; use restricted storage and sanitize to opaque aliases before any
release record. Logs/metrics alone do not prove artifact provenance.

## Validation and acceptance

Every direct current Quality script and inline migration/pytest step, every
SPEC-042 named supplemental validator, static/shell/Harness proof, exact-source
build, synthetic startup/preflight/restore, secret review and exact VCS-free
candidate must pass. Reliability failed 0. Canonical eval remains
130 total / 125 PASS / 5 NOT_EVALUATED / 0 FAIL / 0 ERROR, zero new scenarios.
Direct scripts remain 100755; workflow/selectors/safety/privacy are not weakened.
Zero Critical/High findings. Handoff distinguishes package, real production
and live gates. Independent OpenCode audit is next; no commit/push/SPEC-043.
