# SPEC-041 — Telegram-first release readiness and production acceptance

Date: 2026-09-28

Status: **APPROVED RELEASE READINESS SPEC**

## Purpose

Establish a production-release acceptance contract for the existing
Telegram-first system. This specification authorizes release-engineering,
configuration, validation, documentation, and operational-proof work only. It
does not authorize a production deployment, live provider spend, feature work,
schema change, commit, push, Zalo work, or SPEC-042.

The exact previous green release baseline is
`private-source-checkpoint-omitted`, with successful GitHub Quality run
`36405527959`. The temporary deferred-CI policy has ended. All locally
reproducible Quality gates are hard gates.

## Release-state vocabulary

- **CODE / CONFIG READY:** repository artifacts, typed configuration,
  deployment representation, runbooks, and local/synthetic acceptance satisfy
  this contract.
- **ACTUAL PRODUCTION DEPLOYED:** an operator has promoted an approved image and
  configuration into production. SPEC-041 does not perform or claim this.
- **LIVE EXTERNAL ACCEPTANCE:** controlled proof against real Telegram,
  provider, DNS/TLS, data services, and monitoring destinations. It is run only
  in an explicitly approved environment with separately managed secrets.
- **APPROVED RELEASE READINESS CANDIDATE — INDEPENDENT AUDIT PENDING:** the
  repository is ready for independent review and operator promotion gates. It
  does not mean deployed or freshly live-verified.

## Release scope

The candidate must prove:

1. configuration fails closed for enabled production capabilities;
2. one known Alembic head and a bounded migration preflight;
3. coherent service topology, startup order, readiness, shutdown, and recovery;
4. credible synthetic backup and restore with authority intact;
5. explicit application rollback versus database downgrade decisions;
6. no committed secrets or secrets baked into the runtime image;
7. fail-closed Telegram, provider, control-plane, governance, and optional
   capability configuration;
8. operational privacy, retention, erasure, export, and derived-state deletion;
9. content-safe observability, SLO, alert, and incident contracts;
10. bounded synthetic staging-style acceptance with no default external I/O;
11. repository approval without uncontrolled production mutation.

## Architecture and authority

PostgreSQL is authoritative for tenant/Assistant/connection ownership,
conversation and work state, memory, knowledge content, provider governance,
schedules, privacy/governance state, voice artifacts, and feedback. Redis is
transient coordination/queue state. Qdrant is optional, derived, content-free
vector state whose candidates must be revalidated against PostgreSQL.

The supported startup sequence is: authoritative dependencies, single-owner
migration preflight and upgrade, API readiness, workers, then external ingress.
`/live` is process liveness. `/ready` requires PostgreSQL at exact head and
Redis whenever configured runtime paths require it; optional disabled
capabilities do not block readiness. Qdrant and local model services degrade
their optional features and do not replace PostgreSQL authority.

Webhook and polling are mutually exclusive ingress ownership modes. Webhook is
the staging representation; polling remains a supported controlled alternative
and refuses to run while a webhook is installed.

## Configuration and secrets contract

`backend/app/core/config.py` is typed runtime authority. `.env.example` is a
complete, placeholder-only inventory, not a production secret file.
`compose.staging.yaml` is a target-neutral staging representation, not a
production deployment engine.

Settings are classified in the release-readiness runbook as required,
conditional/optional, development/test-only, staging representation,
production-sensitive, secret, or non-secret. Production-sensitive settings
record purpose, safe-default status, requirement, validation, and failure
behavior.

Production must reject local database credentials, loopback database/Redis,
debug logging, unresolved placeholders, missing enabled-capability credentials,
incomplete webhook configuration, missing provider model/credential, incomplete
control-plane authentication, inconsistent workers/features, or ungoverned TTS.
Optional capabilities remain valid when disabled.

Secrets are injected at runtime by the operator's secret manager and are never
committed, rendered into evidence, printed by preflight, stored in metrics, or
baked into the image. Repository examples use visibly synthetic values only.

## Migration, backup, and rollback

Migration for SPEC-041 is **NONE**. The only acceptable head is
`0026_conversation_feedback`. Preflight must prove a single source head,
database connectivity, current revision, an upgrade path to that head, and
failure on mismatch. Migration failure stops promotion. No automatic downgrade
or manual `ALTER` is a rollback strategy.

Before production migration, an operator must produce and verify an
authoritative PostgreSQL backup under an approved retention/RPO/RTO policy.
Redis is not restored as truth; Qdrant is rebuilt. Post-backup erasures must be
reapplied from an external operator record before workers or ingress resume.

Application rollback is preferred when the current schema remains compatible.
Guarded destructive downgrades are forbidden when current governed state would
be lost. In that case disable traffic/capability as appropriate and forward-fix
at the current schema. Restore requires incident authority and reconciliation
of privacy deletions and derived state.

## Runtime and acceptance contract

The deployed topology consists of an API/webhook process; dispatcher,
conversation, planning, command, outbound, scheduler, governance, retention,
and provider-governance workers; PostgreSQL; Redis; and optional Qdrant,
knowledge indexing, semantic-memory indexing, and summary workers when their
features are enabled. Each worker uses bounded leases, current authority, and
graceful drain; no exactly-once external-I/O claim is made.

Synthetic acceptance must cover Telegram text, ordered splits/replies, edits,
voice, retries/unknown outcomes, presence and reactions; provider admission,
budgets, rate/concurrency, usage and possible-I/O; memory, personal context,
semantic memory, knowledge/RAG, schedules, privacy/governance, feedback,
multi-tenancy, safety, observability, backup/restore, and recovery. No database
session/transaction/lock may span Telegram, provider, TTS, reaction, embedding,
or Qdrant I/O.

The guarded SPEC-022 live mechanism is documented but not automatically run.
Absent credentials or infrastructure are external prerequisites, not synthetic
test failures. Current repository approval may rely on historical live
chronology plus current synthetic regression; fresh live proof is an
operator-time promotion gate.

## Observability, SLO, and incident contract

Metrics and logs are content-safe and bounded: no prompt, response, memory,
knowledge, audio bytes, credentials, raw provider body, or prohibited identity
labels. Operational failure classes remain visible. SLOs and alerts are
repository documentation/configuration contracts until an operator supplies
and verifies a monitoring backend and notification destinations; SPEC-041 does
not claim external alerts are active.

The release checklist covers inbox lag, planning failure, provider admission
and failure, outbound retry/unknown, lease recovery, pool saturation, Redis,
optional Qdrant degradation, privacy workers, traffic disable, provider
disable, restore decisions, and escalation.

## Quality and security gates

Every direct GitHub Quality validator and every additional product-critical
validator must exit zero. Scripts directly invoked by Quality retain mode
`100755`; workflow checks and selectors are not weakened. Canonical evaluation
remains exactly 130 total, 125 PASS, 5 historical judge-disabled
NOT_EVALUATED, 0 FAIL, and 0 ERROR. SPEC-041 adds zero product-evaluation
scenarios.

Security review covers secret leakage, debug mode, control-plane exposure,
network binding, default credentials, webhook trust/body bounds, provider URL
configuration, and media/object path or URL handling. Fresh services and a
VCS-free candidate must prove no dependency on `.git`, `.env`, developer
`.venv`, hidden fixtures, real credentials, or unrelated Docker state.

Any new canonical failure, schema requirement, product behavior requirement,
Critical finding, or High finding blocks approval. There is no deferred-debt
classification.

## External prerequisites

Operator approval and provision are required for:

- dedicated Telegram bot token, public webhook URL, DNS/TLS, webhook secret,
  canonical connection, and bounded live test chat;
- production PostgreSQL and Redis, and Qdrant/local embedding service only for
  enabled derived-index features;
- approved provider accounts, credentials, models/capabilities, pricing,
  budgets, data-handling eligibility, credits, and rate/concurrency values;
- production secret manager and credential rotation/revocation ownership;
- hosting/orchestration, immutable image reference, network/TLS controls, and
  a single migration owner;
- identity provider values, deployment bootstrap subjects, role review, and
  named deployment/incident/rollback/restore owners;
- backup destination, retention, restore authority, RPO/RTO, and post-backup
  erasure-reapplication record;
- monitoring backend, dashboard, alert thresholds, notification destinations,
  and on-call/escalation ownership; and
- final independent audit and operator promotion approval.

Unavailable prerequisites do not fabricate proof or imply code failure unless
the repository contract itself is wrong.

## Acceptance

Approval requires all mandatory SPEC-041 gates, no product behavior or
migration, exact baseline continuity, a complete configuration inventory,
fail-closed production configuration, clean container/build, fresh database,
migration preflight, backup/restore, dependency-aware readiness, all capability
validators, complete Quality, VCS-free and fresh-service proof, no real-secret
dependency, exact external-prerequisite classification, and zero
Critical/High findings.

The successful repository-only status is:

**APPROVED RELEASE READINESS CANDIDATE — INDEPENDENT AUDIT PENDING**
