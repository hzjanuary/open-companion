# SPEC-032 — AI Evaluation and Conversation Quality Framework

Date: 2026-09-13

Status: **APPROVED PRODUCT SPEC**. This specification authorizes the bounded
repository implementation and validation described below. It is not production
rollout, provider-spend, legal/compliance, model-training, or user-data
processing approval.

SPEC-030 is the completed predecessor. SPEC-014 remains
`BLOCKED_ON_EXTERNAL_PREREQUISITE`; SPEC-031 remains
`FROZEN / BLOCKED — ZALO OA/App prerequisite unavailable`. Zalo is frozen.
SPEC-032 begins the Telegram-first roadmap and does not begin SPEC-033.

## Purpose

Create a durable, repeatable repository quality framework that detects
conversation-behavior regressions, compares candidate behavior with approved
product expectations, represents useful quality dimensions, preserves hard
correctness/safety/privacy contracts, and produces reviewable failure evidence.

An evaluation result is evidence about a bounded fixture and evaluator
contract. It is not production quality measurement, model training, user
profiling, prompt optimization, routing authority, billing truth, or a claim
that semantic safety is comprehensive.

## Existing-system audit

The repository has no conversation-quality evaluation abstraction. Existing
`evaluation` terminology belongs to deterministic SLI/alert computation
(SPEC-023), provider usage quality, ambient sampling, and ordinary tests.

Reusable product seams already exist:

- immutable typed personality values and deterministic effective snapshots;
- pure bounded context construction with current-turn, personal-context,
  explicit-memory, recent-history and summary precedence;
- typed provider requests/results/errors, controlled fakes in tests, bounded
  retry/correction/fallback, and strict response-plan policy;
- deterministic structural safety and protection vocabulary;
- deterministic ambient post-policy and sampling;
- pure schedule/DST/quiet-hours rules and code-owned proactive templates;
- pure Telegram/media normalization and provenance metadata;
- canonical tenant/Assistant/connection authority and exact memory scope;
- content-safe telemetry and governed provider admission/accounting; and
- repository-standard validators using `scripts/lib/resolve-uv.sh`.

SPEC-032 composes these seams as offline tooling. It does not change production
runtime behavior merely to make evaluation convenient.

## Evaluation purpose and taxonomy

V1 supports two executable types and one descriptive type:

1. **Deterministic contract evaluation** — objective properties such as
   response-plan shape, silence/response, provenance, zero external calls,
   exact scope and forbidden mutations.
2. **Bounded scenario/state-transition evaluation** — a maximum six-turn
   synthetic scenario executed through one closed driver such as planning,
   context, ambient, scheduling or media.
3. **Response-quality rubric representation** — reviewable 0–4 dimension
   definitions and thresholds. V1 does not pretend that keyword/regex rules
   measure semantic quality.

Pairwise model comparison, live LLM-as-judge execution and provider/model
benchmarking are deferred. Exact deterministic text may be asserted only for
command/fallback/template contracts; flexible conversation prose is never a
golden snapshot.

## Hard gates and soft quality

Hard contract failures and quality signals are separate result channels.

Hard-gate examples include cross-tenant/Assistant scope, unauthorized memory,
provider, schedule, semantic-index or routing mutation, unsafe targeting,
unconsented proactive behavior, raw media persistence, invalid provenance,
unsupported actions, and implicit live provider/Telegram use. One failed hard
gate fails the scenario and suite regardless of any soft score.

Soft dimensions are `relevance`, `instruction_following`,
`personality_adherence`, `context_use`, `clarity`, `concision`,
`non_repetition`, and `social_appropriateness`. Each is scored 0–4 only by an
explicitly supplied compatible judge. Instruction following means satisfying
the user's explicit response constraints without overriding a hard policy:

- 0: contradicts the dimension or causes material quality failure;
- 1: poor;
- 2: mixed/minimum;
- 3: good;
- 4: strong.

Rubric weights are positive integers 1–4 and normalized when aggregated.
Scenario thresholds are 0–4; the conservative default is 3.0. A scored
scenario passes soft quality only when every required dimension exists and the
weighted score meets its threshold. Missing/incompatible judge output is
`NOT_EVALUATED`, not PASS and not zero. Canonical CI gates hard results and
evaluator errors; it reports optional soft dimensions separately.

## Scenario and fixture model

The canonical fixture format is UTF-8 JSON, schema
`ai-eval-suite-v1` containing scenarios of schema `ai-eval-scenario-v1`.
JSON is chosen for strict standard parsing, reviewable diffs, no new dependency,
and no executable fixture logic.

Every suite declares stable ID, positive version, default soft threshold and a
bounded ordered scenario list. Every scenario declares:

- stable lowercase dotted ID, category, capability and bounded tags;
- synthetic tenant/Assistant/connection/conversation/participant scope;
- one closed evaluator kind and structured evaluator input;
- one to six synthetic user/context turns;
- explicit hard expectations;
- optional 0–4 rubric dimensions, definitions, weights and threshold; and
- provenance (`repository_synthetic` or explicitly approved
  `manually_sanitized`) with a nonempty source/review note.

V1 checked-in fixtures must use `repository_synthetic`. Sanitized manual
fixtures are schema-representable for future explicit operator action but are
not accepted into the canonical suite by default. Production-harvested
provenance is invalid.

The loader rejects unknown versions/evaluators/gates/dimensions, duplicate IDs,
empty scenarios, more than six turns, invalid thresholds/weights, conflicting
expectations, unsafe provenance, implicit live-provider mode, secret-shaped
values, and malformed or foreign target scope. Failure is closed before any
scenario executes.

## Deterministic evaluators

The closed v1 driver catalog is:

- `planning_contract`: uses a controlled provider double and the existing
  planning service/response-plan policy for success, denial, malformed output,
  bounded correction/fallback and structured safety behavior.
- `context_contract`: exact-scope filters synthetic context/memory candidates,
  then uses the existing bounded context constructor.
- `ambient_contract`: uses the existing deterministic ambient post-policy to
  separate participation decision quality from response content.
- `scheduling_contract`: evaluates consent, inactive authority, quiet hours,
  inactivity and staleness using existing scheduling values/pure quiet-hours
  logic; provider calls are structurally zero.
- `media_contract`: uses Telegram media normalization for photo, voice/audio and
  unsupported metadata, with explicit caption/transcript provenance and zero
  automatic memory writes.

Objective hard expectations may assert must/must-not respond; exact decision,
origin, safety outcome or provenance; response-plan validity; maximum response
length; forbidden deterministic property; zero external provider, Telegram,
memory, semantic-index, schedule and routing-policy writes; included/excluded
context keys; and exact tenant/Assistant authority.

Subjective relevance, instruction following, warmth or personality fit are
never inferred from a substring. Rubric definitions remain available for human
or future governed judge review.

## Capability coverage

### Personality

Scenarios carry an explicit synthetic Assistant and approved typed personality
configuration. Deterministic gates verify the selected personality belongs to
that Assistant and hard boundaries do not drift. Tone, verbosity and multi-turn
consistency are rubric dimensions, not exact prose snapshots. A foreign
Assistant personality is a hard failure.

### Instruction following

Scenarios represent explicit user response constraints separately from
correctness and safety. A compatible judge may score whether a flexible
response followed the instruction, but an instruction can never authorize a
privacy, safety, tenancy, provider, scheduling or mutation hard-gate bypass.

### Context and memory

Scenarios cover relevant recent context, irrelevant/foreign context exclusion,
summary non-overlap, explicit recall enabled/disabled, current-turn precedence,
creator-private personal context, no automatic inference/write and no
cross-Assistant memory. Scope failure is a hard failure.

### Safety

SPEC-012/024 remains the sole policy. Scenarios exercise safe behavior,
protected/opted-out targeting, refusal/neutral transformation and no bypass via
media or schedules. Evaluation introduces no classifier or alternate safety
policy.

### Ambient participation

Scenarios separately assert respond/silence decisions, minimum confidence,
mention/teasing suppression and anti-spam boundedness. Semantic response quality
is an optional rubric.

### Proactive scheduling

Scenarios assert consent, quiet hours, inactivity, staleness, current authority,
scheduled origin and zero provider calls. SPEC-029 code-owned templates remain
deterministic; eval execution creates no production schedule.

### Telegram media

Fixtures exercise current-turn photo metadata/caption, voice/audio transcript
provenance, unsupported fallback, provider-capability denial and zero
media-to-memory automatic write. They contain no file download, bytes, token,
real file ID or live Telegram dependency.

### Multi-tenant and multi-Assistant

Every fixture has explicit synthetic scope. The loader validates the target
scope and drivers admit context/personality/memory/preferences only from the
same canonical tenant/Assistant chain. A1/A2 and tenant A/B substitution is a
hard failure. Evaluation does not query production databases.

## Optional judge decision

V1 defines the rubric/result contract but deliberately provides **no live
LLM-as-judge adapter or CLI network mode**. `--judge disabled` is the only
canonical setting. Rubric-bearing scenarios return `NOT_EVALUATED` for soft
quality while hard gates still execute.

A future judge requires a separate Product Owner decision and must use the
existing SPEC-026 governed provider boundary, explicit provider/model and judge
version, bounded scenario count/concurrency/repetitions, usage accounting and
budget admission. It may not directly instantiate provider SDKs, mutate routing,
silently use network, or become the sole truth for any hard contract.

## Baselines, regression and determinism

Checked-in fixture expectations and thresholds are the v1 baseline. There is no
remote service or opaque snapshot blob. Canonical results depend only on the
repository state and fixture bytes, use stable input order and stable JSON key
order, and contain no current timestamp or random identifier. Same input and
repository state produce byte-identical machine output.

All hard gates must pass. Scored thresholds are enforced only when a compatible
explicit judge result exists; missing results remain visible and do not fail the
offline hard gate. A changed scenario/schema/version is a normal reviewable
source diff, never an automatic baseline rewrite.

## Provider comparison and cost

V1 does not compare live providers/models. Controlled doubles test provider
integration contracts including success, governance denial, malformed output,
timeout/error and authorized fallback. Canonical CI performs zero external
provider calls and incurs zero provider cost.

Future live comparison must be an explicit noncanonical mode with a maximum 50
scenarios, one repetition by default (hard maximum three), bounded concurrency,
SPEC-026 admission/accounting and no routing mutation. Results are operational
estimates, never pricing/billing truth.

## Result and report contract

Statuses are `PASS`, `FAIL`, `NOT_EVALUATED`, and `ERROR`.

Each scenario result records suite/version, scenario ID/category, evaluator,
hard-gate results, dimension results, optional normalized score, failure codes,
and deterministic duration class (`not_measured` in canonical mode). Optional
provider/model/judge metadata exists only when an authorized future judge runs.

Terminal output is concise and identifies scenario, contract/dimension,
expected and a bounded observed reason. Machine JSON is stable, sorted and
schema-versioned. Reports do not dump full runtime context, prompts, provider
bodies or secrets. Synthetic fixture text may appear only in the checked-in
fixture, not in default failure reasons.

Suite status is FAIL on any hard failure or evaluator ERROR. A scenario with
passing hard gates and unevaluated rubrics has scenario status
`NOT_EVALUATED`; it is not counted as a soft pass. Canonical CLI exit is nonzero
for suite FAIL/ERROR or an explicitly supplied evaluated score below threshold.

## Privacy and governance

- Canonical fixtures are repository-authored synthetic data.
- Real production conversations are never automatically or implicitly
  harvested, queried, copied or persisted.
- Future manually sanitized fixtures require explicit repository/operator
  action, provenance and review outside canonical default acceptance.
- Eval tooling has no production database, Redis, Qdrant, Telegram or provider
  credential dependency and creates no production memory, schedule, route or
  usage state.
- Artifacts are transient unless an operator explicitly writes a selected JSON
  path. They are not added to subject/group/deployment export because v1 has no
  subject data.
- No prompt, response, memory, tenant/Assistant/conversation/participant or
  Telegram identifier becomes a production telemetry label. Offline scenario
  IDs may appear in local reports only.

Synthetic fixtures are repository data. Production conversation ingestion is
out of scope. Evaluation results are bounded review artifacts, not a content
archive.

## CLI and CI policy

The repository CLI is:

```bash
uv run python -m app.runtime.ai_evaluations
```

It runs the default suite, filters by `--category` or `--scenario`, accepts an
optional `--json PATH`, and supports only `--judge disabled`. It emits stable
ordered terminal/JSON output and exits nonzero on hard failure, evaluator error,
invalid fixture or enforced evaluated threshold failure.

`scripts/validate-ai-evals.sh` runs on every Quality push/PR after
`scripts/validate.sh`. It uses canonical `resolve-uv.sh`, the offline suite,
unit/integration/meta tests, lint/type checks and deterministic repeated-output
comparison. It requires no Docker, `.env`, history, hidden binary, external
credential or network call. The script is tracked executable mode 100755.

## Acceptance criteria

1. Strict fixture parsing rejects duplicate IDs, malformed/unknown versions,
   unknown evaluator/gate/dimension, invalid threshold/weight, empty/conflicting
   scenarios, unsafe provenance, secrets and implicit live-provider requests.
2. Hard privacy/safety/isolation failure fails the suite regardless of a high
   soft score.
3. Missing evaluator is ERROR; missing optional judge/dimension is
   NOT_EVALUATED, never PASS or zero.
4. Deterministic ordering and byte-identical canonical JSON are proven without
   timestamps/randomness.
5. Existing planning/context/response-plan/ambient/scheduling/media logic is
   exercised through controlled synthetic drivers, not expectations echoed by
   the evaluator.
6. Meta-evaluation distinguishes an accepted response, irrelevant/invalid
   response, personality-scope mismatch and forbidden hard violation within
   the evaluator's declared objective scope.
7. The initial suite contains 25–50 reviewed synthetic scenarios covering every
   named capability and all mandatory negative cases.
8. Evaluation cannot select foreign Assistant data, create production memory or
   schedules, mutate provider routing, call live providers implicitly, require a
   Telegram credential or persist raw media.
9. CLI default/category/scenario/JSON behavior and exact exit statuses are
   tested; reports identify bounded expected/observed reasons.
10. Canonical mode is offline, deterministic and zero-cost. No judge credential
    or external provider SDK path is required.
11. No migration is added; Alembic remains one head at
    `0021_multi_assistant_tenancy`.
12. The dedicated validator, general validator and all affected safety, memory,
    provider, scheduling, multi-tenancy, media, observability and deployment
    validators pass, with isolated Docker resources where those older
    validators require them.

## Explicit out of scope

Fine-tuning, RLHF, reward-model training, online learning, production
experimentation/A-B testing, automatic prompt mutation, autonomous model
selection/routing, user/reputation scoring, production conversation harvesting,
SaaS dashboards, data warehouses, persisted eval database, billing, SPEC-033
RAG, Zalo, real Telegram acceptance and live LLM judging.

## Migration

**NONE.** Eval configuration is checked-in repository data and results are
transient. Alembic head remains `0021_multi_assistant_tenancy`.

## External prerequisites

None for canonical repository implementation or CI. A future live judge or
provider comparison requires separate product authority, explicit provider/data
eligibility, credentials, SPEC-026 route/budget/accounting configuration,
retention review and operator approval. Production rollout and any assertion of
real-user quality require independent evidence and are not implied here.
