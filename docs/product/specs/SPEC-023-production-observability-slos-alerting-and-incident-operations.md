# SPEC-023 Production Observability, SLOs, Alerting, and Incident Operations

## Status

Product specification for review. This document authorizes product and
acceptance design only. It authorizes no runtime implementation, migration,
validator, test, deployment manifest, commit, or push until a separate
implementation phase is explicitly approved.

SPEC-001 through SPEC-022 are complete. SPEC-022 has been approved and
committed; its live Telegram acceptance remains an externally gated operational
step, not a product-policy change. SPEC-014 remains deferred behind its Zalo
prerequisite and no Zalo runtime is authorized.

## Objective

Define the product-level production observability commitment for January
Telegram: approved service-level indicators (SLIs) and service-level objectives
(SLOs) with error budgets, bounded and content-safe alerting rules, and a
repeatable, owner-approved incident operations lifecycle with metadata-only
evidence. The objective is a single authoritative, Product-Owner-approved
operations contract that converts the existing content-free `january_`
telemetry, recovery classifications, readiness signals, and live-acceptance
evidence into measurable production objectives and a disciplined response to
violations.

## Background

SPEC-015 established the content-safe `january_` metrics catalog and a
loopback-only, disabled-by-default Prometheus-compatible exporter with
component-boundary histograms. SPEC-016 classified durable work as replayable
dead letter or quarantine, made `delivery_unknown` always quarantine, and added
the operator `operations inspect/show/replay` CLI. SPEC-018 and SPEC-019 added
summary and semantic-memory metrics. SPEC-016 explicitly described its
recovery, dead-letter, quarantine, and capacity metrics as alert-ready evidence
rather than a production SLO claim. SPEC-020 deferred any availability,
throughput, RPO, RTO, or cost claim until launch and hosting decisions were
accepted, and defined production deployment, secrets, migrations, rollback,
recovery, readiness, and incident-operation boundaries. SPEC-021 added the
authenticated operator control plane with content-safe audit and a roadmap for a
future dashboard and operator CLI. SPEC-022 defined live-acceptance evidence
bundles, production acceptance criteria, and the operating owner, incident
contact, and rollback authority roles.

The remaining product gap is the production observability contract itself:
explicit SLIs and SLOs with error budgets, alerting rules derived from the
existing telemetry, and an incident operations lifecycle whose records are as
content-safe as the metrics that feed it. This specification turns the existing
alert-ready evidence and operational discipline into an observable,
owner-approved production commitment without new product data stores or schema
changes.

## Product scope

In scope are:

- An SLI catalog derived from existing `january_` metrics, durable recovery
  state, readiness signals, and live-acceptance evidence conventions.
- Product-owned SLO targets and error-budget policy for approved measurement
  windows.
- An alerting rule catalog mapped to SLO burn and recovery risk, with severity,
  detection latency, acknowledgement, escalation, and expiry.
- A content-safe alert and notification boundary.
- An incident operations lifecycle: detection, acknowledgement, severity
  classification, roles and authority, response, communication, mitigation,
  resolution, review, and remediation.
- A metadata-only incident evidence convention consistent with SPEC-022 evidence
  bundles and SPEC-021 audit.
- Readiness, recovery, and dependency-degradation alerting that distinguishes
  worker backlog from HTTP readiness.

Existing product behavior remains authoritative:

- PostgreSQL remains canonical for durable product and work state; Redis is
  at-least-once coordination; Qdrant remains rebuildable derived state.
- `delivery_unknown` is always quarantine; ambiguous delivery is never blindly
  replayed.
- Metrics, logs, traces, health, queues, alert payloads, and incident records
  contain no raw messages, prompts, provider bodies, memories, vectors, bot
  tokens, webhook secrets, or authorization headers.
- `/live` remains process-only; `/ready` checks bounded required dependencies
  and schema; optional derived services do not automatically make the API
  unready when documented fallback exists.
- Control-plane membership does not grant Telegram group authority.

## Explicit non-goals

- Runtime code, migrations, validators, tests, deployment manifests, cloud
  integrations, or dashboards in this design phase.
- Claiming achieved availability, latency, throughput, RPO, RTO, or cost before
  launch and hosting decisions are accepted; the targets in this specification
  are commitments for a future implementation phase to measure and prove.
- Replacing SPEC-015 telemetry, SPEC-016 recovery and operations CLI, SPEC-020
  deployment and recovery, SPEC-021 control-plane and audit, or SPEC-022 live
  acceptance and evidence.
- Autonomous incident remediation, auto-scaling, or any production mutation
  without the approved rollback authority.
- A second source of truth, a new product data store, or turning the API into a
  hidden worker supervisor.
- Billing, cost-optimization productization, provider routing, multi-tenancy,
  Zalo, or new Telegram media/voice behavior.
- Weakening ambiguity, privacy, safety, rate-limit, or redaction rules to
  simplify monitoring.
- Generic replay of ambiguous Telegram delivery as an incident fix.
- Including product content or credentials in alert payloads or incident
  records.

## Functional requirements

### FR-01: SLI catalog

The product defines a closed set of SLIs, each with an unambiguous definition, a
measurement source drawn from existing content-free telemetry or durable
recovery state, a validity rule, and a unit:

| SLI | Definition | Source |
| --- | --- | --- |
| Webhook acknowledgement latency | Time to acknowledged durable ingress for valid updates | Existing HTTP/webhook duration histogram |
| Health/readiness latency | Time to `/live`, `/health`, `/ready` response | Existing HTTP duration histogram |
| Mention response latency | End-to-end addressed response time when measured | Persisted end-to-end timestamp when available; otherwise component histograms, not asserted cross-process |
| Non-LLM command response latency | Command completion time | Component histograms |
| Ingress acknowledgement durability | Share of valid updates acknowledged after durable commit | Durable ingress status counts |
| Delivery confirmation rate | Share of outbound actions reaching confirmed delivery | Delivery-certainty counts |
| Recovery backlog | Dead-letter and quarantine accumulation | SPEC-016 recovery metrics and durable recovery state |
| Provider error rate | Provider request failures and timeouts as a share of provider requests | Provider metrics |
| Rate-limit pressure | Rate-limit events and retry-after pressure | Rate-limit metrics |
| Readiness degraded time | Time `/ready` reported dependency failure | Readiness signals |

SLIs use closed low-cardinality outcome labels only. Raw platform IDs, request
or correlation IDs, usernames, URLs, and provider/model identifiers never become
labels or exposition values.

### FR-02: SLOs and error budgets

The Product Owner approves SLO targets and a measurement window (a rolling
28-day window for error-budget calculation) for each SLI:

- Latency objectives: valid webhook acknowledgement p95 under 500 ms; health
  check p95 under 250 ms; non-LLM command response p95 under 1 second; mention
  response p95 under 8 seconds when measurable end-to-end.
- Availability objective: an approved availability target for the accepted
  topology once the operating environment is defined.
- Delivery confirmation objective: an approved target share of outbound actions
  with confirmed delivery.
- Recovery objective: an approved cap on dead-letter and quarantine backlog and
  an approved maximum stale-lease age.

SLO compliance is measured only from the approved environment and is never
claimed by CI or synthetic validation. Error-budget exhaustion triggers the
policy in FR-03 rather than autonomous action.

### FR-03: Alerting rules

Alerting rules are derived from SLIs and recovery risk and are content-safe:

- Each SLO has a burn-rate rule that alerts within a bounded detection latency
  of the violation condition.
- Recovery-risk rules alert on dead-letter, quarantine, and stale-lease
  accumulation thresholds derived from SPEC-016 metrics.
- Readiness and dependency rules alert on `/ready` degradation and on recovery
  after degradation.
- Rules debounce single noisy events, enforce severity caps, and must not
  create busy loops or unbounded retries.
- Alert acknowledgement carries an expiry; stale acknowledgements escalate to
  the next owner.
- The alerting system's own loss or staleness is itself alertable.

### FR-04: Alert notification boundary

Alert payloads and notifications contain only content-free fields: rule name,
severity, alert state, timestamp, opaque metric values, and the approved owner
or escalation target. They never contain message text, prompts, memories,
vectors, provider bodies, tokens, webhook secrets, authorization headers, raw
platform IDs, usernames, or URLs. Notification channels and destinations are
approved by the operating owner.

### FR-05: Incident lifecycle

An incident follows a defined lifecycle with an owner and content-safe record
at every phase:

1. Detection by alert or operator observation.
2. Acknowledgement within the approved SLA and severity-appropriate window.
3. Classification by severity and affected surface.
4. Response by the approved operator and incident contact, with rollback
   authority available.
5. Communication on approved content-safe channels at a bounded status
   frequency.
6. Mitigation without unapproved production mutation; rollback only through the
   approved authority.
7. Resolution and verification of recovery.
8. Post-incident review with timeline, cause, remediation, and error-budget
   impact.

### FR-06: Severity classification

- Sev1: user-visible production degradation, availability loss, or confirmed
  content/credential exposure risk; page immediately.
- Sev2: sustained SLO burn, error-budget exhaustion, or accumulating recovery
  backlog; page or attend within the approved window.
- Sev3: investigate within the approved window; no immediate user impact.
- Sev4: track and remediate without paging.

### FR-07: Roles and authority

Each environment defines an operating owner, an incident contact, and a
rollback authority, reusing the SPEC-022 ownership vocabulary. The rollback
authority is the only role permitted to trigger production rollback or
disable/delete the Telegram webhook during an incident. Roles are recorded in
content-free incident records and correlated with SPEC-021 control-plane
membership without granting Telegram group authority.

### FR-08: Incident communication

Status updates occur on approved content-safe channels at a bounded frequency.
Updates correlate incidents through opaque incident and request/correlation IDs
and never carry product content or credentials.

### FR-09: Incident evidence

Each incident produces a metadata-only evidence record consistent with the
SPEC-022 evidence-bundle conventions: environment, severity, timeline, owners,
opaque identifiers, metric values, result classifications, recovery outcomes,
and remediation state. It contains no message content, prompts, memories,
vectors, provider bodies, or credentials.

### FR-10: Post-incident review and remediation

Every incident of Sev1 or Sev2 severity produces a review with an observed
timeline, root-cause classification, error-budget impact, corrective actions,
and remediation ownership. Remediation is tracked to closure and fed back into
SLO targets, alert thresholds, and runbooks.

### FR-11: Recovery integration

Incidents use the SPEC-016 `operations inspect/show/replay` CLI for
dead-letter and quarantine handling. Replay handles one dead letter, rechecks
durable state in its transaction, preserves business identity and idempotency,
and never performs external I/O. Quarantined, completed, and leased work is
refused. Ambiguous delivery remains operator-owned.

### FR-12: Readiness and worker-backlog distinction

Alerting distinguishes HTTP readiness from worker health and backlog. API
readiness degradation alerts on `/ready` dependency failures; worker backlog
and stuck durable work alert through recovery and queue metrics. Optional
derived services that have a documented safe fallback do not make the API
unready and are signaled through their own worker metrics.

## Non-functional requirements

### NFR-01: Content safety

Alert payloads, notification bodies, incident records, review documents, and
metric exposition contain no product content, prompts, memories, vectors,
provider bodies, credentials, raw platform IDs, usernames, or URLs. The same
content-safety guard discipline as SPEC-022 evidence bundles applies to every
alert and incident artifact.

### NFR-02: Low cardinality

All alerting and SLI labels are closed outcome categories only, consistent with
SPEC-015 and SPEC-016 conventions. No unbounded label values are introduced.

### NFR-03: Reliability of alerting

Alerting and notification failures are themselves observable and alertable.
Rules debounce and cap severity; no rule produces a busy loop or unbounded
retry. Detection latency bounds are defined per severity.

### NFR-04: No false confidence

CI and synthetic validators never claim production SLO compliance. SLO evidence
is computed only from the approved environment's exported telemetry and durable
state.

### NFR-05: Security

Alerting and incident-tooling credentials enter through the SPEC-020 external
secret boundary, are never committed or baked into images, use least privilege,
and are covered by rotation and access review. Notification channels are
authenticated and access-reviewed.

### NFR-06: Compatibility

Existing telemetry, recovery, ambiguity, privacy, safety, rate-limit,
control-plane, and delivery-certainty behavior remains unchanged.

## Architecture constraints

- The dependency direction remains unchanged:
  `domain <- application <- infrastructure <- interface <- runtime surfaces`.
- No new canonical data store is introduced. SLI/SLO computation and alerting
  rules are declarative code/configuration; any durable error-budget or
  incident-state persistence must first be proven representable in existing
  durable recovery or content-safe audit tables before an additive migration is
  proposed.
- The API does not become a hidden worker supervisor and no alerting or SLO
  logic runs inside the webhook acknowledgement path.
- The metrics exporter remains loopback-only and disabled by default; production
  export uses an operator-owned network boundary per SPEC-020.
- No transaction or ordering lock spans external I/O.
- Incident and alerting tooling cannot mutate production beyond the approved
  rollback authority.

## Privacy requirements

- SLIs, SLOs, alerts, notifications, and incident records carry no message
  text, prompts, memories, vectors, provider bodies, raw platform IDs,
  usernames, or URLs.
- Staging alerting and incident drills use synthetic data; production content
  is never copied into alert payloads, incident records, or review documents.
- Incident-record retention is governed separately from product-content
  retention and remains consistent with SPEC-011 privacy and retention
  controls.
- Alert payloads contain no personal data.

## Security requirements

- Alerting and incident-tooling credentials use the SPEC-020 external secret
  boundary; they are never committed, baked into images, returned by APIs, or
  logged.
- Least-privilege access to alerting, notification, and incident systems, with
  access review tied to control-plane membership.
- Webhook secrets continue to use constant-time validation and explicit rotation
  (SPEC-003/004); no new secret class is introduced by this specification.
- Incident tooling cannot perform unapproved production mutations; rollback and
  webhook deletion remain explicitly gated (SPEC-022).
- No credentials or tokens appear in alert bodies, notification channels, or
  incident evidence.

## Operational requirements

- A runbook exists for each severity class and each required drill scenario
  (alert loss, missed alert, quarantine accumulation, dead-letter saturation,
  provider outage, database/Redis loss, secret rotation during an incident,
  rollback trigger, and post-incident evidence review).
- The operating owner defines and approves the incident roster, escalation
  path, notification channels, acknowledgement SLA, and status-update
  frequency.
- At least one content-safe incident drill per severity category is performed
  before production relies on the alerting path.
- Error-budget and SLO measurements are reproducible from the exported metrics
  catalog.
- Incident evidence links to SPEC-022 live-acceptance evidence and SPEC-021
  audit events through opaque identifiers.

## Acceptance criteria

Design review is complete when the Product Owner approves:

- The SLI catalog, measurement sources, and validity rules (FR-01).
- SLO targets, measurement windows, and error-budget policy (FR-02).
- The alerting rule catalog, severity model, detection-latency bounds, and
  acknowledgement/escalation policy (FR-03, FR-06).
- The content-safe notification boundary and approved channels (FR-04).
- The incident lifecycle, roles, communication, evidence, and post-incident
  review policy (FR-05, FR-07–FR-10).
- The no-migration stance and the architectural constraints.
- The privacy, security, and operational requirements.
- The next bounded task.

A future implementation phase is complete only with executable or observable
proof: reproducible SLO/error-budget computation from content-free telemetry;
content-safe rendered alert rules; content-safe incident evidence; successful
drills; existing validators passing; and no schema migration.

## Failure scenarios

| Scenario | Required handling |
| --- | --- |
| Metric exporter or collection loss | Staleness alert fires; SLO measurement pauses and is reported unknown, never zero. |
| Alert fatigue | Debounce, severity caps, and rule review; no busy loops. |
| Missed alert | Bounded detection latency; acknowledgement expiry; escalation to next owner. |
| Quarantine accumulation | Operator recovery only; no blind replay; capacity alert. |
| Dead-letter saturation | Replay gate enforced by SPEC-016; backlog alert. |
| Provider outage | Degraded mention response; SLO burn alert; incident communication. |
| PostgreSQL or Redis loss | Readiness degraded; incident; recovery per SPEC-020; restore PostgreSQL first. |
| Secret rotation during an incident | Old credentials fail closed; rotation follows the approved overlap window. |
| Alerting system down | Documented out-of-band escalation path is used. |
| Content or credential leakage into evidence | Content-safety review gate rejects the artifact before distribution. |

## Out-of-scope items

Runtime implementation, migrations, validators, tests, deployment manifests,
dashboard UI (deferred to the SPEC-021 control-plane roadmap), billing,
multi-tenancy, provider load balancing, cloud-provider selection, autonomous
remediation, auto-scaling, Zalo, and new Telegram media or voice behavior.

## Dependencies

- SPEC-003/004 Telegram adapter, webhook, ingress, and idempotency.
- SPEC-011 memory privacy and retention.
- SPEC-015 observability and telemetry contract.
- SPEC-016 recovery classification, dead letter, quarantine, and operations CLI.
- SPEC-018 and SPEC-019 summary and semantic-memory metrics.
- SPEC-020 deployment, secrets, migration, readiness, recovery, and rollback
  boundaries.
- SPEC-021 authenticated control plane and content-safe audit.
- SPEC-022 live acceptance evidence and operating-owner, incident-contact, and
  rollback-authority roles.
- Existing validators remain authoritative; new proof is added only in an
  approved implementation phase.

Next bounded task: SPEC-024.

## Migration expectation

No migration is authorized by this specification. The existing telemetry
catalog, durable recovery state, and content-safe audit tables are expected to
represent the SLI/SLO, alerting, and incident state required by this
specification. A future implementation phase must first audit whether existing
tables suffice; if they cannot, it must propose an additive migration with a
separate approval, retention, privacy, and downgrade rationale before any
implementation. Alerting and incident state never stores content or secrets.

## Risks

| Risk | Required mitigation |
| --- | --- |
| SLO targets exceed what the topology can deliver | Targets are approved product commitments measured only after the operating environment exists. |
| Alert fatigue or missed alerts | Debounce, severity caps, detection-latency bounds, acknowledgement expiry, escalation. |
| False readiness or false SLO compliance | Bounded readiness checks; SLO computed only from approved-environment telemetry. |
| Content or credential leakage in alerts/evidence | Content-safety guard on every artifact and review gate. |
| Ambiguous delivery handled as incident replay | `delivery_unknown` remains quarantine; SPEC-016 replay rules only. |
| Alerting tooling becomes a production mutation path | Least-privilege, approved rollback authority, no unapproved mutation. |
| Incident evidence outlives its purpose | Separate retention governed consistently with SPEC-011. |
| Secret or channel compromise | External secret boundary, rotation, access review, authenticated channels. |
| Unbounded recovery backlog | Backlog thresholds, capacity alerts, operator replay. |

## Deliverables

- This approved product specification.
- In a future implementation phase: an SLI/SLO definition and error-budget
  policy document, a content-safe alert rule catalog, a severity and incident
  runbook, incident evidence and post-incident-review templates, the required
  ADRs, and executable/observable proof. This design phase creates none of
  those artifacts.

## External prerequisites

- Product Owner and operating-owner approval of SLO targets, error-budget
  policy, severity model, and ownership.
- An approved hosting/orchestration target and monitoring, alerting, and
  notification backends (SPEC-020 decisions).
- Approved content-safe notification channels and incident roster.
- Access review for alerting, notification, and incident tooling.
- A drill environment with synthetic data for incident rehearsal.
- Retention and access policy for incident records.

## Product Owner approval checklist

- [ ] SLI catalog, measurement sources, and validity rules are approved.
- [ ] SLO targets, measurement windows, and error-budget policy are approved.
- [ ] Alert rule catalog, severity model, detection-latency bounds, and
      acknowledgement/escalation policy are approved.
- [ ] Content-safe alert and notification boundary and channels are approved.
- [ ] Incident lifecycle, roles, communication, evidence, and review policy are
      approved.
- [ ] Privacy, security, and operational requirements are approved.
- [ ] No-migration stance and architecture constraints are approved.
- [ ] Failure scenarios and risks are reviewed.
- [ ] External prerequisites and drill plan are accepted.
- [ ] Next bounded task is confirmed.
