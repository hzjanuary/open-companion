# SPEC-032 Design Handoff

Date: 2026-09-13

Status: **APPROVED DESIGN**. Product authority is
`docs/product/specs/SPEC-032-ai-evaluation-conversation-quality-framework.md`.
Implementation is authorized within this bounded design.

## Existing audit

No existing conversation-quality framework exists. SLO alert evaluation is a
separate operational concern. The implementation must reuse pure production
seams—context construction, response-plan policy, planning orchestration,
ambient policy, scheduling rules and media normalization—without importing
database/HTTP clients into the evaluation domain or changing production
behavior for fixture convenience.

## Package and dependency shape

```text
app.application/context, planning_service, response_plan, ambient, scheduling
app.domain/personality, safety, planning, media, tenancy
app.infrastructure/telegram/media (pure normalizer)
                         ▲
                         │ closed synthetic adapters
app.evaluation.models <- fixtures <- evaluators <- runner <- reporting
                                                        ▲
                                             runtime.ai_evaluations CLI
```

`app.evaluation` is offline tooling, not a production runtime or public API.
It must not import SQLAlchemy repositories, production Settings, real provider
factories, Telegram adapters, Redis or Qdrant. The CLI may read checked-in JSON
and write an explicitly requested local JSON report only.

## Eval domain model

- `EvalSuite`: suite schema/version/default threshold and ordered scenarios.
- `EvalScenario`: stable identity, category/capability/tags, synthetic scope,
  provenance, evaluator kind/input, bounded turns, hard expectations and rubric.
- `EvalExecutionCase`: expectation-free ID/scope/mode/turn/input projection handed
  to drivers so an evaluator cannot echo fixture expectations.
- `EvalObservation`: objective facts produced by one closed evaluator.
- `EvalHardGateResult`: gate, expected summary, bounded observed summary,
  PASS/FAIL.
- `EvalDimensionResult`: dimension, status, optional 0–4 score and reason.
- `EvalResult`: scenario status, hard and soft channels, normalized score.
- `EvalRun`: suite identity, deterministic ordered results and suite gate status.

All persistent fixture models use Pydantic strict/extra-forbid validation. The
result models are immutable dataclasses/enums and serialize through one stable
formatter. Status vocabulary is exactly PASS/FAIL/NOT_EVALUATED/ERROR.

## Scenario schema

Top-level JSON:

```json
{
  "schema_version": "ai-eval-suite-v1",
  "suite_id": "telegram-core-v1",
  "suite_version": 1,
  "default_soft_threshold": 3.0,
  "scenarios": []
}
```

Each scenario has schema version, dotted ID, category, capability, tags,
`scope`, `provenance`, one closed `evaluator`, `provider_mode` (`disabled` or
`mock`), one-to-six `turns`, evaluator-specific `input`, nonempty
`hard_expectations`, and optional `rubric`.

The input remains JSON data but is immediately validated by an evaluator-
specific Pydantic model before use. No module/function path, expression,
template execution, environment expansion, filesystem reference or arbitrary
code is supported. Duplicate suite IDs, malformed/unknown versions,
unknown evaluator/gate/dimension, secret-shaped strings, `live` modes,
conflicting expectations and unsafe provenance fail loading.

## Evaluator interface

```python
class ScenarioEvaluator(Protocol):
    kind: EvaluatorKind
    def evaluate(self, scenario: EvalExecutionCase) -> EvalObservation: ...
```

The registry is an explicit mapping. Missing registry entries produce ERROR;
they are not ignored. Each implementation validates its input, calls existing
pure product code where applicable, and emits facts independent of expected
values. The runner creates the expectation-free projection; a driver never
receives the expectations or rubric object.

Drivers:

- Planning: controlled provider double → existing
  `generate_validated_plan`/`ResponsePlanPolicy`; supports success, denied,
  malformed, timeout and fallback traces.
- Context: validates synthetic scoped candidates, filters against exact target
  authority, then calls `build_context`.
- Ambient: validates a candidate and calls `apply_ambient_post_policy`.
- Scheduling: applies exact consent/activity/staleness/authority conditions and
  existing `in_quiet_hours`; always zero provider/mutation facts.
- Media: translates synthetic metadata through `normalize_media`; reports
  content provenance/fallback and zero raw persistence/memory writes.

## Hard-gate model

Hard gates are a closed enum and compare only objective observation fields.
Expected values are typed by gate. Gate evaluation is a separate function from
scenario execution and has no driver access. Conflicting gates—for example
must-respond and must-not-respond—are rejected at load.

Every scenario runs all gates in stable declared order. Any FAIL makes the
scenario FAIL. Any evaluator exception becomes ERROR with a bounded closed
reason and fails the suite. Aggregate/soft score is never consulted after a
hard failure to determine pass/fail.

## Scoring model

Rubric dimensions are the eight approved closed values, including explicit
instruction following. Definitions are
nonempty, weights are integers 1–4, score range is 0–4 and threshold range is
0–4. Weighted mean is rounded deterministically to four decimal places. Missing
required dimension, judge-version mismatch or absent judge yields
NOT_EVALUATED and no aggregate. Unknown is never zero.

Canonical v1 supplies no judge, so rubric-bearing scenarios report soft
NOT_EVALUATED while their hard gates still protect CI. The suite canonical gate
passes only when every hard gate passes and no evaluator errors occur; soft pass
counts remain zero when no judge ran.

## Result schema and artifacts

Machine output schema is `ai-eval-run-v1`, emitted as UTF-8 sorted/indented JSON
with a trailing newline. It contains no current clock, elapsed wall-time,
random run ID or raw runtime dump. Results retain stable scenario IDs, closed
categories/evaluators/statuses, gate names/results/reasons, soft dimension
statuses/scores and optional explicit future judge metadata.

Terminal output prints suite totals then failing/error/not-evaluated scenario
summaries. Failure reasons are allowlisted/bounded and never print the full
scenario input, prompt, response, credential-shaped value or private data.

## Runner

`run_suite(suite, registry, selection, judge=None)`:

1. fixture is already fully validated;
2. filter category/scenario while preserving fixture order;
3. error if a requested filter selects nothing;
4. resolve evaluator or emit ERROR;
5. execute without expectations;
6. evaluate hard gates;
7. mark rubric dimensions NOT_EVALUATED when judge is absent;
8. compute optional score only from a complete compatible result;
9. return stable ordered run and exit classification.

No parallelism is required; 25–50 fast local cases run sequentially for
deterministic, reviewable failure ordering.

## Optional provider/judge integration

V1 has only the `Judge` protocol/result contract and a disabled sentinel. The
CLI accepts `--judge disabled` and rejects every other value before execution.
There is no real provider construction and no network-capable adapter. A future
implementation must wrap an `AttemptGovernedModelProvider`, record explicit
provider/model/judge version and usage, cap concurrency/repetition/scenarios and
cannot mutate routing policy.

## Fixture loading and initial suite

Default fixture path: `evals/fixtures/telegram-core-v1.json`, resolved from the
repository root supplied by the CLI module rather than user home or `.env`.
Initial target: 39 repository-synthetic scenarios, spread across personality,
context, memory, safety, ambient, scheduling, media, multi-tenant and planning.
Stable synthetic UUIDs and literal data are reviewed source, not random output.

No fixture includes real Telegram tokens/IDs, production tenant/Assistant IDs,
provider keys, raw media, production messages or hidden files. Sanitized manual
provenance is schema-capable but prohibited in the canonical file.

## CLI

```text
python -m app.runtime.ai_evaluations
  [--fixture PATH]
  [--category CATEGORY]
  [--scenario ID]
  [--json PATH|-]
  [--judge disabled]
```

Exit 0: canonical hard gate passes, even when optional soft rubrics are clearly
NOT_EVALUATED. Exit 1: hard fail, evaluator error or evaluated threshold fail.
Exit 2: fixture/argument/filter/configuration error. JSON `-` emits only JSON;
otherwise terminal summary goes to stdout and parse errors to stderr.

## CI integration

`scripts/validate-ai-evals.sh`:

1. strict Bash, repository-root resolution and `resolve-uv.sh`;
2. run evaluation unit/integration/meta tests;
3. run default suite plus category and scenario selection smoke tests;
4. produce two temporary JSON outputs and compare them byte-for-byte;
5. run Ruff/format/mypy on evaluation/CLI tests and package;
6. assert no migration 0022 and one existing Alembic head through source
   filename/history checks that need no database;
7. strict trap cleanup, no `|| true`, credentials, network or Docker.

CI runs it immediately after `scripts/validate.sh`. The tracked file must be
100755 and work with PATH `uv` or repository-local fallback. Clean-runner proof
uses a temporary `git archive` extraction plus a PATH-provided uv shim, without
depending on history, `.env`, `.tools/uv`, Docker or ignored fixtures.

## Privacy boundaries

- Canonical provenance is repository-synthetic only.
- No production store or external endpoint is read.
- Evaluators expose only bounded facts, not prompts/responses.
- Reports are local/transient and contain no secret-bearing values.
- Scenario ID is permitted in offline reports, never a production metric label.
- No eval telemetry is added to the production metric registry in v1.

## Test strategy

Unit proof covers schema/version/duplicates/malformed input, closed catalogs,
secret/provenance/live-mode rejection, conflict detection, gate precedence,
missing evaluator/judge, score aggregation, ordering, report bytes and CLI exit
codes.

Integration proof exercises each driver over the real pure production seams and
asserts no production mutation/provider/Telegram call. Meta-evaluation provides
deliberately accepted, irrelevant/invalid, personality-mismatched and forbidden
scope cases and proves only the declared objective distinctions.

The complete mandatory validator matrix remains required before final handoff.

## Migration

None. No PostgreSQL persistence is justified. Alembic head remains
`0021_multi_assistant_tenancy`.
