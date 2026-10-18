# SPEC-024 Design Handoff

## Status

APPROVED DESIGN

This is the System Architect's implementation-ready design handoff for
SPEC-024 (Safety Moderation, Abuse Prevention, and User Protection). The
Product Owner approved the product specification at
`docs/product/specs/SPEC-024-safety-moderation-abuse-prevention-and-user-protection.md`.
This design phase creates this handoff only: no runtime code, migration,
validator, test, deployment manifest, ADR, runbook, or other document is
changed, and no commit or push is performed. The next engineer may implement
SPEC-024 from this document without reviewing the product specification.

## Repository Baseline

- Baseline HEAD: `private-source-checkpoint-omitted` (SPEC-023
  implemented and committed).
- `origin/main` matches the baseline commit.
- The worktree currently contains the Product Owner's SPEC-024 changes:
  `M docs/product/SPEC.md`, `M docs/product/README.md`, and the new untracked
  `docs/product/specs/SPEC-024-safety-moderation-abuse-prevention-and-user-protection.md`.
- This design phase adds exactly one file:
  `docs/plans/handoff/SPEC-024-DESIGN-HANDOFF.md`.
- `git diff --check` passes after this file is created. No commit or push is
  authorized in this phase.

## 1. Objective

SPEC-024 makes the existing deterministic safety surface observable and
bounded: every safety decision becomes an auditable content-free record
(FR-01), the assistant's own output and targeting behavior are moderated
within the existing hard boundaries (FR-02/FR-03), abuse of the assistant is
resisted and counted without compliance (FR-04/FR-05/FR-06), sustained abuse
triggers protective enforcement that never sanctions the member (FR-07), and a
content-free human review queue plus operating-owner escalation close the loop
(FR-08/FR-11), all under content-safe evidence and audit (FR-12) with
per-group administrator controls (FR-09) and a user protection model centered
on opt-out and standing stop (FR-10).

The implementation phase must not weaken SPEC-011/012/016/021/022/023
boundaries, must not add content retention, must not grant moderators group
authority or content access, and must keep every existing validator green.

### FR to implementation-task mapping

| FR | Requirement (SPEC-024) | Implementation tasks |
| --- | --- | --- |
| FR-01 | Safety decision pipeline is observable; rejected/neutral-fallback never retried as a compliance request | Audit decision-recording coverage in `backend/app/runtime/response_planning_worker.py` (pre/post-generation) and `backend/app/runtime/outbound_delivery_worker.py` (pre-delivery); add participant attribution to decision records where derivable (see Database Impact); expose content-free signal extraction; confirm refused/fallback outcomes never re-enter provider I/O. |
| FR-02 | Assistant-output safety: hard boundaries, no config disables them, no roast mode, short language-aware non-escalating refusals | Extend the refusal/fallback template surface (`safe_fallback` in `backend/app/domain/safety.py`, `command_response` in `backend/app/application/commands.py`); add one unit test per hard boundary asserting REFUSE/TRANSFORM behavior; assert no configuration key can disable `safety-policy-v1`. |
| FR-03 | Targeting protection: recheck opt-out, privacy-deletion, and protection level before every outbound mention/teasing; standing stop is immediate and persistent | Add protection state to the per-participant context consumed by `ResponsePlanPolicy.apply` in `backend/app/application/response_plan.py` and to the outbound recheck at `backend/app/runtime/outbound_delivery_worker.py` lines ~380/~409; persist standing stop; record `mention_target_opted_out`/`teasing_target_opted_out`/protected outcomes as decisions. |
| FR-04 | Abuse of the assistant: injection creates no platform action; private memory never disclosed on demand; harmful requests refused; manipulation counted | Confirm prompt-injection refusals already record `prompt_injection_action_attempt`/`unsupported_action`; add private-memory-extraction refusal coverage at the prompting/planning boundary; feed counts into FR-06 signals. |
| FR-05 | Loop and amplification prevention: no `answer_every_message` mode; eligibility and rate limits before provider calls; no pile-ons; bot-to-bot loops broken | Add regression tests proving no configuration enables answer-every-message, eligibility precedes provider calls, and assistant-to-assistant loops are rejected by eligibility rules. |
| FR-06 | Abuse signal detection: content-free per-conversation and per-participant counts; thresholds configured by group admin and operating owner, conservative defaults | Define the signal catalog (safety decision counts by category/outcome; mention/teasing frequency toward a single participant; rate-limit violations; memory-extraction attempts; dangerous-instruction requests; manipulation attempts); implement on-demand content-free aggregation over `safety_policy_decisions`/`rate_limit_events`/outbound targeting data; add per-group threshold configuration with conservative defaults. |
| FR-07 | Protective enforcement: stop targeting, reduce/pause interaction, record content-free protective action; reversible only through review | Implement protection-state application in planning and delivery targeting paths; implement interaction reduction/pause policy against the abusive participant; record content-free protective actions (see Metrics/Database Impact); gate reversibility behind FR-08 review. |
| FR-08 | Moderation review queue: bounded content-free items; actions acknowledge/escalate/restore targeting/pause or restrict; fresh authorization | Implement the review-queue store (candidate additive migration — see Database Impact); implement the four actions with idempotency; require SPEC-010 fresh authorization for per-group actions and SPEC-021 control-plane authorization for escalated/cross-group actions; render items content-free. |
| FR-09 | Administrator safety controls: per-group safety level, teasing cap, response frequency, member protection; compatible with existing commands | Extend the command grammar in `backend/app/application/commands.py` and `backend/app/runtime/telegram_command_worker.py`; extend `conversation_configuration_revisions` semantics; add protect-member action; keep `/quiet` `/resume` `/mode` `/frequency` `/mentions` `/teasing` compatible. |
| FR-10 | User protection model: opt-out and standing stop honored immediately and persistently; protected members never targeted; no profiling/rating/punishment | Persist standing stop; add protect-member state (FR-09); add tests that protected/opted-out/deleted participants are never targeted; assert no punitive or sanctioning behavior exists. |
| FR-11 | Escalation to operating owner: content-safe alerting and incident path; metadata-only evidence; rollback authority unchanged | Add safety escalation rules to the alert catalog (`backend/app/application/observability/alerts.py`) and `docs/runbooks/alerting.md`; add incident-runbook guidance reusing SPEC-023; keep rollback/webhook-disconnect gated to the SPEC-022 rollback authority. |
| FR-12 | Evidence and audit: every decision, protective action, review action, escalation recorded content-free | Route actions through the SPEC-021 audit surface (`control_audit_events`); apply `assert_content_safe` (SPEC-022) to every new artifact and add a review-gate test that prohibited keys/credentials are rejected. |

Non-functional requirements are enforced across sections: NFR-01/04 (content
safety, no added retention) in Privacy, Metrics, and Alerting; NFR-02/06/07
(deterministic fail-closed, no webhook latency, idempotent reliability) in
Runtime Boundaries and Failure Modes; NFR-03 (closed labels) in Metrics;
NFR-05 (deny-by-default, step-up) in Authorization and APIs; NFR-08
(compatibility) in Runtime Boundaries; NFR-09 (no false confidence) in
Validation Strategy.

## 2. Existing Architecture

### Deterministic safety policy (SPEC-012)

- `backend/app/domain/safety.py` is the authoritative vocabulary:
  `SafetyPolicyVersion.V1` (`safety-policy-v1`), `SafetyStage`
  (`pre_generation`, `post_generation`, `pre_delivery`), `SafetyOutcome`
  (`allow`, `transform`, `refuse`, `silent`), and `SafetyReasonCode`
  (`mention_target_opted_out`, `teasing_target_opted_out`, `target_not_in_context`,
  `sensitive_teasing_disallowed`, `private_data_boundary`,
  `invalid_model_safety_annotation`, `prompt_injection_action_attempt`,
  `unsupported_action`, `model_refusal`, `safe_fallback`, `rate_limited`).
- `SafetyPolicy.system_instructions()` renders the hard boundaries: no
  harassment, identity attacks, targeted humiliation, private-data disclosure,
  sexual content involving minors, self-harm encouragement, or dangerous
  instruction execution; no tools/raw platform identifiers/arbitrary actions;
  teasing only against explicit permitted targets and stops after opt-out.
- `safe_fallback(language)` returns a short language-aware neutral text that
  never repeats rejected content or targets. Enforcement is deterministic
  structural policy, explicitly not comprehensive semantic moderation.

### Targeting and response policy (SPEC-005/006/007/012)

- `backend/app/application/response_plan.py`: `ResponsePlanPolicy.apply` limits
  mentions and teasing targets to current internal context IDs, drops mentions
  whose participant is not `mention_allowed` or is `privacy_deleted`, disallows
  sensitive-topic teasing, and transforms unsafe/contradictory teasing into a
  language-aware `safe_fallback` neutral response with no mention or sticker.
  `InteractionMetadata` (response-plan-v2) is `extra="forbid"` strict
  structured metadata (`kind`, `teasing_target_participant_ids`,
  `sensitive_topic_categories`).
- `backend/app/application/context.py` carries per-participant
  `mention_allowed`/`teasing_allowed`; `backend/app/infrastructure/database/context.py`
  loads them from `participants` (defaults `False` when the row is absent).
- The outbound worker rechecks targeting before delivery:
  `backend/app/runtime/outbound_delivery_worker.py` filters mentions
  (`ParticipantModel.mention_allowed.is_(True)`, ~line 380) and teasing
  (`teasing_allowed.is_(True)`, ~line 409).

### Safety and rate-limit persistence (SPEC-012, migration `0009`)

- `safety_policy_decisions` (content-free): `planning_job_id`,
  `response_plan_id`, `conversation_id`, `policy_version`, `stage`, `outcome`,
  `reason_code`, `transformed`, `created_at`. Recorded by
  `backend/app/infrastructure/database/safety.py::SqlAlchemySafetyRepository.record_decision`
  from the planning worker (pre-generation ALLOW/SILENT/rate-limited,
  post-generation) and the delivery worker (pre-delivery).
- `rate_limit_events` (content-free): `planning_job_id`, `outbound_action_id`,
  `operation`, `limiting_scope`, `provider_id`, `allowed`, `retry_after_seconds`,
  `configuration_version`.
- Rate limiting (`backend/app/domain/rate_limit.py`, `application/rate_limiting.py`,
  `application/rate_limit_rules.py`): generation scopes deployment, connection,
  conversation, participant, provider; delivery scopes deployment, connection,
  conversation; Redis fixed-window Lua check fails closed for provider and
  Telegram I/O and requeues durable work; privacy and administration mutations
  remain local.

### Privacy and erasure (SPEC-011)

- `backend/app/infrastructure/database/privacy.py` erases a subject across
  participants, messages, incoming updates, command arguments, response plans,
  outbound actions, memories, and summaries; it sets `mention_allowed=False`,
  `teasing_allowed=False`, `privacy_deleted_at`, and redacts content-bearing
  columns. Targeting must recheck this state before every outbound action.
- Memory (`/memory`, `/forget`, `/forget_me`) honors same-conversation
  visibility and profile-deletion tombstones; `conversations.memory_privacy_revision`
  tracks revisions.

### Command surface (SPEC-010)

- `backend/app/application/commands.py` is the deterministic grammar:
  `/quiet`, `/resume`, `/mode`, `/frequency`, `/personality`, `/stickers`,
  `/mentions`, `/teasing`, `/memory`, `/forget`, `/forget_me`; operations are
  `read|configuration|preference|memory`. Protected mutations use fresh
  Telegram authorization via durable `telegram_command_jobs`.
- Group configuration is versioned in `conversation_configuration_revisions`
  (`response_mode`, `ambient_frequency`, `teasing_level`, humor, formality,
  sticker/emoji frequency, name usage, follow-up questions) with
  `conversations.settings` JSONB and immutable personality snapshots (SPEC-009).

### Control plane (SPEC-021)

- `backend/app/interface/http/control_plane.py` exposes `/control/v1` with a
  deny-by-default authorizer over `control_audit_events` (`tenant_id`, action,
  outcome, resource_type/resource_id, request_id, metadata JSONB). Membership
  grants no Telegram group authority. Step-up and recent-authentication
  boundaries cover high-impact actions.

### Observability and alerting (SPEC-015/022/023)

- `backend/app/infrastructure/telemetry.py` is the closed catalog; recorder
  validates metrics and rejects prohibited label names. Relevant metrics:
  `january_safety_decisions_total` (`stage`, `outcome`, `reason`),
  `january_rate_limit_events_total` (`operation`, `scope`, `result`).
- `backend/app/application/observability/` contains the content-safe
  `content_safety.assert_content_safe`, the SLI/SLO layer, `alerts.py` (11-rule
  catalog, severity model, debounce, caps, ack expiry, escalation), and
  `incidents.py`. `docs/runbooks/alerting.md` documents the boundary: payloads
  carry rule/severity/state/timestamp/opaque values only.
- SPEC-022 ownership: operating owner, incident contact, rollback authority;
  the rollback authority is the only role that may trigger production rollback
  or webhook disable/delete during an incident.

### Recovery (SPEC-016)

- `operational_recovery_items`/`operational_recovery_events` are content-free;
  the `operations inspect/show/replay` CLI (`backend/app/runtime/operations.py`)
  is the only replay path, with quarantine/completed/leased/`delivery_unknown`
  refusal semantics.

### Validation estate

- `scripts/validate.sh` (ruff, format, mypy, non-integration suite),
  `scripts/validate-observability.sh` (telemetry catalog presence + the
  SPEC-015 no-migration guard + observability tests),
  `scripts/validate-live-acceptance.sh` (SPEC-022), and DB-backed
  `validate-ingress.sh`/`validate-safety.sh`/`validate-memory.sh`/
  `validate-commands.sh`/`validate-reliability.sh` (PostgreSQL/Redis via
  Docker, `alembic upgrade head`). The host requires the temporary uncommitted
  `label=disable` SELinux override and isolated ports for DB-backed runs.
- Three schema-pin integration tests assert head revision
  `0014_authenticated_control_plane`; any approved migration must update them
  in the same change.

## 3. Runtime Boundaries

- The webhook acknowledgement path gains no new latency beyond existing
  deterministic checks; all advisory classification is bounded, non-blocking,
  and never on the ack path (NFR-06).
- The deterministic structural guard remains authority and is never disabled
  by configuration, operator action, or incident procedure; when an advisory
  check cannot be evaluated the assistant defaults to the stricter outcome
  (NFR-02).
- Moderation is bounded to assistant output, requests to the assistant, and
  targeting of members. The assistant never moderates user-to-user content,
  never acts as a public community moderator, and never sanctions, expels, or
  bans members (spec "Moderation boundaries").
- Signal aggregation, threshold evaluation, review-queue materialization, and
  alerting run out of band — never inside the webhook path, never supervising
  workers, never mutating production beyond the approved rollback authority.
- No autonomous user sanctions; every enforcement and review outcome is either
  protective behavior or an administrator/operator decision.
- Dependency direction stays `domain <- application <- infrastructure <-
  interface <- runtime`; no transaction or ordering lock spans external I/O.
- Existing command behavior, response policy, personality, memory, privacy,
  retention, rate limits, delivery certainty, recovery, control-plane, and
  observability contracts remain unchanged (NFR-08).

## 4. Database Impact

Following the SPEC-023 migration discipline (Migration Expectations) and
ADR-0020 representability precedent, the implementation phase must first audit
existing content-free tables before any schema change. No migration is
authorized by this design phase.

- **Signals (FR-06) are derivable without migration.** Safety decision
  category/outcome/stage and rate-limit outcomes already live in
  `safety_policy_decisions` and `rate_limit_events`; per-participant attribution
  is derivable through existing foreign keys
  (`planning_job_id -> response_planning_jobs -> message_id -> participants`)
  or from outbound targeting data for mention/teasing frequency. Aggregation is
  an on-demand content-free computation; no new canonical store is required.
- **Protection state (FR-07/FR-09/FR-10) is not representable today.**
  `participants` has `mention_allowed`/`teasing_allowed`/`privacy_deleted_at`
  but no structured protection flag; `conversations.settings` JSONB is not a
  structured authority. Candidate additive migration:
  `participants.protected_at` (nullable timestamp) set by administrator
  protection and by protective enforcement, cleared only through the review
  path. This requires a separate approval including retention, privacy, and
  downgrade rationale before implementation.
- **Review queue (FR-08) is not representable today.** `control_audit_events`
  records actions but not bounded queue state with protection_state, timeline,
  and status. Candidate additive migration: a content-free
  `safety_review_items` table (category, stage, outcome counts, opaque
  conversation/participant references, protection state, status, timestamps;
  no text/prompts/usernames/raw platform IDs). Requires separate approval as
  above.
- **Retention (NFR-04):** safety decision and review records follow SPEC-011
  retention parity, governed separately from product-content retention;
  rejected content is never persisted beyond the existing bounded
  incoming-message retention and never copied into moderation artifacts.
- No content-bearing column may ever be added to any safety, review, audit, or
  alert surface (NFR-01/FR-12).
- If migrations are approved, the three schema-pin integration tests that
  assert head `0014_authenticated_control_plane` are updated in the same
  change.

## 5. APIs

- **Telegram command surface (per-group, FR-09/FR-08):** extend the grammar in
  `backend/app/application/commands.py` and dispatch in
  `backend/app/runtime/telegram_command_worker.py` for per-group safety
  settings (safety level, teasing cap, response frequency), member protection,
  and per-group review-queue actions (acknowledge, escalate, restore targeting,
  pause/restrict). All protected mutations use the existing fresh-authorization
  contract (SPEC-010).
- **Control plane (escalated/cross-group, FR-08/FR-11):** extend
  `backend/app/interface/http/control_plane.py` with content-free safety
  aggregates, audit, and operating-owner global actions under deny-by-default,
  step-up, and audit (SPEC-021). No endpoint returns message text, prompts,
  usernames, or raw platform IDs.
- **No new public endpoints.** `/`, `/health`, `/live`, `/ready`, the Telegram
  webhook route, and the `/control/*` plane keep their contracts.
- **Rate-limit and step-up controls cover review and escalation endpoints**
  (NFR-05); no action grants a moderator Telegram group authority or access to
  conversation content.

## 6. Workers

- Existing workers remain the enforcement and recording surface:
  `response_planning_worker.py` (pre/post-generation decisions and rate-limit
  events), `outbound_delivery_worker.py` (pre-delivery recheck and targeting
  filter), `telegram_command_worker.py` (opt-outs, `/forget_me`, per-group
  settings), and the ingress/retention workers.
- **Protective enforcement** is applied in the existing planning and delivery
  targeting paths (a decision + targeting filter change), not a new
  supervisor.
- **Signal aggregation and review-queue materialization** are on-demand,
  idempotent computations reading durable content-free state; they may live as
  an application-layer service rather than a new worker. If a dedicated worker
  is justified, it is a separate bounded runtime surface that never runs in the
  webhook path, never supervises workers, and has no busy loop, unbounded
  retry, or dead-letter escalation beyond SPEC-016 (NFR-07).
- Alerting evaluation stays in the SPEC-023 out-of-band surface.

## 7. Authorization

- **Per-group protected changes** (safety settings, protect member, per-group
  review actions) require SPEC-010 fresh Telegram authorization.
- **Escalated and cross-group actions** (operating-owner review and global
  actions) require SPEC-021 deny-by-default control-plane authorization with
  step-up and explicit confirmation for high-impact actions (NFR-05,
  FR-08/FR-09).
- **Protection reversibility:** protective enforcement is reversible only
  through the FR-08 review path (restore targeting); single signals never
  create permanent protection (spec "Failure handling").
- Moderator and operating-owner actions are audited (FR-12) and never grant
  Telegram group authority, never expose conversation content, and never grant
  the rollback role; the SPEC-022 rollback authority remains the only role that
  may trigger production rollback or webhook disable/delete (FR-11).
- Moderator account compromise is handled by SPEC-021 revocation, step-up, and
  audit; protective actions remain reversible (spec "Failure handling").

## 8. Moderation Pipeline

1. Ingress → deterministic eligibility (SPEC-005) → pre-generation safety
   decision recorded (`safety_policy_decisions`, `pre_generation`).
2. Optional bounded advisory classification of intent signals; never
   authoritative over structural rules, fail-closed to the stricter outcome.
3. Generation → post-generation structural check (`post_generation`):
   hard-boundary REFUSE/TRANSFORM with `safe_fallback`; model refusal valid.
4. Targeting recheck before every outbound mention/teasing against current
   opt-out, privacy-deletion, and protection state (FR-03).
5. Pre-delivery safety decision (`pre_delivery`) in the delivery worker.
6. Rejected or neutral-fallback outcomes are never retried as a compliance
   request (FR-01); refusals are short, language-aware, and non-escalating
   (FR-02).
7. Sustained signals (FR-06) trigger protective enforcement (FR-07): stop
   targeting, reduce or pause interaction with the abusive participant, record
   a content-free protective action; reversible only through review.
8. Review queue (FR-08): content-free items with category, stage, outcome
   counts, opaque identifiers, timeline, and protection state; actions
   acknowledge/escalate/restore/pause-or-restrict.
9. Escalation (FR-11): sustained or high-severity signals alert the operating
   owner through the content-safe SPEC-023 incident path; evidence is
   metadata-only per SPEC-022.

## 9. Abuse Detection

- **Signal catalog (FR-06), all content-free counts:**
  - Safety decision counts by category and outcome (from
    `safety_policy_decisions`).
  - Mention and teasing frequency toward a single participant (from outbound
    targeting data).
  - Rate-limit violations and delivery-budget pressure (from
    `rate_limit_events`).
  - Repeated private-memory-extraction attempts and dangerous-instruction
    requests (from refusal reason codes).
  - Repeated prompt-injection or manipulation attempts (from
    `prompt_injection_action_attempt`/`unsupported_action` outcomes).
- Signals are counts and categories only, never content; thresholds are
  configuration owned by the group administrator and the operating owner with
  conservative defaults (FR-06).
- Manipulation is never complied with (FR-04): injection creates no platform
  action, private memory is never disclosed on demand, harmful requests are
  refused regardless of framing.
- Loop prevention (FR-05): no `answer_every_message` mode; eligibility and
  rate-limit checks precede expensive provider calls; the assistant does not
  join pile-ons, repeat insults, or continue a conversation a member asked it
  to stop; bot-to-bot and assistant-to-assistant loops are broken by existing
  eligibility rules.
- Abuse prevention is layered (spec "Abuse prevention model"): deterministic
  structural guard → advisory classification → content-free signal aggregation
  → protective enforcement → human review and escalation → audit and
  accountability.

## 10. Privacy

- No new content retention (NFR-04): safety signals, review queues, audit
  records, alert payloads, and incident evidence carry no message content,
  prompts, memories, vectors, provider bodies, usernames, raw platform IDs, or
  credentials (NFR-01, FR-12).
- Rejected content is never persisted beyond existing bounded incoming-message
  retention and is never copied into moderation artifacts.
- User protection is targeting-only (FR-10): members are never profiled, rated,
  or sanctioned for content; protective state is limited to targeting and
  interaction behavior.
- Opt-out, privacy-deletion, and protection state are rechecked before every
  outbound targeting action (FR-03); `/forget_me` erasure (SPEC-011) clears
  targeting state and privacy-deleted participants are never targeted.
- Private memory never surfaces in group context and is never disclosed on
  demand, including under manipulation attempts (FR-04).
- Retention of safety decision and review records is governed separately from
  product-content retention and stays consistent with SPEC-011 controls
  (NFR-04).
- Staging and drill data are synthetic; production content is never copied into
  moderation artifacts, evidence, or review documents.

## 11. Failure Modes

| Scenario | Required handling (implementation) |
| --- | --- |
| Advisory classifier or provider unavailable | Deterministic structural guard remains authority; stricter default applies; no safety bypass (NFR-02). |
| Safety subsystem outage | Fail closed; observable and alertable (SPEC-023); no busy loop or unbounded retry (NFR-07). |
| False-positive moderation signal | Content-free counts and review path; no permanent protective state from a single signal; administrator can restore after review (FR-08). |
| False-negative (harmful output) | Structural guard and neutral fallback; incident per SPEC-023 with content-free evidence; rule/threshold review. |
| Repeated abuse toward a member | Protective enforcement (FR-07), review, and escalation (FR-11); the member is never asked to justify. |
| Manipulation of the assistant | Refusal per FR-04; counted as a content-free signal; never complied with. |
| Moderator account compromise | SPEC-021 revocation, step-up, audit; no content or secrets exposed; protective actions reversible. |
| Review queue growth | Bounded retention, escalation, alerting; no content backlog; operator replay discipline. |
| Evidence or alert leakage | Content-safety guard rejects the artifact before distribution (SPEC-022/023); review gate. |

## 12. Metrics

- The existing closed catalog is the authority. Reuse where possible:
  `january_safety_decisions_total` (`stage`/`outcome`/`reason`) is the primary
  signal source; `january_rate_limit_events_total`, targeting-filter outcomes,
  and recovery/worker metrics contribute to FR-06 signals.
- New metrics, if genuinely needed, follow SPEC-015 rules (declared in
  `METRICS`, closed low-cardinality labels, no prohibited names; any addition
  is called out in review). Candidate additions for the implementation phase:
  - `january_safety_protective_actions_total` (`action`: stop_targeting,
    reduce_interaction, pause_interaction, restore_targeting) — FR-07.
  - `january_safety_review_actions_total` (`action`, `outcome`) — FR-08.
  - `january_safety_escalations_total` (`severity`) — FR-11.
  - `january_safety_signals_total` (`signal_type`, `scope` in
    {conversation, participant, deployment}) — aggregated counts only,
    never participant identifiers (NFR-03).
  - `january_safety_fail_closed_total` (`subsystem`) — count of fail-closed
    stricter defaults taken.
  - Review-queue depth is better derived from durable state than a new gauge
    kind; if a gauge is still required, the catalog kind set must be extended
    deliberately.
- No metric label ever carries participant IDs, request IDs, usernames, or
  content (NFR-03).

## 13. Alerting

- Extend the existing content-safe alert rule catalog
  (`backend/app/application/observability/alerts.py`,
  `docs/runbooks/alerting.md`) with safety rules under the same severity model,
  debounce, severity caps, acknowledgement expiry, and escalation order
  (operating owner -> incident contact -> rollback authority):
  - `safety_fail_closed_surge` — rate of fail-closed stricter defaults
    exceeds threshold; Sev2 (capped), detection within ~15 min.
  - `safety_protective_actions_surge` — sustained protective enforcement
    bursts; Sev2 (capped) so the operating owner can review.
  - `safety_review_queue_growth` — review queue depth or oldest pending item
    grows; Sev3, escalating on sustained growth.
  - `safety_escalation_high_severity` — sustained high-severity signals toward
    a member; Sev1/2 page to the operating owner (FR-11), metadata-only
    evidence consistent with SPEC-022 bundles.
  - Reuse `alerting_staleness`; alerting's own loss remains alertable.
- Every payload passes `assert_content_safe`
  (`app.application.observability.content_safety`) before emission (NFR-01);
  no rule produces a busy loop or unbounded retry; thresholds and rule targets
  are proposed defaults requiring operating-owner approval, consistent with
  SPEC-023.

## 14. Validation Strategy

- Existing validators remain authoritative and must pass unchanged:
  `scripts/validate.sh`, `scripts/validate-observability.sh`,
  `scripts/validate-live-acceptance.sh`, and the DB-backed
  `validate-ingress.sh`/`validate-safety.sh`/`validate-memory.sh`/
  `validate-commands.sh`/`validate-reliability.sh` suite.
- Implementation-phase proof is executable and observable: deterministic
  synthetic signal aggregation and threshold evaluation; protective
  enforcement and standing-stop behavior; targeting recheck under
  opt-out/protection/privacy-deletion state; review-queue action idempotency
  and authorization; content-safe rendered alerts/review items/evidence
  (guard rejects prohibited keys/credentials); fail-closed behavior under
  simulated subsystem failure; no weakening of SPEC-011/012/016/021/022/023
  boundaries; and, unless migrations are separately approved, confirmation that
  no schema migration was added (mirroring the `validate-observability.sh`
  no-migration guard).
- CI and synthetic runs never claim comprehensive moderation or that no harmful
  interaction can occur (NFR-09); moderation coverage is bounded, documented,
  and measured only from approved-environment evidence (SPEC-023).
- DB-backed runs on this host require the temporary uncommitted `label=disable`
  Docker SELinux override and isolated ports; this handoff adds no committed
  Compose change.

## 15. Test Plan

- Unit tests (deterministic, no live I/O):
  - `backend/tests/test_safety.py` additions: one test per FR-02 hard boundary;
    protection-state filtering in `ResponsePlanPolicy.apply`; targeting recheck
    under opt-out/protection/privacy deletion; standing-stop persistence;
    no-config-disables-boundaries assertion; no answer-every-message mode.
  - New `backend/tests/test_safety_signals.py`: signal aggregation and
    threshold evaluation over seeded `safety_policy_decisions`/rate-limit
    data; conservative defaults.
  - New `backend/tests/test_review_queue.py`: the four actions, idempotency,
    authorization denial, content-safe item rendering.
  - New `backend/tests/test_moderation_alerts.py`: alert rule rendering,
    severity caps, debounce, content-safety rejection.
  - Adversarial tests: prompt injection creates no platform action,
    private-memory extraction refused, manipulation counted, bot-to-bot loop
    broken.
- Integration tests (existing DB-backed patterns under the override):
  decision recording; protective-action recording; review-queue persistence
  (if the additive migration is approved); `/forget_me` interplay; per-group
  settings via `telegram_command_jobs`; escalation evidence content-safe.
- Regression: existing non-integration and integration suites stay green; the
  three schema-pin integration tests assert head `0014_authenticated_control_plane`
  until any separately approved migration updates them in the same change.
- No migration and no runtime-behavior regression are tested for beyond the
  approved scope.

## 16. Rollback

- SPEC-020 rollback discipline applies; forward-fix rather than routine
  production schema downgrade remains the rule.
- Protective enforcement is reversible through the FR-08 review path (restore
  targeting); an administrator may clear protection after review; standing stop
  honors the member's persistent request.
- New enforcement surfaces ship behind the `JANUARY_` environment boundary so
  a misbehaving protective behavior can be disabled without a code rollback —
  but no flag, operator action, or incident procedure may disable the SPEC-012
  hard boundaries (NFR-02).
- If additive migrations are approved, rollback is forward-fix with a written
  recovery step per the approved migration rationale; the SPEC-022 rollback
  authority is the only role that may trigger production rollback or webhook
  disable/delete during an incident (FR-11).

## 17. Deployment

- SPEC-020 deployment boundaries: new settings enter through
  `Settings`/`JANUARY_` environment variables, secrets through the external
  secret boundary; no committed Compose override (the host `label=disable`
  SELinux override is temporary and uncommitted).
- New configuration: per-group safety level, teasing cap, response frequency,
  and threshold defaults (operating-owner approved); review-queue retention
  bound; alert-rule targets consistent with SPEC-023.
- Staging evidence before production reliance: staged drills with synthetic
  data for protective enforcement, review flow, escalation, and fail-closed
  behavior; content-safe evidence bundles per SPEC-022.
- No new external monitoring/notification backend is required; reuse the
  SPEC-023 alerting surface and approved channels.

## 18. Risks

| Risk | Mitigation |
| --- | --- |
| Scope creep into public community moderation | Explicit moderation boundaries; the assistant never moderates user-to-user content or sanctions users. |
| Privacy expansion from moderation | Content-free signals only; no rejected-content storage; SPEC-011 retention parity. |
| False positives harm members | Single signals never create permanent protection; human review; reversible actions. |
| Classifier overrides hard rules | Deterministic structural guard is authority; advisory checks never authoritative. |
| Abuse overwhelms the assistant | Rate limits, eligibility, bounded signals, protective enforcement, alerting. |
| Prompt injection or extraction | FR-04 refusal, structural guard, content-free signal counting, no platform-action injection. |
| Moderator abuse or compromise | Deny-by-default authorization, step-up, audit, revocation; no content access. |
| Over-moderation reduces product value | Conservative thresholds, per-group configurability, review path, measured coverage. |
| Safety adds latency to webhook path | Deterministic checks before provider I/O; advisory classification bounded and non-blocking. |
| New persistence without approval | SPEC-023 migration discipline: audit representability first; additive migrations only with separate approval. |
| Protective state becomes permanent | Reversibility gated behind the review path; retention bound. |

## 19. Dependencies

- SPEC-010 Telegram administration commands and fresh authorization.
- SPEC-011 memory privacy, retention, erasure, and forget semantics.
- SPEC-012 safety policy and distributed rate limiting (authoritative safety
  enforcement).
- SPEC-015 observability and content-safe telemetry.
- SPEC-016 recovery, dead-letter, and quarantine discipline.
- SPEC-017 ambient selective participation and social response policy.
- SPEC-018 and SPEC-019 summaries and semantic-memory boundaries.
- SPEC-020 deployment, secrets, readiness, migration, and recovery.
- SPEC-021 authenticated control plane, authorization, and audit.
- SPEC-022 live-acceptance evidence and operating-owner/incident-contact/
  rollback-authority roles.
- SPEC-023 SLOs, alerting, and incident operations.
- Telegram platform capabilities (group bot visibility, Privacy Mode, member
  events); platform-level reporting/banning remain Telegram's own features.
- Product Owner and operating-owner approval of thresholds, review scope,
  escalation policy, and any additive migration.

## 20. Future Extensions

- Public community moderation and user-to-user content policy.
- Autonomous user sanctions, banning, muting, expelling, or warnings.
- Semantic moderation of all messages, media, or voice content; user profiling;
  reputation scoring; cross-group behavioral tracking.
- A moderation dashboard UI (deferred to the SPEC-021 control-plane roadmap).
- Platform-level reporting and enforcement integrations beyond the assistant's
  own boundary.
- Zalo equivalents of this contract (deferred behind SPEC-014).
- Multi-tenant or billing-backed moderation services.
