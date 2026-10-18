# SPEC-026 Provider Routing, Cost Budgets, and Usage Governance

## Status

Product Owner approved on 2026-09-02 as the authoritative product contract for
SPEC-026. The implementation and design phases were subsequently authorized;
the repository candidate is under final validation. Production prices, budget
amounts, retention, health thresholds, and rollout remain operating-owner
decisions. No production compliance or billing claim is authorized.

SPEC-025 is the completed predecessor. SPEC-026 does not begin or define
SPEC-027.

## Objective

Make provider selection, usage measurement, and cost containment explicit,
versioned, inspectable, and enforceable across the existing deployment,
Assistant, and PlatformConnection boundaries without weakening safety,
privacy, rate limiting, provider concurrency, or durable-work guarantees.

The product must be able to answer, without inspecting prompts or responses:

- which approved routing policy governed a provider attempt;
- why a primary or fallback provider was eligible or rejected;
- whether provider usage is complete, partial, unknown, or invalid;
- what operational cost was estimated from operator-supplied pricing;
- which applicable budget admitted or denied work before provider I/O; and
- how retries, corrections, fallback attempts, and ambiguous outcomes affected
  governed usage.

## Problem statement

January currently supports configured generation providers and a local Ollama
embedding capability, bounded provider retries and fallback for response
planning, distributed throughput limits, and a deployment-wide provider
concurrency semaphore. Provider usage is recorded only where a provider reports
it, and optional pricing produces operational estimates rather than invoices.

Those capabilities do not yet form one product contract. Routing is primarily
deployment configuration, generation paths do not all share the same routing
and accounting behavior, embedding is a separate capability, missing usage can
make cost incomplete, and there is no durable pre-I/O budget decision across
deployment, Assistant, and PlatformConnection scopes. A crash after provider
I/O can also leave the system uncertain whether a billable request occurred.

Without an explicit contract, fallback can accidentally bypass cost controls,
unknown usage can be mistaken for zero, tenant administration can be confused
with deployment authority, or new routing can weaken existing privacy and
coordination guarantees.

## Scope

SPEC-026 defines:

- a non-secret provider and capability registry for providers already supported
  by the repository;
- immutable, versioned routing policy for generation and embedding workloads;
- deterministic primary and fallback eligibility and selection;
- bounded provider health states and their routing effects;
- durable attempt-level usage classification and operational cost estimation;
- independently governed generation and embedding budgets at deployment,
  Assistant, and PlatformConnection scope;
- pre-I/O budget reservation, denial, release, and reconciliation semantics;
- interaction with existing rate limits, provider concurrency, retries,
  correction attempts, fallback, leases, and recovery;
- content-safe control-plane administration, audit, and aggregate operational
  views; and
- acceptance and migration expectations for a later implementation phase.

The existing modular monolith, PostgreSQL source of truth, Redis coordination,
SPEC-021 tenant/resource model, supported providers, and existing workers remain
the product boundary.

## Explicit non-goals

- Billing truth, invoices, payments, credits, chargebacks, tax, subscription
  plans, or customer-facing metering.
- Conversation, group, participant, subject, or user budgets. They are not
  Product Owner-authorized by this specification.
- New providers, new provider adapters, provider SDK replacement, model
  benchmarking, or live provider qualification.
- Hosted embedding expansion. A generation capability never implies an
  embedding capability; the current separately configured Ollama embedding
  boundary remains authoritative.
- Prompt optimization, semantic routing, quality scoring, auction routing,
  least-cost model arbitration, or autonomous model switching.
- A new authentication system, secret manager, tenant model, tenant onboarding
  system, or broader multi-tenancy.
- Weakening or replacing safety evaluation, privacy invalidation, rate limits,
  provider concurrency, durable leases, recovery, or delivery ambiguity rules.
- Exposing prompts, responses, memories, vectors, credentials, provider bodies,
  raw platform identifiers, or subject data in usage or cost interfaces.
- Legal, regulatory, residency, or provider-contract compliance certification.
- SPEC-027 behavior.

## Product vocabulary

- **Workload class:** `chat_generation` or `embedding`. They are independently
  routed, accounted, and budgeted.
- **Generation operation:** a bounded subtype such as response planning,
  malformed-output correction, fallback generation, or summary generation.
- **Embedding operation:** a bounded subtype such as query embedding, index
  embedding, or rebuild embedding.
- **Routing policy revision:** an immutable, versioned list of eligible routes
  and decision rules for one scope and workload class.
- **Route:** one registered provider capability and model configuration used as
  `primary` or an ordered `fallback`.
- **Usage observation:** provider-reported usage and its quality classification,
  never an inferred zero.
- **Operational cost estimate:** deterministic arithmetic over usage and an
  operator-supplied price revision. It is not billing truth.
- **Budget:** a versioned limit for one scope, workload class, measurement kind,
  and UTC accounting window.
- **Reservation:** a conservative, durable pre-I/O debit against every
  applicable hard budget, later released or reconciled.

## Product decisions

### Provider registry expectations

The registry is the authoritative inventory of provider capabilities that may
be selected. Each entry must contain only bounded, non-secret metadata:

- stable provider ID from the repository-supported closed set;
- stable capability ID and workload class;
- configured model identifier and provider-advertised capabilities;
- compatibility facts required by the workload, including structured-output
  support for response planning and embedding dimension/version where relevant;
- lifecycle state and health state;
- allowed data-handling classification and deployment eligibility;
- external credential reference/status, never the credential value;
- current routing and pricing revision references; and
- creation, activation, supersession, and actor metadata suitable for audit.

Registry membership does not prove a capability healthy, affordable, or
authorized for a particular workload. A chat-generation registration never
grants embedding eligibility. Provider credentials stay at the existing
external secret boundary and must never be returned through registry APIs.

The initial registry is limited to the adapters and capabilities already
supported by the repository: OpenAI, Gemini, Groq, OpenRouter, and Ollama for
their existing generation behavior, and the separately configured Ollama
embedding capability. Enabling a new provider or hosted embedding recipient is
future product work.

### Versioned provider-routing policy

Routing policy is immutable after publication. A policy revision contains a
schema/version identifier, scope, workload class, ordered routes, capability
requirements, allowed fallback reasons, budget behavior, activation time, and
supersession state. Unknown versions fail closed.

The policy resolution order is:

1. PlatformConnection revision, when present for the bound connection;
2. Assistant revision, when present for the bound Assistant;
3. deployment default revision.

The first applicable revision supplies the route order. This precedence affects
selection only; it never removes deployment, Assistant, or PlatformConnection
budgets that otherwise apply.

Durable work snapshots the resolved policy revision before execution so normal
replay is deterministic. Immediately before external I/O, the worker must
recheck current deny conditions: disabled/draining capability, revoked data
eligibility, disabled resource, hard-budget denial, safety/privacy denial,
rate-limit denial, or unavailable coordination. A later permissive policy does
not silently rewrite existing work. A current restrictive policy always stops
new external I/O.

### Model and capability compatibility

A route is eligible only when its registered capability satisfies every
requirement of the workload. Compatibility is explicit and deny-by-default;
provider name or model naming conventions are not evidence.

Response planning requires the existing typed structured-output contract and
local response-plan validation. Summary generation requires its existing
bounded summary contract. Embedding requires the configured embedding version,
dimension, and derived-index compatibility. Incompatible routes are skipped
before rate, concurrency, budget, or provider I/O is consumed. If no compatible
route remains, work follows the workload-specific unavailable behavior.

### Primary and fallback selection

Selection is deterministic from the resolved revision. The first eligible
route is primary; later routes are attempted only in declared order and only
for a closed fallback reason authorized by that revision.

Fallback may follow exhausted, retryable provider availability failures. It
must not follow a safety refusal, privacy denial, invalid authorization,
unsupported capability, malformed policy, disabled/draining route, or an
applicable exhausted hard budget. A malformed provider response may use the
existing single bounded correction attempt before fallback where the workload
already permits it. Authentication, permission, or invalid-request failures do
not blindly fall back.

Every fallback must independently pass data eligibility, capability, budget,
rate-limit, and concurrency checks. Fallback is not a mechanism to evade a
deployment or resource budget. The attempt record must distinguish `primary`,
`retry`, `correction`, and `fallback` roles.

### Provider health semantics

Provider capability health uses the closed states:

- `ready`: eligible for new work;
- `degraded`: eligible according to policy, with the state observable;
- `unavailable`: automatically ineligible until recovery criteria are met;
- `draining`: no new external I/O; already-started calls may finish; and
- `disabled`: administratively ineligible.

Health derives from bounded operational evidence and explicit administrative
state. Budget exhaustion, a single request failure, a tenant authorization
failure, and a rate-limit decision are not provider-health changes. Health
thresholds and recovery windows are versioned operating configuration. State
transitions are content-free and auditable. Unknown health or stale required
health evidence fails closed for a route whose policy requires it.

### Generation and embedding separation

`chat_generation` and `embedding` have separate registrations, routing policy,
budgets, usage, pricing, rate-limit operations, and health evidence. Capacity or
budget in one class cannot be borrowed by the other. Existing provider
concurrency may remain deployment/provider coordinated, but admission must
still preserve workload-specific accounting.

Summary generation is governed as chat generation and must not bypass generation
budgets or accounting. Semantic query, index, and rebuild operations are
embedding work and must not bypass embedding budgets. Existing lexical fallback
when embedding is unavailable remains available and does not consume an
embedding-provider budget.

## Usage accounting

### Attempt-level record

Every actual external provider I/O attempt must produce one durable,
content-free accounting outcome, including primary calls, transport retries,
malformed-output corrections, fallbacks, summary generation, and embedding
query/index/rebuild calls. A logical job may therefore have several chargeable
attempts. Worker replay must not create a second record for the same known
attempt identity, while genuinely repeated external I/O is a distinct attempt.

The record must identify the workload and operation, provider capability,
route/price/policy revisions, applicable deployment/Assistant/connection
scopes, timestamps, outcome, usage quality, reported token/unit fields where
available, reserved amount, reconciled estimate, and ambiguity state. It must
not store product content or credentials. Subject, participant, conversation,
group, Telegram, or other raw platform identities are neither required nor
authorized for this ledger.

### Unknown, partial, and invalid usage

Usage quality is explicit:

- `reported`: all fields required for the applicable calculation are valid;
- `partial`: the provider supplied some, but not all, required usage fields;
- `unknown`: the provider supplied no usable usage value or the outcome is
  ambiguous after external I/O; and
- `invalid`: supplied values are malformed, negative, contradictory, or outside
  the accepted numeric contract.

Missing, partial, invalid, or ambiguous usage must never be stored, exported,
aggregated, displayed, or emitted as zero. Known fields remain known and absent
fields remain null/unknown. Invalid usage is retained as a content-free quality
outcome; untrusted numeric values do not enter budget arithmetic.

### Cost estimation is not billing truth

Operational cost is an estimate derived from a specific usage observation and
a specific price revision. It must always expose its provenance and quality.
The product must call it an `estimate`, never a bill, invoice, charge, credit,
or amount owed. Provider dashboards, invoices, contracts, taxes, discounts,
cached-token rules, batch pricing, and post-period adjustments remain external
billing truth.

If usage or a required price component is unknown, partial, or invalid, the
corresponding reconciled cost estimate is unknown or partial, never zero.
Aggregates must expose both known estimated cost and the count/share of attempts
with incomplete cost; they must not present the known subtotal as a complete
total.

### Operator-supplied pricing

Pricing is non-secret, immutable, versioned operating configuration supplied by
an authorized deployment operator. A price revision identifies currency,
provider capability/model, workload class, effective interval, unit basis, and
integer fixed-point rates. Floating-point currency arithmetic is prohibited.
Overlapping active revisions for the same priced unit fail closed.

The repository may retain the existing input/output microusd-per-million token
shape and add an explicit embedding unit when implementation requires it. The
actual prices, effective dates, currency policy, and provider-contract
interpretation require operating-owner approval. Missing pricing remains
unknown and must not be inferred from provider marketing pages at runtime.

## Budget contract

### Supported scopes

Budgets are authorized at exactly these scopes:

- **Deployment:** a tenant-independent ceiling across all applicable work;
- **Assistant:** an additional ceiling for work attributed to one existing
  tenant-bound Assistant; and
- **PlatformConnection:** an additional ceiling for work attributed to one
  existing tenant-bound PlatformConnection.

Conversation and group budgets are not authorized. Tenant membership is an
authorization boundary, but SPEC-026 does not introduce a separate tenant
budget or any new tenant semantics.

Every applicable budget must admit the attempt. Deployment is always
applicable. When work is bound to an Assistant and PlatformConnection, both
resource budgets also apply. A more specific policy cannot override, refill,
or bypass a broader budget.

### Workload and measurement independence

Each budget governs exactly one workload class. Generation and embedding limits
are independent. A budget may limit estimated fixed-point cost, provider units,
or both, but its measurement kind is explicit. Known usage from one kind is not
silently converted into another without the applicable price revision.

Budget revisions define a hard or soft enforcement mode and a fixed daily or
monthly UTC accounting window. Window identity and reset time are deterministic
and inspectable. Actual amounts, enabled scopes, and alert thresholds are
operating configuration requiring human approval; no implicit unlimited or
zero budget may be created from missing configuration.

### Pre-I/O enforcement and reservation

All applicable hard budgets must be checked and conservatively reserved before
external provider I/O. The reservation uses the bounded request maximum and the
price revision selected for the attempt. For a hard cost budget, absent required
pricing or inability to form a conservative reservation denies external I/O.
For a hard unit budget, inability to determine the bounded maximum also denies
external I/O.

The reservation and attempt identity are durable and idempotent. Their database
transaction ends before provider I/O; no row lock, database session, Redis
lease acquisition, or control-plane request remains open across the call.
After the call, the reservation is reconciled to valid reported usage and its
estimate. If no external I/O occurred, it is released. If external I/O may have
occurred but usage is unknown, the conservative reservation remains consumed
until an authorized reconciliation policy resolves it; ambiguity is never
credited automatically.

Concurrent admission must serialize or use an equivalent atomic compare-and-
reserve operation so two individually eligible calls cannot overspend the same
hard remainder. Expired/crashed reservations need bounded, audited recovery
that distinguishes `no_io` from `io_possible`; time expiry alone must not grant
a credit when external I/O may have happened.

Soft budgets do not deny I/O. They record a bounded exceeded decision and alert
state while normal rate, concurrency, safety, and routing checks continue.

### Quota exhaustion behavior

Hard-budget exhaustion is an expected admission denial, not a provider error or
provider-health failure. It produces no provider I/O and no fallback that would
bypass the exhausted budget.

- Response planning follows the existing safe no-response/retry disposition
  selected for a temporary local dependency denial and must not expose budget
  values or operator configuration to an end user.
- Summary generation remains durable and deferred until its authorized next
  window or operator action; it does not loop without bounded retry policy.
- Embedding index/rebuild work remains pending/deferred without corrupting the
  canonical PostgreSQL memory record.
- Response-path embedding uses the existing content-safe lexical fallback when
  available.
- Control-plane callers receive a stable closed reason and next reset time only
  when their authorization permits that scope.

Disabling a budget does not erase its historical revisions or accounting.
Changing a limit applies prospectively and cannot rewrite past estimates.

### Rate-limit interaction

Budgets and rate limits answer different questions and both remain mandatory.
Budget admission does not increment, reset, merge, or weaken any existing
deployment, connection, conversation, participant, provider, generation, or
embedding throughput limit. Redis coordination failure continues to fail closed
for provider I/O as defined by SPEC-012.

The implementation may order checks to minimize wasted coordination, but it
must release a reservation if a later rate-limit decision proves no external
I/O occurred. Retry-after behavior remains bounded by the existing durable-work
contract and cannot extend a budget window or create an unbounded retry loop.

### Concurrency interaction

The existing Redis TTL provider semaphore remains independent of budgets and
throughput rate limiting. Every selected route must acquire capacity before I/O;
budget availability does not imply capacity. Active capacity cannot be stolen,
and a coordination failure fails closed.

If capacity is denied before I/O, the attempt reservation is released. A
release failure must not erase a successful provider result or convert known
usage to zero; it is recorded as a separate coordination/recovery outcome. No
database lock is held while waiting for or holding provider capacity across I/O.

### Retry and fallback cost accounting

Every call that reaches a provider can incur usage and is accounted separately,
regardless of whether its result is accepted. Transport retries, correction
attempts, and fallback attempts each require their own pre-I/O reservation and
reconciliation. A successful fallback does not erase the usage or estimated
cost of earlier failed attempts.

A crash after I/O but before durable completion is recorded as `io_possible`
with unknown usage when the provider result cannot be recovered. Normal replay
must not claim exactly-once provider charging. The next attempt requires new
admission; the earlier conservative reservation remains visible so replay
cannot silently exceed a hard budget.

## Authorization requirements

Authorization is deny-by-default, server-side, current at the protected action,
and based on existing SPEC-021 identities and resources.

- An active `deployment_operator` may manage the deployment provider registry,
  deployment routing, price revisions, deployment budgets, and deployment-wide
  aggregate usage/cost estimates. SPEC-026 explicitly extends that existing
  tenant-independent capability to these actions.
- `tenant_owner` and `tenant_admin` may manage routing and budgets for an
  Assistant or PlatformConnection owned by their tenant and may read authorized
  resource aggregates.
- `operator` may read or manage only explicitly granted resources and only when
  the existing grant includes the corresponding configuration capability.
- `auditor` may read content-free policy revisions, decisions, and aggregates
  within the existing authorized tenant/resource scope, but cannot mutate them.
- `viewer` receives no usage/cost or routing administration capability unless a
  future product decision explicitly grants a bounded read view.

Tenant roles never imply deployment authority. `deployment_operator` never
implies tenant membership, tenant resource access, or access to tenant content.
Cross-tenant, cross-Assistant, and cross-connection requests fail closed. No
role can read credential values. Changes, denials, and privilege transitions
are content-free and auditable under existing control-plane conventions.

## Privacy and content-safety requirements

- Prompts, responses, message text, memory text, summaries, vectors, provider
  bodies, credentials, authorization headers, user IDs, participant IDs,
  conversation IDs, group IDs, Telegram IDs, usernames, and raw platform IDs
  must not enter metric labels.
- Metric labels use closed bounded enums only. Provider is allowed only from the
  registered closed set; model identifiers and durable resource/request IDs are
  not metric labels.
- Usage, budget, price, routing, and audit records contain no prompt, response,
  memory, summary, vector, or provider body. Assistant/connection internal keys
  may exist in protected durable accounting solely for authorized scope
  attribution; they are never telemetry labels or public identifiers.
- Logs are allowlisted and content-free. They must not contain provider request
  or response bodies, credentials, raw platform identifiers, or budget-ledger
  dumps.
- Provider routing changes the external recipient of content. A route is
  eligible only when its data-handling classification is approved for that
  workload and deployment. Fallback cannot broaden the recipient set beyond the
  published policy.
- Existing memory consent, privacy invalidation, safety, governance retention,
  export, erasure, encryption ownership, and backup rules remain authoritative.
- New durable provider-policy, usage, pricing, reservation, and budget records
  must be added to the SPEC-025 data inventory with explicit retention, export,
  erasure relevance, backup, and encryption classification during
  implementation design.

## Observability requirements

The later implementation must expose content-safe evidence for:

- routing decisions by workload, route role, bounded outcome, and reason;
- provider health state and transitions;
- provider attempts, latency, and bounded result;
- usage quality (`reported`, `partial`, `unknown`, `invalid`);
- estimated known cost plus incomplete-estimate attempt counts;
- budget admission, denial, reservation, release, reconciliation, exhaustion,
  and recovery by workload and scope type;
- retries, corrections, fallbacks, and ambiguous `io_possible` outcomes; and
- worker backlog, duration, and terminal result for every governed workload.

Metric label names must exactly match emitted labels, and label values must be
closed bounded sets. Allowed dimensions include registered provider,
`chat_generation`/`embedding`, bounded operation, route role, result,
usage-quality, budget-scope type, and admission decision. Prohibited dimensions
include model strings, price revision IDs, request/job/resource IDs, tenant,
Assistant, PlatformConnection, conversation, group, participant, user,
Telegram identifiers, URLs, prompts, content, credentials, and provider bodies.

Fine-grained authorized attribution belongs in protected durable records and
control-plane queries, not metrics. Existing SLI and alert semantics remain;
cost or budget metrics must not be relabeled as availability or billing truth.

## Failure behavior

| Condition | Required behavior |
| --- | --- |
| Unknown policy/schema version | Fail closed before provider I/O; audit bounded reason. |
| No compatible or data-eligible route | Use workload-specific unavailable/deferred or lexical-fallback behavior; no incompatible I/O. |
| Primary transient failure | Apply bounded retry, then only an explicitly eligible fallback. |
| Safety/privacy/authorization denial | No provider I/O and no fallback. |
| Hard budget exhausted | No provider I/O; expose only authorized closed reason/reset metadata. |
| Hard budget cannot be estimated | Fail closed; missing price or usage bound is not zero. |
| Soft budget exceeded | Continue only if every other gate allows; emit bounded evidence. |
| Rate-limit or concurrency denial | Preserve existing fail-closed behavior and release no-I/O reservation. |
| Usage missing or partial | Persist explicit quality and null unknown fields; never zero-fill. |
| Provider usage invalid | Exclude untrusted values from arithmetic; record `invalid`. |
| Crash before I/O | Recover/release reservation as `no_io` with durable proof. |
| Crash or timeout after possible I/O | Keep conservative debit and record `io_possible`/unknown; do not auto-credit. |
| Accounting persistence unavailable | Fail closed before new provider I/O when hard enforcement cannot be proven. |
| Telemetry exporter unavailable | Preserve durable product result; telemetry failure must not duplicate I/O. |
| Policy or price updated during queued work | Preserve snapshot for deterministic selection, but enforce current revocations and hard denials. |

## Acceptance criteria

An implementation of SPEC-026 is acceptable only when all of the following are
proven:

1. Provider capabilities are registered with non-secret metadata, explicit
   workload compatibility, data eligibility, lifecycle, and health state.
2. Immutable versioned routing resolves deterministically across deployment,
   Assistant, and PlatformConnection scopes; unknown versions fail closed.
3. Primary, retry, correction, and fallback attempts are distinguished, and
   fallback occurs only for authorized reasons after fresh eligibility checks.
4. Generation and embedding have independent registry capabilities, routing,
   accounting, pricing, budgets, and rate-limit behavior.
5. Every actual provider I/O attempt, including summary and semantic-memory
   paths, produces one idempotent content-free usage outcome.
6. Reported, partial, unknown, invalid, and ambiguous usage remain distinct;
   missing usage is never represented or aggregated as zero.
7. Every operational cost value names its estimate status and price provenance;
   no surface presents it as billing truth.
8. Deployment, Assistant, and PlatformConnection hard budgets atomically reserve
   before I/O, all applicable scopes must admit, and concurrent attempts cannot
   overspend the known remainder.
9. Missing price/bounds fail closed for applicable hard cost/unit budgets; soft
   budget behavior is separately observable.
10. No-I/O reservations release, reported usage reconciles, and ambiguous
    post-I/O outcomes retain a conservative debit until authorized resolution.
11. Retry, correction, fallback, crash, and replay tests prove that every
    possible external attempt remains accounted and no accepted earlier cost is
    erased.
12. Existing generation/delivery rate limits, embedding rate limits, provider
    concurrency, safety, privacy, leases, and recovery remain effective and
    independently tested.
13. Deployment administration requires current `deployment_operator` authority;
    tenant/resource administration obeys existing SPEC-021 roles and exact
    tenant, Assistant, and PlatformConnection ownership.
14. Cross-scope access, credential reads, and policy attempts against unrelated
    resources fail closed and are content-free audited.
15. Metrics use only the approved bounded labels; logs, metrics, audits, and
    accounting contain no prohibited content, secrets, or raw platform IDs.
16. Provider-health transitions do not confuse budget, rate, tenant, or single-
    request failures with provider availability.
17. Multi-worker integration tests prove atomic reservation under race, bounded
    retry/fallback, lease recovery, and no database lock across provider I/O.
18. Control-plane contract tests prove revision conflicts, authorization,
    redaction, aggregate completeness indicators, and no billing terminology.
19. Migration upgrade/downgrade/upgrade and repository-required base/head proof
    pass against supported PostgreSQL, with the prior committed head unchanged.
20. Documentation and operational validation explain estimates, unknown usage,
    budget exhaustion, health, recovery, pricing ownership, and rollback without
    claiming legal compliance or production rollout.

## Required implementation proof

The separately authorized implementation must include focused unit tests,
PostgreSQL/Redis integration tests, control-plane authorization tests,
observability label-contract tests, worker recovery tests, migration lifecycle
proof, deployment validation for any affected worker configuration, and the
general repository validator. Tests use fake providers and deterministic usage
fixtures by default; live provider calls are an explicit external verification,
not a normal CI requirement.

At minimum, test matrices must cover scope precedence, cumulative budgets,
simultaneous reservations at the last available unit, unknown/partial/invalid
usage, absent pricing, price revision boundaries, primary/retry/correction/
fallback accounting, summary and embedding paths, current-policy revocation,
rate/concurrency denial after reservation, crash before I/O, ambiguous crash
after I/O, cross-tenant denial, deployment authority, and prohibited telemetry
labels.

## Migration expectation

This product-specification task creates no migration. A later implementation is
expected to need an additive migration after committed
`0016_data_governance`—ordinarily `0017` on the current linear history—for
versioned registry/routing/pricing/budget state, reservations, and unified usage
accounting. It must not rewrite, squash, or repurpose migration 0016.

The design must first determine which existing generation-attempt fields can be
reused without split sources of truth. New constraints must enforce immutable
revision identity, non-overlapping active price semantics, idempotent attempt
and reservation identities, valid usage-quality/nullability combinations,
closed workload/scope/status values, and tenant/resource ownership. Downgrade
must be explicit and must not pretend externally incurred usage can be undone.

Any new durable data must be reconciled with SPEC-025 retention, export,
erasure relevance, encryption, backup/restore, and governance audit before the
migration is approved.

## Dependencies

- SPEC-006 typed provider abstraction, strict output validation, retry,
  correction, and fallback contract.
- SPEC-012 safety policy and distributed rate limiting.
- SPEC-015 content-safe operational telemetry and estimate semantics.
- SPEC-016 durable recovery and provider-concurrency semantics.
- SPEC-018 generation-backed conversation summaries.
- SPEC-019 separately governed embedding and derived-index boundary.
- SPEC-020 deployment, secrets, and runtime ownership.
- SPEC-021 identity, tenant/resource authorization, revision, and audit model.
- SPEC-023 SLI, alerting, and incident evidence boundaries.
- SPEC-025 governance, encryption, retention, export, erasure, and
  tenant-independent `deployment_operator` capability.

## Risks

| Risk | Required mitigation |
| --- | --- |
| Operational estimate diverges from provider invoice | Preserve price/usage provenance, completeness, and explicit non-billing language. |
| Missing usage is treated as free | Closed usage-quality states; null unknown values; conservative hard-budget reservation. |
| Concurrent calls overspend a hard limit | Atomic durable compare-and-reserve across every applicable scope. |
| Crash after provider I/O loses cost | `io_possible` ambiguity, retained reservation, idempotent replay, no exactly-once claim. |
| Fallback leaks content to an unapproved recipient | Versioned data eligibility and fresh pre-I/O checks for every route. |
| Resource override bypasses deployment control | Cumulative budgets; deployment cap always applies. |
| Health flaps or conflates tenant failures | Closed state model, bounded thresholds, recovery window, distinct decision reasons. |
| Routing change makes queued work nondeterministic | Immutable snapshot plus current restrictive-policy recheck. |
| Metrics leak identity or explode cardinality | Closed label allowlist and durable protected attribution outside telemetry. |
| Summary or embedding path bypasses governance | Unified attempt contract and workload-specific acceptance tests. |
| Budget denial causes unbounded retry | Workload-specific bounded defer/recovery disposition. |
| Pricing configuration is stale or overlapping | Immutable effective revisions, overlap rejection, operator ownership. |

## External prerequisites and unresolved approvals

Repository implementation is not blocked by choosing production values, but
production enablement requires human approval of:

- the provider capabilities/models allowed for each workload and their
  data-handling/residency eligibility;
- provider credentials and secret-management operating ownership;
- provider health thresholds, evaluation windows, and recovery thresholds;
- authoritative price revisions, currency, effective dates, and the process for
  reconciling estimates with provider billing;
- enabled deployment/Assistant/PlatformConnection budgets, hard versus soft
  modes, daily/monthly UTC windows, amounts, and alert thresholds;
- alert routing, dashboard access, retention duration, backup treatment, and
  incident/reconciliation ownership for usage and budget records;
- migration execution, production rollout, rollback, and operating-owner
  acceptance; and
- any legal, contractual, residency, or compliance declaration concerning
  external providers.

These approvals must not be inferred from repository defaults, sample prices,
test fixtures, provider documentation, or this specification.

## Out-of-scope future capabilities

- Conversation, group, participant, subject, or per-user budgets.
- Tenant billing accounts, plan entitlements, invoices, payments, credits,
  chargebacks, and customer-visible billing exports.
- Dynamic least-cost, latency, quality, auction, or machine-learned routing.
- Automated price scraping or treating provider pricing pages as billing truth.
- New generation providers, hosted embedding providers, multimodal providers,
  tool execution, streaming, batch inference, and reserved-capacity products.
- Cross-deployment/global budgets, multi-region routing, or expanded
  multi-tenancy.
- Automated procurement, credential issuance, provider-contract acceptance, or
  compliance certification.
- SPEC-027 and all later product scope.

## Product-specification completion evidence

This document, its entries in `docs/product/SPEC.md` and
`docs/product/README.md`, and a clean `git diff --check` are the complete
authorized deliverable for this Product Owner task. No runtime behavior is
claimed until a separately authorized implementation satisfies the acceptance
criteria above.
