# 0023 Provider Governance Attempt and Reservation Boundary

## Status

Accepted for the Product Owner-authorized SPEC-026 implementation candidate.

## Context

Provider selection, usage quality, operational estimates, retries, and budgets
must cover response planning, summaries, and embeddings without moving policy
into provider adapters or weakening the existing rate, concurrency, safety, and
privacy boundaries. Missing provider usage cannot be treated as zero, and a
crash after external I/O cannot safely refund a budget reservation.

## Decision

PostgreSQL is authoritative for immutable capability, route, health, price, and
budget revisions and for one content-free attempt ledger. Every provider call
uses a durable boundary:

1. resolve and snapshot the versioned route;
2. atomically create the attempt and reserve every applicable hard budget;
3. commit, then apply the existing Redis rate and provider-concurrency gates;
4. durably transition `reserved` to `io_started` before adapter I/O;
5. perform external I/O without a database session or lock; and
6. durably classify usage and reconcile or conservatively retain reservations.

Attempt keys fence ordinary replay, but no exactly-once provider-call claim is
made. Expired `reserved` work is released as proven no-I/O; expired
`io_started` work becomes `io_possible` and consumes the conservative bound.
Chat generation and embedding use separate registry entries, routes, prices,
usage classes, and budgets. Redis rate limiting and provider concurrency remain
independent mandatory gates.

Budget enablement is immutable revision data. Disabling an optional resource
budget is prospective and preserves its history; disabling the deployment
budget makes enforced provider admission unavailable. The reservation lease is
configuration-validated to exceed provider-call timeouts so recovery cannot
classify active I/O as abandoned.

Operational costs use integer microusd and operator-supplied price revisions.
They are estimates, never billing truth. Missing, partial, invalid, and
ambiguous provider usage remain explicit and nullable. Content, credentials,
raw platform identities, and resource IDs are prohibited from metric labels.

Deployment administration uses the existing live `deployment_operator`
authority. Assistant and PlatformConnection administration requires the exact
SPEC-021 tenant binding and owner/admin roles; auditors are read-only and
operators/viewers are denied absent a future explicit grant model.

## Consequences

- Migration `0017_provider_routing_cost_budgets` is additive after 0016 and
  backfills legacy generation attempts without zero-filling usage.
- Governed activation is explicit: `legacy` is the default, `observe` records
  without hard denial, and `enforce` fails closed on missing route, registry,
  deployment budget, required price/bound, or coordination authority.
- A downgrade is rejected once governed attempts exist because external usage
  cannot be undone by schema rollback.
- Production prices, budget amounts, health thresholds, retention, and rollout
  remain operating-owner decisions.

## Alternatives considered

- Adapter-local counters were rejected because retries and cross-worker races
  require one durable authority.
- Redis-only budgets were rejected because expiry cannot distinguish no-I/O
  from possible provider cost.
- Fallback outside the admission gateway was rejected because it could bypass
  authorization, data eligibility, budgets, rates, or concurrency.
