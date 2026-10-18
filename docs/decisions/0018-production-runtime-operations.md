# 0018 Production Runtime Operations

## Status

Accepted for SPEC-020 implementation design. The hosting platform, secret
manager, and production operating owner remain product-owner decisions.

## Decision

January keeps a stateless API and independently managed worker roles. API
startup does not run migrations or hidden workers. A single observable
migration job runs before application roles; compatible application versions
may overlap during rollout; and production rollback prefers a compatible image,
configuration rollback, or forward migration rather than routine schema
downgrade.

`/live` is process-only. `/ready` checks bounded required dependencies and
schema compatibility. Optional Qdrant, Ollama, provider, summary, and semantic
index capabilities do not make the API unready when their documented fallback
is safe. Worker readiness and queue/recovery backlog are separate operational
signals.

Secrets are externally injected, validated at the process boundary, redacted
from all operational output, and rotated through controlled restart unless a
selected platform proves safe atomic reload. PostgreSQL remains canonical;
Redis coordination and Qdrant derived state are reconstructible. Graceful
shutdown stops new claims, releases durable leases, and preserves the existing
ambiguous Telegram-delivery quarantine policy.

## Consequences

- Deployment artifacts must define API and worker roles separately.
- Operators need a migration owner, secret owner, recovery owner, and
  environment-specific credentials.
- Local Compose is a staging-shaped validation artifact, not a production
  orchestrator contract.
- Production readiness cannot be inferred from process liveness or optional
  derived-service health.
- A later target-specific ADR is required before cloud/orchestrator manifests
  and live production rollout.

## Alternatives rejected

1. Starting all workers from API lifespan: rejected because it couples scaling,
   restart, and failure domains.
2. Running migrations from every API replica: rejected because it races schema
   ownership and rollout compatibility.
3. Treating Redis or Qdrant as backup authority: rejected because PostgreSQL
   owns canonical state and privacy decisions.
4. Automatically retrying sends after shutdown: rejected because Telegram
   ambiguity can create duplicate visible messages.

## Follow-up

The implementation phase must accept the hosting platform, secret manager,
availability/RPO/RTO, rollout strategy, staging resources, and monitoring
systems before creating target-specific artifacts.
