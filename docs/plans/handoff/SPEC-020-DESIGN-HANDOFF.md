# SPEC-020 Design Handoff

## Baseline

- Baseline before this documentation work: private-source-checkpoint-omitted.
- Worktree was clean and git diff --check passed before edits.
- SPEC-019 is the latest completed implementation; SPEC-014 remains deferred.
- No runtime implementation, migration, commit, or push is authorized.

## Decisions

The Product Owner selected SPEC-020 as Production Deployment, Secrets, and
Runtime Operations. This phase creates the product contract only and does not
select a cloud provider or implement deployment behavior.

The contract preserves PostgreSQL authority, Redis at-least-once coordination,
Qdrant rebuildability, separate worker processes, content-safe operations,
fail-closed external I/O, /live as process-only, bounded dependency-aware
/ready, single-owner migrations, controlled-restart secret rotation, and
forward-fix rather than routine production schema downgrade.

## Files changed

- docs/product/specs/SPEC-020-production-deployment-secrets-and-runtime-operations.md
- docs/plans/handoff/SPEC-020-DESIGN-HANDOFF.md
- docs/product/SPEC.md (sequence/status reference only)
- docs/product/README.md (SPEC index/roadmap reference only)

No runtime code, migration, architecture document, ADR, or runbook is changed.

## Unresolved questions

Hosting/orchestration, operating owner, secret manager, key management, managed
versus self-hosted dependencies, launch size, availability, RPO/RTO, readiness
dependency policy, rollout strategy, staging resources, and approved
monitoring/scanning/audit systems require Product Owner decisions before
target-specific implementation.

## Implementation plan

1. Accept the unresolved deployment/security/recovery decisions and record the
   required ADRs.
2. Add local configuration, role lifecycle, shutdown, readiness/liveness, and
   container-hardening proof without changing product policy.
3. Add target-specific deployment artifacts and a single-owner migration job.
4. Provision isolated staging secrets, Telegram/provider accounts, domain,
   PostgreSQL, Redis, and optional derived services.
5. Validate rollout, degradation, worker recovery, rotation/revocation,
   migration failure, restore, webhook cutover, and cleanup.
6. Obtain staging evidence and approval before production rollout.

## Validation performed

- Read docs/product/SPEC.md, docs/product/README.md, docs/ARCHITECTURE.md,
  private historical execution record (omitted from this snapshot), and
  private historical execution record (omitted from this snapshot).
- Inspected current runtime, validators, Docker/Compose, runbooks, decisions,
  tests, and product SPECs read-only.
- No runtime code, migration, ADR, or runbook was changed.
- Documentation validation: git diff --check.

