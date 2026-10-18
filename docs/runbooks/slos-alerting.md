# SLI Catalog, SLO Targets, and Error-Budget Policy

Authoritative for SPEC-023. Defines the closed SLI catalog, the approved SLO
targets, the proposed operating-owner objectives, and how error budgets are
computed over the rolling 28-day window. The declarative definition lives in
`backend/app/application/observability/`; this document is the policy.

## SLI catalog (FR-01)

The SLI catalog is a closed set. Every SLI maps to an existing content-free
measurement source and carries an unambiguous definition, a validity rule, and
a unit. No SLI adds a measurement source; the 34-metric `january_` catalog
(SPEC-015/018/019) stays authoritative.

| SLI | Definition | Source | Unit |
| --- | --- | --- | --- |
| `webhook_ack_latency` | Time to acknowledged durable ingress for valid updates | `january_http_request_duration_seconds` on the webhook route template | seconds |
| `health_readiness_latency` | Time to `/live`, `/health`, `/ready` response | `january_http_request_duration_seconds` on those routes | seconds |
| `mention_response_latency` | End-to-end addressed response time when measured; otherwise component histograms, not asserted cross-process | persisted end-to-end timestamp when available; otherwise `january_worker_operation_duration_seconds` | seconds |
| `command_response_latency` | Non-LLM command completion time | `january_worker_operation_duration_seconds` (runtime=commands) | seconds |
| `ingress_ack_durability` | Share of valid updates acknowledged after durable commit | `january_telegram_updates_total` (accepted/duplicate by transport) and durable ingress status counts | fraction |
| `delivery_confirmation_rate` | Share of outbound actions reaching confirmed delivery | delivery-certainty counts (SPEC-007/016) and `january_outbound_actions_total` | fraction |
| `recovery_backlog` | Dead-letter and quarantine accumulation and stale durable leases | `january_recovery_events_total`, `january_dead_letter_events_total`, `january_quarantine_events_total`, and `operations inspect` durable counts | count |
| `provider_error_rate` | Provider request failures and timeouts as a share of provider requests | `january_model_requests_total`, `january_model_request_duration_seconds` | fraction |
| `rate_limit_pressure` | Rate-limit events and retry-after pressure | `january_rate_limit_events_total` | count |
| `readiness_degraded_time` | Time `/ready` reported dependency failure | `/ready` `dependency_unavailable` 503 status class through the HTTP duration histogram | seconds |

Validity rules: latency SLIs require at least 30 finite, nonnegative
observations in the window; rate and backlog SLIs require nonnegative counts.
A window that does not meet its validity rule reports `unknown`, never a zero
budget or a zero error rate.

SLIs use closed low-cardinality outcome labels only. Raw platform IDs, request
or correlation IDs, usernames, URLs, and provider/model identifiers never
become labels or exposition values.

## SLO targets (FR-02)

Approved latency targets (Product Owner):

| SLI | Objective | Window |
| --- | --- | --- |
| Webhook acknowledgement | p95 < 500 ms | rolling 28 days |
| Health check | p95 < 250 ms | rolling 28 days |
| Non-LLM command response | p95 < 1 s | rolling 28 days |
| Mention response | p95 < 8 s when measurable end-to-end | rolling 28 days |

Proposed operating-owner objectives — recorded as defaults, not approved
policy. They require explicit operating-owner approval before production
reliance:

| Objective | Proposed default | Window |
| --- | --- | --- |
| Availability for the accepted topology | 99.9% good ratio | rolling 28 days |
| Delivery-confirmation share | 99% confirmed | rolling 28 days |
| Dead-letter backlog cap | 50 items | rolling 28 days |
| Quarantine backlog cap | 50 items | rolling 28 days |
| Stale-lease count cap | 5 leases | rolling 28 days |
| Oldest-pending work age cap | 15 minutes | rolling 28 days |

Representability finding: the durable recovery catalog exposes
`stale_lease_count` and `oldest_pending_age_seconds` (from `operations
inspect`), but not a per-lease stale-lease age. The backlog objective therefore
uses those two measurable signals as the stale-lease and worker-backlog
proxies; a per-lease stale-age field is not added because no schema migration
is authorized (SPEC-023 Migration expectation).

## Error-budget policy

- Budget base for a latency objective: `1 - percentile` of the window's events
  (5% for a p95 SLO). For a good-ratio objective: `1 - good_ratio`.
- The window is a rolling 28 days in the approved environment.
- Bad events are observations above the bound (latency) or non-good outcomes
  (good-ratio).
- `burn_rate = bad_ratio / (1 - objective)`.
- SLO compliance is measured only from the approved environment's exported
  telemetry and durable state. CI and synthetic validation never claim
  production SLO compliance (NFR-04).
- A window with missing metric or exporter data is reported `unknown`, never
  zero budget remaining.
- Error-budget exhaustion triggers the alerting policy (see `alerting.md`);
  it never triggers autonomous action.

## Reproducible computation

`backend/app/application/observability` computes SLOs deterministically:

- `evaluate_latency(observations, objective)` computes the p95 (nearest-rank),
  bad ratio, burn rate, and budget remaining; `unknown` when the window lacks
  enough valid observations.
- `evaluate_good_ratio(good_count, bad_count, objective)` for availability and
  delivery-confirmation objectives.
- `evaluate_backlog(recovery_summary, objective)` consumes the `operations
  inspect` summary shape (recovery counts plus planning/outbound work
  summaries) and reports breach against the caps.

Every result is reproducible from the exported metrics catalog and durable
state. `./scripts/validate-observability.sh` runs a deterministic synthetic
proof of these computations.
