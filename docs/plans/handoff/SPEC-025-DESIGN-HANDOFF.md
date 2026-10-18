# SPEC-025 Implementation Authority and Design Handoff

## Status

APPROVED FOR IMPLEMENTATION AND AUDIT REMEDIATION by Product Owner decision on
2026-08-13. This handoff is retrospective because the interrupted candidate
predated a separate design-handoff file. It records authority; it does not
broaden the approved Product SPEC or authorize SPEC-026.
The Product Owner's 2026-09-02 final authorization additionally approves the
bounded deployment-wide `deployment_operator` authority described below.

## Authorities

- Product contract:
  `docs/product/specs/SPEC-025-data-governance-encryption-export-and-deletion-compliance.md`
- Execution record: `private historical execution record (omitted from this snapshot)`
- Architecture decision:
  `docs/decisions/0022-data-governance-export-erasure-and-audit.md`
- Migration authority: modify the uncommitted `0016_data_governance` migration;
  do not create `0017` for candidate repairs.

## Approved design

- PostgreSQL owns durable export/erasure lifecycle and content-free audit.
- Command identity is the idempotency key for Telegram export and erasure.
- Export packages have one `governance-export-v1` manifest containing request
  reference, scope, generation timestamp, and bounded categories.
- Retrieval credentials are high-entropy bearer values minted only immediately
  before delivery. Only hashes are persisted. HTTP retrieval uses a fixed POST
  path and the `Authorization` header; credentials never enter a URL.
- Telegram delivery reuses the existing outbound worker and ambiguity policy.
  Durable payloads contain only a request reference; ambiguous credential
  sends are quarantined and cannot be generically replayed.
- Governance claims use bounded leases; retention and expiry use deterministic
  bounded batches.
- Erasure in-progress state carries command-worker owner/expiry metadata;
  crash-stranded state is closed with the bounded `worker_restart` reason and
  becomes safely replayable after expiry without stealing an active lease.
- Subject and group operations retain their existing verified-participant and
  fresh-group-admin boundaries. Deployment export requires a durable active
  `deployment_operator` grant on an existing SPEC-021 identity. The grant is
  independent of tenant memberships in both directions and is checked from the
  database on every request.
- The first authority is an explicit self-grant by an externally configured JWT
  subject while no active deployment authority exists. PostgreSQL serializes
  this bootstrap transition. Active deployment operators may then grant or
  revoke other existing identities; every changed state and every denial is
  content-safe audited. Operators must set bootstrap subjects to `[]` before
  intentionally revoking the final authority if they do not want re-bootstrap.
- Grant/revoke request receipts are content-free and uniquely keyed by actor,
  operation, and bounded request ID, so concurrent duplication and delayed
  replay cannot undo a newer authority transition.
- Deployment export is a command-idempotent control-plane POST operation keyed
  by authenticated identity plus bounded request ID. The first call queues the
  request and returns `202`; the governance worker materializes it through the
  normal bounded lease after rechecking current deployment authority. Revoked
  authority terminally fails the request without a package. A repeat after
  completion returns one plaintext retrieval credential in the HTTPS response
  body; only its hash and bounded source metadata persist.
- `/data_summary` is subject-scoped, deterministic, and content-safe.
- Subject erasure and group reset atomically revoke active export credentials
  and clear already-materialized packages for the erased scope.
- A pre-erasure backup cannot contain a later tombstone. Production restore
  therefore requires an operating-owner external erasure record and
  reconciliation before workers or derived-index rebuild resume; the
  repository does not claim to provide that external record.
- External retention durations, encryption/key ownership, compliance
  declarations, backup purge schedule, and production rollout remain
  operating-owner decisions.

## Validation contract

Focused unit/integration proof precedes repository validation. Migration proof
must cover `0015 -> 0016 -> 0015 -> 0016`; deployment validation must require
both governance and retention workers. Docker-only proof may remain explicitly
pending when the execution environment cannot access Docker.

SPEC-026 — not started; Product Owner decision required.
