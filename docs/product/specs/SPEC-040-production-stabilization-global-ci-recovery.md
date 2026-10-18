# SPEC-040 — Production Stabilization and Global CI Recovery

Date: 2026-09-27

Status: **APPROVED STABILIZATION SPEC**. This approval authorizes only the
bounded reliability, clean-runner, and release-gate recovery work described
here. It authorizes no product feature, production behavior change, schema
weakening, commit, push, or remote workflow mutation.

## Purpose

SPEC-040 ends the temporary deferred-global-CI policy carried by SPEC-033
through SPEC-039. The candidate must remove the six historical
`fk_assistants_tenant` reliability failures at their true cause and prove that
the complete current GitHub Quality workflow is reproducible and green from
clean local state.

This is stabilization work. It adds no Telegram behavior, command, provider
capability, user setting, memory or RAG behavior, evaluation scenario, or other
product surface. Zalo remains frozen.

## Historical debt

The deferred failure family is the six stateful cases in
`backend/tests/integration/test_memory_schema.py` that construct an Assistant
using tenant ID `00000000-0000-4000-8000-000000000030`. Historical global
Quality evidence reported six failures at the production
`fk_assistants_tenant` constraint and left global Quality red while bounded
SPEC validators were accepted.

SPEC-040 does not accept that outcome. Local approval requires zero reliability
failures and every locally reproducible Quality command exiting zero. Remote
Quality remains pending until an independently reviewed candidate is committed
and pushed by the Product Owner.

## Production authority decision

`control_tenants -> assistants -> platform_connections -> conversations` is
the current production authority chain. Every Assistant must reference a real
tenant, and `fk_assistants_tenant` is correct, required production behavior.
The constraint must remain enforced.

Migration `0021_multi_assistant_tenancy` uses the fixed legacy tenant only to
canonicalize migration-time legacy ownership when its documented predicate is
true. That migration behavior is not authority for an integration test to
assume an immortal global fixture. Production runtime must not create a magic
tenant to make tests pass, and UUID `...0030` receives no production special
case.

Tests that create tenant-owned rows must establish their complete authority
graph explicitly. Any shared repair must remain test-scoped, deterministic,
transaction-safe, order-independent, and no broader than the affected setup.

## Schema and migration contract

No migration is expected or authorized. The required single Alembic head
remains `0026_conversation_feedback`.

If the investigation shows that production schema behavior must change, work
stops before creating a migration with status
`BLOCKED — SCHEMA CHANGE REQUIRES PRODUCT/ARCHITECTURE DECISION`.

## Clean-runner contract

The candidate must succeed without a developer `.venv`, ignored `.env`, local
credentials, pre-existing database contents, default host ports, unrelated
Docker resources, untracked hidden fixtures, deep Git history, shell aliases,
or user-specific paths. Repository readiness probes and the canonical UV
resolver remain authoritative. Validation uses unique Compose project names,
supported alternate ports, bounded readiness checks, and only destroys
SPEC-040-owned resources.

A VCS-free candidate export must contain tracked baseline files, tracked
candidate modifications, untracked candidate additions, and candidate
executable modes, but no `.git`. Its clean-runner-compatible matrix includes at
least `validate.sh`, `validate-reliability.sh`, `validate-ai-evals.sh`, and
every validator changed by SPEC-040.

## Validator and test integrity

Green may not be obtained by reducing test selection; adding skip or xfail;
accepting nonzero status; filtering failures; using `continue-on-error`, failure
masking, arbitrary correctness sleeps, disabled workflow steps, weakened
constraints, disabled triggers, or production-like global bootstrap state.

The preferred validator change is no change. If a validator lifecycle defect
is proved, its repair must be transparent and preserve or strengthen coverage.
The reliability validator remains a hard gate.

The affected six tests must pass individually on fresh databases, together in
file order, in reverse order, and in deterministic alternate orders. The full
memory marker and full reliability validator must pass. A direct SQL attack
must still reject an Assistant with a nonexistent tenant and accept an
Assistant only after its Tenant exists.

## Quality and evaluation contract

Every correctness command directly executed by `.github/workflows/ci.yml`,
plus all current product-critical SPEC-033 through SPEC-039 validators, must be
mapped and run locally. Every direct CI shell entrypoint must have candidate Git
mode `100755`. Static format, lint, type, shell, Harness, migration lifecycle,
fresh-database, independent-database, test-order, PATH-UV, shallow-history, and
security/privacy checks must all pass.

SPEC-040 adds zero product evaluation scenarios. The canonical result remains
exactly 130 total: 125 PASS, 5 expected judge-disabled NOT_EVALUATED, 0 FAIL,
and 0 ERROR.

## Stabilization orchestration decision

Do not add `scripts/validate-production-stabilization.sh` merely as a wrapper.
The GitHub Quality workflow and existing validators are the authoritative
orchestrators, and the completed-plan matrix will record their direct results.
Create a dedicated script only if investigation proves a reusable,
non-duplicative clean-runner contract that existing entrypoints cannot express;
otherwise its additional indirection has no product or release-engineering
value.

## Documentation and debt closure

The final candidate documents the precise authority-chain root cause, the
before/after failure counts, the corrected setup layer, the full Quality
mapping, fresh-state and VCS-free proof, repeatability, and troubleshooting.
Historical handoffs retain their truthful chronology; SPEC-040 records that
their deferred global debt is locally resolved and awaits remote proof.

## Approval gates

The only successful local status is
`APPROVED STABILIZATION CANDIDATE — REMOTE CI PENDING`. It requires:

- all six historical tests and the full memory suite green in order-independent
  fresh-state runs;
- `validate-reliability.sh` exiting zero with zero failures, repeatedly;
- all locally reproducible Quality commands exiting zero;
- the unchanged canonical evaluation result;
- the production foreign key and invalid/valid insert proofs;
- a green VCS-free clean candidate and clean-runner proof;
- no Critical or High findings; and
- no new product behavior or migration.

No local result may claim `COMPLETE`. Remote closure requires a later real
GitHub Quality run on the Product Owner's reviewed and pushed SHA.
