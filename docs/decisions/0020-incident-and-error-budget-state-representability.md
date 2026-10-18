# 0020 Incident and Error-Budget State Representability

## Status

Accepted for SPEC-023 implementation.

## Context

SPEC-023 authorizes no schema migration. Its implementation must first audit
whether existing content-free state can represent the SLI/SLO, alerting, and
incident state the contract requires: error-budget state, incident state, and
alerting state. Alerting and incident state must never store content or
secrets.

## Decision

The audit found the existing content-free tables and catalog sufficient; no
migration is added.

- Error-budget state: computed on demand from the exported `january_` catalog
  over the rolling 28-day window. No persistence is required; a window with
  missing data reports `unknown`, never zero.
- Incident state: representable in the existing `operational_recovery_items`
  and `operational_recovery_events` tables (recovery classification, actor,
  `replayed_at`) and correlated through `control_audit_events` by opaque
  incident/correlation/run identifiers. Incident evidence and post-incident
  reviews are metadata-only artifacts produced by
  `backend/app/application/observability/incidents.py` and stored under the
  SPEC-022 evidence-bundle convention; they are not a new canonical store.
- Alerting state: declarative configuration plus `january_` counters. The
  staleness signal uses exporter last-seen age; no new metric is added.
- Finding: the durable recovery catalog exposes `stale_lease_count` and
  `oldest_pending_age_seconds` (from `operations inspect`) but not a per-lease
  stale-lease age. The recovery-backlog objective therefore uses those two
  measurable signals as its stale-lease and worker-backlog proxies.

## Alternatives considered

1. An additive migration for per-lease stale-lease age or incident tables:
   rejected because the existing representability is sufficient and no
   migration is authorized without a separate approval including retention,
   privacy, and downgrade rationale.
2. A new canonical incident data store: rejected by the SPEC-023 architecture
   constraints.

## Consequences

- The alembic head remains `0014_authenticated_control_plane`; no
  `backend/alembic/versions/*023*` file exists.
- Incident records and error-budget artifacts stay content-safe and
  metadata-only, consistent with SPEC-011 privacy and retention controls.
- The `validate-observability.sh` validator carries a no-migration guard for
  SPEC-023 mirroring the existing SPEC-015 guard.

## Follow-up

Incident-record retention is governed separately from product-content
retention and stays consistent with SPEC-011; the operating owner approves the
retention and access policy.
