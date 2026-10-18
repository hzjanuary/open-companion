# SPEC-040 Design Handoff

Status: **APPROVED STABILIZATION DESIGN**

Date: 2026-09-27

## Reproduction strategy

Use unique Compose project names and alternate host ports. Destroy and recreate
the SPEC-040-owned PostgreSQL volume before each isolated reproduction, migrate
base to the single current head, inspect the expected tenant row, and select
the repository integration marker explicitly. Preserve exact commands and
results in the active and completed plans.

Run the six historical tests individually, then together in source order,
reverse order, and deterministic alternate permutations. Next run the full
memory validator and the exact reliability validator. If isolated tests pass
but the chain fails, bisect validator/test state transitions and inspect tenant
authority immediately before the first failing insert.

## Failure root-cause tree

The investigation distinguishes four branches:

1. **Missing local authority setup:** a test creates an Assistant for a tenant
   it did not create and happens to pass only when migration or prior-test state
   supplies that row.
2. **Order/state leakage:** an earlier test or validator removes the legacy
   tenant or leaves a partial schema, while affected setup assumes it remains.
3. **Validator lifecycle defect:** database reset or migration cycling differs
   between standalone and chained execution.
4. **Production contract defect:** the foreign key or migration is wrong. This
   branch requires Product/Architecture review and blocks implementation; it is
   not authorized by this handoff.

Initial evidence rules out a deterministic six-test body failure on pristine
head databases: all six pass individually with the legacy migration row
present, and the standalone memory validator passes its full migration cycle.
The broader reliability chain remains the next authoritative reproduction.

## Database authority expectations

The required graph is:

```text
ControlTenantModel
  -> AssistantModel(tenant_id)
  -> PlatformConnectionModel(tenant_id, assistant_id)
  -> conversation / participant / message / memory state
```

The production `fk_assistants_tenant` is preserved. Migration
`0021_multi_assistant_tenancy` may create the reserved legacy tenant while
canonicalizing legacy data, but tests may not treat that conditional migration
row as an immortal fixture. A direct nonexistent-tenant insert must fail and a
Tenant-then-Assistant insert must succeed.

## Fixture lifecycle

If chain reproduction proves stale affected setup, repair the smallest shared
test-local layer in `test_memory_schema.py`: explicitly ensure the synthetic
Tenant before the Assistant within the setup transaction. Prefer one named,
scoped helper used by exactly the affected tests over six magic inserts or a
broad autouse fixture. The helper must tolerate a migration-provided row,
create it when absent, avoid unrelated seed data, and not escape into runtime.

Cleanup and subsequent setup must not rely on a previous test. Fixed authority
IDs are acceptable only inside isolated serial database tests and must be
documented; no claim of cross-worker parallel safety will be made without
running that proof.

## Isolation and clean runner

All destructive database operations target only named SPEC-040 Compose
projects. Use `scripts/lib/db-ready.sh` and health checks, not sleeps. Leave
unrelated host containers and volumes untouched. Unset credentials and reject
`.env` in VCS-free proof. Resolve UV through `scripts/lib/resolve-uv.sh`; do not
depend on the developer shell or project-local link stubs.

The candidate export is built from the tracked baseline plus all candidate
changes and executable modes, excludes `.git`, and runs on unique service
ports. Shallow-history proof inspects each validator for historical-object
dependencies and exercises the candidate without Git metadata.

## Quality workflow mapping

Read `.github/workflows/ci.yml` as the source of truth. For every Quality step,
record the exact local command, services, environment, and result. Do not infer
coverage from `validate.sh`; execute each direct validator and inline migration
or pytest command. Add product-critical SPEC-033 through SPEC-039 validators
that are not direct steps.

The full matrix is run once after the repair and again from clean final state.
Canonical eval must remain 130 / 125 PASS / 5 NOT_EVALUATED / 0 FAIL / 0 ERROR.

## Docker and service isolation

Use per-run `COMPOSE_PROJECT_NAME` values and supported PostgreSQL, Redis, and
Qdrant host-port variables. Inventory running resources before and after the
matrix. Never stop or modify unrelated stacks. Remove only resources whose
project names were created for SPEC-040.

## Executable-mode audit

Enumerate each direct `./scripts/*.sh` invocation in Quality and compare its
candidate Git mode and worktree mode. Every direct script must be `100755` in
the candidate. Run `bash -n` on shell surfaces and reject mode repair that is
present only in the local filesystem but absent from candidate metadata.

## Migration-head audit

No migration is planned. `uv run alembic heads` must return only
`0026_conversation_feedback`. Existing lifecycle and populated-downgrade guards
must remain unchanged and green. A need for schema change blocks the work.

## No-test-weakening policy

Candidate diffs and relevant workflow/script/test surfaces are searched and
reviewed for skip, xfail, failure masking, `continue-on-error`, reduced
selection, correctness sleeps, broad exception swallowing, constraint/trigger
weakening, production magic IDs, and disabled Quality steps. Existing unrelated
cleanup idioms are not silently represented as candidate changes; any touched
line must retain honest exit behavior.

## Final local gate

Approval requires all 36 mandatory proofs, zero Critical/High findings, a green
second full clean matrix, repeated fresh reliability passes, clean VCS-free
candidate results, unchanged product/eval behavior, single migration head, and
an exact final worktree report. No partial or allowed-red result qualifies.

## Remote GitHub gate

No commit, push, dispatch, or GitHub mutation occurs in SPEC-040. Local success
is `APPROVED STABILIZATION CANDIDATE — REMOTE CI PENDING`. Global debt closes
only after independent audit, Product Owner commit/push, and a real green
GitHub Quality run on that SHA.
