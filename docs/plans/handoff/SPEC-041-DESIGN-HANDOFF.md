# SPEC-041 Design Handoff

Date: 2026-09-28

Status: **APPROVED RELEASE READINESS DESIGN**

## Release scope and no-feature boundary

Harden and prove release configuration, deployment representation, migration
preflight, operational procedures, and complete acceptance for the existing
Telegram-first system. Do not change application behavior, APIs, commands,
workers, persistence models, migration history, evaluation scenarios, provider
capabilities, or Zalo state. Documentation and release tooling must describe
only behavior already authorized by SPEC-020 through SPEC-040.

## Current architecture and service topology

PostgreSQL is the only authoritative data store. Redis owns transient streams,
rate coordination, and provider concurrency. Qdrant is optional derived state
for semantic memory and knowledge and is never authority.

| Service | Responsibility | Dependency | Failure posture / scaling |
| --- | --- | --- | --- |
| migration | single-owner Alembic upgrade | PostgreSQL | nonzero stops rollout; exactly one owner |
| API/webhook | liveness, readiness, authenticated control plane, webhook ingest | PostgreSQL; Redis when configured | not ready on required dependency/head failure; horizontally scalable after migration |
| dispatcher | durable ingress outbox to Redis | PostgreSQL, Redis | retry from durable authority; multiple fenced consumers |
| conversation | normalize/process accepted updates | PostgreSQL, Redis | idempotent durable work; consumer-group scaling |
| planning | safety/context/provider planning | PostgreSQL, Redis; optional provider/Qdrant | leases and current-authority fencing; no DB session across I/O |
| commands | deterministic Telegram commands and TTS work | PostgreSQL; Redis/provider/Telegram as enabled | leased/idempotent; possible-I/O is conservative |
| outbound | Telegram text/edit/voice delivery | PostgreSQL, Redis, Telegram | retry confirmed no-send; quarantine uncertain delivery |
| scheduler | materialize durable proactive occurrences | PostgreSQL | bounded leases/catch-up; no direct Telegram send |
| governance | export/erase recovery work | PostgreSQL | privacy authority wins; bounded retry |
| retention | redact/purge expired content/artifacts | PostgreSQL | idempotent bounded batches; operator monitors backlog |
| provider governance | reconcile reservations/ambiguous attempts | PostgreSQL | no new I/O when hard enforcement unavailable |
| optional index/summary workers | derived semantic-memory, knowledge, summaries | PostgreSQL; Qdrant/provider as applicable | disabled unless paired feature enabled; retry/rebuild from authority |

## Configuration contract

`Settings` is the runtime parser and invariant authority. `.env.example` must
enumerate its complete `JANUARY_*` surface using local-safe values and empty
secret placeholders. The release-readiness runbook owns the operator-facing
classification and sensitive-setting matrix.

Production-config validation has two modes:

1. default offline mode validates source/static contracts, example completeness,
   placeholder safety, staging Compose rendering with synthetic values, typed
   fail-closed cases, single Alembic source head, and script/container policy;
2. explicit production-config mode reads the current environment, prints only
   setting names/reasons, requires `JANUARY_ENVIRONMENT=production`, instantiates
   typed settings without `.env`, rejects obvious placeholder/synthetic values,
   and requires the Telegram-first core plus safety, governance, retention,
   provider governance, command, outbound, metrics, and control-plane controls.

Neither mode contacts Telegram/providers or mutates infrastructure. Database
connectivity/current-revision checking is a separate explicit migration
preflight against the operator-selected database.

## Secrets contract

Secrets include database URL/password, Redis URL when credentialed, Telegram
bot/webhook secrets, provider API keys, and the control-plane JWT secret. They
are runtime-injected, redacted by typed settings, absent from `.env.example`,
excluded by `.dockerignore`, and never printed by validators. Non-secret but
sensitive production identifiers and endpoints are still operator-controlled.

## Migration preflight and deployment sequence

Preflight:

1. verify exactly one source head: `0026_conversation_feedback`;
2. validate production configuration and immutable image reference;
3. verify PostgreSQL connectivity and inspect `current` without logging URL;
4. create/verify the operator-owned backup;
5. run `alembic upgrade 0026_conversation_feedback` as the sole migration owner;
6. verify `current` equals the expected head; any failure stops promotion.

Deployment order:

```text
PostgreSQL + Redis (+ optional Qdrant)
  -> backup and migration preflight
  -> single-owner migration
  -> API /ready
  -> durable workers
  -> worker/backlog evidence
  -> webhook registration or polling owner
  -> bounded Telegram/provider smoke
```

There are no arbitrary sleeps. Readiness probes and bounded service health are
used. Webhook and polling never own ingress simultaneously.

## Startup, readiness, shutdown, and recovery

`/live` is process-only. `/ready` requires PostgreSQL connectivity at exact
head and Redis when delivery, rate limit, or provider concurrency uses it.
Optional Qdrant/provider services are not global readiness dependencies when
their capabilities are disabled; feature paths degrade/fail closed as their
existing contracts require.

Workers install SIGINT/SIGTERM drain handlers, finish bounded current work, and
rely on lease expiry/current-owner fencing after abrupt exit. Recovery covers
inbox/outbox, planning jobs, provider possible-I/O, outbound unknown delivery,
voice artifacts, schedules, governance, and retention. No exactly-once
external effect is claimed.

## Rollback decision tree

```text
Release unhealthy?
  -> Disable external ingress / affected capability and preserve evidence.
  -> Is prior application compatible with current schema?
       yes -> roll application image/config back; verify /ready and workers.
       no  -> Is an existing guarded downgrade explicitly safe on current data?
                yes -> incident owner may authorize backup + downgrade procedure.
                no  -> keep current schema, forward-fix; do not force downgrade.
  -> Is authoritative data damaged or unavailable?
       yes -> restore only under restore authority, reapply post-backup erasures,
              rebuild derived state, then reopen workers/traffic.
```

Database downgrade is never implied by application rollback. Manual DDL and
unguarded destructive downgrade are forbidden.

## Backup and restore

Use the existing PostgreSQL logical backup/restore validator for synthetic
proof. Production backup trigger, encrypted destination, retention, RPO/RTO,
verification, and restore authority are external operator decisions. Redis is
recreated; Qdrant is rebuilt. Restore acceptance reruns migration head,
multi-tenancy, governance, memory/retrieval authority, and live artifact/action
integrity. Post-backup privacy erasures are reapplied before traffic.

## Telegram and provider acceptance

Synthetic Telegram acceptance uses current adapters/fakes and covers text,
reply/order, edits, presence, reactions, voice, retries, exact rejection,
unknown delivery, webhook security/body limits, unsupported updates,
idempotency, and polling cursor/webhook exclusion.

Provider acceptance covers route/capability eligibility, current policy,
budgets, rate/concurrency, bounded timeout, usage quality, fallback, and
possible-I/O. Disabled capabilities require no credentials. Enabled remote
providers and TTS fail closed without required credentials. Live verification
remains guarded and operator-triggered.

## Privacy, retention, observability, and incident acceptance

Acceptance proves subject export/erase, derived deletion/revalidation, feedback
semantics, voice purge, retention worker execution, scheduled recovery,
content-safe metrics/logs, and control-plane least authority.

Repository SLO and alert rules are operational contracts, not a claim that an
external backend or notification route is active. The checklist maps inbox
lag, planning/provider/outbound failure, lease recovery, DB pool saturation,
Redis, optional Qdrant, and privacy worker failures to operator observation and
incident actions.

## Staging acceptance and production promotion gate

The staging representation is rendered and audited offline, then exercised
with fresh isolated services and synthetic credentials. It binds host-facing
database, Redis, Qdrant, and HTTP ports to loopback, uses runtime secret
passthrough, waits for migration completion, provides API readiness, restart
policy, and graceful stop, and profiles optional knowledge indexing.

Promotion requires exact SHA and green remote Quality; production-config and
migration preflight; verified backup; operator-approved providers/budgets,
Telegram/DNS/TLS, roles, monitoring, incident/rollback ownership; independent
audit; and a bounded post-deploy smoke. SPEC-041 performs none of those external
mutations.

## Quality and evidence

Execute every direct `.github/workflows/ci.yml` script plus the additional
conversation, governance, backup/restore, memory, and production-readiness
validators. Preserve mode `100755`, exact selectors, failure semantics, and
canonical eval `130 / 125 / 5 / 0 / 0`. Build the non-root runtime image, run
fresh service/migration proof, inject dependency/config failures, scan secrets
and integrity patterns, and run a VCS-free candidate with PATH-resolved UV.

## External prerequisite policy

Real bot/provider secrets, public webhook DNS/TLS, production data services,
provider credits and approved routes, monitoring/notification destinations,
secret manager, hosting/orchestrator, named owners, backup objectives, and final
promotion authorization are reported exactly as unavailable or operator-owned.
They are never fabricated and do not block repository-readiness approval when
the Product Spec permits operator-time external acceptance.
