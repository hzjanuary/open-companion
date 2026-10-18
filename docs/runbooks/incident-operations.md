# Incident Operations

Authoritative for SPEC-023 FR-05, FR-07 through FR-12 and the operational
requirements. Defines the incident lifecycle, roles and authority,
communication, evidence, post-incident review, recovery integration, drills,
and the readiness-versus-worker-backlog distinction.

## Lifecycle (FR-05)

Each incident follows these phases, with a content-safe record at every phase:

1. Detection by alert or operator observation.
2. Acknowledgement within the approved SLA and severity-appropriate window.
3. Classification by severity and affected surface.
4. Response by the approved operator and incident contact, with rollback
   authority available.
5. Communication on approved content-safe channels at a bounded status
   frequency.
6. Mitigation without unapproved production mutation; rollback only through
   the approved authority.
7. Resolution and verification of recovery.
8. Post-incident review with timeline, cause, remediation, and error-budget
   impact (required for Sev1/Sev2).

The lifecycle is implemented as pure content-safe artifact builders in
`backend/app/application/observability/incidents.py`
(`build_incident_evidence`, `build_post_incident_review`) and the templates in
`docs/templates/incident-evidence.md` and
`docs/templates/post-incident-review.md`.

## Roles and authority (FR-07)

Each environment defines an operating owner, an incident contact, and a
rollback authority, reusing the SPEC-022 ownership vocabulary. The rollback
authority is the only role permitted to trigger production rollback or
disable/delete the Telegram webhook during an incident. Roles are recorded in
content-free incident records and correlated with SPEC-021 control-plane
membership without granting Telegram group authority.

Escalation order: operating owner -> incident contact -> rollback authority.

## Communication (FR-08)

Status updates occur on approved content-safe channels at a bounded frequency
(default: every 30 minutes for Sev1, every 2 hours for Sev2). Updates correlate
incidents through opaque incident and request/correlation IDs and never carry
product content or credentials.

## Evidence (FR-09)

Each incident produces a metadata-only evidence record consistent with the
SPEC-022 evidence-bundle conventions: environment, severity, timeline, owners,
opaque identifiers, metric values, result classifications, recovery outcomes,
and remediation state. It contains no message content, prompts, memories,
vectors, provider bodies, or credentials. Every artifact passes the
content-safety guard before emission, and a review gate rejects leakage before
distribution.

## Post-incident review and remediation (FR-10)

Every Sev1/Sev2 incident produces a review with an observed timeline,
root-cause classification (closed set: provider outage, dependency outage,
capacity exhaustion, deployment rollout, configuration error, secret rotation,
recovery backlog, alerting failure, unknown), error-budget impact, corrective
actions, and remediation ownership. Remediation is tracked to closure and fed
back into SLO targets, alert thresholds, and runbooks.

## Recovery integration (FR-11)

Incidents use the SPEC-016 `operations inspect/show/replay` CLI for dead-letter
and quarantine handling. Replay handles one dead letter, rechecks durable
state in its transaction, preserves business identity and idempotency, and
never performs external I/O. Quarantined, completed, and leased work is
refused. `delivery_unknown` always remains quarantine; ambiguous delivery is
operator-owned and never blindly replayed.

## Readiness versus worker backlog (FR-12)

API readiness degradation alerts on `/ready` dependency failures. Worker
backlog and stuck durable work alert through recovery and queue metrics.
Optional derived services that have a documented safe fallback do not make the
API unready and are signaled through their own worker metrics.

## Ownership roster and ack SLA (operating-owner defined)

The operating owner defines and approves the incident roster, escalation path,
notification channels, acknowledgement SLA, and status-update frequency for
each environment. The current defaults (per-severity ack expiry, escalation
order, status frequency) are recorded in `alerting.md` and this document as
defaults pending explicit operating-owner approval.

## Drills (operational requirements)

At least one content-safe incident drill per severity category is performed
before production relies on the alerting path. Required drill scenarios:

- Alert loss / alerting-system staleness (`alerting_staleness`).
- Missed alert: ack expiry and escalation to the next owner.
- Quarantine accumulation: `operations inspect/show/replay`; no blind replay.
- Dead-letter saturation: replay gate enforced by SPEC-016; backlog alert.
- Provider outage: degraded mention response; SLO burn alert; incident
  communication.
- Database/Redis loss: `/ready` degraded; incident; recovery per SPEC-020;
  restore PostgreSQL first.
- Secret rotation during an incident: old credentials fail closed; rotation
  follows the approved overlap window.
- Rollback trigger: only the rollback authority may trigger production
  rollback or webhook disable/delete.
- Post-incident evidence review: content-safety review gate on every artifact.

Drills use synthetic data; production content is never copied into alert
payloads, incident records, or review documents. The deterministic synthetic
drill proof runs in `./scripts/validate-observability.sh` (one content-safe
scenario per severity). Live drills that need Telegram staging resources remain
externally gated by the SPEC-022 blocker and are deferred, not redesigned.

## Runbooks by severity

| Severity | First action | Time to investigate |
| --- | --- | --- |
| Sev1 | Page operating owner immediately; classify affected surface; communicate; escalate via approved path | Immediate |
| Sev2 | Attend within the approved window; inspect recovery backlog; open incident record | <= 15 min |
| Sev3 | Open a tracked item; investigate within the approved window | <= 24 h |
| Sev4 | Track and remediate without paging | No page |
