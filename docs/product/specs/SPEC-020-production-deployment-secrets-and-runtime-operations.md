# SPEC-020 Production Deployment, Secrets, and Runtime Operations

## Status

Product design complete for review. This document authorizes no runtime
implementation, migration, deployment manifest, commit, or push.

SPEC-019 is the latest completed implementation. SPEC-014 remains deferred
behind the external Zalo prerequisite.

## Background

SPEC-001 through SPEC-019 establish a modular monolith with a stateless API,
separate ingress, dispatcher, conversation, planning, command, outbound,
retention, summary, and semantic-index workers, PostgreSQL canonical state,
Redis Streams and coordination, and optional Qdrant/Ollama derived-memory
infrastructure.

The repository is intentionally local-operator oriented. Docker Compose,
explicit worker processes, optional process-local telemetry, and synthetic
validators prove application behavior but do not establish production
deployment, secret, migration, rollout, or incident operations.

SPEC-020 defines those operational boundaries without changing product policy.
The deployment layer must not turn the API into a hidden worker supervisor,
make Redis or Qdrant canonical, or weaken privacy, safety, idempotency, or
ambiguous-delivery rules.

## Outcome

January can be deployed and operated in an approved staging or production
environment with explicit ownership for secrets, processes, dependencies,
migrations, readiness, rollout, rollback, recovery, and evidence.

## Objectives

- Define a production topology for the API and independently scaled workers.
- Separate local, test, staging, and production configuration and credentials.
- Define secret provisioning, loading, validation, rotation, revocation, and
  redaction.
- Make startup, readiness, liveness, graceful shutdown, lease recovery, and
  restart behavior deterministic.
- Establish migration, rollout, rollback, backup, restore, and incident
  lifecycles.
- Preserve existing privacy, fail-closed, dependency-direction, idempotency,
  and ambiguous Telegram-delivery rules.
- Distinguish local synthetic proof from staging/live production evidence.

## Non-goals

- Runtime code, migrations, deployment manifests, or cloud integrations in this
  design phase.
- Selecting a cloud provider, orchestrator, secret manager, database vendor,
  Redis vendor, metrics backend, or ingress controller without approval.
- Authentication, administration dashboard, billing, tenant management, new
  media/voice behavior, or Zalo implementation.
- Changing conversation, personality, safety, rate-limit, memory, summary, or
  semantic-retrieval policy.
- Claiming availability, throughput, RPO, RTO, or cost targets before launch
  and hosting decisions are accepted.
- Treating Docker Compose as the production deployment contract.

## Scope

In scope are API and worker lifecycle, PostgreSQL/Redis/Qdrant/Ollama/provider
roles, environment separation, configuration precedence, secret lifecycle,
startup ordering, readiness/liveness, graceful shutdown, migration
compatibility, rollout/rollback, runtime recovery, security/privacy
boundaries, operational validation, ADRs, runbooks, and implementation phases.

Existing behavior remains authoritative:

- PostgreSQL is canonical for product state and durable work. Redis and Qdrant
  are not backup authorities.
- Redis is at-least-once coordination; consumers remain idempotent and leases
  remain recoverable.
- No transaction or ordering lock spans provider, embedding, Qdrant, or
  Telegram I/O.
- Ambiguous Telegram delivery remains delivery_unknown/quarantine and is not
  silently retried as exactly-once delivery.
- Qdrant is rebuildable derived state and PostgreSQL revalidation remains
  mandatory before memory text enters context.
- /live is process-only. /ready checks bounded required dependencies and schema.
  Optional derived services do not automatically make the API unready when safe
  fallback exists.
- Logs, metrics, health, queues, crash reports, and deployment status contain no
  raw messages, prompts, provider bodies, memory text, vectors, or credentials.

## Architecture impact

SPEC-020 changes operational composition around the existing modular monolith;
it does not change the dependency direction:

    HTTPS ingress -> stateless API replicas -> PostgreSQL / Redis
                                      |
                                      +--> dispatcher
                                      +--> conversation workers
                                      +--> planning workers -> model provider
                                      +--> command workers -> Telegram auth
                                      +--> outbound workers -> Telegram API
                                      +--> retention workers
                                      +--> summary workers -> model provider
                                      +--> semantic-index workers -> Qdrant

The deployment layer owns placement, process identity, resource limits,
networking, secret references, and lifecycle signals. It does not own business
idempotency, memory authority, safety policy, or platform actions. API replicas
are stateless. Worker roles scale independently only where existing leases,
consumer groups, ordering locks, and idempotency prove it safe.

## Deployment topology

| Role | Responsibility | Durable dependency |
|---|---|---|
| API | Health, readiness, webhook acknowledgement, durable ingress | PostgreSQL; Redis when required |
| Poller | Optional long polling for one Telegram connection | PostgreSQL, Telegram |
| Dispatcher | Publishes durable outbox references | PostgreSQL, Redis |
| Conversation worker | Normalizes ingress and creates durable state | PostgreSQL, Redis |
| Planning worker | Builds context and response plans | PostgreSQL, Redis, provider |
| Command worker | Commands and fresh authorization | PostgreSQL, Redis, Telegram |
| Outbound worker | Executes validated actions | PostgreSQL, Redis, Telegram |
| Retention worker | Canonical retention/redaction | PostgreSQL |
| Summary worker | Optional derived summaries | PostgreSQL, Redis, provider |
| Semantic worker | Embedding and Qdrant indexing | PostgreSQL, Redis, embedding, Qdrant |

Webhook and polling remain mutually exclusive per connection. Starting or
stopping a role must not lose durable work or create a second ingress source.

## Environment separation

- Local: disposable Compose services, fake adapters, no production secrets.
- Test/CI: deterministic tests and project-owned dependencies; no public
  Telegram/provider side effects by default.
- Staging: production-shaped topology with separate bot, provider credentials,
  database, Redis, Qdrant, domain, and secret namespace.
- Production: approved credentials, encrypted persistent state, controlled
  operators, monitoring, backups, incident response, and change approval.

Production rejects local/test defaults, development passwords, demo allowlists,
unsafe debug logging, and missing required secret references. Configuration is
immutable for a running process unless a separately proven reload boundary is
accepted; controlled restart is the default.

## Secret management lifecycle

Secret classes include Telegram bot/webhook tokens, model and embedding keys,
database/Redis credentials, Qdrant/Ollama credentials, deployment identities,
observability credentials, and backup-encryption keys.

1. Provision secrets in an approved external mechanism; never commit them, bake
   them into images, or place them in Compose defaults.
2. Inject and validate only at the process boundary. Fail before external side
   effects when required values are absent or invalid.
3. Keep secret-bearing requests inside adapters. Redact values from logs,
   errors, health, metrics, crash reports, and inspection output.
4. Rotate through staging validation, an approved overlap/cutover window, a
   controlled restart or proven safe reload, and old-credential rejection.
5. Revoke suspected credentials, fail closed for affected I/O, record only a
   content-free incident reference, and resume after replacement.
6. Govern secret-manager retention, backups, and operator access separately
   from product-content retention.

Live reload is not promised unless atomic client replacement and redaction are
proven by the selected platform.

## Configuration strategy

Configuration has three ownership layers:

1. Code-owned invariants: safety, privacy, schema, dependency direction,
   default-off integrations, and fail-closed behavior.
2. Environment-owned settings: environment, endpoints, role, resource limits,
   pools, timeouts, and specified feature enablement.
3. Secret-owned values: tokens, passwords, API keys, and encryption material.

Environment values cannot weaken hard invariants or hide unimplemented paths.
Startup rejects contradictory modes, unsafe production defaults, invalid URLs,
unsupported capabilities, and secret/environment mismatches. A safe
configuration fingerprint contains allowlisted names, versions, modes, and
booleans only; it never contains values, secret hashes, credentials, prompts,
or arbitrary environment variables.

## Worker lifecycle and startup ordering

Every role validates configuration and secrets, establishes clients, verifies
dependencies and schema compatibility, creates or reclaims only its documented
consumer/lease boundary, publishes lifecycle state, stops claiming work when
draining, keeps locks out of external I/O, and releases or safely expires
leases after failure.

Startup provisions dependencies, verifies PostgreSQL/Redis, runs the
single-owner migration job, starts API replicas, verifies /live /health /ready,
starts dispatcher and consumers, starts optional workers, and only then
registers or switches the Telegram webhook. API startup does not run
migrations or hidden workers.

## Graceful shutdown

Termination begins a bounded drain. A role stops claiming work, stops accepting
new ingress at the deployment boundary, completes only work within the drain
policy, releases leases, acknowledges only committed work, closes clients, and
emits content-safe shutdown telemetry.

External requests are not assumed cancellable or exactly-once. Termination
after a Telegram request begins follows the existing ambiguous-result policy and
must not become an automatic duplicate send.

## Readiness and liveness behavior

/live remains a bounded process check and does not call PostgreSQL, Redis,
Telegram, providers, Ollama, or Qdrant. /ready checks PostgreSQL and schema,
plus Redis when ingress, rate-limit, or concurrency configuration requires it.
Telegram configuration is checked when production ingress requires an active
connection without exposing credentials.

Optional providers, Qdrant, Ollama, summaries, and semantic indexing do not
make the API unready when documented fallback is safe. Their worker health and
backlog are separate signals. Readiness errors are safe, request-ID-bearing,
and recover after dependencies recover. Worker readiness is distinct from HTTP
readiness.

## Migration lifecycle

Production migrations use expand/validate/contract discipline: review
ownership, classification, locks, duration, compatibility, and recovery; apply
additive changes; validate in production-shaped staging; deploy compatible
old/new roles; and remove obsolete structures only after the compatibility
window.

Migration jobs are single-owner and observable, not run by API replicas.
SPEC-020 itself authorizes no migration. A later implementation SPEC adds one
only if current tables cannot represent required durable deployment state.

## Rollback strategy

Rollback prefers a compatible prior image/configuration or disabling an
optional capability. A failed schema change receives a forward-compatible
corrective migration; routine production database downgrade is prohibited.
PostgreSQL restore follows the existing backup runbook, then Redis is
reconstructed and Qdrant rebuilt from PostgreSQL as needed. Ambiguous Telegram
delivery uses the explicit operator workflow, never generic rollback.

## Runtime recovery

Deployment operations detect crashed, stuck, or restarting roles; preserve
lease/consumer recovery; alert on pending, dead-letter, quarantine, and stale
lease growth; and retain content-free inspection. Recovery restores PostgreSQL
first, reconstructs Redis coordination, rebuilds Qdrant if needed, verifies
Telegram webhook/polling state, and records release/configuration/operator
references without product content.

Rehearsals cover API loss, worker loss, Redis loss, PostgreSQL restore,
provider outage, Qdrant loss, lease expiry, migration failure, and termination
during external I/O.

## Operational validation

Implementation proof covers unsafe configuration refusal, non-root images,
single-owner migrations, endpoint success/degradation/recovery, role startup,
drain/restart without duplicate terminal effects, secret rotation/revocation,
compatible rollback, backup restore, optional semantic fallback, and
content-safe logs/health/metrics. Synthetic proof does not equal staging or
production evidence.

## Docker and production validation expectations

The implementation phase retains the existing canonical validation, Docker
image build, and Compose configuration validation. It runs relevant database,
ingress, conversation, planning, delivery, command, memory, safety,
observability, reliability, scalability, ambient, summary, semantic-memory,
and backup/restore validators.

An isolated Compose smoke test applies migrations, verifies /, /health, /live,
/ready, and /docs, stops required dependencies to verify safe /ready
degradation and recovery, exercises graceful shutdown, runs docker compose
down, verifies empty docker compose ps, and runs git diff --check.

Production-shaped staging additionally requires dedicated credentials/resources,
an HTTPS webhook, external monitoring, backup evidence, and approved cleanup.
No local validation uses a production bot, chat, or credential.

## Security boundaries

Process roles use least privilege. Database schema ownership is separate from
ordinary application access where supported. Redis and Qdrant are private by
default. Telegram webhook secrets use constant-time validation and rotation.
Images run non-root, contain no repository secrets, and follow selected
supply-chain scanning and pinning. Operators and deployment logs do not become
a second product-data store.

## Privacy implications

Staging never copies production content. Backups inherit PostgreSQL privacy
ownership and are sensitive data. Qdrant vectors and scope metadata remain
privacy-sensitive derived data. Incident evidence uses synthetic/redacted IDs.
Deployment failure must not resurrect deleted memories or redacted messages
through stale derived state. Logs, traces, metrics, queues, health, and crash
reports remain content-free.

## Risks

| Risk | Required mitigation |
|---|---|
| Unsafe hosting assumption | Select platform and operating owner before implementation. |
| Secret exposure | External secret mechanism, redaction tests, image scanning, rotation rehearsal. |
| Hidden worker/API coupling | Separate role definitions and lifecycle tests. |
| Migration race or bad rollback | Single-owner job, compatibility window, staging rehearsal, forward-fix policy. |
| False readiness | Bounded dependency checks plus separate worker/backlog signals. |
| Duplicate shutdown send | Existing ambiguity policy and termination-during-I/O rehearsal. |
| Canonical/derived confusion | PostgreSQL-authority recovery tests and runbook. |
| Staging data leakage | Environment isolation, classification, and access review. |
| Stuck durable work | Lease expiry, reclaim, alerting, and operator rehearsal. |

## Acceptance criteria

Design review is complete when the Product Owner accepts the hosting target and
operating owner; secret manager and rotation boundary; environment topology;
required/optional readiness dependencies; migration compatibility and rollback;
backup RPO/RTO; worker scaling/drain/restart policy; staging resources; and
telemetry, alerting, image-scanning, and audit systems.

Later implementation is complete only with executable or observable proof of
deployed lifecycle, failure, recovery, security, privacy, and cleanup criteria.

## Validation matrix

| Area | Required implementation proof |
|---|---|
| Static | Canonical validation, Ruff, strict mypy, Harness checks, and git diff check. |
| Schema | Database validator, relevant lifecycle, and single-owner migration evidence. |
| Container | Build, Compose config, non-root identity, runtime file/network inspection. |
| HTTP | Endpoint success plus safe dependency degradation and recovery. |
| Workers | Startup, lease reclaim, drain, SIGTERM, restart, and no duplicate terminal effects. |
| External failures | Telegram/provider/Redis/PostgreSQL/Qdrant/Ollama fail-closed/fallback proof. |
| Secrets | Redaction, missing/invalid refusal, rotation, revocation, old-credential rejection. |
| Recovery | Failed migration, compatible rollback, restore, Redis reconstruction, Qdrant rebuild. |
| Privacy | No content/credential leakage in operational artifacts. |
| Staging | Dedicated resources, HTTPS webhook, external monitoring, operator sign-off. |
| Cleanup | docker compose down and empty docker compose ps. |

Existing validators remain authoritative. A target-specific deployment validator
is added only after platform selection; a generic script must not pretend to
validate an unknown orchestrator.

## Required ADRs

The implementation phase must accept decisions for production target/process
supervision; secret manager and rotation; environment/configuration precedence;
migration ownership and compatibility; availability/backup/RPO/RTO; readiness
and worker health; telemetry/alerting/incident access; and image/network
security. This design phase creates no ADRs.

## Required runbooks

Production release/deployment; environment and secret provisioning; secret
rotation/revocation; migration and failed-migration recovery; rollback and
forward-fix; worker drain/restart/lease recovery; Telegram webhook and polling
cutover; PostgreSQL backup/restore/disaster recovery; dependency outage and
readiness degradation; staging validation/cleanup; and incident response with
content-safe evidence.

## Explicit out-of-scope items

Runtime code, migrations, cloud manifests, authentication, administration APIs,
new Telegram media/voice behavior, scheduled messaging, semantic moderation,
billing, provider routing, multi-tenancy, Zalo, automatic webhook mutation at
API startup, and generic replay of ambiguous Telegram delivery.

## Phased implementation plan

1. Decisions: accept hosting, operator, secret, launch-size, availability,
   RPO/RTO, environment, and dependency decisions; add ADRs.
2. Local lifecycle proof: add configuration, role lifecycle, drain,
   readiness/liveness, and container-hardening proof without product-policy
   changes.
3. Staging deployment: create target-specific artifacts, migration job, secret
   references, process definitions, and external monitoring; prove rollout,
   dependency failure, recovery, and cleanup.
4. Recovery/security rehearsal: test rotation/revocation, migration failure,
   compatible rollback, restore, Redis reconstruction, Qdrant rebuild,
   provider outage, Telegram ambiguity, and redacted incident evidence.
5. Production approval: review staging evidence against accepted SLO/RPO/RTO
   and security/privacy criteria, then approve a controlled rollout.

## Product-owner decisions required

- Hosting/orchestration platform and operating owner.
- Secret manager and key-management service.
- Managed versus self-hosted PostgreSQL, Redis, Qdrant, and Ollama.
- Launch size, availability target, RPO, RTO, and maintenance window.
- Required versus optional production readiness dependencies.
- Rolling, blue/green, or canary deployment strategy.
- Staging Telegram/provider accounts, domain, and dedicated test groups.
- Approved monitoring, alerting, image-scanning, and audit systems.

