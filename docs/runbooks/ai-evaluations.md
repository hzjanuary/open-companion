# Offline AI Evaluations

SPEC-032 provides a repository-local conversation-quality regression suite for
Telegram-first product behavior. It is development/CI tooling, not a production
runtime, quality SLO, model-training pipeline, or live acceptance test.

## Canonical run

From the repository root:

```bash
uv run python -m app.runtime.ai_evaluations
./scripts/validate-ai-evals.sh
```

The default suite is `evals/fixtures/telegram-core-v1.json`. Its 64 cases are
repository-authored synthetic data. The validator runs all unit, integration,
negative, determinism and clean-runner proofs without Docker, Telegram/provider
credentials, a production database, or an external network request.

Twelve SPEC-034 cases cover authoritative direct reply selection, erasure and
tenant/Assistant exclusion, history de-duplication, deterministic splitting,
predecessor blocking, first-action reply targeting and ambient/proactive
replylessness.

The concise terminal summary distinguishes `PASS`, `FAIL`, `NOT_EVALUATED` and
`ERROR`. Exit 0 means every objective hard gate ran and passed. Rubric-bearing
cases remain visibly `NOT_EVALUATED` when the optional judge is disabled; that
does not turn them into soft passes. Exit 1 means a hard failure, evaluator
error, or an explicitly evaluated score below threshold. Fixture, argument and
empty-selection errors exit 2.

## Selection and machine output

```bash
uv run python -m app.runtime.ai_evaluations --category media
uv run python -m app.runtime.ai_evaluations \
  --scenario multi-tenant.foreign-tenant-history
uv run python -m app.runtime.ai_evaluations --json /tmp/january-eval-report.json
uv run python -m app.runtime.ai_evaluations --json -
```

`--json -` emits only the `ai-eval-run-v1` JSON document. A path writes the
same sorted, stable document and keeps the summary on stdout. Canonical output
has no timestamp, run UUID, measured duration, prompt, response text, provider
body, secret or production identifier.

## Fixture review

Every scenario must use `ai-eval-scenario-v1`, a stable ID, one closed
evaluator, an explicit synthetic tenant/Assistant/connection/conversation/
participant scope, one to six turns, at least one hard expectation, and
`repository_synthetic` provenance. Inputs are inert JSON and are validated by
the selected evaluator before execution.

Review fixture changes as product-contract changes:

- keep hard safety, privacy, authority, provenance and zero-side-effect gates
  separate from subjective rubrics;
- never lower or remove a hard gate to make a candidate pass;
- never add real messages, Telegram file IDs/tokens, provider keys, production
  UUIDs, raw media, executable hooks, environment expansion or file paths;
- use exact output only for deterministic template/fallback contracts, not
  flexible generated prose; and
- increment suite/scenario schema versions only with matching loader, docs and
  compatibility proof.

The loader rejects duplicate IDs, unknown catalogs/versions, conflicting or
mistyped gates, secret-shaped data, unsafe provenance and any provider mode
other than `disabled` or controlled `mock`.

## Judge and provider boundary

V1 accepts only `--judge disabled`. The code contains a typed future judge
contract and deterministic score aggregation, but no live adapter, credential
lookup or provider construction. A future live judge/provider comparison needs
new Product Owner authority and must use SPEC-026 admission, usage accounting,
explicit provider/model/judge versions, data eligibility and bounded cost. It
can never replace or average away a hard gate.

## Recovery

Evaluation has no migration or production state. Delete an explicitly written
local JSON report when it is no longer useful. If a fixture or evaluator change
regresses the suite, inspect the bounded failing gate and revert or correct the
reviewed source change; do not rewrite a hidden baseline. The current single
Alembic head is `0026_conversation_feedback`; evaluation itself creates no
production state.
