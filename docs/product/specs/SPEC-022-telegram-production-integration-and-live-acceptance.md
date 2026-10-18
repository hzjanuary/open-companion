# SPEC-022 Telegram Production Integration and Live Acceptance

## Status

Product specification for review. This document authorizes product and
acceptance design only. It authorizes no SPEC-023 work and does not change the
existing Telegram adapter, ingress contract, worker topology, migration
history, safety policy, or control-plane authorization model until a separate
implementation phase is explicitly approved.

SPEC-021 remains the preceding control-plane specification. SPEC-014 remains
deferred behind its external Zalo prerequisite.

## Background

SPEC-003 and SPEC-004 define the typed Telegram adapter, secure webhook
boundary, controlled polling, durable inbox, transactional outbox, and
at-least-once idempotency model. SPEC-005 through SPEC-019 define the
conversation, response, safety, privacy, memory, summary, observability, and
recovery behavior that consumes normalized Telegram updates. SPEC-020 defines
production deployment and runtime operations. SPEC-021 defines authenticated
operator administration without granting Telegram group authority.

The remaining product gap is live acceptance with a dedicated Telegram bot,
real Telegram delivery, a controlled staging group, and an approved production
cutover. This specification turns those external prerequisites into an
observable acceptance gate. Synthetic tests remain necessary, but they do not
count as evidence that Telegram webhook delivery, identity, permissions,
network behavior, and production recovery work with the intended bot.

## Outcome

An approved Telegram bot can receive and acknowledge real updates through one
controlled ingress mode, process them through the existing durable runtime,
and send an observable, policy-compliant response in a dedicated staging group
without duplicate terminal effects, secret leakage, unsafe retries, or loss of
durable work. Production cutover is permitted only after the same evidence is
reviewed for the production bot, domain, credentials, group, and operating
owner.

## Objectives

- Verify the configured Telegram bot identity before any live acceptance run.
- Prove one and only one ingress mode per Telegram connection.
- Validate the complete live path from Telegram update through durable ingress,
  workers, response planning, delivery, and observable completion.
- Prove webhook registration, secret validation, acknowledgement, retries,
  duplicate handling, and controlled shutdown behavior.
- Prove Telegram API errors, network failures, rate limits, and ambiguous
  delivery preserve existing recovery and idempotency guarantees.
- Separate staging credentials, bot, group, domain, and data from production.
- Define a reversible production cutover and an evidence-based rollback gate.
- Preserve privacy, safety, retention, semantic-memory, summaries,
  observability, and authenticated administration boundaries.

## Non-goals

- Implementing Zalo or beginning SPEC-023 or any later specification.
- Adding new Telegram message, media, voice, scheduling, billing, or routing
  capabilities.
- Replacing the existing Telegram adapter, durable inbox/outbox, Redis
  coordination, worker leases, response planner, or delivery ambiguity model.
- Making webhook registration an implicit side effect of API startup.
- Running polling and webhook delivery for the same connection concurrently.
- Using a production bot, group, credential, or message content in local or
  synthetic validation.
- Treating a successful `getMe`, health endpoint, unit test, or deployment
  build as sufficient live acceptance on its own.
- Granting control-plane operators Telegram administrator privileges implicitly.
- Disabling Privacy Mode, safety controls, rate limits, retention, redaction,
  authorization checks, or content-safe telemetry merely to simplify proof.

## Scope

In scope are Telegram credential and bot identity verification, staging and
production environment prerequisites, explicit webhook lifecycle, polling
exclusivity, supported and unsupported update handling, live ingress and
delivery acceptance, failure and recovery drills, rate-limit behavior,
operational evidence, production cutover, rollback, and acceptance ownership.

Existing product behavior remains authoritative:

- PostgreSQL is the canonical source of durable Telegram ingress, normalized
  conversation state, response work, delivery state, privacy state, and audit
  metadata.
- Redis Streams and consumer groups are at-least-once coordination, not a
  second source of truth.
- Qdrant remains rebuildable derived state; semantic retrieval failure follows
  the existing bounded fallback.
- Telegram administrator commands continue to perform fresh platform-derived
  authorization. Control-plane membership is not Telegram group authority.
- Ambiguous outbound delivery remains `delivery_unknown` or quarantine and is
  not automatically replayed as if exactly-once delivery were possible.
- Operational logs, metrics, traces, health, queues, and incident evidence
  remain free of raw message content, prompts, provider bodies, memories,
  vectors, bot tokens, webhook secrets, and authorization headers.

## Functional requirements

### FR-01: Connection readiness

Before a connection is eligible for live acceptance, the operator must verify
the intended environment and connection identifier, bot identity, platform,
delivery mode, public HTTPS endpoint, secret reference, dedicated test group,
expected group permissions, owning operator, incident contact, and rollback
authority. Missing, malformed, ambiguous, or inconsistent configuration fails
closed.

### FR-02: Bot identity verification

The acceptance procedure must call Telegram `getMe` using the configured bot
credential and compare the returned identity with the approved connection
record. Evidence may record only redacted identity metadata such as bot ID,
username, environment, timestamp, and result. The bot token must never appear
in output, logs, screenshots, metrics, or handoff documents.

An identity mismatch, revoked or invalid token, Telegram authentication error,
or unverifiable response blocks acceptance and must not proceed to webhook
registration or live traffic.

### FR-03: Explicit webhook lifecycle

Webhook lifecycle is an explicit operator/deployment operation:

1. Verify bot identity and inspect `getWebhookInfo`.
2. Confirm the approved HTTPS URL, path, secret, allowed updates, and target
   connection.
3. Register or update the webhook through the controlled operational action.
4. Verify Telegram reports the expected URL and allowed updates.
5. Send a controlled test update and verify durable acknowledgement and
   downstream completion.
6. Record activation time and operator.
7. On rollback or decommission, explicitly delete the webhook and verify the
   Telegram state, unless polling is intentionally activated instead.

API startup must not register, replace, or delete a Telegram webhook. Failed
registration or verification leaves the connection unavailable and must not
silently fall back to polling.

### FR-04: Polling and webhook exclusivity

For each Telegram connection, exactly one of `disabled`, `webhook`, or
`polling` is active. Webhook and polling must never run concurrently. Polling
must inspect Telegram webhook state and refuse to poll while a webhook URL is
present; it must not delete a webhook automatically.

A mode change requires explicit drain/stop of the old mode, verification of
Telegram state, and activation of the new mode. Evidence must show that no
second ingress source was active during the transition.

### FR-05: Supported update types

The live boundary must accept and route these existing typed update types:

- `message`;
- `edited_message`;
- `my_chat_member`;
- `chat_member`.

Supported updates must validate the envelope and limits, persist the durable
inbox record, create the transactional outbox reference, and acknowledge only
after the durable transaction succeeds. Downstream consumers retain the
existing stable update identity and idempotency behavior.

### FR-06: Unsupported update types

Unknown or unsupported update types must be rejected or recorded as
unsupported at the boundary without creating business queue work. They must
not create a conversation, response plan, outbound action, or Telegram side
effect. Classification may be counted in content-free telemetry but must not
include raw update bodies.

### FR-07: Live response acceptance

The dedicated staging group must prove at least one addressed message and one
supported membership/configuration event where applicable. The addressed
message must produce the expected safe response path or an intentional,
observable silence decision. Evidence correlates the update, opaque internal
identifiers, worker outcome, and delivery outcome without copying message text
into operational artifacts.

A response is accepted only when Telegram delivery is confirmed or classified
according to the existing delivery-certainty contract. Timeout or ambiguous
post-send outcomes are not counted as confirmed duplicate-safe success.

### FR-08: Duplicate updates

Replaying the same Telegram update for the same connection must produce one
canonical durable ingress record and no duplicate terminal response effect.
At-least-once Redis publication and worker redelivery remain permitted; the
database idempotency authority and downstream ledgers classify new, duplicate,
stale, and completed work.

### FR-09: Retry behavior

Retries remain bounded, classified, and owned by the existing layer:

- Telegram controls webhook retries, handled by durable deduplication;
- outbox publication retries remain durable and lease/retry based;
- worker retries retain existing attempt and lease limits;
- outbound retries follow delivery certainty;
- ambiguous outcomes become `delivery_unknown` or quarantine, not blind replay;
- no retry holds a database transaction or external-I/O lock.

Invalid requests, authentication failures, unsupported updates, policy
refusals, and confirmed Telegram rejections must not be retried as transient
network failures.

### FR-10: Network and Telegram API failures

Acceptance must exercise or observe controlled DNS/connectivity failure,
timeout, malformed Telegram response, authentication failure, forbidden
chat/action, invalid request, conflict, and server-side failure where the test
account permits. Each maps to a stable internal category, preserves safe
correlation, and produces the documented recovery state. No failure silently
creates a second terminal effect.

### FR-11: Rate limits

Telegram `429` responses must honor retry-after guidance within the existing
bounded retry policy. The integration must not busy-loop, exceed local
rate/concurrency controls, or treat a rate limit as successful delivery.
Durable work remains recoverable and observable. Addressed work retains its
existing priority over ambient participation.

### FR-12: Webhook acknowledgement

The endpoint returns the existing typed accepted/duplicate acknowledgement only
after durable ingress commits. Persistence failure returns a bounded
dependency-unavailable response so Telegram may retry. Invalid secrets,
oversized bodies, malformed updates, wrong connection IDs, and disabled
delivery are rejected without being acknowledged as accepted work.

### FR-13: Operational evidence

Every live run produces a reviewable evidence bundle containing environment,
connection, redacted bot identity, webhook/polling state, timestamps,
correlation IDs, result classifications, health/readiness, worker lifecycle,
duplicate/retry outcomes, and cleanup confirmation. It contains no message
content, credentials, tokens, prompts, memories, vectors, or provider bodies.

## Non-functional requirements

### NFR-01: Security

- Staging and production use separate bots, tokens, webhook secrets, domains,
  databases, queues, groups, and telemetry destinations.
- Secrets enter through the approved external boundary and are never
  committed, baked into images, returned by APIs, or logged.
- Webhook secrets use constant-time comparison and explicit rotation.
- Public ingress is HTTPS-only and restricted to the configured path and
  connection.
- Bot identity, connection, and tenant scope are verified server-side.
- Personal Telegram accounts and undocumented client automation are not
  production credentials.
- Least-privilege bot/group permissions and all existing safety controls remain
  active during acceptance.

### NFR-02: Privacy

Staging data is synthetic or explicitly approved test content. Production
content is not copied into fixtures, screenshots, traces, tickets, or
validation artifacts. Live evidence records metadata and redacted outcome
classes only. Retention and deletion behavior remains unchanged.

### NFR-03: Reliability and recovery

The live path tolerates Telegram and Redis at-least-once delivery, worker
restart, lease expiry, API restart, and transient dependency loss without lost
durable work or duplicate terminal effects. PostgreSQL restore and Qdrant
rebuild remain governed by SPEC-020.

### NFR-04: Observability

Health, readiness, metrics, logs, and traces distinguish accepted, duplicate,
rejected, unsupported, pending, confirmed, failed, and ambiguous outcomes.
Telemetry is content-safe and correlates through opaque internal identifiers
and request IDs.

### NFR-05: Compatibility

Existing command behavior, response policy, personality revisions, privacy,
semantic-memory fallback, summaries, rate limits, delivery certainty, and
recovery classifications remain unchanged.

## Required staging environment

The Product Owner and operating owner must provide a dedicated Telegram bot
and approved `getMe` identity, separate token and webhook secret, HTTPS
hostname/certificate, dedicated test group, approved bot membership and
Privacy Mode configuration, isolated PostgreSQL/Redis/optional derived
services, synthetic provider behavior, telemetry destination, incident and
rollback owners, and a cleanup window. Network tests must not use production
resources.

## Required production environment

Production additionally requires an approved production bot and ownership,
HTTPS ingress/DNS/certificate/firewall, secret provisioning and access review,
backup/restore and migration procedures, separate worker/rate-limit/alerting
configuration, a low-risk production test group, a live acceptance plan,
rollback trigger, support escalation, and evidence that staging passed without
production credentials or content.

## Production Telegram acceptance criteria

Production cutover is accepted only when:

1. The approved production bot identity matches the intended connection.
2. Exactly one ingress mode is selected and the other is proven inactive.
3. HTTPS, secret validation, allowed updates, body limits, and routing pass.
4. A low-risk live update reaches durable ingress and its downstream outcome
   is observed.
5. Duplicate replay, worker restart, and dependency recovery pass in staging
   with a production-safe equivalent reviewed for launch.
6. API/network failures, rate limits, and ambiguous delivery have documented
   recovery ownership.
7. No acceptance artifact exposes secrets or product content.
8. Monitoring, alerting, backups, rollback, incident response, and cleanup are
   ready and owned.
9. Product Owner and operating owner approve the evidence bundle.

Failure of any criterion blocks cutover. A successful `getMe` check alone is
never production authorization.

## Operational verification matrix

| Area | Required observable proof |
|---|---|
| Bot identity | `getMe` matches approved metadata; mismatch blocks acceptance |
| Webhook state | expected URL, secret, connection, and update set verified |
| Mode exclusivity | polling refuses an active webhook; no concurrent source |
| Webhook security | wrong/missing secret and connection are rejected |
| Ingress durability | update commits inbox/outbox before acknowledgement |
| Unsupported input | no business work is created |
| Duplicate update | one canonical update and no duplicate terminal send |
| Worker recovery | restart/lease reclaim completes durable work safely |
| Telegram errors | auth, forbidden, invalid, conflict, server, timeout, malformed responses classified |
| Rate limits | retry-after is bounded and durable; no busy loop |
| Ambiguity | timeout/post-send uncertainty becomes `delivery_unknown` or quarantine |
| Privacy | logs, metrics, evidence, and APIs contain no content or secrets |
| Readiness | dependency loss and recovery produce documented states |
| Cutover | activation owner, time, configuration, and rollback point recorded |
| Cleanup | test resources are removed or explicitly retained by approval |

## Risks

| Risk | Mitigation |
|---|---|
| Wrong bot or group receives traffic | `getMe`, connection, domain, and group verification |
| Webhook and polling both consume updates | explicit mode state and Telegram inspection |
| Telegram retries duplicate effects | PostgreSQL deduplication and downstream ledgers |
| Send timeout creates uncertainty | preserve `delivery_unknown`/quarantine; operator recovery |
| Bot cannot see group messages | verify Privacy Mode, membership, and live update types |
| Rate limits cause backlog | bounded retry-after, local limits, priority, backlog alerts |
| Live evidence leaks content | metadata-only evidence and redaction review |
| Credential leakage | external secret boundary, redaction, rotation, access review |
| Cutover is hard to reverse | explicit activation, rollback point, and owner |

## Dependencies

- SPEC-003 Telegram adapter and identity operations.
- SPEC-004 durable ingress, webhook/polling exclusivity, and idempotency.
- SPEC-005 through SPEC-012 conversation, planning, delivery, personality,
  privacy, safety, and rate-limit contracts.
- SPEC-015 through SPEC-019 observability, reliability, ambient behavior,
  summaries, and semantic retrieval boundaries.
- SPEC-020 deployment, secrets, migration, backup, and recovery operations.
- SPEC-021 authenticated operator and group administration boundaries.
- Telegram bot ownership, Bot API access, HTTPS, groups, secret manager,
  monitoring, and operating-owner approval.

## Explicit acceptance checklist

- [ ] SPEC-003/004 are reviewed as the live Telegram authority.
- [ ] Staging bot, token, secret, domain, database, queue, group, and provider
      resources are isolated and owned.
- [ ] Staging `getMe` identity verification passes without secret disclosure.
- [ ] Webhook registration, inspection, test delivery, deletion, and rollback
      are exercised explicitly.
- [ ] Polling refuses an active webhook and mode transitions prove exclusivity.
- [ ] Supported update types pass live boundary validation.
- [ ] Unsupported types create no business work.
- [ ] Duplicate replay creates no duplicate terminal effect.
- [ ] Acknowledgement occurs only after durable persistence.
- [ ] Network, Telegram API, timeout, forbidden, auth, malformed, and rate-limit
      behavior is classified and recoverable.
- [ ] Worker restart, lease recovery, readiness degradation, and dependency
      recovery are observed.
- [ ] Production identity, permissions, HTTPS, monitoring, backup, rollback,
      and incident ownership are approved.
- [ ] Production low-risk acceptance passes with metadata-only evidence.
- [ ] Secrets and product content are absent from artifacts and telemetry.
- [ ] Product Owner and operating owner approve cutover.
- [ ] The SPEC-022 handoff records evidence, limitations, prerequisites, and
      the next recommended specification.
