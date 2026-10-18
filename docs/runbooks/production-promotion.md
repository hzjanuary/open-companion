# Production Promotion (SPEC-042)

This is an operator-gated target-neutral procedure, not a deployment script.
Use the [Product Spec](../product/specs/SPEC-042-production-promotion-live-acceptance.md),
release manifest (private execution record omitted from this snapshot) and
[checklist](production-promotion-checklist.md). No operation is authorized by
reading this runbook or passing local tests.

## 1. Freeze identity and obtain authority

Record approved source SHA and exact-SHA green Quality, immutable index/digest
and platform identity, lock/build inputs, non-secret config revision and secret
reference versions, environment and role owner. Never deploy solely `latest`.
SPEC-042 builds only the approved `private-source-checkpoint-omitted`
source; promotion-doc changes do not create a different approved runtime.

The current repository offers target-neutral staging Compose and explicit
Telegram lifecycle guards, not an authorized production controller. Obtain a
reviewed target-specific command sequence and approval record with target,
source/digest/configuration, permitted publication/deploy/migration/traffic
actions, expiry, single migration owner, deploy/rollback/restore/privacy/
incident/on-call roles, count/spend bounds, observation interval/cadence and
abort thresholds. Do not set a newly invented permissive env gate.
`--confirm-live-telegram` confirms intent of a particular operation only.

If any required authority is absent, stop production actions; repository-only
package status may be `PROMOTION PACKAGE READY — OPERATOR AUTHORIZATION REQUIRED`.
No production credentials should be pasted into this document or a chat.

## 2. Preflight configuration, backup and database

Run offline repository gates first:

```bash
./scripts/validate-production-readiness.sh --offline
./scripts/validate-deployment.sh
./scripts/validate-reliability.sh
./scripts/validate-ai-evals.sh
```

The full current Quality workflow and named SPEC-042 supplemental validators
must also pass, including inline migration/pytest checks. No deferred failure.

From an approved runtime secret-injection context, never a rendered/env-dumped
command or `set -x` shell:

```bash
./scripts/validate-production-readiness.sh --production-config
./scripts/production-config-fingerprint.sh
```

Both are offline and ignore `.env`. Fingerprint scope is allowlisted runtime
metadata and secret-key injection presence, not full config or secret rotation
identity. Pair it with separately approved non-secret configuration revision
and protected secret-version references. Optional disabled features require no
credential; enabled features require matching worker profiles and providers.
Require safety, rate/concurrency, provider enforcement, auth/bootstrap,
privacy/governance/retention, command/outbound/recovery and metrics controls.

Before any production migration **or deployment**, verify an authoritative
encrypted PostgreSQL backup. Record only opaque ID, timestamp, completion,
checksum/catalog verification, encryption, destination class, retention,
restore authority, approved RPO/RTO and erasure-reconciliation ownership.
`validate-backup-restore.sh` proves synthetic restore credibility only. No
backup credential/content is evidence. Missing verified production backup is
`BLOCKED — VERIFIED PRODUCTION BACKUP REQUIRED`.

Only after explicit read-only production access approval:

```bash
./scripts/validate-production-readiness.sh --database-preflight
```

This uses bounded read-only revision checks; it never migrates. Also inspect
required schema/catalog integrity and constraints through the approved
metadata-only operator procedure. Source head alone is not database current.

## 3. Migration decision

One current `0026_conversation_feedback`: NOT REQUIRED, do not rerun a write
merely to obtain evidence. Known supported older revision: require migration
scope, verified backup, single owner and bounded controller execution of:

```bash
uv run alembic upgrade 0026_conversation_feedback
```

Unknown, absent, multiple, newer or diverged revision: NO-GO; do not force.
Repeat database preflight and require exact current head before application
traffic. Failure stops rollout. No manual ALTER, constraint bypass or routine
`downgrade`. A schema/product change is outside this SPEC and requires decision.

## 4. Deploy immutable artifact with traffic closed

Use the operator-approved controller commands, attached to the approval record.
Record controller outcome, actual image digest/config revision and timestamp;
compare against the manifest. Registry publication requires its own authority.
Do not treat `compose.staging.yaml` (hardcoded staging/webhook) as production
configuration or run an invented production command here.

When invoking module commands from a source export, set `PYTHONPATH=backend`;
the approved runtime image already supplies `/app/backend`. Use an artifact/
injection context without developer `.env`. Stock worker entrypoints do not all
configure INFO log handlers themselves: prove the approved target's safe
`january` lifecycle/metric collection, without raising third-party HTTP client
logging to INFO (Telegram request URLs can contain credentials). Synthetic
rehearsal INFO wrappers are not a production logging recipe.

Keep external ingress closed. In webhook mode, the reviewed edge controller
must deny/withhold public ingress while internal probes work; coordinate any
previous webhook owner and pending-update preservation. In polling mode keep
the poller stopped. Starting workers may perform paid/delivery work from
existing queues: approval must cover that drain/activation and backlog review.
No delete/truncate/queue flush as a traffic-control mechanism.

Start authoritative dependencies, optional enabled derived services, completed
schema job, API, then required worker roles. Use bounded probes/health and
dependency completion, not arbitrary startup sleeps.

| Role | Actual module / condition |
| --- | --- |
| API/webhook | `app.main:app` |
| dispatcher | `app.runtime.ingress_outbox_dispatcher` |
| conversation | `app.runtime.conversation_worker` |
| planning | `app.runtime.response_planning_worker` |
| commands / TTS | `app.runtime.telegram_command_worker` |
| outbound | `app.runtime.outbound_delivery_worker` |
| recovery/accounting | existing lease paths and `app.runtime.provider_governance_worker` |
| privacy/governance | `app.runtime.governance_worker` |
| retention / voice purge | `app.runtime.retention_worker` |
| scheduler | `app.runtime.proactive_scheduler_worker`, when scheduling enabled |
| summaries | `app.runtime.conversation_summary_worker`, feature and worker enabled, `summaries` profile |
| semantic memory | `app.runtime.semantic_memory_index_worker`, feature/worker/embedding configured, `semantic-memory` profile |
| knowledge indexing | `app.runtime.knowledge_index_worker`, feature/worker/embedding configured, `knowledge-rag` profile |

Global API readiness does not certify optional worker topology. Require
loop/lifecycle evidence, no crash/restart cycle, bounded leases/recovery,
backlogs and safe terminal/error metrics for every required role. PostgreSQL
owns truth, Redis coordination, Qdrant derived state; disabled optional Qdrant
absence is not a core-readiness failure.

## 5. Readiness, monitoring and explicit GO

Fetch approved HTTPS `/live` and `/ready` with TLS verification. `/live` is
process liveness; `/ready` requires exact schema and configured Redis. Record
status/time, not credentials or URL identifiers. Never use insecure public
HTTP or `curl -k`. Synthetic failure injection stays isolated.

Verify control-plane anonymous/overreach fail closed with synthetic or
specifically approved staging proof; do not probe third-party infrastructure.
Verify safety/provider/privacy gates and retention/erase/voice/feedback/memory/
derived cleanup processes without deleting real data.

Demonstrate backend ingestion, dashboard access, logs, worker failure visibility,
DB/Redis/pool pressure, provider errors/unknown accounting, outbound retry/
delivery_unknown and privacy failures. Verify alert destination and role/team
on-call/escalation. Ratify SLO/abort thresholds and finite observation duration,
cadence and owner; repository alert YAML is not proof of active external alerts.

Explicit GO requires all artifact, approval, backup, configuration, schema,
API/worker, safety/auth/privacy/governance, monitoring/owners and ingress gates.
Any missing/unknown mandatory item is NO-GO, no partial implicit promotion.

## 6. Single ingress ownership and bounded acceptance

Follow [live acceptance](live-acceptance.md) only with separate explicit bot/
chat/credential/live authorization. Inspect approved bot identity/current
webhook state through SPEC-022 operations; never use startup side effects.
Webhook→polling: close/drain old ingress, stop owner, authorized webhook-delete
without dropping pending updates, verify removal/exclusivity, then start one
poller. Polling→webhook: stop/drain poller, verify no owner, authorized register
and inspect resulting HTTPS URL/update set, then open approved ingress.
Record transition and inverse rollback; never overlap owners.

Use at most ten outbound Telegram API operations total, including presence/
reaction/retry/lifecycle overhead. Count actual calls and reserve remaining
worst-case automatic calls before each stimulus. No provider-backed response
without billing scope. Minimum harmless synthetic prompt under approved model,
price/hard budget/rate/concurrency; count every actual paid attempt. Verify usage
and terminal state. Do not repeat ambiguous possible-I/O for a green result.
TTS requires both scopes, enablement, one generation and governed artifact/purge
metadata. No destructive privacy or harmful-content live test.

Check durable ingress/idempotency, scoped authority, response/reply, bounded
ordering if safely triggered, deterministic acknowledgement, persisted outbound
terminal delivery/mapping, no duplicate or cross-chat effect. Record counts,
times, operation/status/latency classes and opaque aliases only.

Do not use `verify-model-provider.sh --live` for SPEC-042: it is a raw diagnostic
generation helper, not the persisted governed route/budget/usage path. Likewise
`verify-telegram-delivery.sh --live` is a raw adapter diagnostic, not durable
inbox-to-outbox acceptance. Their opt-in flags cannot substitute for approval
or governance. Authorized smoke must traverse the deployed governed workers
and durable outbound state; lifecycle inspection is precheck only.

## 7. Observe and decide

Observe the actual approved finite window and cadence after deploy/ingress.
Record start/end, samples and owner: readiness, worker/inbox lag, planning and
provider errors, outbound/retry/unknown, pool/Redis and privacy failures.
Unknown/missing window means NO-GO, not an invented long wait. No stability
claim from a single health probe or synthetic test. Finish with explicit
accepted/NO-GO outcome tied to source/digest/config/schema.

## 8. Traffic disable, rollback and restore escalation

Immediate abort: schema/artifact mismatch, missing backup/required worker,
failed readiness, unsafe auth/safety/provider governance, secret/tenant/privacy
defect, duplicate owner or unintended recipient. Sustained errors/backlogs/
unknown delivery abort at approved thresholds. Stop unsafe ingress/external I/O
under incident authority; protect people/privacy and preserve durable evidence.

Use actual reviewed edge/poller/worker stop commands. Stop new provider/delivery
claims when required and allow bounded drains; possible sends remain unknown.
Webhook deletion needs explicit scope and verified resulting state. Do not
delete data, flush queues, automatically resend unknown deliveries or routinely
revoke tokens as first-line traffic stop.

Before rollback classify previous approved digest/config compatibility:
ROLLBACK SAFE, ROLLBACK REQUIRES FORWARD FIX, or RESTORE REQUIRED. Unknown previous
artifact/compatibility is not rollback READY. Execute compatible image/config
rollback only when covered by authority; verify head/readiness/workers/backlogs
before reopening. No blind DB downgrade, especially guarded voice/feedback state.

Restore is separate authority, not automatic rollback. For authoritative
loss/corruption stop and escalate; never overwrite production automatically.
Approved isolated restore verifies schema/constraints/authority, reapplies
post-backup erasures, recreates Redis and rebuilds/revalidates Qdrant before
traffic. Never restore erased voice bytes or content to satisfy pending work.

## 9. Evidence and handoff

Update manifest/handoff with observed source/digest/config/schema/approval/
backup/deploy/readiness/live/monitoring/window/rollback results, exact counts and
NOT EXECUTED fields. Restricted collector may carry scoped IDs: sanitize to
opaque aliases before repository evidence; do not log bodies, prompts, keys,
memory/knowledge/audio or real users/chats. Retention/access destination needs
operator approval. Cleanup only identified synthetic resources; preserve all
unrelated stacks. No production cleanup/restore without authority.

Independent OpenCode production-promotion audit is next. Do not commit, push,
start SPEC-043 or claim production/live acceptance from package proof.
