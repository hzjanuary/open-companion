# Production Stabilization and Quality Recovery

This runbook is the operational record for SPEC-040. It adds no product
behavior and no migration. The required single Alembic head remains
`0026_conversation_feedback`.

## What was repaired

The production authority chain is:

```text
control_tenants -> assistants -> platform connections -> conversation data
```

`fk_assistants_tenant` is intentional and remains validated with `ON DELETE
RESTRICT`. Two integration-test setups had stale assumptions after canonical
multi-tenancy was introduced:

- six memory-schema tests truncated Assistants and then constructed an
  Assistant for the synthetic legacy tenant without ensuring that Tenant still
  existed; the broad reliability order exposed this after knowledge-RAG setup
  replaced tenant rows;
- the demo-bootstrap test truncated Assistants but implicitly relied on exactly
  one active Tenant remaining after earlier Quality steps.

The memory tests now use one file-local helper to establish the synthetic
legacy Tenant inside the same setup transaction before creating Assistants.
The demo test explicitly establishes and selects that same synthetic Tenant.
Neither helper is autouse or reachable from production runtime. Production
bootstrap, models, migrations, and constraints are unchanged.

## Canonical checks

Start with the repository validators, not ad hoc SQL changes:

```bash
./scripts/validate.sh
./scripts/validate-reliability.sh
./scripts/validate-ai-evals.sh
```

Reliability is a hard gate. A valid result ends with:

```text
All checks passed!
Reliability checks: valid
```

The canonical eval inventory remains 130 scenarios: 125 `PASS`, five
judge-disabled `NOT_EVALUATED`, zero `FAIL`, and zero `ERROR`.

Run every direct validator and inline pytest/migration step in
`.github/workflows/ci.yml`; `validate.sh` alone is not the full Quality job.
Also run the product-critical validators that are not direct workflow steps:

```bash
./scripts/validate-conversation.sh
./scripts/validate-governance.sh
./scripts/validate-backup-restore.sh
./scripts/validate-memory.sh
```

## Fresh database and alternate ports

Use a unique Compose project and unused supported ports. Do not stop unrelated
host stacks.

```bash
COMPOSE_PROJECT_NAME=spec040-reliability \
JANUARY_DB_HOST_PORT=5580 \
JANUARY_REDIS_HOST_PORT=6430 \
./scripts/validate-reliability.sh
```

Destroy only that validation project when finished:

```bash
COMPOSE_PROJECT_NAME=spec040-reliability \
JANUARY_DB_HOST_PORT=5580 \
JANUARY_REDIS_HOST_PORT=6430 \
docker compose down -v --remove-orphans
```

Fresh-state proof means a newly created PostgreSQL volume, `base -> head`, and
no seed row supplied by another validator. Use Docker health/readiness probes
and `scripts/lib/db-ready.sh`; do not add sleeps for correctness.

## Tenant-integrity check

On a freshly migrated test database:

1. Inspect `pg_constraint` and require validated
   `fk_assistants_tenant` with `RESTRICT` delete behavior.
2. Insert an Assistant referencing a nonexistent Tenant and require PostgreSQL
   to reject it on that named constraint.
3. Insert a synthetic Tenant, then its Assistant, and require success.

Never disable the constraint, use `NOT VALID`, change the Tenant column to
nullable, or create a production magic Tenant to make a test pass.

## Clean runner and candidate export

The release candidate must work without `.git`, ignored `.env`, credentials,
developer shell aliases, prior volumes, or user-specific paths. Build the
export from the baseline plus all candidate tracked changes, untracked
candidate files, and candidate executable modes. In the VCS-free tree run at
minimum:

```bash
./scripts/validate.sh
./scripts/validate-reliability.sh
./scripts/validate-ai-evals.sh --clean-inner
./scripts/validate-zalo-verification.sh
./scripts/validate-conversation-feedback.sh --clean-inner
```

The `--clean-inner` modes are the validators' explicit no-Git entrypoints. In
the ordinary repository worktree, invoke those two validators without the flag
so their outer clean-export orchestration is also exercised.

Use `scripts/lib/resolve-uv.sh` when invoking UV from repository scripts. For a
CI-like PATH proof, expose an ordinary `uv` executable on `PATH` and do not rely
on `.venv` link stubs or shell aliases.

## Troubleshooting

- `fk_assistants_tenant` in a test setup means the test omitted current Tenant
  authority or leaked state/order; inspect rows immediately before the
  Assistant insert. Do not alter the production constraint.
- `exactly one active tenant or telegram_tenant_id is required` means a test or
  deployment must supply unambiguous tenant authority. Tests should create and
  select their synthetic Tenant explicitly.
- Port allocation errors mean a validation project reused a host port. Choose
  another supported port and a unique Compose project; do not stop the process
  that already owns it unless it is known SPEC-040 state.
- A missing `uv` command is an environment preflight failure. Install UV on
  `PATH` or provide the documented executable at `.tools/uv`; never depend on a
  user-specific absolute path.
- A validator that requires Git history or ignores nonzero test status is not a
  valid clean-runner proof. Fix the validator transparently without reducing
  coverage.

## Release gate

Local approval may be reported only as
`APPROVED STABILIZATION CANDIDATE — REMOTE CI PENDING` after the complete second
Quality matrix and VCS-free candidate are green, with zero Critical or High
findings. Do not commit or push as part of SPEC-040 implementation. Global CI
debt closes only after independent audit, Product Owner commit/push, and a real
green GitHub Quality run on that pushed SHA.

That remote gate is now closed for committed baseline
`private-source-checkpoint-omitted`: GitHub Quality run `36405527959`
completed successfully. Historical SPEC-033 through SPEC-039 handoffs keep
their original chronology, but their deferred-CI exception is no longer active.
SPEC-041 and later work must keep every Quality gate green.
