# Content-Safe Alert Rule Catalog

Authoritative for SPEC-023 FR-03, FR-04, FR-06, FR-12 and NFR-02/03. The
declarative catalog lives in `backend/app/application/observability/alerts.py`;
this document is the operator-facing policy.

## Severity model (FR-06)

| Severity | Meaning | Response |
| --- | --- | --- |
| Sev1 | User-visible production degradation, availability loss, or confirmed content/credential exposure risk | Page immediately |
| Sev2 | Sustained SLO burn, error-budget exhaustion, or accumulating recovery backlog | Page or attend within the approved window |
| Sev3 | Investigate within the approved window; no immediate user impact | No page |
| Sev4 | Track and remediate without paging | No page |

## Detection latency, debounce, and severity caps (NFR-03)

- Detection-latency bounds per severity: Sev1 within ~5 minutes of the
  condition, Sev2 within ~15 minutes, Sev3 within ~24 hours. Every rule
  declares `detection_latency_seconds`.
- Debounce: a rule does not re-alert within its debounce interval unless the
  condition worsens (severity increases).
- Severity caps: no rule produces a verdict more severe than its
  `severity_cap`. Recovery-risk and staleness rules are capped at Sev2;
  readiness dependency is capped at Sev1.
- No rule creates a busy loop or unbounded retry; evaluation is idempotent
  computation over bounded inputs.

## Rule catalog (FR-03)

Burn-rate rules use the standard multi-window thresholds: fast burn
`>= 14.4x` the error budget, slow burn `>= 6x`, base burn `>= 1x` (SLO
breach).

| Rule | Class | Condition | Severity | Cap | Detection |
| --- | --- | --- | --- | --- | --- |
| `burn_mention_response` | burn_rate | mention SLO burn >= 14.4x / 6x / 1x | Sev1 / Sev2 / Sev3 | Sev1 | 5 min |
| `burn_webhook_ack` | burn_rate | webhook ack SLO burn >= 14.4x / 6x / 1x | Sev2 / Sev2 / Sev3 | Sev2 | 15 min |
| `burn_health_readiness` | burn_rate | health/readiness SLO burn >= 14.4x / 6x / 1x | Sev3 / Sev3 / Sev4 | Sev3 | 24 h |
| `burn_command_response` | burn_rate | command SLO burn >= 14.4x / 6x / 1x | Sev3 / Sev3 / Sev4 | Sev3 | 24 h |
| `recovery_dead_letter_backlog` | recovery_risk | dead-letter backlog > 50 | Sev2 | Sev2 | 15 min |
| `recovery_quarantine_accumulation` | recovery_risk | quarantine backlog > 50 | Sev2 | Sev2 | 15 min |
| `recovery_stale_leases` | recovery_risk | stale leases > 5 | Sev2 | Sev2 | 15 min |
| `worker_backlog_oldest_pending` | recovery_risk | oldest pending work > 15 min | Sev3 | Sev3 | 24 h |
| `readiness_dependency` | readiness | `/ready` reports a bounded required dependency unavailable | Sev1 | Sev1 | 5 min |
| `readiness_recovery` | readiness | `/ready` recovered after degradation | Sev4 | Sev4 | 5 min |
| `alerting_staleness` | staleness | metrics exporter/collection stale or lost | Sev2 | Sev2 | 15 min |
| `safety_fail_closed_surge` | safety_risk | fail-closed stricter defaults in burst window >= 3 | Sev2 | Sev2 | 15 min |
| `safety_protective_actions_surge` | safety_risk | protective enforcement actions in burst window >= 5 | Sev2 | Sev2 | 15 min |
| `safety_review_queue_growth` | safety_risk | open review items >= 20 or oldest open item > 4 h | Sev3 | Sev3 | 1 h |
| `safety_escalation_high_severity` | safety_risk | high-severity safety signals in burst window >= 3 | Sev1 | Sev1 | 15 min |

Readiness versus worker backlog (FR-12): API readiness degradation alerts only
on `/ready` dependency failures (`readiness_dependency`); worker backlog and
stuck durable work alert through recovery and worker metrics
(`recovery_*`, `worker_backlog_oldest_pending`), never through `/ready`.
Optional derived services with a documented safe fallback do not make the API
unready and are signaled through their own worker metrics.

Safety escalation (SPEC-024 FR-11): the `safety_*` rules evaluate content-free
aggregates over the fail-closed burst window and review queue depth. They page
the operating owner on sustained fail-closed or high-severity surges and keep
review-queue growth at Sev3. All safety rule payloads carry counts and ages
only; they never reference participants, messages, prompts, memories, or raw
platform identifiers.

## Acknowledgement expiry and escalation (FR-03)

- Sev1 ack expiry 15 minutes; Sev2 1 hour; Sev3 24 hours; Sev4 none.
- Escalation order: operating owner -> incident contact -> rollback authority.
  A stale acknowledgement escalates to the next owner at each expiry step.
- The alerting system's own loss or staleness is itself alertable
  (`alerting_staleness`).

## Notification boundary (FR-04, NFR-01)

Alert payloads and notifications carry only content-free fields: rule name,
severity, alert state, timestamp, opaque metric values, and the approved owner
or escalation target. They never contain message text, prompts, memories,
vectors, provider bodies, tokens, webhook secrets, authorization headers, raw
platform IDs, usernames, or URLs.

- Every payload passes the content-safety guard
  (`app.application.observability.content_safety.assert_content_safe`) before
  emission; the runtime acceptance-evidence gate applies the same discipline
  to evidence bundles.
- Notification channels and destinations are approved by the operating owner
  and are authenticated and access-reviewed (NFR-05).
- Alerting and incident-tooling credentials enter through the SPEC-020
  external secret boundary; they are never committed, baked into images,
  returned by APIs, or logged.

## Evaluation

`evaluate_alerts(inputs, now)` computes verdicts from exported metric series,
durable recovery state, readiness, and exporter staleness. `DebounceGate`
suppresses repeats; `escalate_verdict` applies acknowledgement expiry.
`render_alert_payload` renders a content-safe payload. The module never runs
inside the webhook acknowledgement path and never supervises workers.
