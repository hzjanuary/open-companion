# 0022 Data Governance Export, Erasure, and Audit

## Status

Accepted for SPEC-025 implementation.

## Context

SPEC-025 makes data governance a product surface: subject, group, and
deployment exports with single-use expiring retrieval; erasure wrapped on the
existing `/forget_me` and `/memory reset_group` paths; a written retention
schedule with automated enforcement; content-free governance audit; and a
declared encryption-ownership and compliance posture. The existing
content-safe audit surface (`control_audit_events`, `safety_policy_decisions`)
cannot represent export request lifecycles, temporary export packages, erasure
completion status, or the bounded governance audit trail, and the existing
retention worker does not purge governance audit records.

## Decision

One additive alembic migration (`0016_data_governance`, head after
`0015_safety_moderation`) adds content-free lifecycle state, a deployment
authority surface, and the explicitly authorized temporary export-package
surface:

- `control_deployment_authorities` — one durable, revocable
  `deployment_operator` capability attached to an existing SPEC-021 identity,
  independent of tenant memberships. Grant/revoke and denied decisions use
  `control_audit_events` with a null tenant scope, so
  `control_audit_events.tenant_id` becomes nullable. An externally configured
  JWT subject may explicitly self-grant only while no active deployment
  authority exists; establishment is serialized in PostgreSQL. Afterwards only
  an active deployment operator may grant or revoke. Authorization always reads
  current database state, so revocation applies on the next request.
- `control_deployment_authority_operations` — content-free mutation receipts
  uniquely keyed by actor, operation, and bounded request ID. They make
  concurrent calls idempotent and prevent a delayed old grant replay from
  undoing a later revocation. The existing control-audit request-ID column is
  widened to the middleware's established 128-character bound.

- `governance_export_requests` — export request lifecycle (scope, status,
  category list, single-use token hash, expiry, delivery timestamps). The token
  hash is SHA-256 of a high-entropy value minted immediately before outbound
  adapter I/O; the plaintext credential exists only in memory and is never
  persisted. Durable command/outbound rows carry only the request ID.
- `governance_export_packages` — the materialized single-use package for one
  request; delivered at most once (retrieval clears it) and expired by the
  governance worker after `governance_export_ttl_days`.
- `governance_erasure_requests` — durable content-free erasure records with
  complete/partial/failed status and an owner/expiry lease for crash recovery,
  written by the existing `/forget_me confirm` and `/memory reset_group`
  command paths.
- `governance_audit_events` — content-free audit trail for export and erasure
  requests, completions, and failures, carrying opaque scope references and
  closed outcomes only (NFR-01/FR-12). Bounded by
  `governance_audit_retention_days` and purged automatically by the retention
  worker (FR-08).

Group reset coverage is extended to derived summaries (FR-07) by a new
`GROUP_RESET` invalidation reason in `SummaryInvalidationReason`; subject
erasure already covers derived summaries and the derived index. The
content-free deployment manifest is exposed through the authenticated
control-plane POST surface only to an active `deployment_operator`. No tenant
role is promoted to deployment authority, and deployment authority grants no
tenant access. The request's bounded control-plane request ID provides the
durable idempotency key. The first POST returns `202`; the existing governance
worker uses the normal lease/materialization path; a repeat after completion
returns the export credential once in the HTTPS response body. It is persisted
only as a hash and never placed in a URL. The worker rechecks current deployment
authority after claim and before materialization; a revoked principal produces
a terminal content-free `authorization_revoked` failure and no package.

Retrieval uses a fixed POST path and the `Authorization` bearer header so the
credential never appears in a URL, request path, or query string. Telegram may
retain the delivered credential as an external platform copy; Lumi does not.
Ambiguous delivery follows the existing outbound quarantine policy and generic
requeue is refused for credential-bearing late-bound actions.

Subject erasure and group reset take precedence over export: in the same
primary-database transaction they revoke matching token hashes, expire active
requests, and clear materialized packages. Retrieval locks the request row so
concurrent requests remain single-use and serialize against erasure.
Lifecycle request, completion, partial/failure, retrieval, and expiry audit
events commit in the same PostgreSQL transactions as their corresponding state
transitions; uniqueness fences ordinary replay.

The migration id is `0016_data_governance` because the alembic `version_num`
column is `varchar(32)`.

## Alternatives considered

1. Reusing Redis or ephemeral storage for export packages: rejected; packages
   must survive restarts, be independently verifiable, and expire under a
   declared schedule.
2. Storing export tokens in plaintext: rejected; tokens are bearer
   credentials and are stored as one-way hashes only.
3. A content-bearing governance store: rejected; SPEC-025 governance surfaces
   are content-safe by construction except the subject's own export package.
4. Extending the existing audit tables instead of adding a governance audit
   table: rejected; governance events carry governance-specific request and
   scope references, and a dedicated content-safe table keeps the retention
   schedule bounded and explicit.
5. Inferring deployment authority from a tenant role: rejected; administering
   one tenant is not authority over the deployment.

## Consequences

- The alembic head is `0016_data_governance`; the readiness check
  (`backend/app/infrastructure/database/database.py`), the command, memory,
  and safety schema-pin tests, and `validate-backup-restore.sh` reference it.
- `scripts/validate-governance.sh` exercises `downgrade 0015_safety_moderation`
  then `upgrade head` to prove the migration is cleanly additive.
- Configurable defaults are not policy authority: `governance_export_ttl_days`
  (default 2, range 1–7) and `governance_audit_retention_days` (default 90,
  range 30–365) are operator-configurable settings; the written retention
  schedule (FR-08) distinguishes automatically enforced schedules from
  operator-configurable ones.
- Erasure, export, and retention all fail closed on repository errors; export
  retrieval is single-use and deny-by-default (NFR-04).
- The change is additive and downgrades cleanly to `0015_safety_moderation`;
  downgrade drops the four governance tables and the deployment-authority
  table, removes deployment-scoped control audit rows, and restores the prior
  non-null tenant constraint.

## Follow-up

Retention for the pre-existing `safety_review_items` and
`safety_policy_decisions` surfaces stays under SPEC-011/SPEC-024 controls;
SPEC-025 adds bounded retention for `control_audit_events` and
`governance_audit_events` only. Multi-tenant expressibility of every
governance surface is future work. The operating owner approves the written
retention schedule, the encryption-ownership matrix, and the compliance
posture with the SPEC-025 handoff.
