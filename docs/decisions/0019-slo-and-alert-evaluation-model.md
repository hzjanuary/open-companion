# 0019 SLO Computation and Alert-Evaluation Model

## Status

Accepted for SPEC-023 implementation.

## Context

SPEC-023 requires approved SLO targets with error budgets over a rolling
28-day window, content-safe alerting rules with bounded detection latency,
debounce, severity caps, acknowledgement expiry, and escalation, and
executable proof. The existing 34-metric `january_` catalog is content-free
and authoritative; the metrics exporter is loopback-only and disabled by
default. No new canonical data store and no schema migration are authorized.

## Decision

SPEC-023 adds a declarative, application-layer module
`backend/app/application/observability` that defines:

- A closed SLI catalog mapped by name to existing metrics and durable recovery
  state, each with a definition, validity rule, and unit.
- SLO targets as code: four Product-Owner-approved latency p95 objectives, and
  availability/delivery-confirmation/backlog objectives recorded as proposed
  operating-owner defaults that are never claimed as approved policy.
- Error-budget and burn-rate computation (`evaluate_latency`,
  `evaluate_good_ratio`, `evaluate_backlog`) that reports windows with
  insufficient or missing data as `unknown`, never as zero budget remaining.
- A declarative alert rule catalog and a pure `evaluate_alerts` computation
  with debounce, severity caps, acknowledgement expiry, and escalation, plus a
  content-safety guard on every rendered payload.

Latency percentiles are computed from the local observation series
(nearest-rank). The exported Prometheus text today emits `_count`/`_sum` only,
so p95 must be derived from raw observations in-process or from bucket
exposition in an operator-owned monitoring backend; this module proves the
computation deterministically against the recorder's observation series and
never claims production compliance (NFR-04).

Alert evaluation is a separate bounded runtime surface that reads exported
metrics and durable recovery state. It never runs inside the webhook
acknowledgement path and never supervises workers. Incident and alerting
tooling cannot mutate production beyond the approved rollback authority.

## Alternatives considered

1. Persisting error-budget state in a new store: rejected because no new
   canonical data store is authorized; budget is computed on demand.
2. Turning the API into a worker supervisor or running evaluation in the
   webhook path: rejected by the architecture constraints.
3. Adding a new metric for staleness: rejected; the catalog already signals
   exporter staleness through exporter last-seen age, and the alerting
   staleness rule consumes that signal.
4. Claiming production SLO compliance in CI: rejected by NFR-04.

## Consequences

- The 34-metric catalog remains unchanged and authoritative; no metric is
  added.
- SLO and alert computation are reproducible from the exported catalog and
  durable state via `./scripts/validate-observability.sh`.
- Recovery-backlog alert inputs consume the `operations inspect` summary
  shape, so the durable recovery repository and replay semantics stay
  unchanged.
- Latency p95 in production depends on the operator-owned monitoring backend's
  histogram handling, which remains an external SPEC-020 decision.

## Follow-up

Operating-owner approval of the proposed objectives (availability,
delivery-confirmation, backlog caps) before production reliance; approval of
notification channels and the ownership roster.
