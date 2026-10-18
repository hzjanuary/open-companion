# SPEC-042 Design Handoff

Date: 2026-09-30

Status: APPROVED PRODUCTION PROMOTION DESIGN

## Authority and scope

The [Product Spec](../../product/specs/SPEC-042-production-promotion-live-acceptance.md)
implements the user's explicit no-production-authority boundary. This is
target-neutral release engineering, not selection of hosting, new product,
schema, features, new permissive gate or automatic deployment. Baseline
`private-source-checkpoint-omitted`, successful Quality `36721562006`,
single head `0026_conversation_feedback`. No migration and Zalo frozen.

## Artifact and environments

Build approved source via `git archive` into a fresh directory, no developer
`.env`/`.venv`/Git. Compare archive blob content/modes with the commit and runtime
source with the export. No-cache pulled-base Docker build uses locked non-dev
dependencies, non-root runtime and revision label. Record index/platform/config
digests and build-input/base digests. Local digest is not registry publication.
The manifest (private execution record omitted from this snapshot) retains the actual
identity and evidence. Promotion docs/tooling are deliberately outside the
approved runtime artifact; any runtime diff would require a new approved SHA.

Classifications: local isolated synthetic rehearsal; separately provisioned
authorized staging; actual production. Never reuse production secrets/bots/
queues/chats/destinations for synthetic validation. `compose.staging.yaml`
hardcodes staging/webhook and is a reference, not a production deploy engine.
No production controller/target is supplied; its commands must be attached and
reviewed by the operator before execution, not fabricated here.

## Configuration and secrets

Existing `validate-production-readiness.sh` offline mode is the first gate.
`--production-config` validates injected Settings without network or `.env`.
`--database-preflight` additionally uses a bounded read-only transaction and
requires a known single revision on the approved path. Production DB contact
still requires explicit read-only access authority. Synthetic passes have
explicit synthetic provenance, never production labels.

New `production-config-fingerprint.sh` is offline tooling only, reusing the
existing metadata allowlist plus secret-name injection presence; canonical JSON
SHA256 never includes secret values. It intentionally cannot detect secret
rotation or every config change. Pair with an approved non-secret config
revision and protected secret-version references. Tests prove deterministic
normalization, metadata/presence sensitivity, rotation invariance and redacted
failure. No runtime/application module changes.

Secrets remain runtime-injected, excluded from Git/build/logs/metrics/evidence.
No printing raw Compose environments, tickets, IDs, URL credentials or runtime
model dumps. A secret available locally would not establish release authority.

## External approval and prerequisite handling

Existing SPEC-022 explicit confirmation flags are necessary operation guards;
they are not production release tickets. No target-specific approved promotion
mechanism or approval was supplied. Document an operator-reviewed record of
target/digest/config/actions/owners/window/bounds; do not create a truthy env
flag and declare approval. Inventory each prerequisite by observed availability.
Unavailable credentials/approval are NOT AVAILABLE; target/backend/owner facts
not supplied are UNKNOWN; disabled optional dependencies may be NOT REQUIRED.
Keep package work possible while every external gate remains NO-GO.

## Deployment and readiness sequence

1. Freeze source/index/config, exact-SHA green Quality and independent review.
2. Obtain explicit target/action approval and role ownership; verify encrypted
   PostgreSQL backup, restore authority, privacy reconciliation and RPO/RTO.
3. Inject config; run offline, production-config and authorized read-only DB
   preflight. Inspect schema/catalog integrity without user content.
4. At head skip migration. Supported older revision requires separate approved
   single-owner bounded upgrade. Unknown/newer/diverged is blocked.
5. Deploy approved digest through operator-reviewed controller with ingress
   closed; start API, dependencies and required workers; require `/live`,
   `/ready`, exact head, lifecycle/loop/backlog and error observations.
6. Verify safety/auth/privacy/governance, monitoring/alerts/on-call, exclusive
   Telegram owner and explicit GO before opening ingress.
7. Run separately scoped Telegram/provider/TTS smoke; then observe the approved
   finite window, apply abort criteria and record the actual outcome.

Worker map: `ingress_outbox_dispatcher`, `conversation_worker`,
`response_planning_worker`, `telegram_command_worker`,
`outbound_delivery_worker`, `governance_worker`, `retention_worker`,
`provider_governance_worker`; `proactive_scheduler_worker` when enabled.
Optional `conversation_summary_worker`, `semantic_memory_index_worker`,
`knowledge_index_worker` need feature/worker config and matching Compose profile.
Recovery is inside existing lease/claim paths and provider-governance worker,
not a fictional standalone recovery service. API is not a worker supervisor.

PostgreSQL is truth, Redis transient, Qdrant derived. Disabled Qdrant absence
does not block core readiness. `/live` survives dependency failure; `/ready`
requires current head and configured Redis. Synthetic startup uses new volumes,
unique ports, health/dependency probes, no correctness sleeps and no external
Telegram/provider traffic. Running optional flags without the required worker
profile is a deployment NO-GO even if global readiness is green.

## Ingress and live proof

Webhook and polling are exclusive. Inspect identity/current state only after
live authority; do not register at startup. Mode transition drains/stops the
old owner, explicitly mutates/verifies webhook state when authorized, then
activates the new owner and verifies again. Never drop pending updates by
default. Public endpoints require HTTPS/TLS validation.

The updated [live runbook](../../runbooks/live-acceptance.md) bounds a run to
at most ten outbound Telegram calls including automated presence, reaction,
retry and lifecycle overhead. Reserve worst-case capacity before stimulating
work. Provider-backed replies need explicit billing approval; fake-adapter proof
is used without it. TTS needs both authorizations, opt-in capability, one
generation and governed purge eligibility. No real destructive privacy smoke.

Durable live proof checks ingress/idempotency, ownership, plan/action, terminal
delivery/mapping, no duplicate or foreign scope. Use opaque aliases/counts;
existing collector identifiers remain restricted and are sanitized before
repository evidence. Never archive live bodies or audio in release docs.

## Operations, incidents and observation

Metrics/logs/dashboard/alert destination and incident/privacy/on-call coverage
must be demonstrated before traffic, not inferred from SPEC-023 files. The
operator approves the finite observation window, cadence and abort thresholds;
unratified operational defaults do not authorize new release policy. Observe
readiness, worker/inbox lag, planning/provider/outbound/unknown, pool/Redis and
privacy failures. Missing window/backend/owner means NO-GO.

Authority/security/privacy failure is immediate traffic disable. Sustained
errors follow approved thresholds. Preserve durable state; stop affected
external-I/O workers and ingress through the actual target controller. Webhook
delete and token rotation require their own authority. Application rollback
requires previous immutable digest and schema compatibility; unknown means
not ready, incompatible means forward-fix. No blind DB downgrade. Restore is
separately authorized, reconciles erasures and rebuilds derived state.

## Quality and retention

Current workflow and selectors unchanged. All 24 direct scripts, every inline
CI command, named supplemental gates, new-tool tests, static/shell/Harness and
exact VCS-free checks must pass; modes 100755, reliability zero failures and
eval 130/125/5/0/0. Secret scanning reports paths/counts only; synthetic fixtures
are reviewed, not called live credentials. No Critical/High issue may remain.

Retain redacted logs locally for audit and repository metadata summary. External
evidence retention/access destination is operator-approved; no production data
retention duration is invented. Independent OpenCode audit is the next step.
