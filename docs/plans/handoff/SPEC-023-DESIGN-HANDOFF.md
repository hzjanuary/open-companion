# SPEC-023 Design Handoff

## Status

APPROVED DESIGN

This is the System Architect's implementation-ready design handoff for
SPEC-023 (Production Observability, SLOs, Alerting, and Incident Operations).
The Product Owner approved the product specification at
`docs/product/specs/SPEC-023-production-observability-slos-alerting-and-incident-operations.md`.
This design phase creates this handoff only: no runtime code, migration,
validator, test, deployment manifest, ADR, runbook, or other document is
changed, and no commit or push is performed. The next engineer may implement
SPEC-023 from this document without reviewing the product specification.

## 1. Executive Summary

SPEC-023 turns the repository's existing content-free operational evidence into
an observable, Product-Owner-approved production commitment: an SLI catalog, SLO
targets with error budgets over a rolling 28-day window, a bounded and
content-safe alerting rule catalog, and a repeatable incident operations
lifecycle with metadata-only evidence. Nothing about the runtime needs to
change for the contract to be defined and proven. Every SLI and alert source
already exists: the `january_` metrics catalog and loopback exporter
(SPEC-015/018/019), the durable recovery classifications and `operations
inspect/show/replay` CLI (SPEC-016), the bounded `/health`, `/live`, and
`/ready` surfaces, the content-safe control-plane audit (SPEC-021), and the
live-acceptance evidence-bundle and ownership vocabulary (SPEC-022). The
implementation phase therefore adds declarative definitions, content-safe
artifacts, runbooks, drills, and proof — and no schema migration. CI never
claims production SLO compliance; evidence is computed only from the approved
environment's exported telemetry and durable state.

## 2. Repository Baseline

- Baseline HEAD: `private-source-checkpoint-omitted`.
- `origin/main` matches the baseline commit.
- SPEC-022 has been approved and committed; the worktree is clean of SPEC-022
  artifacts.
- The worktree currently contains the Product Owner's SPEC-023 changes:
  `M docs/product/SPEC.md`, `M docs/product/README.md`, and the new untracked
  `docs/product/specs/SPEC-023-production-observability-slos-alerting-and-incident-operations.md`.
- This design phase adds exactly one file: `docs/plans/handoff/SPEC-023-DESIGN-HANDOFF.md`.
- No commit or push is authorized in this phase.

## 3. Scope

The implementation phase, when approved, will produce:

- An SLI catalog (FR-01) where every SLI maps to an existing content-free
  measurement source and carries an unambiguous definition, validity rule, and
  unit.
- SLO targets and error-budget policy over a rolling 28-day window (FR-02),
  measured only from the approved environment.
- An alerting rule catalog (FR-03) — SLO burn-rate, recovery-risk, and
  readiness/dependency rules — with severity model (FR-06), detection-latency
  bounds, debounce, severity caps, acknowledgement expiry, and escalation.
- A content-safe alert and notification boundary (FR-04) and the approved
  channels and ownership roster.
- An incident operations lifecycle (FR-05, FR-07–FR-10): detection,
  acknowledgement, classification, response, communication, mitigation,
  resolution, and post-incident review, with metadata-only evidence consistent
  with SPEC-022 evidence bundles and SPEC-021 audit.
- Recovery integration through the existing SPEC-016 CLI (FR-11) and the
  readiness-versus-worker-backlog distinction (FR-12).
- Runbooks for each severity class and each required drill scenario, at least
  one content-safe drill per severity before production reliance, and
  reproducible SLO/error-budget computation from the exported catalog.

## 4. Out-of-Scope

- Runtime code changes to existing application, infrastructure, interface, or
  runtime surfaces; the API does not become a worker supervisor.
- Any schema migration; error-budget and incident state is represented in
  existing content-free tables or computed declaratively (see Migration
  Expectations).
- Dashboard UI (deferred to the SPEC-021 control-plane roadmap), cloud-provider
  selection, deployment manifests, and monitoring-backend integrations
  (SPEC-020 decisions remain external).
- Claiming achieved availability, latency, throughput, RPO, RTO, or cost before
  launch and hosting decisions are accepted; CI and synthetic validators never
  claim SLO compliance.
- Replacing SPEC-015 telemetry, SPEC-016 recovery/CLI, SPEC-020 deployment and
  recovery, SPEC-021 control-plane/audit, or SPEC-022 live acceptance.
- Autonomous remediation, auto-scaling, or any production mutation beyond the
  approved rollback authority.
- Billing or cost-optimization productization, multi-tenancy, Zalo, or new
  Telegram media/voice behavior.
- Weakening ambiguity, privacy, safety, rate-limit, or redaction rules; generic
  replay of ambiguous delivery; product content or credentials in alerts or
  incident records.

## 5. Existing Architecture Review

### Telemetry (SPEC-015/018/019)

- `backend/app/infrastructure/telemetry.py` is the authoritative catalog:
  `METRICS` defines 34 `january_` metrics (kind `counter` or `histogram`) with
  closed label sets, and `PROHIBITED_LABEL_NAMES` rejects `request_id`,
  `correlation_id`, `conversation_id`, `message_id`, `memory_id`, `username`,
  `text`, `prompt`, `memory`, `query`, `vector`, `url`, `token`, `secret`,
  `model`, `provider_request_id`, and similar content-bearing names. Recorders
  validate every increment/observe against the catalog and reject unknown
  metrics, prohibited labels, wrong label sets, and unbounded values.
- `InMemoryMetricsRecorder` is process-local (never global); `NoOpMetricsRecorder`
  is the disabled default. `MetricsHttpExporter` serves Prometheus text on a
  loopback-only socket.
- `backend/app/application/ports/telemetry.py` defines the `MetricsRecorder`
  protocol (`increment`/`observe`/`exposition`) used across application code.
- Middleware (`backend/app/interface/http/middleware.py`) records
  `january_http_requests_total` and `january_http_request_duration_seconds`
  with `route`/`method`/`status{1xx..5xx}` labels; the webhook route records
  `january_telegram_updates_total` with `outcome`/`transport`.
- SLI-relevant metrics: HTTP duration histogram (webhook ack latency, health
  latency), `january_telegram_updates_total` (ingress durability), provider
  metrics (`january_model_requests_total`,
  `january_model_request_duration_seconds`), rate-limit metrics
  (`january_rate_limit_events_total`), recovery metrics
  (`january_recovery_events_total`, `january_dead_letter_events_total`,
  `january_quarantine_events_total`, `january_provider_concurrency_events_total`),
  and worker metrics (`january_worker_operations_total`,
  `january_worker_operation_duration_seconds`).
- `docs/runbooks/observability.md` documents: recording and export are
  independent and disabled by default; export binds to `127.0.0.1:9464` (a
  distinct local port per runtime process); the catalog never contains content;
  and recovery/dead-letter/quarantine/capacity metrics are "alert-ready
  evidence for retry exhaustion, quarantine accumulation, and capacity
  saturation, not a production SLO claim."

### Configuration

- `backend/app/core/config.py`: `JANUARY_` env prefix; `environment` is a
  closed `local|test|staging|production` literal; `metrics_enabled` and
  `metrics_export_enabled` default false and export requires enabled
  (`model_validator`); `metrics_bind_host` is loopback-only
  (`127.0.0.1`/`::1`); `metrics_port` defaults 9464; `safe_configuration_fingerprint`
  exposes an allowlisted metadata subset without secret material.

### Health, readiness, and webhook surfaces

- `backend/app/interface/http/routes.py`: `/live` is process-only;
  `/health` and `/ready` check bounded required dependencies (PostgreSQL, and
  Redis when delivery/rate-limit/concurrency require it). `/ready` returns a
  dependency-unavailable error and a `request_id` when a required dependency
  fails; optional derived services with a documented fallback do not make the
  API unready. The webhook route validates the secret constant-time, bounds the
  body, durably accepts updates, and records outcome metrics.

### Recovery (SPEC-016)

- `backend/app/domain/recovery.py`: `RecoveryKind` (`planning`, `outbound`),
  `RecoveryDisposition` (`dead_letter`, `quarantine`), `RecoveryReason`
  (retry budget, lease expiry, dependency unavailable, provider retry
  exhausted, delivery rejection exhausted, invalid terminal plan, operator
  replay, ambiguous external delivery, invariant violation).
- `backend/app/infrastructure/database/recovery.py`
  (`SqlAlchemyRecoveryRepository`): `classify`, `summarize` (counts by
  kind/disposition plus per-kind state, oldest-pending age, active/stale lease
  counts), `show` (one item), and `replay` (one dead letter, rechecks durable
  state in its transaction, preserves identity and idempotency, no external
  I/O, refuses quarantined/completed/leased/`delivery_unknown`).
- `backend/app/runtime/operations.py`: the operator CLI —
  `inspect [--kind {planning,outbound}]`, `show <id>`, `replay --kind
  {planning,outbound} --id <uuid> --confirm` — emits JSON only, exit codes
  0/1/2.
- Tables `operational_recovery_items` (unique `(work_kind, work_id)`, index
  `(disposition, created_at)`, `replayed_at`) and `operational_recovery_events`
  (`event_type`, `actor`) are content-free by design.

### Control plane and evidence (SPEC-021/022)

- `backend/app/interface/http/control_plane/` adds the authenticated operator
  API with content-safe `control_audit_events` (action, outcome,
  resource_type/resource_id, request_id, metadata JSONB). Membership is
  correlated for incident owners but grants no Telegram group authority.
- `backend/app/runtime/acceptance_evidence.py` defines `FORBIDDEN_EVIDENCE_KEYS`
  and `assert_content_safe`; SPEC-022 evidence bundles use metadata only, with
  owners (operating owner, incident contact, rollback authority) and result
  classification. The rollback authority is the only role that may trigger
  production rollback or webhook disable/delete during an incident.

### Validation estate

- `scripts/validate.sh` (ruff, format, mypy, non-integration suite: 209
  passed, 41 deselected), `scripts/validate-observability.sh` (telemetry
  catalog presence + `SPEC-015 must not add a migration` guard + the
  observability/http/planning tests), `scripts/validate-live-acceptance.sh`
  (SPEC-022, 20 tests), and the DB-backed validators (ingress, safety, memory,
  commands, reliability) that run PostgreSQL/Redis via Docker with `alembic
  upgrade head`. The host requires the temporary uncommitted `label=disable`
  SELinux override for DB-backed Docker runs (default profile exits 139).

## 6. Required Architectural Changes

None to the runtime. The implementation phase adds declarative and
documentation surfaces only:

- A declarative SLI/SLO and error-budget definition (code/configuration, not a
  store) that references existing metrics, recovery state, and readiness
  signals by name.
- A content-safe alerting rule catalog (declarative) whose inputs are the
  exported `january_` catalog and durable recovery state.
- Incident operations artifacts: runbooks, severity model, ownership roster,
  evidence and post-incident-review templates, and drill plans.
- If alert evaluation must run in-process, it is a separate runtime surface
  that reads exported metrics and recovery state; it never runs inside the
  webhook acknowledgement path and never supervises workers.
- SLO/error-budget and incident state must be representable in existing
  content-free tables (`operational_recovery_items`/`operational_recovery_events`
  and `control_audit_events`) or computed on demand. No new canonical data
  store and no schema change are authorized.

Dependency direction stays
`domain <- application <- infrastructure <- interface <- runtime`; no
transaction or ordering lock spans external I/O; alerting and incident tooling
cannot mutate production beyond the approved rollback authority.

## 7. Data Flow

1. Runtime surfaces record bounded content-free measurements through the
   `MetricsRecorder` protocol into the process-local `InMemoryMetricsRecorder`.
2. The `MetricsHttpExporter` serves the Prometheus catalog on the loopback-only
   port (e.g., `127.0.0.1:9464`, one port per runtime process); an
   operator-owned scraper behind a SPEC-020 network boundary collects it.
3. Workers classify durable failures into `operational_recovery_items` with
   dispositions and reasons; the operator inspects and replays via
   `app.runtime.operations` (`inspect`/`show`/`replay --confirm`).
4. SLO/error-budget computation reads the exported catalog over the rolling
   28-day window in the approved environment; it reports a window as
   "unknown" (never zero) when metric or exporter data is missing.
5. Alert evaluation consumes exported metrics plus recovery and readiness
   state, applies debounce and severity caps, and emits content-free
   notifications through approved channels with acknowledgement expiry and
   escalation.
6. Incident detection records a metadata-only evidence bundle (SPEC-022
   conventions) and, for Sev1/Sev2, produces a post-incident review with
   timeline, root-cause class, error-budget impact, and corrective actions fed
   back into targets and runbooks.

## 8. Worker Responsibilities

- No new workers are required to satisfy the contract.
- Existing workers remain the measurement source: their `january_worker_*`
  operation metrics and the recovery classifications they write are the
  worker-health and backlog signals (FR-12).
- HTTP readiness (`/ready`) is the API dependency signal; worker backlog and
  stuck durable work alert through recovery and queue metrics, never through
  `/ready`. Optional derived services with documented fallback are signaled
  through their own worker metrics and do not make the API unready.
- If an alert evaluator is added as a process, it is a separate bounded runtime
  surface (reads exported metrics and recovery state), not a worker
  supervisor, and it never mutates production.

## 9. API Surface

- No new API endpoints are authorized by this specification.
- Existing `/`, `/health`, `/live`, `/ready`, the Telegram webhook route, and
  the `/control/*` plane remain unchanged; SPEC-022 webhook lifecycle and
  mode-exclusivity operations remain operator-invoked CLIs.
- The control plane's authenticated membership is the correlation basis for
  incident owners and audit references; it grants no Telegram group authority
  (SPEC-021/022).
- Dashboards remain on the SPEC-021 control-plane roadmap; this phase adds no
  UI.

## 10. Configuration Changes

The implementation phase adds configuration only through the existing
`Settings`/`JANUARY_` environment boundary, with secrets entering through the
SPEC-020 external secret boundary:

- SLO window and targets: rolling 28-day window (approved); webhook
  acknowledgement p95 < 500 ms; health p95 < 250 ms; non-LLM command p95 < 1 s;
  mention response p95 < 8 s when measurable end-to-end (approved targets).
- To-be-approved objectives (proposed defaults for owner decision):
  availability target for the accepted topology, delivery-confirmation target
  share, dead-letter/quarantine backlog cap, and maximum stale-lease age.
- Alerting: burn-rate rule windows and multi-burn ratios, detection-latency
  bounds per severity (e.g., Sev1 page within ~5 min of condition, Sev2 within
  ~15 min, Sev3 within ~24 h), debounce intervals, severity caps, ack expiry
  (e.g., Sev1 ack expiry 15 min) and escalation path, and notification-channel
  destinations approved by the operating owner.
- Drill and evidence flags for staged incident rehearsal using synthetic data.
- All values above that the specification leaves to the operating owner are
  defaults to be explicitly approved, not authoritative policy set by this
  handoff. The metrics exporter remains disabled by default and loopback-only.

## 11. Telemetry Changes

- The existing 34-metric catalog is unchanged and authoritative for SLIs.
  SLI mapping is by name:
  - Webhook ack latency: `january_http_request_duration_seconds`
    (route `/api/v1/platforms/telegram/webhook/{platform_connection_id}`).
  - Health/readiness latency: the same histogram on `/health`, `/ready`,
    `/live`.
  - Ingress ack durability: `january_telegram_updates_total`
    (accepted/duplicate by transport).
  - Delivery confirmation: delivery-certainty counts (SPEC-007/016) and
    `january_outbound_actions_total`.
  - Recovery backlog: `january_recovery_events_total`,
    `january_dead_letter_events_total`, `january_quarantine_events_total`, and
    `operations inspect` durable counts.
  - Provider error rate: `january_model_requests_total` / `january_model_request_duration_seconds`.
  - Rate-limit pressure: `january_rate_limit_events_total`.
  - Readiness degraded time: `/ready` dependency failures (503
    `dependency_unavailable` status class).
  - Worker health/backlog: `january_worker_operations_total`,
    `january_worker_operation_duration_seconds`, recovery state.
- If a needed alert input genuinely does not exist (for example an explicit
  alerting-staleness gauge), the implementation may add a closed content-free
  metric to the catalog following the same rules (declared in `METRICS`, closed
  low-cardinality labels, no prohibited names). Any such addition must be
  called out in review; the default is to reuse the existing catalog.
- SLO windows whose metric or exporter data is missing are reported unknown,
  never zero.

## 12. Security Considerations

- Alerting and incident-tooling credentials enter through the SPEC-020
  external secret boundary; they are never committed, baked into images,
  returned by APIs, or logged. No new secret class is introduced (SPEC-003/004
  webhook secrets unchanged, constant-time validation, explicit rotation).
- Least-privilege access to alerting, notification, and incident systems, with
  access review tied to control-plane membership.
- Notification channels are authenticated and access-reviewed; destinations
  are approved by the operating owner.
- Incident tooling cannot perform unapproved production mutations; rollback and
  webhook disable/delete remain gated to the SPEC-022 rollback authority.
- Every alert payload and evidence artifact passes a content-safety guard
  (reuse the `acceptance_evidence.assert_content_safe` discipline) before
  emission; leakage is rejected at a review gate before distribution.

## 13. Privacy Considerations

- Alerts, notifications, SLI/SLO artifacts, incident records, and review
  documents carry no message text, prompts, memories, vectors, provider
  bodies, raw platform IDs, usernames, or URLs (NFR-01/FR-04, SPEC-011).
- Staging alerting and incident drills use synthetic data; production content
  is never copied into alert payloads, incident records, or review documents.
- Incident-record retention is governed separately from product-content
  retention and stays consistent with SPEC-011 privacy and retention controls;
  alert payloads contain no personal data.
- Correlation in incident communication uses opaque incident and
  request/correlation IDs only (FR-08).

## 14. Failure Recovery

| Scenario | Required handling |
| --- | --- |
| Metric exporter or collection loss | Staleness alert fires; SLO measurement pauses and reports unknown, never zero. |
| Alert fatigue | Debounce, severity caps, rule review; no busy loops or unbounded retries. |
| Missed alert | Bounded detection latency; acknowledgement expiry; escalation to next owner; documented out-of-band escalation path. |
| Quarantine accumulation | Operator recovery only via `operations inspect/show/replay`; no blind replay; capacity alert. |
| Dead-letter saturation | Replay gate enforced by SPEC-016; backlog alert. |
| Provider outage | Degraded mention response; SLO burn alert; incident communication. |
| PostgreSQL or Redis loss | `/ready` degraded; incident; recovery per SPEC-020; restore PostgreSQL first. |
| Secret rotation during an incident | Old credentials fail closed; rotation uses the approved overlap window. |
| Alerting system down | Alerting's own loss/staleness is alertable; documented out-of-band escalation path used. |
| Content/credential leakage into evidence | Content-safety review gate rejects the artifact before distribution. |

## 15. Validation Strategy

- Existing validators remain authoritative and must pass unchanged:
  `scripts/validate.sh`, `scripts/validate-observability.sh`,
  `scripts/validate-live-acceptance.sh`, and the DB-backed
  `validate-ingress.sh`/`validate-safety.sh`/`validate-memory.sh`/
  `validate-commands.sh`/`validate-reliability.sh` suite.
- Implementation-phase proof (added only in an approved implementation phase)
  is executable and observable: reproducible SLO/error-budget computation from
  the content-free catalog over a synthetic window; content-safe rendered
  alert rules (guard rejects prohibited labels/keys); content-safe incident
  evidence; successful content-safe drills per severity; all existing
  validators passing; and a confirmation that no schema migration was added
  (mirroring the `validate-observability.sh` no-migration guard).
- No CI or synthetic run claims production SLO compliance (NFR-04).
- DB-backed runs on this host require the temporary uncommitted
  `label=disable` Docker SELinux override and isolated ports; this handoff adds
  no committed Compose change.

## 16. Runtime Proof Strategy

- Deterministic synthetic proof: exercise SLI definitions, SLO computation,
  and alert rendering against an `InMemoryMetricsRecorder` seeded with bounded
  synthetic series, and against durable recovery state from local
  PostgreSQL/Redis under the override. No live Telegram, provider, or external
  I/O is required.
- Content-safety proof: assert rendered alerts, evidence bundles, and
  post-incident-review artifacts contain no prohibited keys or
  credential-shaped strings (the `acceptance_evidence.assert_content_safe`
  pattern).
- Drill proof: staged drills with synthetic data per severity (alert loss,
  missed alert, quarantine accumulation, dead-letter saturation, provider
  outage, database/Redis loss, secret rotation during incident, rollback
  trigger, evidence review) before production reliance.
- Live production SLO evidence is never claimed here; it is measured only in
  the approved environment after hosting decisions are accepted.

## 17. Testing Strategy

- Unit tests: SLI definitions and validity rules; SLO/error-budget computation
  over synthetic histograms and the 28-day window (including unknown-window
  handling); alert rule rendering and content-safety rejection; severity
  classification; debounce, severity caps, ack expiry, and escalation logic;
  evidence-template guards.
- Integration tests (existing patterns, DB-backed under the override): recovery
  interplay — reading `operational_recovery_items`/`operations inspect`
  summaries as alert inputs and confirming `replay` refusal semantics remain
  unchanged (quarantine/completed/leased/`delivery_unknown`).
- Regression: existing non-integration and integration suites stay green; the
  three schema-pin integration tests continue to assert head
  `0014_authenticated_control_plane`.
- No migration and no runtime-behavior change are tested for.

## 18. Migration Expectations

No migration is authorized by SPEC-023. The implementation phase must first
audit whether the existing content-free tables represent required state:

- Error-budget state: computed from exported telemetry (no persistence
  required) or, if persisted, proven representable in existing tables.
- Incident state: representable in `operational_recovery_items`/
  `operational_recovery_events` (recovery classification, actor, replayed_at)
  and correlated through `control_audit_events` by opaque request/incident
  IDs.
- Alerting state: declarative configuration and `january_` counters; a
  staleness signal may use the catalog.
If audit finds existing tables insufficient, an additive migration may be
proposed only with a separate approval including retention, privacy, and
downgrade rationale before implementation. Alerting and incident state never
stores content or secrets.

## 19. Risks

| Risk | Mitigation |
| --- | --- |
| SLO targets exceed what the topology can deliver | Targets are approved commitments measured only after the operating environment exists. |
| Alert fatigue or missed alerts | Debounce, severity caps, detection-latency bounds, ack expiry, escalation, staleness alertable. |
| False readiness or false SLO compliance | Bounded readiness checks; SLO computed only from approved-environment telemetry; windows report unknown, never zero. |
| Content or credential leakage in alerts/evidence | Content-safety guard on every artifact and a review gate before distribution. |
| Ambiguous delivery handled as incident replay | `delivery_unknown` remains quarantine; SPEC-016 replay rules only. |
| Alerting tooling becomes a production mutation path | Least privilege, SPEC-022 rollback authority only, no unapproved mutation. |
| Incident evidence outlives its purpose | Separate retention governed consistently with SPEC-011. |
| Secret or channel compromise | External secret boundary, rotation, access review, authenticated channels. |
| Unbounded recovery backlog | Backlog thresholds, capacity alerts, operator replay. |
| Operating-owner defaults not ratified | Values left to the operating owner are recorded as proposed defaults requiring explicit approval before production. |

## 20. External Dependencies

- Product Owner and operating-owner approval of SLO targets, error-budget
  policy, severity model, ownership roster, notification channels, and ack
  SLA.
- Approved hosting/orchestration target and monitoring, alerting, and
  notification backends (SPEC-020 decisions).
- Content-safe notification channels and an approved incident roster and
  escalation path.
- Access review for alerting, notification, and incident tooling; retention
  and access policy for incident records.
- A drill environment with synthetic data.
- Staging Telegram resources for live drills remain externally gated (the
  SPEC-022 live-acceptance blocker); drills that need live Telegram are
  deferred, not redesigned.

## 21. Deliverables

- This design handoff.
- In the approved implementation phase: an SLI/SLO and error-budget policy
  document; a content-safe alert rule catalog; a severity and incident runbook;
  incident-evidence and post-incident-review templates; the required ADRs
  (e.g., the SLO computation and alert-evaluation model, and any metric
  additions); and executable/observable proof (reproducible SLO computation,
  content-safe rendered alerts and evidence, drills, existing validators
  passing, no migration).
- This design phase creates none of the implementation-phase artifacts.

## 22. Implementation Order

1. Audit existing telemetry, recovery, and audit tables for SLI/SLO and
   incident-state representability (Migration Expectations).
2. Define the SLI catalog and SLO/error-budget policy, mapping every SLI to an
   existing measurement source.
3. Build the alerting rule catalog: severity model, detection-latency bounds,
   debounce, severity caps, ack expiry, escalation, and staleness alerting.
4. Define the content-safe notification boundary and obtain channel/roster
   approval.
5. Build the incident lifecycle, roles, communication, evidence templates, and
   post-incident review.
6. Author runbooks for each severity class and drill scenario; run synthetic
   drills per severity.
7. Add implementation-phase proof and validators; keep every existing validator
   green; confirm no migration.
8. Record ADRs for any material decision (SLO computation and alert-evaluation
   model, metric additions) and obtain Product Owner and operating-owner
   approval.

## 23. Files Expected To Change

Files listed for the future implementation phase (not changed by this design
phase):

- `docs/product/specs/SPEC-023-production-observability-slos-alerting-and-incident-operations.md` (existing, already approved).
- New: `docs/plans/handoff/SPEC-023-DESIGN-HANDOFF.md` (this file).
- New (implementation phase): SLI/SLO and error-budget policy document (e.g.,
  `docs/runbooks/slos-alerting.md`); alert rule catalog; incident-operations
  runbook (`docs/runbooks/incident-operations.md`); evidence and
  post-incident-review templates; optional declarative alert-evaluation module
  under `backend/app/` following the dependency direction; corresponding unit
  tests under `backend/tests/`; a validator script following the existing
  `scripts/validate-*.sh` conventions; ADRs under `docs/decisions/`.
- `docs/product/SPEC.md` and `docs/product/README.md`: one SPEC-023 status/roadmap
  reference line each at implementation completion.
- No `backend/alembic/versions/*` file may be added.

## 24. Known Blockers

- Live Telegram acceptance for SPEC-022 remains externally gated (no approved
  staging bot, token, public HTTPS URL, or test group); live drills and
  production SLO measurement inherit that blocker.
- Hosting/orchestration and monitoring/alerting/notification backends are not
  selected (SPEC-020); SLO evidence is only measured after those decisions.
- The host Docker default SELinux profile terminates containers with code 139;
  DB-backed validation uses the temporary uncommitted `label=disable` override
  and isolated ports.
- SPEC-014 remains deferred behind its Zalo prerequisite; it does not block
  observability.

## 25. Next Engineering Task

Get Product Owner and operating-owner approval of the SLI/SLO targets,
error-budget policy, severity model, alert rule catalog, and ownership roster,
then implement the declarative SLI/SLO and alert rule catalog, incident
operations artifacts, runbooks, drills, and proof per this handoff, keeping all
existing validators green and adding no schema migration. Do not start SPEC-024
from this handoff.
