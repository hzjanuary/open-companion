# SPEC-026 Implementation Design Handoff

## 1. Executive summary

This is the implementation-ready architecture for the Product Owner-approved
[SPEC-026 Provider Routing, Cost Budgets, and Usage Governance](../../product/specs/SPEC-026-provider-routing-cost-budgets-and-usage-governance.md).
It is a design deliverable only and authorizes no runtime, migration, test,
validator, deployment, ADR, runbook, commit, or push change.

The design introduces one governed provider-attempt pipeline shared by response
planning, conversation summaries, semantic query embedding, semantic index
embedding, and rebuild embedding. PostgreSQL is authoritative for provider
capabilities, immutable routing and pricing revisions, durable work-policy
snapshots, usage attempts, budget windows, reservations, and recovery state.
Redis remains coordination only for existing throughput rate limits and
deployment/provider concurrency.

For every possible external provider call, the pipeline:

1. resolves or loads an immutable routing snapshot;
2. validates current capability, data-recipient, resource, and health denials;
3. creates an idempotent attempt and atomically reserves every applicable
   deployment, Assistant, and PlatformConnection budget;
4. commits before Redis coordination or provider I/O;
5. applies the existing workload and provider rate limits;
6. acquires the existing provider concurrency lease;
7. durably marks that external I/O may begin;
8. performs exactly one provider call without a database session or row lock;
9. releases concurrency without allowing release failure to mask the result;
10. records provider usage quality and reconciles reservations; and
11. records workload validation, health evidence, and bounded telemetry.

This pipeline does not claim exactly-once provider charging. A crash after the
durable `io_started` transition is recorded as `io_possible`; usage remains
unknown and the conservative reservation remains consumed. Replay uses a new
attempt identity and cannot silently erase the earlier possible cost.

## 2. Baseline

- Repository: `hzjanuary/open-companion`.
- Current `HEAD`: `private-source-checkpoint-omitted`.
- Current `origin/main`: `private-source-checkpoint-omitted`.
- Current migration head: committed `0016_data_governance`.
- SPEC-025 is committed at the baseline. Its handoff retains historical
  pre-commit recovery evidence and must not be interpreted as current git
  state.
- The approved SPEC-026 Product Spec and its two product-index entries are
  uncommitted predecessor changes to this design handoff.
- No SPEC-026 runtime, schema, test, validator, deployment, ADR, or runbook work
  exists at this baseline.

## 3. Scope

The later implementation is limited to:

- a durable non-secret registry for already-supported generation capabilities
  and the existing Ollama embedding capability;
- immutable routing, health-policy, pricing, and budget revisions;
- deterministic routing snapshots at deployment, Assistant, and
  PlatformConnection scope;
- capability/data-recipient/health eligibility and ordered fallback;
- unified attempt, usage-quality, estimate, and ambiguity accounting;
- hard and soft deployment/Assistant/PlatformConnection budgets, separately
  for `chat_generation` and `embedding`;
- pre-I/O atomic reservations and post-I/O reconciliation;
- bounded recovery of abandoned reservations and `io_possible` attempts;
- existing control-plane authorization, revision, idempotency, and audit
  conventions;
- content-safe telemetry and aggregate control-plane views; and
- deployment and validation changes required to operate those behaviors.

## 4. Out of scope

- Billing, invoices, payments, credits, chargebacks, plans, taxation, or any
  claim that estimates are provider billing truth.
- Conversation, group, participant, subject, user, or tenant budgets.
- New provider adapters or hosted embedding recipients.
- Semantic, quality, auction, least-cost, or machine-learned routing.
- New authentication, secret-management, tenant, or SaaS-onboarding models.
- Persisting or exposing prompts, responses, memories, summaries, vectors,
  credentials, provider bodies, or raw platform identities.
- Weakening existing safety, privacy, rate-limit, concurrency, lease, recovery,
  or ambiguity semantics.
- Production budget values, prices, health thresholds, rollout approval, legal
  conclusions, or SPEC-027.

## 5. Existing provider architecture

### 5.1 Generation

- `backend/app/domain/planning.py` owns the closed `ProviderId`, provider-error,
  planning-status, and generation-attempt enums.
- `backend/app/application/model_provider.py` defines `ModelProvider`,
  `ProviderCapabilities`, `GenerationRequest`, `ProviderResult`, and nullable
  token usage.
- `backend/app/infrastructure/model_providers.py` creates direct HTTP adapters
  for OpenAI, Gemini, Groq, OpenRouter, and Ollama from environment settings.
- `backend/app/application/planning_service.py` performs bounded transport
  retry, one optional correction, one optional fallback, strict local response-
  plan validation, and process-local usage metrics.
- `backend/app/runtime/response_planning_worker.py` rebuilds current context and
  safety state, applies generation and provider rate limits, decorates providers
  with concurrency, and stores attempts/final plans.
- `model_generation_attempts` has provider request, token, latency, and error
  columns, but the repository currently populates only provider/model/kind/
  status/error. Failed transport retries are not reliably distinguished from
  primary attempts, and this table cannot represent summaries or embeddings.

### 5.2 Summaries

`backend/app/runtime/conversation_summary_worker.py` claims PostgreSQL summary
jobs and invokes only the configured primary generation provider. It uses the
provider rate limit and optional concurrency wrapper but does not share response-
planning retry/fallback/accounting orchestration. Provider and malformed-output
failures are released for retry without a dedicated bounded summary retry
budget.

### 5.3 Embeddings

`backend/app/application/semantic_memory.py` defines the provider-neutral
embedding and derived-index ports. `backend/app/infrastructure/semantic_memory.py`
implements the existing Ollama embedding adapter and Qdrant derived index. The
`embed_with_controls` helper applies the existing embedding provider rate limit
and provider concurrency. The adapter returns only a vector, so provider usage
is absent. Query embedding occurs while building planning context; index and
rebuild embedding occur under existing semantic-job leases.

### 5.4 Coordination and telemetry

- SPEC-012 Redis rate limiting has distinct `generation`, `embedding`, and
  `delivery` operations. Response planning uses deployment, connection,
  conversation, participant, and provider scopes. Embedding uses its separate
  provider rule.
- SPEC-016 provider concurrency is a Redis TTL semaphore keyed by deployment and
  provider, independent of rate limits. Its current decorator can allow a Redis
  release exception to mask a successful provider result; SPEC-026 must correct
  that integration without weakening capacity enforcement.
- SPEC-015/023 telemetry uses an application `MetricsRecorder`, a process-local
  registry, and a loopback exporter. Provider pricing is currently environment
  JSON keyed by `provider:model`; it emits estimates only when usage is present.
  Worker processes create recorders but do not currently start exporters.
- SPEC-021 supplies external JWT identities, tenant roles, Assistant and
  PlatformConnection bindings, optimistic revisions, idempotency records, and
  content-free control audits. SPEC-025 adds tenant-independent current
  `deployment_operator` authority.

## 6. Provider registry design

### 6.1 Domain values

Add `backend/app/domain/provider_governance.py` with closed enums and validated
immutable values:

- `WorkloadClass`: `chat_generation`, `embedding`;
- `GenerationOperation`: `response_planning`, `summary_generation`;
- `EmbeddingOperation`: `semantic_query`, `semantic_index`, `semantic_rebuild`;
- `ProviderLifecycle`: `enabled`, `draining`, `disabled`;
- `ProviderHealth`: `ready`, `degraded`, `unavailable` (nullable means unknown);
- `RouteRole`: `primary`, `retry`, `correction`, `fallback`;
- `UsageQuality`: `reported`, `partial`, `unknown`, `invalid`;
- `AttemptState`: `reserved`, `io_started`, `io_complete`, `no_io`,
  `io_possible`;
- `AttemptOutcome`: a closed union of success, refusal, provider error,
  invalid-output, budget/rate/concurrency denial, governance unavailable, and
  recovery outcomes;
- `BudgetScope`: `deployment`, `assistant`, `platform_connection`;
- `BudgetMeasurement`: `estimated_cost_microusd`, `input_tokens`,
  `output_tokens`, `total_tokens`, `requests`;
- `BudgetMode`: `hard`, `soft`;
- `BudgetWindow`: `daily_utc`, `monthly_utc`; and
- `ReservationState`: `reserved`, `released`, `consumed`, `ambiguous`.

Do not extend `ProviderId`; the approved provider set remains unchanged.

### 6.2 Capability record

A provider capability is an immutable, non-secret registration containing:

- provider ID and a closed adapter key;
- workload class and bounded model identifier;
- capability schema version (`provider-capability-v1` initially);
- generation facts (`json_schema`, `json_object`, output-token parameter,
  usage-report support, provider-request-ID support) or embedding facts
  (dimension and embedding-version input);
- a closed data-handling class (`local` or an operator-approved existing
  external recipient class);
- a closed credential slot/reference name and configured/not-configured status,
  never a secret value;
- a reservation-bound strategy; and
- creator/time metadata.

Capability metadata is immutable. Lifecycle and observed health are held in a
separate current-state projection so operational state changes do not mutate
the registered contract. Unknown capability schema versions are ineligible.

### 6.3 Activation and compatibility rollout

Add `provider_governance_mode = legacy | observe | enforce`, default `legacy`.

- `legacy` preserves the current environment primary/fallback behavior and
  makes no claim that budgets are enforced.
- `observe` requires published registry/routing/pricing metadata and writes
  attempts/reservations/estimates, but hard budget decisions are measured and
  not allowed to deny. It is a bounded rollout state, not production budget
  enforcement.
- `enforce` requires one active deployment route and at least one explicitly
  configured deployment budget for each enabled workload. Missing authority,
  policy, capability, required price/bound, or accounting persistence fails
  closed before I/O.

No migration seeds provider/model rows because migrations cannot safely derive
environment or secret configuration. Deployment operators publish registry
entries and revisions through the authenticated control plane. Enabling
`observe` or `enforce` is an explicit operating-owner action after validation.

## 7. Versioned routing policy

### 7.1 Resolution

`ProviderRoutingService.resolve(work_source, workload)` loads exact Assistant
and PlatformConnection ownership, then resolves in this order:

1. active PlatformConnection head;
2. active Assistant head;
3. active deployment head.

The first head supplies route order. A single query/repository transaction must
prove ownership and must return no cross-tenant policy. Absence of a resource
override is represented as `not_configured`, not as an unlimited or empty
policy. In `enforce`, absence of the deployment policy fails closed.

### 7.2 Immutable revisions and work snapshots

Published `provider_routing_policy_revisions` and their route/reason children
are append-only. Publishing atomically compare-and-swaps one
`provider_routing_policy_heads` row using `lock_version`; stale `If-Match`
requests receive `409` and do not publish.

Before a durable work item performs any provider I/O, create exactly one
`provider_work_policy_snapshots` row per work item and workload. Existing work
first claimed after activation receives a snapshot before its first governed
call. The snapshot references the exact routing revision plus Assistant,
connection, and tenant attribution established at resolution time.

Replay uses the snapshot route order. Before every actual provider attempt,
current state is reread for restrictive changes: capability draining/disabled,
data eligibility revoked, Assistant/connection disabled, deployment authority
configuration invalid, health ineligible, and hard budget denial. A newer
permissive policy never rewrites the snapshot.

## 8. Capability matching

Add an application `CapabilityMatcher` with no I/O. It accepts a strictly parsed
policy requirement document and a registered capability. `provider-routing-v1`
allows only these requirements:

- workload equality;
- response-plan JSON Schema/local validation support;
- summary schema support;
- maximum requested output units within adapter capability;
- usage/reservation-bound availability where a hard budget requires it;
- embedding dimension and embedding-version compatibility; and
- data-handling class allowed by deployment policy.

Unknown keys, unknown requirement versions, mismatched workload, missing model,
or ambiguous capability facts return a closed `unsupported_capability` reason
before budget/rate/concurrency consumption. Provider or model name heuristics
are prohibited.

## 9. Fallback semantics

Move route iteration out of `planning_service.py` into a shared
`GovernedProviderRouter`. Workload-specific validators remain injected
callbacks: response-plan policy, summary schema, or embedding-vector validation.

For every route and every possible I/O:

1. classify role as `primary`, `retry`, `correction`, or `fallback`;
2. run fresh capability/current-deny checks;
3. reserve budgets and create the attempt;
4. run the relevant rate gate and acquire concurrency;
5. execute once and account it; and
6. decide from the published closed fallback-reason set whether another call is
   allowed.

Retry remains inside the current route and uses the configured bounded backoff,
including a validated provider `Retry-After` capped by repository settings.
Correction is a new I/O attempt against the same route. Fallback begins only
after allowed retry/correction exhaustion and receives its own independent
admission. Safety refusal, privacy/authorization denial, invalid request,
authentication/permission error, unsupported capability, malformed policy,
draining/disabled state, and any applicable hard-budget denial never fall back.

Summary generation adopts the same bounded retry/fallback executor with its own
summary validator. Embedding has no new provider fallback in SPEC-026 because
only Ollama is currently registered; the routing representation supports an
ordered list without authorizing a new adapter. Semantic query retains lexical
fallback after governed embedding failure.

## 10. Provider-health semantics

### 10.1 Durable state

Each capability has:

- manual lifecycle (`enabled`, `draining`, `disabled`);
- nullable observed health (`ready`, `degraded`, `unavailable`);
- current health-policy revision;
- consecutive/recent bounded success and eligible-failure counters;
- last evaluated/success/failure timestamps; and
- compare-and-swap version.

Effective route state is manual lifecycle first; otherwise observed health.
Null/stale observed health is ineligible when the policy requires current health.

### 10.2 Evidence and transitions

Only provider-origin availability evidence contributes: successful provider
response, timeout, transport failure, provider unavailable, or malformed
provider result where the health policy declares it relevant. Budget, rate,
concurrency, tenant authorization, safety, privacy, and local policy failures do
not change provider health. Authentication/permission/configuration errors mark
the capability operationally unavailable with a distinct closed reason but are
never counted as broad provider-outage evidence.

Health-policy revisions define bounded observation window, degradation
threshold, unavailable threshold, recovery-success threshold, and staleness
time. Actual values remain operating-owner configuration. State transitions use
row-version compare-and-swap and append a content-free health event. No single
ordinary request changes health unless an explicitly approved threshold is one.

The bounded provider-governance recovery worker also evaluates stale state; it
does not probe providers or create external I/O.

## 11. Usage ledger design

### 11.1 Unified authoritative ledger

Create `provider_usage_attempts` as the only new-write source of truth for
governed attempts. A row is created before I/O with:

- UUID and stable `attempt_key`;
- exactly one source FK: response-planning job, conversation-summary job, or
  semantic-index job;
- workload, operation, attempt ordinal, route role;
- capability/provider/model snapshots;
- routing, health-policy, and optional price revision IDs;
- tenant/Assistant/PlatformConnection attribution where applicable;
- state, provider outcome, application outcome, error/retry classification;
- reservation, I/O-start, response, and final timestamps;
- nullable provider request ID;
- request count (`1` only after `io_started`);
- nullable input/output/total reported units;
- usage quality and estimate quality;
- nullable integer estimated microusd; and
- `io_possible` ambiguity/recovery reason.

No source content enters the row. Semantic query attempts use the enclosing
response-planning job as their durable source with operation
`semantic_query`; this requires passing the planning job identity through the
context-reader/retriever interfaces. Rebuild/index attempts use the existing
semantic job. Summary attempts use the existing summary job.

`attempt_key` is constructed from source kind, source UUID, workload, operation,
route position, role, correction ordinal, and transport ordinal, then stored as
a bounded opaque value. A database unique constraint is authoritative. A
uniqueness race reloads the existing row; it never creates a second call.

### 11.2 State machine

```text
candidate
   |
   +-- denied before reservation ----------> no_io
   |
   +-- atomic reserve ----------------------> reserved
                                                |
                           rate/capacity deny --+--> no_io + release
                                                |
                           durable I/O mark ----+--> io_started
                                                        |
                               provider result ---------+--> io_complete
                                                        |
                               stale/crash recovery ----+--> io_possible
```

Only `reserved -> io_started` authorizes adapter invocation. `io_complete`,
`no_io`, and `io_possible` are terminal. Workload validation may update a
separate nullable application outcome after `io_complete`; it never changes
usage or reservation arithmetic.

### 11.3 Usage quality

Validation is centralized:

- `reported`: every field required by the capability/price basis is valid;
- `partial`: at least one usable reported field exists and at least one required
  field is absent;
- `unknown`: no usable provider-reported units exist, or I/O is ambiguous;
- `invalid`: negative, non-integral, contradictory, or out-of-contract values.

Unknown fields are SQL `NULL`, never `0`. Request count is an internal fact
separate from provider-reported usage: it becomes `1` at `io_started`, including
when token usage remains unknown. Aggregate queries return known sums plus
reported/partial/unknown/invalid counts and a completeness ratio. They never
label a known subtotal as a total.

## 12. Cost calculation model

### 12.1 Price revisions

Prices use integer microusd and one of:

- `generation_tokens`: input and output microusd per million tokens; or
- `embedding_request`: microusd per request for the currently supported Ollama
  embedding operation.

All arithmetic uses checked integers. Generation reconciliation is:

```text
ceil((input_tokens * input_rate + output_tokens * output_rate) / 1_000_000)
```

Reservation is intentionally at least as conservative:

```text
ceil(max_input_tokens * input_rate / 1_000_000)
+ ceil(max_output_tokens * output_rate / 1_000_000)
```

An adapter/capability must provide a tested conservative input bound. Permitted
strategies are an adapter tokenizer, a proven adapter-specific UTF-8 byte upper
bound, or an explicit fixed provider maximum. If no proven bound exists, a hard
token/cost budget denies before I/O. Output bound comes from the validated
request maximum.

For the current embedding adapter, provider-reported token usage remains
unknown; request count is known. A per-request embedding price may therefore
produce an explicit request-based estimate. It must not be described as a
token-based or provider-billed amount.

### 12.2 Estimate quality

- `complete_estimate`: required reported usage and price are present;
- `partial_estimate`: only a valid subset can be estimated;
- `reservation_estimate`: conservative bound retained because actual usage is
  unknown/invalid/ambiguous; and
- `unavailable`: no authorized price or calculable basis.

The API always returns `estimated_cost_microusd`, `estimate_quality`, currency,
price revision, and incompleteness counts together. UI/API terminology must use
“estimated,” never invoice/charge/owed/billing-total language.

## 13. Budget hierarchy

### 13.1 Stable budget identity

A stable budget is uniquely identified by:

```text
(scope_type, scope_resource, workload_class, measurement, window_kind)
```

Deployment has no tenant/resource ID. Assistant and PlatformConnection budgets
carry the existing tenant binding and exact resource FK. Daily and monthly UTC
budgets may coexist and both apply. Multiple measurement kinds may coexist and
all hard limits apply.

Every governed I/O requires the deployment budgets for its workload. Assistant
and connection budgets additionally apply when attributed. Absence of an
optional resource budget means `not_configured`, not “unlimited.” It does not
remove the mandatory deployment constraint.

### 13.2 Revision and window behavior

Budget amount, mode, alert threshold, and effective time are immutable revision
data. Publishing a revision never clears current-window counters. Admission
uses the current revision limit against the stable budget window’s existing
consumed plus reserved amount. Raising a limit adds headroom; lowering it may
make the window immediately exhausted but never rewrites prior usage.

Daily windows are `[00:00 UTC, next 00:00 UTC)`. Monthly windows are
`[first day 00:00 UTC, first day of next month 00:00 UTC)`. Window boundaries
are computed in application code and stored; a unique constraint prevents two
counter rows for the same budget/window start.

## 14. Budget reservation and enforcement model

### 14.1 Atomic admission

`BudgetAdmissionRepository.reserve()` receives one attempt plus all applicable
budget/amount pairs. In one PostgreSQL transaction it:

1. creates/reloads the attempt by unique key;
2. resolves the UTC window rows;
3. locks them in deterministic order: deployment, Assistant,
   PlatformConnection, then budget UUID;
4. snapshots current budget revisions and counters;
5. writes one evaluation row per applicable budget;
6. denies without counter mutation if any hard remainder is insufficient or a
   hard reservation cannot be calculated; or
7. increments reserved counters and creates one reservation per budget.

Soft evaluations never deny, but use the same accounting rows and report
`within` or `exceeded`. A replay of an already admitted attempt returns the
existing result and never increments counters again.

### 14.2 Release and reconciliation

- Before-I/O denial: atomically decrement reserved values and mark all
  reservations `released`; finalize attempt `no_io`.
- Complete reported usage: atomically decrement reserved values, increment
  consumed by the reconciled amount, and mark `consumed`.
- Partial/invalid/unknown usage after known I/O: consume the conservative
  reservation for hard enforcement; expose estimate quality and never silently
  refund the difference.
- `io_possible`: move reserved to consumed-conservative and mark `ambiguous`.
- Reconciliation never makes a window counter negative. Every transition is
  guarded by attempt state and row version.

One provider attempt can reserve several budget measurements and scopes. The
transaction is all-or-none so it cannot reserve deployment but miss a required
connection budget.

## 15. Generation versus embedding accounting

| Concern | Chat generation | Embedding |
| --- | --- | --- |
| Operations | response planning, summary generation | semantic query, index, rebuild |
| Capability | typed generation/structured output | dimension/version-compatible Ollama |
| Reported units | input/output/total tokens when provider supplies them | unknown tokens; request count known |
| Pricing | input/output microusd per million tokens | optional microusd per request |
| Required deployment budget | generation-only | embedding-only |
| Rate limit | existing logical generation scopes plus per-attempt provider scope | existing embedding provider scope per call |
| Failure fallback | ordered eligible provider route | lexical fallback for query; durable retry for index/rebuild |

No counters, headroom, price, or policy are shared across the two workload
classes. Provider concurrency may remain keyed by provider as required by
SPEC-016; ledger attribution remains workload-specific.

## 16. Transaction boundaries

The exact external-I/O boundary is:

```text
TX A: load/lock current policy state -> create attempt -> evaluate/reserve -> commit
Redis: existing workload/provider rate checks
Redis: acquire provider concurrency lease
TX B: compare attempt=reserved -> set io_started/request_count=1 -> commit
External provider I/O (no DB session, transaction, or row lock)
Redis: release concurrency; retain release error separately
TX C: store usage/outcome -> reconcile all reservations -> health evidence -> commit
TX D: workload-specific result/final job state when not safely co-committable with TX C
```

TX C must complete before a successful result is discarded. If workload result
finalization requires a separate transaction, the attempt already preserves
the possible provider cost. Current context/privacy/safety/resource state is
rechecked at the latest safe point before TX B. A restrictive change between TX
B and the external call is the same unavoidable race already acknowledged for
provider I/O; no exactly-once or instantaneous cancellation claim is added.

The concurrency release is attempted in `finally`, but its failure is captured
as a coordination outcome and cannot replace a valid provider result or skip TX
C. Provider clients close only after all in-flight attempt finalization.

## 17. Retry and fallback accounting

Transport ordinal is part of attempt identity. Each real call independently
reserves and reconciles; delays do not keep transactions or concurrency leases
open. Provider `Retry-After` is parsed, capped by configured min/max, and applied
only to retryable categories. Each fallback route starts a new route ordinal and
role.

Malformed response-plan or summary output records provider I/O/usage first,
then `application_outcome=invalid_output`. A correction is a separately
reserved call. A safety refusal records its possible usage and terminal
`refused` outcome but does not trigger fallback. An accepted fallback does not
alter preceding failed attempt rows or estimates.

## 18. Rate-limit interaction

Preserve the current logical generation admission for deployment, connection,
conversation, and participant once per response-planning job. Do not remove or
merge those rules. The governed executor applies the provider-scope generation
rule before every actual generation I/O, including retry, correction, and
fallback. Summary generation retains its provider-scope generation rule per
call. Embedding retains its separate embedding provider rule per call.

Budget reservation occurs before these Redis checks. A rate denial proves no
I/O and triggers atomic reservation release. Redis unavailable remains fail-
closed under SPEC-012. Rate denial is not provider health evidence and does not
consume provider usage, though it has an admission record and existing safety/
rate audit evidence.

## 19. Concurrency interaction

Retain `RedisConcurrencyLimiter` keys and deployment/provider limits. Acquire
only after budget and rate admission and immediately before the durable
`io_started` transition. Retry, correction, fallback, summary, query embedding,
and index/rebuild embedding all acquire independently.

Capacity denial or Redis unavailability releases the no-I/O reservation and
uses existing retry/defer behavior. Lease tokens remain Redis-only and never
enter PostgreSQL, logs, metrics, or API output. Release failure emits a bounded
coordination result, preserves provider usage/result processing, and relies on
TTL expiry for capacity recovery.

## 20. Authorization model

### 20.1 Deployment

Every deployment registry, lifecycle, health-policy, routing, pricing, budget,
and aggregate endpoint calls the existing current
`has_deployment_authority()` check. SPEC-026 uses the already approved
tenant-independent `deployment_operator`; it creates no new role. Authority is
rechecked on every mutation and sensitive read. Tenant membership never implies
this capability, and deployment authority grants no tenant content access.

### 20.2 Tenant resources

- `tenant_owner` and `tenant_admin`: read/publish Assistant and
  PlatformConnection routing and budgets within the exact tenant binding; read
  those resource aggregates.
- `auditor`: read immutable revisions, decisions, and aggregates within the
  exact tenant binding; no mutation.
- `viewer`: no SPEC-026 access.
- `operator`: fail closed for SPEC-026 until a currently implemented explicit
  resource grant can express provider-governance configuration capability. The
  current schema has no such capability-bearing grant table; SPEC-026 does not
  broaden all tenant operators merely because they hold the role.

This interpretation satisfies the Product Spec’s “only when explicitly
granted” condition without inventing a role or expanding multi-tenancy. A
future approved grant system may enable operator access without changing these
resource checks.

All resource queries join `(tenant_id, assistant_id)` or
`(tenant_id, connection_id)` before loading policy, budget, or usage. Generic
`404`/`403` behavior must not reveal cross-tenant existence. Control-plane
mutations use bounded request idempotency and `If-Match`; successful, denied,
and conflict outcomes use existing content-free audit conventions.

## 21. Database and migration design

Create one additive migration after committed `0016_data_governance`, normally:

```text
0017_provider_routing_cost_budgets
```

Do not modify migration 0016. The implementation design requires every schema
change below.

### 21.1 New tables

| Table | Purpose and required constraints |
| --- | --- |
| `provider_capabilities` | Immutable non-secret provider/model/workload/capability contract. Unique `(provider_id, model, workload_class, capability_schema_version)`; provider/workload/schema/data-class checks; no secret column. |
| `provider_capability_states` | One mutable lifecycle/health projection per capability. PK/FK capability; lifecycle/health checks; health policy FK; row version; timestamps/counters nonnegative. |
| `provider_health_policy_revisions` | Immutable thresholds/windows/staleness configuration. Positive bounded values, schema version, creator identity, effective timestamp. |
| `provider_health_events` | Append-only content-free state transitions and closed reason. Capability/time index; nullable from/to for unknown; no diagnostic body. |
| `provider_routing_policy_revisions` | Immutable deployment/Assistant/connection revision. Scope-shape check, tenant/resource FKs, workload/schema/version/effective fields, creator identity, unique scope version. |
| `provider_routing_policy_routes` | Ordered capability routes. Unique `(policy_revision_id, position)` and `(policy_revision_id, capability_id)`; positive bounded position. |
| `provider_routing_fallback_reasons` | Closed allowed reason set per policy revision. Unique policy/reason and reason check. |
| `provider_routing_policy_heads` | One current revision pointer per exact scope/workload with row version. Scope-shape check and unique scope key; referenced revision must match scope/workload in repository validation. |
| `provider_work_policy_snapshots` | Exact policy selected for one durable source/workload before first I/O. Exactly-one-source-FK check; unique source/workload; attribution and routing revision FKs. |
| `provider_price_revisions` | Immutable effective provider capability price. Currency, unit basis, fixed-point nonnegative rates, effective range, shape check, creator identity. Exclusion constraint prevents overlapping ranges for the same capability/currency/unit basis. |
| `provider_budgets` | Stable scope/workload/measurement/window identity. Scope-shape and tenant/resource FKs; unique exact budget identity. |
| `provider_budget_revisions` | Immutable amount/mode/threshold/effective revision for a stable budget. Positive amount, closed mode, threshold basis points, creator identity, unique budget/version. |
| `provider_budget_heads` | Current budget revision pointer with row version; unique budget FK. |
| `provider_budget_windows` | Authoritative reserved/consumed integer counters by stable budget and UTC window. Unique `(budget_id, window_start)`; valid interval; nonnegative checked counters and row version. |
| `provider_usage_attempts` | Unified attempt/admission/usage/estimate state. Unique attempt key and source/ordinal identity; exactly-one-source-FK; closed states/qualities; nullability, nonnegative, and governed-vs-legacy checks. |
| `provider_budget_evaluations` | Snapshot of each applicable budget decision for an attempt. Unique `(attempt_id, budget_id)`; decision and nonnegative counter/limit snapshot checks. |
| `provider_budget_reservations` | Per-attempt/per-budget reserved and reconciled amount. Unique `(attempt_id, budget_id)`; state and amount checks; window FK. |

### 21.2 Existing-table changes

| Existing table | Change | Reason |
| --- | --- | --- |
| `control_assistant_bindings` | Add unique constraint/index on `assistant_id` alone after duplicate preflight. | Prevent one Assistant from being attributed to two tenants. |
| `control_connection_bindings` | Add unique constraint/index on `connection_id` alone after duplicate preflight. | Prevent one PlatformConnection from being attributed to two tenants. |
| `model_generation_attempts` | No destructive change. Backfill into the new ledger and stop new writes after governed activation. | Preserve rollback/history while establishing one new-write ledger for all workloads. |

No conversation, group, participant, user, or Telegram ID column is added to
the budget/usage schema. `provider_usage_attempts` may reference a planning job,
whose existing domain relationship remains protected; it must not denormalize
subject/platform identities.

### 21.3 Backfill

Migration 0017 copies existing `model_generation_attempts` into
`provider_usage_attempts` using the existing UUID as ledger UUID, source kind
`response_planning`, origin `legacy_backfill`, nullable capability/policy/price,
and usage quality derived strictly from nullable/valid token fields. Missing
tokens become `unknown`, never zero. Existing created timestamps and known
provider/model/status/error/latency fields are preserved.

Legacy rows are allowed nullable governance references through an explicit
`record_origin` shape constraint. New `governed` rows require capability and
policy snapshot references. Runtime never dual-writes after `observe`/`enforce`
activation; read APIs use the unified ledger only.

PostgreSQL range exclusion for prices requires `btree_gist`. The implementation
must validate extension availability before migration approval and use
`CREATE EXTENSION IF NOT EXISTS btree_gist`; downgrade must not drop a shared
extension. If the production database owner cannot authorize that extension,
implementation stops for an operating-owner database decision rather than
weakening overlap enforcement.

### 21.4 Indexes and lock order

Add claim/recovery indexes on `(state, reservation_expires_at, created_at, id)`,
usage aggregate indexes on `(workload_class, occurred_at)`, capability/price
lookups, and scope/window indexes. Do not index content because none is stored.

All multi-budget transactions lock in the fixed order deployment -> Assistant
-> PlatformConnection -> budget UUID. Publishing locks the stable head before
creating/activating a revision. Health updates lock one capability state only.

## 22. Worker and runtime changes

### 22.1 Shared governed executor

Add an application `GovernedProviderExecutor` and infrastructure repository.
Raw provider adapters remain behind the existing provider-neutral ports; they
must not know budgets or control-plane roles. The executor owns attempt
admission, per-call rate/concurrency coordination, I/O state transitions, usage
validation, estimate reconciliation, and health evidence.

Refactor:

- response planning to use resolved route lists and emit every transport retry,
  correction, and fallback attempt with correct role/result/usage;
- summary generation to use the same bounded route executor and to add bounded
  terminal/defer behavior;
- semantic retriever to receive the enclosing planning-job source and use the
  embedding route/accounting path;
- semantic index/rebuild worker to use semantic-job source identities and the
  same embedding executor; and
- provider concurrency handling so release failure cannot mask a result.

### 22.2 Provider-governance recovery worker

Add `backend/app/runtime/provider_governance_worker.py` using existing
`RuntimeLifecycle`, bounded batch, poll, graceful stop, and restart conventions.
It performs no external provider, Telegram, or Qdrant I/O. It:

- claims expired `reserved` attempts with `SKIP LOCKED` and releases them as
  `no_io` only when `io_started_at` is null;
- claims expired `io_started` attempts and marks `io_possible`, consuming the
  conservative reservation;
- evaluates stale provider-health projections from already durable evidence;
- uses owner/lease expiry and stale-owner fencing; and
- emits completed/failed duration/result accurately.

Recovery batches are deterministic by expiry, creation time, and UUID. A crash
during recovery is idempotent through guarded terminal transitions.

### 22.3 Workload disposition

- Response planning: hard-budget/no-route/governance denial before I/O produces
  content-safe `NO_RESPONSE` with a new closed local reason; it does not create
  an end-user budget explanation or unbounded retry.
- Summary: defer to the next applicable budget window with a configured bounded
  maximum; after exhaustion, use existing recovery/dead-letter conventions.
- Semantic query: immediately use existing lexical fallback.
- Semantic index/rebuild: use existing bounded job attempts and retryable versus
  terminal classification; canonical PostgreSQL memory remains unaffected.

## 23. API and control-plane changes

All paths remain under the existing authenticated control-plane router. Exact
routes for implementation:

### 23.1 Deployment-operator routes

- `GET/POST /control/v1/deployment/provider-capabilities`
- `GET/PATCH /control/v1/deployment/provider-capabilities/{capability_id}/state`
- `GET/POST /control/v1/deployment/provider-health-policies`
- `GET/POST /control/v1/deployment/provider-routing/{workload}`
- `GET/POST /control/v1/deployment/provider-prices`
- `GET/POST /control/v1/deployment/provider-budgets`
- `GET /control/v1/deployment/provider-usage-summary`

### 23.2 Tenant resource routes

- `GET/POST /control/v1/tenants/{tenant_id}/assistants/{assistant_id}/provider-routing/{workload}`
- `GET/POST /control/v1/tenants/{tenant_id}/assistants/{assistant_id}/provider-budgets`
- `GET /control/v1/tenants/{tenant_id}/assistants/{assistant_id}/provider-usage-summary`
- `GET/POST /control/v1/tenants/{tenant_id}/connections/{connection_id}/provider-routing/{workload}`
- `GET/POST /control/v1/tenants/{tenant_id}/connections/{connection_id}/provider-budgets`
- `GET /control/v1/tenants/{tenant_id}/connections/{connection_id}/provider-usage-summary`

`POST` publishes immutable revisions using `If-Match` against the current head
and the existing bounded request-id idempotency pattern. Responses never return
credentials. Capability list responses expose only authorized non-secret
metadata. Aggregate responses return known values plus quality/incompleteness
counts. Pagination is bounded, stable, and scoped. Raw attempts/provider request
IDs are not returned by aggregate endpoints.

Deployment and tenant audit actions use closed names such as
`provider_capability.create`, `provider_capability.state`,
`provider_routing.publish`, `provider_price.publish`, and
`provider_budget.publish`. Audit detail remains bounded metadata only.

## 24. Configuration and secrets changes

Add bounded settings:

- `provider_governance_mode` (`legacy` default, `observe`, `enforce`);
- `provider_governance_worker_enabled`;
- `provider_governance_owner_name`;
- `provider_governance_batch_size`;
- `provider_governance_poll_interval_seconds`;
- `provider_reservation_lease_seconds`;
- bounded summary budget-deferral/retry settings; and
- per-service metrics port overrides in deployment configuration where exporter
  endpoints would otherwise collide.

Registry, routing, health thresholds, prices, budget amounts, and alert
thresholds are PostgreSQL revisions, not environment JSON. Existing provider
API keys, Ollama/OpenAI-compatible base URLs, database/Redis secrets, and JWT
secrets remain environment-injected `SecretStr` values. Capability rows store
only closed credential slot names/status. Adapter construction maps a closed
provider/credential slot to existing settings; arbitrary database URLs or
secret names are never dereferenced.

`metrics_provider_pricing` remains accepted only in `legacy` mode for backward
compatibility. `observe`/`enforce` reject it as an authoritative price source so
there is no dual pricing truth. Startup validation for `enforce` checks control
plane, database, published deployment routes/budgets, and supported capability
schemas without revealing secret values.

## 25. Telemetry

Add registry definitions with exact, closed labels:

- `january_provider_routing_decisions_total{workload,operation,route_role,outcome,reason}`;
- `january_provider_usage_quality_total{provider,workload,usage_quality}`;
- `january_provider_estimate_outcomes_total{provider,workload,estimate_quality}`;
- `january_provider_estimated_cost_microusd_total{provider,workload}`;
- `january_provider_budget_decisions_total{workload,scope,mode,outcome}`;
- `january_provider_budget_reservations_total{workload,scope,outcome}`;
- `january_provider_health_transitions_total{provider,from_state,to_state,reason}`;
- `january_provider_governance_recovery_total{operation,outcome}`; and
- worker operation/duration entries for the new recovery runtime.

Allowed values for workload, operation, route role, outcome, reason, quality,
scope, mode, and health state are declared alongside the metrics. Provider is
validated against the closed `ProviderId` set. Model, policy/price/budget/
attempt/resource IDs, tenant, Assistant, connection, conversation, group,
participant, user, Telegram IDs, URLs, content, prompts, memories, vectors,
credentials, and provider bodies are prohibited labels.

Metrics report estimates, never billing totals. Incomplete attempts have a
quality counter; the estimated-cost counter includes only known integer
microusd. Dashboards must show the incomplete count beside known subtotals.

Every provider-calling runtime must construct its owned recorder and start the
existing loopback exporter using a service-specific port when export is enabled.
Collectors aggregate replicas. Exporter failure stays telemetry-only and must
not re-run or lose an already durable provider result.

## 26. Failure and recovery semantics

| Failure | Durable outcome and recovery |
| --- | --- |
| Database unavailable before admission | Fail closed; no provider I/O. Source job uses bounded local-dependency disposition. |
| Unknown policy/capability schema | `no_io/invalid_policy`; no fallback. |
| Capability/resource currently revoked | `no_io/current_denial`; no fallback. |
| Hard budget unavailable/exhausted | Atomic `denied`; no reservation or provider I/O; no bypass fallback. |
| Rate/concurrency denied after reserve | `no_io`; release reservations; preserve existing retry/defer semantics. |
| Crash while merely `reserved` | Recovery proves no `io_started`, releases once, source may create next attempt. |
| Crash after `io_started` | Recovery sets `io_possible`, usage unknown, conservative amount consumed, replay uses new attempt. |
| Provider response with missing usage | `io_complete/unknown`; never zero; conservative hard debit. |
| Partial/invalid usage | Preserve valid/null fields and quality; conservative hard debit. |
| Concurrency release failure | Record bounded coordination error; process provider result and rely on TTL. |
| Usage finalization temporarily fails | Source job must not mark provider result complete first; recovery sees `io_started` and protects budget. |
| Workload result finalization fails after usage | Usage remains complete; source replay creates no duplicate for the same attempt key and may create a new call only through a new ordinal. |
| Telemetry failure | Durable behavior remains; never repeat I/O for metrics. |
| Health update race | Compare-and-swap/reload; attempt finalization remains authoritative. |
| Stale health evidence | Route ineligible where policy requires current evidence. |

## 27. Privacy and security

- The database additions contain non-secret policy/accounting metadata only.
- No prompt, response, message, memory, summary, vector, provider body,
  authorization header, credential, or platform payload is added.
- No user, participant, conversation, group, Telegram, or raw platform ID is
  denormalized into the usage/budget tables.
- Assistant/connection internal UUIDs exist only for protected scope attribution
  and never become metric labels or public identifiers.
- Credential values remain `SecretStr` at the process boundary and are never
  returned, audited, logged, or stored in registry rows.
- Model and provider request IDs may exist in protected durable attempt records
  for provenance, but are prohibited from metrics and allowlisted logs.
- API serialization uses explicit response models, never ORM dumping.
- Arbitrary base URLs from control-plane input are prohibited, preventing the
  registry from becoming an SSRF configuration surface.
- Fallback rechecks data-handling eligibility for the exact provider recipient.
- Tenant resource joins and new global binding uniqueness prevent ambiguous
  cross-tenant attribution.
- Retention, governance export relevance, erasure relevance, encryption, and
  backup classification must be added to SPEC-025 documentation during the
  implementation phase. Usage records are content-free operating records, not
  user content, and their final retention remains operating-owner approval.

## 28. Test strategy

### 28.1 Unit proof

- strict parsing and unknown-version rejection for every new enum/schema;
- exact capability matching for response plan, summary, and embedding;
- routing precedence and immutable snapshot behavior;
- fallback allow/deny matrix by every closed reason;
- health evidence inclusion/exclusion and threshold recovery;
- usage `reported/partial/unknown/invalid` validation with no zero fill;
- checked fixed-point/ceiling cost arithmetic and overflow rejection;
- UTC daily/monthly window boundaries, including leap/month/year boundaries;
- cumulative budget selection and deterministic lock order;
- telemetry label definitions, emitted-call match, allowed values, and
  prohibited label/value rejection;
- configuration mode/secret redaction validation; and
- API response language proving estimate—not billing—semantics.

### 28.2 PostgreSQL/Redis integration proof

- migration/backfill exactness and null-to-unknown behavior;
- global unique Assistant/connection ownership constraints;
- policy/head CAS races and immutable published children;
- route resolution and cross-tenant failure;
- last-unit concurrent hard-budget reservation across multiple workers;
- all-or-none multi-scope/multi-measurement reservation;
- idempotent attempt-key race and replay;
- release after rate/concurrency denial;
- reconcile reported, partial, invalid, unknown, and ambiguous usage;
- crash recovery from `reserved` and `io_started` with stale-owner fencing;
- budget revision mid-window without counter reset;
- daily/monthly window rollover;
- price overlap exclusion and effective-boundary selection;
- summary bounded defer/terminal behavior;
- semantic query lexical fallback and index/rebuild durable retry;
- health transition concurrency and irrelevant failure exclusion; and
- no database transaction/lock held while a blocking fake provider waits.

### 28.3 Authorization and privacy proof

- deployment operator versus every tenant role for every deployment route;
- owner/admin/auditor/viewer/operator matrix for Assistant and connection;
- operator denied absent an implemented explicit capability grant;
- cross-tenant/resource enumeration and mutation denial;
- disabled identity/membership/authority denial;
- idempotency and stale `If-Match` conflicts;
- response/audit/log/metric/database inspection for prohibited content,
  credentials, and raw platform identities; and
- aggregate completeness fields with no raw attempt leakage.

### 28.4 Workload regression proof

- response planning keeps pre-generation safety and logical rate limits;
- safety refusal never falls back;
- every transport retry/correction/fallback has distinct accounting;
- fallback success preserves primary estimated usage;
- summary adopts routing/accounting without unbounded retries;
- embedding remains separately budgeted and only Ollama-capable;
- rate/concurrency failure cannot consume a final reservation;
- concurrency release failure cannot mask a successful result; and
- existing privacy invalidation during provider I/O remains authoritative.

## 29. Migration lifecycle validation

The future validator must prove, against supported PostgreSQL:

```text
0016_data_governance
  -> 0017_provider_routing_cost_budgets
  -> 0016_data_governance
  -> 0017_provider_routing_cost_budgets
```

It must also prove repository-required `base -> head -> base -> head`, exactly
one head, offline PostgreSQL SQL generation where supported, backfill, every
constraint/index/exclusion, and current head after completion. Tests must use
both an empty database and representative 0016 generation-attempt data.

Downgrade succeeds automatically only before governed rows/published policy
exist. Once governed external attempts exist, a production downgrade must fail
with an explicit precondition rather than erase accounting. The empty-data
migration lifecycle remains reversible for CI.

## 30. Docker and runtime proof

The implementation validator must start isolated PostgreSQL and Redis, migrate
from 0016, and run all integration suites with fake generation/embedding
providers. It must start response-planning, summary, semantic-index, and
provider-governance workers with short deterministic leases, prove graceful
stop/restart, reclaim both reservation states, and inspect that no duplicate
external call occurs for a reused attempt key.

Staging Compose validation must require the provider-governance worker only when
the mode is `observe` or `enforce`, with migration dependency, restart policy,
graceful stop, configuration, and loopback metrics exposure. A rendered topology
is static evidence only; Docker-backed worker/database/Redis execution is the
release proof. Live provider requests are not required in CI and never use
production credentials.

## 31. Rollback

### Before activation

Rollback the candidate binary and downgrade 0017 after the empty/legacy
precondition succeeds. Legacy provider behavior remains unchanged because
`provider_governance_mode=legacy` is the default.

### Observe mode

Stop provider-calling workers, preserve/export content-free accounting evidence,
return to the previous binary, and retain migration 0017 until the operator
confirms no governed row would be discarded. Observe mode does not authorize
hard enforcement claims.

### Enforce mode or after any governed I/O

An old binary would bypass budgets. Therefore rollback requires disabling
external provider work first (`llm_enabled=false`, summary/semantic provider
workers disabled), preserving migration 0017 and its accounting, and deploying
the previous binary only in that fail-closed state. Re-enabling legacy provider
I/O is a separate Product Owner/operating-owner risk decision. Do not downgrade
away governed attempts, reservations, or estimates.

Policy rollback is a new published revision/head change, never mutation or
deletion of history. Redis rate/concurrency state remains reconstructible and
must not be used to reconstruct budget truth.

## 32. Risks

| Risk | Design control |
| --- | --- |
| Dual legacy/governed sources | Explicit mode; DB is sole route/price/budget truth outside legacy; unified new-write ledger. |
| Existing Assistant/connection can bind to multiple tenants | Migration preflight plus global unique binding constraints. |
| Reservation leak | Durable state machine, lease expiry, bounded recovery worker, no-I/O versus I/O-possible distinction. |
| Budget overspend race | Deterministic multi-row locks and one atomic all-scope reservation transaction. |
| Inaccurate cost | Integer arithmetic, versioned provenance, completeness quality, estimate-only language. |
| Unknown usage appears free | Null preservation and conservative consumption after possible I/O. |
| Retry/fallback bypass | One gateway and a new reservation for every external call. |
| Summary/embedding remain ungoverned | Mandatory shared executor integration and workload tests. |
| Health flapping | Versioned bounded thresholds and CAS state transitions. |
| Fallback changes data recipient | Explicit data class plus current eligibility recheck per attempt. |
| Metrics not externally visible | Per-runtime owned exporter and deployment-specific port validation. |
| Extension unavailable | Pre-migration `btree_gist` approval gate; no weakened overlap rule. |
| Old-binary rollback bypasses enforcement | Disable all provider I/O and retain schema before binary rollback. |
| Excessive ledger growth | Bounded indexes/queries and SPEC-025 retention decision before production. |

## 33. Expected files to change during implementation

This list is prospective; none is changed by this design task.

### New files

- `alembic/versions/0017_provider_routing_cost_budgets.py`
- `backend/app/domain/provider_governance.py`
- `backend/app/application/provider_governance.py`
- `backend/app/application/ports/provider_governance.py`
- `backend/app/infrastructure/database/provider_governance.py`
- `backend/app/runtime/provider_governance_worker.py`
- focused unit and PostgreSQL/Redis integration test modules under
  `backend/tests/`
- `scripts/validate-provider-governance.sh`
- an ADR for the unified provider-attempt/reservation boundary
- a provider-routing/budget operations runbook
- a SPEC-026 final implementation handoff and execution plan if implementation
  spans sessions

### Existing files

- `backend/app/domain/planning.py`
- `backend/app/application/model_provider.py`
- `backend/app/application/planning_service.py`
- `backend/app/application/semantic_memory.py`
- `backend/app/application/rate_limit_rules.py`
- `backend/app/infrastructure/model_providers.py`
- `backend/app/infrastructure/semantic_memory.py`
- `backend/app/infrastructure/concurrency_provider.py`
- `backend/app/infrastructure/database/models.py`
- `backend/app/infrastructure/database/planning.py`
- `backend/app/infrastructure/database/summaries.py`
- `backend/app/infrastructure/database/context.py`
- `backend/app/infrastructure/database/semantic_memory.py`
- `backend/app/infrastructure/telemetry.py`
- `backend/app/runtime/response_planning_worker.py`
- `backend/app/runtime/conversation_summary_worker.py`
- `backend/app/runtime/semantic_memory_index_worker.py`
- `backend/app/runtime/semantic_memory_operations.py`
- `backend/app/interface/http/control_plane.py`
- `backend/app/core/config.py`
- environment examples, `compose.staging.yaml`, demo/operator startup surfaces,
  and affected deployment/observability/general validators
- SPEC-025 data-governance/encryption/compliance/backup documentation for the
  new durable records
- `docs/ARCHITECTURE.md`, the decisions index, product indexes/status, and
  relevant operational documentation

No frontend, new provider adapter, SPEC-027, or unrelated file is expected.

## 34. Implementation phases

### Phase 1 — Schema and pure domain contracts

Create the active execution plan; add closed domain values, migration 0017,
models, strict parsers, repositories, backfill, and unit/migration proof. Do not
route provider I/O through the new system yet.

### Phase 2 — Admission, ledger, and recovery core

Implement immutable revisions, work snapshots, fixed-point pricing, atomic
multi-budget reservation/reconciliation, attempt state machine, and bounded
provider-governance recovery worker with fake-provider integration proof.

### Phase 3 — Response planning

Refactor per-call retry/correction/fallback through the governed executor,
populate full usage, preserve safety and logical rate gates, and prove crash/
replay/concurrency-release behavior.

### Phase 4 — Summaries and embeddings

Adopt the same executor for summary and all embedding paths; add bounded summary
disposition, planning source propagation for query embedding, lexical fallback,
and independent workload accounting proof.

### Phase 5 — Control plane and authorization

Add deployment and tenant-resource endpoints, exact authorization, CAS publish,
idempotency, content-free audits, aggregate completeness, and cross-scope tests.

### Phase 6 — Telemetry and deployment

Register closed metrics, wire per-runtime exporters, add the recovery worker to
staging/operator topology, update environment examples and validators, and
prove graceful lifecycle/restart.

### Phase 7 — Documentation and final validation

Create the ADR/runbook, update architecture and SPEC-025 governance inventory,
run focused then full validation, execute migration lifecycle and Docker proof,
self-audit every requirement, and create the final implementation handoff. Do
not begin SPEC-027.

## 35. Requirement traceability and acceptance checklist

The Product Spec uses normative section headings rather than explicit FR/NFR
numbers. The IDs below are design trace identifiers only; they do not add or
change product requirements.

### 35.1 Functional-requirement map

| Trace ID | Product Spec authority | Concrete implementation surfaces | Primary proof |
| --- | --- | --- | --- |
| FR-01 | Provider registry expectations | capability domain values/table/state; control-plane deployment routes; adapter-slot resolver | registry/schema/redaction tests |
| FR-02 | Versioned provider-routing policy | policy revision/route/reason/head/snapshot tables; routing service; CAS APIs | precedence, immutability, stale-head tests |
| FR-03 | Model and capability compatibility | strict matcher; capability schema; workload validators | exact match/unknown-key tests |
| FR-04 | Primary and fallback selection | governed router; attempt role/ordinal; allowed-reason children | full fallback matrix and role persistence |
| FR-05 | Provider health semantics | health policy/state/event tables; attempt evidence reducer; recovery worker | transition, staleness, exclusion tests |
| FR-06 | Generation and embedding separation | workload enum; separate policy/budget/price keys; all three workers | independent-route/budget tests |
| FR-07 | Attempt-level usage record | unified attempt ledger; source snapshots; per-I/O gateway | retry/correction/fallback/summary/embed proof |
| FR-08 | Unknown/partial/invalid usage | usage validator, nullability checks, quality aggregates | no-zero and malformed-usage tests |
| FR-09 | Cost estimation, not billing | fixed-point calculator, estimate-quality fields, API language | arithmetic/completeness/contract tests |
| FR-10 | Operator-supplied pricing | price revision table/exclusion; deployment-operator API | overlap/effective/authorization tests |
| FR-11 | Supported budget scopes/hierarchy | stable budgets/revisions/heads/windows; exact ownership joins | cumulative all-scope tests |
| FR-12 | Pre-I/O reservation | admission repository; attempt/reservation state machine | concurrency last-unit and no-lock-I/O tests |
| FR-13 | Quota exhaustion | workload dispositions; reset metadata; no-response/deferral/lexical fallback | no-I/O/no-bypass/bounded-retry tests |
| FR-14 | Rate-limit interaction | existing limiter plus per-call provider gate and release | rule-preservation and release tests |
| FR-15 | Concurrency interaction | existing Redis semaphore; executor-owned acquire/release | capacity, TTL, release-failure tests |
| FR-16 | Retry/fallback cost accounting | unique per-call attempts/reservations and application outcomes | retained failed-cost and ambiguity tests |
| FR-17 | Authorization | deployment authority; tenant binding checks; role matrix; audit | every role/scope/cross-tenant test |
| FR-18 | Privacy/content safety | allowlisted models/logs, no-content schema, secret-slot mapping | DB/API/log/metric inspection tests |
| FR-19 | Observability | new closed metrics; per-runtime exporter; aggregate completeness | catalog/emission/cardinality tests |
| FR-20 | Failure behavior | guarded state machine, bounded recovery worker, workload dispositions | fault injection and replay tests |

### 35.2 Non-functional-requirement map

| Trace ID | Derived Product Spec invariant | Design realization |
| --- | --- | --- |
| NFR-01 | Deterministic and versioned | immutable revisions, head CAS, work snapshot, fixed route order |
| NFR-02 | Atomic and idempotent | unique attempt key, deterministic row locks, all-scope transaction, guarded transitions |
| NFR-03 | No DB lock/session across I/O | explicit TX A/B/C boundary around Redis/provider calls |
| NFR-04 | Content-safe and low-cardinality | no-content schema, explicit response models, metric allowlists and closed values |
| NFR-05 | Fail closed | enforced-mode prerequisite, hard-budget/unknown-bound denial, DB/Redis denial |
| NFR-06 | Compatibility/no weakened guarantees | legacy default, existing rate scopes, Redis concurrency keys, local validation and safety preserved |
| NFR-07 | Recoverable and bounded | leased recovery batches, `reserved` versus `io_possible`, no exactly-once claim |
| NFR-08 | Observable without false confidence | durable quality/provenance, known subtotal plus incomplete count, estimate-only language |

### 35.3 Product acceptance checklist

- [ ] AC-01 — Registry metadata, compatibility, lifecycle, health, and secret
  exclusion are implemented and proven.
- [ ] AC-02 — Deployment/Assistant/connection routing revisions resolve in the
  approved order and unknown versions fail closed.
- [ ] AC-03 — Primary/retry/correction/fallback roles and allowed reasons are
  exact and durable.
- [ ] AC-04 — Generation and embedding remain independently governed.
- [ ] AC-05 — Every actual response-plan, summary, query/index/rebuild provider
  call has one idempotent usage attempt.
- [ ] AC-06 — Reported/partial/unknown/invalid/ambiguous usage never zero-fills.
- [ ] AC-07 — Estimate provenance/quality is visible and no API/document calls it
  billing truth.
- [ ] AC-08 — All applicable hard scopes atomically reserve before I/O under
  concurrency.
- [ ] AC-09 — Missing hard-budget price/bound fails closed; soft behavior is
  distinct.
- [ ] AC-10 — Release, reported reconciliation, and conservative ambiguity are
  correct.
- [ ] AC-11 — Retry/correction/fallback/crash/replay retains every possible cost.
- [ ] AC-12 — Existing safety, privacy, rate, concurrency, leases, and recovery
  remain independently proven.
- [ ] AC-13 — Deployment actions require current `deployment_operator`; tenant
  actions use exact existing role/resource boundaries.
- [ ] AC-14 — Cross-scope, credential, and unrelated-resource requests fail
  closed and audit safely.
- [ ] AC-15 — Database, API, logs, audits, and metrics contain no prohibited
  content/secrets/platform IDs.
- [ ] AC-16 — Health evidence excludes budget/rate/tenant/single unrelated
  failures.
- [ ] AC-17 — Multi-worker race, lease recovery, and no-lock-across-I/O tests
  pass.
- [ ] AC-18 — Control-plane CAS/idempotency/redaction/completeness/non-billing
  contracts pass.
- [ ] AC-19 — `0016 -> 0017 -> 0016 -> 0017` and base/head migration proof pass.
- [ ] AC-20 — Architecture, governance inventory, operations, rollback, and final
  handoff are current without a compliance or rollout claim.

## Design decision gates before implementation

Repository implementation authority is still required. Before production
activation, human operating-owner approval is also required for provider/model
and data-recipient eligibility, secret ownership, `btree_gist` availability,
health thresholds, pricing, budget values/modes/windows, alerting, retention,
backup treatment, migration execution, rollout, rollback, reconciliation, and
legal/compliance statements.

Those production values do not need to be invented to implement the versioned,
strictly validated mechanisms and deterministic test fixtures described here.
SPEC-027 remains out of scope and is not started.
