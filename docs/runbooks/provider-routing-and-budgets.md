# Provider Routing and Budget Operations

SPEC-026 is disabled by default. Do not enable `observe` or `enforce` until an
authorized deployment operator has published supported capabilities, current
health policies/states, workload-specific deployment routes, approved price
revisions, and deployment budgets. Prices and resulting cost values are
operational estimates, not invoices or billing truth.

## Safe activation

1. Apply migration `0017_provider_routing_cost_budgets` and retain a database
   backup under the approved backup policy.
2. Through authenticated `/control/v1/deployment/provider-*` endpoints,
   register only existing adapters. Registry entries contain credential slot
   status, never credential values or arbitrary URLs.
3. Publish independent `chat_generation` and `embedding` route revisions.
   Verify model capability, data class, current health, and deterministic route
   order. Ollama remains the only authorized embedding adapter.

SPEC-033 knowledge query, indexing and rebuild all reuse the `embedding`
workload and the existing route/capability/price/budget admission pipeline.
They record the closed operations `knowledge_query`, `knowledge_index`, and
`knowledge_rebuild`. Knowledge index work is attributed to the exact durable
job and Assistant; it never invents a connection scope, mutates routing, or
bypasses denial. Keep production knowledge disabled until this embedding route
and its operating budget are explicitly approved.
4. Publish approved effective price revisions. Missing pricing stays unknown.
5. Publish at least one explicit deployment budget per enabled workload, plus
   authorized Assistant or PlatformConnection budgets where wanted.
6. Run `./scripts/validate-provider-governance.sh`, then activate `observe`
   together with the `provider-governance` recovery worker. Inspect known
   estimated subtotals alongside incomplete-attempt counts.
7. After operating-owner acceptance, activate `enforce`; keep the recovery
   worker enabled. Never infer approval from repository defaults.

SPEC-030 does not add a tenant budget or billing layer. Assistant and
PlatformConnection scopes resolve through their persisted canonical tenant and
composite database constraints; compatibility binding rows are not authority.
An operator must use the resource's owning tenant path, and a foreign resource
identifier returns the privacy-safe not-found result. If the tenant,
Assistant, or connection is not active at the final admission boundary, make
no provider call even when an earlier route snapshot was valid.

## Expected decisions and failures

SPEC-028 media requires enforce mode; observe/legacy never provide an ungoverned
media fallback. Register `image_input` plus a positive
`maximum_image_input_tokens` bound for current-turn photos. Transcription is a
separate workload using the existing Groq family, approved OGG/MP3 formats and
bounded audio size/duration. Its `transcription_request` price is an operator
upper per-request estimate; only request/count and estimated-cost budget units
are supported. No token usage is invented. See [Telegram media](telegram-media.md).

- `budget_denied`, `no_eligible_route`, and coordination failures occur before
  provider I/O and do not change provider health.
- A later rate or concurrency denial releases the reservation.
- `io_started` means provider I/O may have occurred. If the worker crashes, the
  bounded recovery worker marks it `io_possible` and retains the conservative
  debit. Operators must not manually credit it merely because its lease aged.
- Missing, partial, or invalid usage is not zero. Hard enforcement retains the
  conservative reservation when actual usage cannot be trusted.
- Budget enablement is revisioned. A disabled resource revision stops that
  optional budget prospectively without deleting its history or window
  counters. A disabled deployment budget makes `enforce` fail closed because
  the mandatory deployment constraint is absent.
- Fallback occurs only in the published order and for a published closed
  reason. Every fallback repeats budget, rate, concurrency, authorization,
  health, data-eligibility, and safety checks.

## Incident checks

Inspect content-free aggregate summaries, worker recovery outcomes, route
decisions, usage-quality counts, estimate-quality counts, budget decisions,
and provider-health transitions. Never paste prompts, responses, memories,
credentials, provider bodies, provider request IDs, or subject/platform IDs
into logs, labels, tickets, or audit metadata.

If governance persistence or Redis coordination is unavailable, keep provider
I/O disabled until authority is restored. Draining or disabling a capability
blocks new calls; already-started calls may finish. Old binaries must not be
started after governed I/O because they bypass the admission boundary.

`JANUARY_PROVIDER_RESERVATION_LEASE_SECONDS` must remain greater than every
configured provider-call timeout. Configuration rejects a shorter lease so the
recovery worker cannot reclaim an active call. Inspect
`january_provider_attempts_total` and
`january_provider_attempt_duration_seconds` for bounded per-attempt results;
their labels never include model or resource identities.

## Rollback

Before governed activation, return to `legacy` and downgrade only after the
validator proves there are no governed attempts. After any governed I/O,
retain migration 0017 and disable provider-calling workers while rolling back
application behavior. The migration intentionally rejects destructive
downgrade once governed usage exists.

Production pricing, budget values, provider health thresholds, ledger
retention, backup purge, and rollout approval remain external operating-owner
decisions.
