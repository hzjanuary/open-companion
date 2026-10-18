# SPEC-024 Safety Moderation, Abuse Prevention, and User Protection

## Status

APPROVED DESIGN. Product specification approved by the Product Owner. This
document authorizes product and acceptance design only. It authorizes no
runtime implementation, migration, validator, test, ADR, runbook, deployment
manifest, commit, or push until a separate implementation phase is explicitly
approved.

SPEC-023 is implemented as an approved candidate; its proposed operating-owner
objectives and notification channels remain to be ratified. SPEC-022 live
acceptance remains an externally gated operational step. SPEC-014 remains
deferred behind its Zalo prerequisite and no Zalo runtime is authorized.
SPEC-024 does not begin a later specification and does not change the safety,
privacy, rate-limit, or administration policy contracts it builds on.

## Product goals

January/Lumi participates in Telegram groups of friends. SPEC-024 makes the
assistant a safe participant under abuse: the assistant never produces harmful
output, never targets a member who asked not to be targeted, cannot be
manipulated into leaking private memory or executing unsafe platform actions,
and gives group administrators and the operating owner bounded, content-free
visibility and control over safety signals. It formalizes the existing safety
policy (SPEC-012) into an observable product surface with user protection,
bounded moderation boundaries, and human-in-the-loop review — without turning
the assistant into a public community moderator and without storing the content
it rejects.

## Problem statement

SPEC-012 establishes `safety-policy-v1` as deterministic structural
enforcement: hard boundaries prohibit harassment, identity attacks, targeted
humiliation, private-data disclosure, sexual content involving minors,
self-harm encouragement, dangerous instruction execution, and persistent or
sensitive teasing, and it is explicitly not comprehensive semantic moderation.
SPEC-011 bounds memory to same-conversation visibility with erasure controls.
SPEC-010 and SPEC-021 provide Telegram-command and control-plane
administration. SPEC-015 and SPEC-023 provide content-safe observability and
alerting.

The remaining product gaps are:

1. Safety decisions are enforced but not operator-observable; there is no
   bounded way for an administrator or operating owner to see that the
   assistant is being abused, by whom, and how often.
2. User protection is opt-out based and per-command; a member experiencing
   repeated targeting has no standing protection signal and no escalation path.
3. Abuse of the assistant itself — prompt injection, private-memory extraction
   attempts, dangerous-instruction requests, looping, or cost abuse — is
   resisted by existing controls but not aggregated into protective action.
4. There is no defined boundary between what the assistant moderates, what
   administrators review, and what is left to the group and the platform.

SPEC-024 closes these gaps with a safety moderation and user protection
contract: content-free abuse signals, protective enforcement, bounded
moderation boundaries, administrator and operator review, and a user
protection model — all consistent with the existing fail-closed, content-safe,
and deterministic-structural safety architecture.

## Scope

In scope are assistant-output safety moderation, targeting protection, abuse
signals, protective enforcement, user protection controls, moderator review,
administrator safety settings, escalation to the operating owner, and the
content-free evidence and audit records those produce.

Existing product behavior remains authoritative:

- `safety-policy-v1` deterministic structural enforcement (SPEC-012) is the
  authority for every safety decision; any advisory classification added by
  SPEC-024 never overrides it.
- PostgreSQL remains canonical for product, work, and content-free safety
  decision state; Redis is at-least-once coordination; Qdrant remains
  rebuildable derived state.
- Memory, privacy, retention, erasure, and forget semantics remain governed by
  SPEC-011; private memory never surfaces in group context and is never
  disclosed on demand.
- Rate limits and delivery budgets remain governed by SPEC-012; ambiguous
  Telegram delivery remains `delivery_unknown` or quarantine and is never
  blindly replayed.
- Telegram administrator commands continue to require fresh current group
  authorization for protected changes (SPEC-010); control-plane membership is
  not Telegram group authority (SPEC-021).
- The assistant never autonomously bans, expels, or punishes users; user-to-user
  conversation remains the group's and the platform's responsibility.
- Logs, metrics, health, alert payloads, incident records, safety decision
  records, and review queues remain free of rejected text, prompts, provider
  bodies, memories, vectors, raw platform IDs, usernames, tokens, and webhook
  secrets.

## Out of scope

- Runtime code, migrations, validators, tests, ADRs, runbooks, deployment
  manifests, or dashboard UI in this design phase.
- Public Telegram community moderation, global content policy, or moderation
  of general user-to-user conversation on behalf of a community.
- Autonomous user sanctions — banning, muting, expelling, warning, or otherwise
  punishing members without an administrator decision.
- Deep semantic classification of all group messages, media, or voice content;
  user profiling; reputation scoring; or cross-group behavioral tracking.
- Storing, transmitting, or reviewing the content of rejected messages,
  prompts, memories, or provider bodies at any layer.
- Replacing SPEC-012 safety enforcement, SPEC-011 privacy controls, SPEC-010
  command administration, SPEC-021 control-plane authorization, or SPEC-023
  incident operations.
- Weakening rate limits, redaction, retention, opt-outs, or fail-closed
  behavior to reduce friction.
- Multi-tenancy billing, public reporting features, Zalo equivalents
  (deferred behind SPEC-014), or new Telegram media/voice behavior.

## Functional requirements

### FR-01: Safety decision pipeline

Every eligible interaction passes the existing deterministic structural safety
guard before provider and Telegram I/O (SPEC-012), both pre-generation and
post-generation. SPEC-024 makes that pipeline observable: each decision
produces a content-free record with category, stage, outcome, opaque
conversation/participant references, policy version, and timestamp. A rejected
or neutral-fallback decision is never retried as a compliance request.

### FR-02: Assistant-output safety

The assistant rejects or neutral-fallbacks to behavior that constitutes
harassment, identity attacks, hate, targeted humiliation, sexual content
involving minors, self-harm encouragement, private-data disclosure, dangerous
instruction execution, and persistent or sensitive teasing (SPEC-012,
FR-018). No configuration disables these boundaries or enables roast mode.
Refusals are short, language-aware, and non-escalating.

### FR-03: Targeting protection

Before every outbound mention or teasing action, the runtime rechecks the
current participant's opt-out state, privacy-deletion state (SPEC-011), and
protection level (FR-10). A participant who opted out, deleted their profile,
or is protected is never targeted. Stopping is immediate and persistent: a
single request from the participant to stop targeting is honored thereafter.

### FR-04: Abuse of the assistant

The assistant cannot be manipulated into unsafe behavior:

- Prompt injection must not create arbitrary platform actions (NFR-004).
- Requests to reveal private or forgotten memory are refused; private memory is
  never disclosed in group context on demand.
- Requests to produce harmful, dangerous, or unsafe output follow FR-02
  regardless of framing.
- Repeated or adversarial manipulation attempts are counted as content-free
  abuse signals (FR-06), never complied with.

### FR-05: Loop and amplification prevention

The assistant never amplifies abuse or creates loops:

- No `answer_every_message` mode exists (SPEC section 9.4).
- Eligibility and rate-limit checks run before any expensive provider call
  (SPEC FR-005, SPEC-012).
- The assistant does not join pile-ons, repeat insults, or continue a
  conversation a member asked it to stop.
- Bot-to-bot and assistant-to-assistant response loops are broken by the
  existing eligibility rules and remain prohibited.

### FR-06: Abuse signal detection

The assistant aggregates content-free abuse signals per conversation and
participant:

- Safety-decision counts by category and outcome.
- Mention and teasing frequency toward a single participant.
- Rate-limit violations and delivery-budget pressure.
- Repeated private-memory-extraction attempts and dangerous-instruction
  requests.
- Repeated prompt-injection or manipulation attempts.

Signals are stored as counts and categories only, never as content. Thresholds
are configuration owned by the group administrator and the operating owner,
with conservative defaults.

### FR-07: Protective enforcement

When a participant's signals exceed the configured threshold, the assistant
applies protective behavior without storing content and without sanctioning the
participant:

- Stops targeting the affected participant (mentions and teasing).
- Reduces or pauses responses that interact with the abusive participant.
- Records a content-free protective action visible to the group administrator
  and the operating owner.

Protective enforcement is reversible only through the review path (FR-08) and
never requires exposing the triggering content.

### FR-08: Moderation review queue

A bounded, content-free review queue surfaces escalated safety signals to the
group administrator (per-group scope) and the operating owner (escalated or
cross-group scope). Each review item contains category, stage, outcome counts,
opaque identifiers, timeline, and protection state — no message text, prompts,
memories, or usernames. Administrator actions are acknowledge, escalate to the
operating owner, restore targeting after review, or request that the assistant
pause or restrict behavior toward a participant. Queue actions require fresh
Telegram authorization (SPEC-010) or control-plane authorization (SPEC-021).

### FR-09: Administrator safety controls

Group administrators can configure per-group safety settings — safety level,
teasing cap, response frequency, protection of specific members, and review
visibility — without weakening the hard boundaries of SPEC-012. Pause/resume
and existing group configuration commands remain compatible. All protected
changes use the existing fresh-authorization contract.

### FR-10: User protection model

Every member can stop being targeted by the assistant, and the assistant honors
it immediately and persistently (existing mention/teasing opt-out, FR-018).
A group administrator can mark a member as protected (FR-09), and a protected
member is never targeted. Members are never profiled, rated, or punished for
content; protective state is limited to targeting and interaction behavior.

### FR-11: Escalation to the operating owner

Sustained or high-severity safety signals alert the operating owner through the
existing content-safe alerting and incident path (SPEC-023). Incidents carry
metadata-only evidence consistent with SPEC-022 evidence bundles. The rollback
authority remains the only role that may trigger production rollback or
disable/delete the Telegram webhook during an incident.

### FR-12: Evidence and audit

Every safety decision, protective action, review action, and escalation
produces a content-safe audit/evidence record consistent with SPEC-015/021/022:
category, stage, outcome, opaque identifiers, actor, timestamp, and policy
version. Rejected text, prompts, memories, vectors, provider bodies,
usernames, raw platform IDs, tokens, and secrets never appear in any artifact.

## Non-functional requirements

### NFR-01: Content safety

All safety signals, review queues, audit records, alert payloads, and incident
evidence carry no message content, prompts, memories, vectors, provider
bodies, usernames, raw platform IDs, or credentials. The SPEC-022
`assert_content_safe` discipline applies to every new artifact.

### NFR-02: Deterministic, fail-closed enforcement

The hard safety boundaries of SPEC-012 are deterministic structural rules that
apply even when advisory classifiers, providers, or safety subsystems are
unavailable or degraded. No configuration, operator action, or incident
procedure bypasses them. When an advisory check cannot be evaluated, the
assistant defaults to the stricter outcome.

### NFR-03: Low cardinality and bounded labels

New telemetry uses closed, low-cardinality outcome and category labels only
(SPEC-015). No unbounded label values such as participant IDs, request IDs, or
usernames are introduced.

### NFR-04: Privacy and retention parity

SPEC-024 adds no content retention. Safety decision and review records are
content-free and follow retention consistent with SPEC-011; rejected content is
never persisted beyond the existing bounded incoming-message retention and is
never copied into moderation artifacts.

### NFR-05: Security

Review, protection, and escalation actions are authenticated and authorized
server-side (deny-by-default). High-impact moderator actions require the
documented role, explicit confirmation, and recent-authentication boundary
consistent with SPEC-021. No action grants a moderator Telegram group authority
or access to conversation content. Rate-limit and step-up controls cover review
and escalation endpoints.

### NFR-06: Performance

Safety checks run before expensive provider calls and add no latency to the
webhook acknowledgement path beyond existing deterministic checks. Advisory
classification, where present, is bounded and non-blocking with a fail-closed
default.

### NFR-07: Reliability

Safety subsystem failures fail closed and are themselves observable and
alertable (SPEC-023). Review and protective actions are idempotent; no busy
loop, unbounded retry, or dead-letter escalation is introduced (SPEC-016).

### NFR-08: Compatibility

Existing command behavior, response policy, personality, memory, privacy,
retention, rate limits, delivery certainty, recovery, control-plane, and
observability contracts remain unchanged.

### NFR-09: No false confidence

Synthetic and CI validation never claims that moderation is comprehensive or
that no harmful interaction can occur. Moderation coverage is bounded,
documented, and measured only from approved-environment evidence (SPEC-023).

## Privacy requirements

- Safety moderation never inspects, stores, or transmits the content of
  rejected messages, prompts, memories, or provider bodies. Only categories,
  stages, outcomes, counts, and opaque identifiers are recorded.
- User protection is targeting-only: members are never profiled, rated, or
  sanctioned for their content.
- Review queues expose no message text, prompts, memories, usernames, or raw
  platform IDs; correlation uses opaque internal identifiers only.
- Protection state, opt-outs, and privacy-deletion state (SPEC-011) are
  rechecked before every outbound targeting action.
- Private memory never surfaces in group context and is never disclosed on
  demand, including under manipulation attempts.
- Retention of safety decision and review records is governed separately from
  product-content retention and stays consistent with SPEC-011 privacy and
  retention controls.
- Staging and drill data are synthetic; production content is never copied into
  moderation artifacts, evidence, or review documents.

## Abuse prevention model

The abuse prevention model is layered, content-free, and human-in-the-loop:

1. **Deterministic structural guard** — SPEC-012 hard boundaries enforced in
   code before and after generation; never disabled, never advisory.
2. **Advisory classification** — bounded classification of intent signals that
   feeds the guard and signal aggregation; optional, never authoritative over
   structural rules.
3. **Content-free signal aggregation** — per-conversation and per-participant
   counts of safety decisions, targeting frequency, rate-limit violations,
   memory-extraction attempts, and manipulation attempts.
4. **Protective enforcement** — threshold-driven reduction or cessation of
   interaction with an abusive participant, without sanctions and without
   storing content.
5. **Human review and escalation** — group-administrator review of per-group
   signals, escalation to the operating owner, and content-safe incident
   handling.
6. **Audit and accountability** — every decision and action is recorded in
   content-free audit/evidence records.

The assistant is never the judge of user-to-user disputes, never applies
punitive action, and never expels or bans members. Abuse prevention targets the
assistant's own behavior and its protection of members, not community policing.

## Moderation boundaries

Moderation is deliberately bounded:

- **Assistant output** — the assistant's own responses and actions are the
  primary moderated surface; FR-02 boundaries apply unconditionally.
- **Requests to the assistant** — manipulation, extraction, and
  dangerous-instruction attempts are resisted and counted, never complied with.
- **Targeting of members** — mentions, teasing, and repeated interaction toward
  a member are moderated through opt-outs, protection state, and signal
  thresholds.
- **User-to-user content** — not moderated by the assistant; left to the group
  and the platform.
- **Autonomous action** — the assistant never sanctions users; every
  enforcement and review outcome is either protective behavior or an
  administrator/operator decision.

Moderation scope is per group by default; cross-group signals reach the
operating owner only as content-free escalation and alerting (FR-11). The
assistant never acts as a public community moderator (SPEC section 7.3).

## User protection model

User protection has four layers:

1. **Opt-out and standing stop** — any member can stop mentions and teasing;
   the assistant honors it immediately and persistently (existing FR-018).
2. **Protection flag** — a group administrator can protect a member (FR-09);
   protected members are never targeted.
3. **Privacy and memory protection** — private memory is never surfaced or
   disclosed on demand (SPEC-011); `/forget_me` erasure is honored.
4. **Harm prevention and escalation** — no self-harm encouragement, dangerous
   instruction execution, or targeted humiliation (FR-018); sustained abuse
   toward a member escalates to the operating owner through content-safe
   alerting (FR-11).

Protection is defensive: it reduces or stops the assistant's interaction with a
member, never increases scrutiny of the member's content, and never requires
the member to prove harm.

## Administrator controls

- Per-group safety settings: safety level, teasing cap, response frequency, and
  protection of specific members (FR-09), applied without weakening SPEC-012
  boundaries.
- Review queue for per-group safety signals with acknowledge, escalate, restore
  targeting, and pause/restrict actions (FR-08).
- Pause/resume and existing group configuration commands remain compatible
  (SPEC-010).
- Control-plane surfaces (SPEC-021) expose content-free safety aggregates,
  audit, and operating-owner global actions with explicit confirmation and
  step-up for high-impact actions.
- No administrator or operating-owner action silently grants Telegram group
  authority or access to conversation content.

## Failure handling

| Scenario | Required handling |
| --- | --- |
| Advisory classifier or provider unavailable | Deterministic structural guard remains authority; stricter default applies; no safety bypass. |
| Safety subsystem outage | Fail closed; observable and alertable (SPEC-023); no busy loop or unbounded retry. |
| False-positive moderation signal | Content-free counts and review path; no permanent protective state from a single signal; administrator can restore after review. |
| False-negative (harmful output) | Structural guard and neutral fallback; incident per SPEC-023 with content-free evidence; rule/threshold review. |
| Repeated abuse toward a member | Protective enforcement (FR-07), review, and escalation (FR-11); member is never asked to justify. |
| Manipulation of the assistant | Refusal per FR-04; counted as content-free signal; never complied with. |
| Moderator account compromise | SPEC-021 revocation, step-up, audit; no content or secrets exposed; protective actions reversible. |
| Review queue growth | Bounded retention, escalation, alerting; no content backlog; operator replay discipline. |
| Evidence or alert leakage | Content-safety guard rejects the artifact before distribution (SPEC-022/023). |

## Acceptance criteria

Design review is complete when the Product Owner approves:

- The product goals and the bounded moderation scope.
- The functional requirements FR-01 through FR-12, including the safety
  decision pipeline, targeting protection, abuse signals, protective
  enforcement, review queue, and escalation.
- The non-functional requirements, including deterministic fail-closed
  enforcement, content safety, privacy parity, and security.
- The abuse prevention model, moderation boundaries, user protection model, and
  administrator controls.
- The failure-handling table and risks.
- The deferred-work list and the next bounded task.

A future implementation phase is complete only with executable or observable
proof: content-free safety decision and review records, protective enforcement
behavior, targeting protection under opt-out/protection/privacy-deletion state,
fail-closed behavior under subsystem failure, content-safe artifacts, the
existing validator matrix green, and no weakening of SPEC-011/012/016/021/022/
023 boundaries.

## Risks

| Risk | Required mitigation |
| --- | --- |
| Scope creep into public community moderation | Explicit moderation boundaries; assistant never moderates user-to-user content or sanctions users. |
| Privacy expansion from moderation | Content-free signals only; no rejected-content storage; SPEC-011 retention parity. |
| False positives harm members | Single signals never create permanent protection; human review; reversible actions. |
| Classifier overrides hard rules | Deterministic structural guard is authority; advisory checks are never authoritative. |
| Abuse overwhelms the assistant | Rate limits, eligibility, bounded signals, protective enforcement, alerting. |
| Prompt injection or extraction | FR-04 refusal, structural guard, content-free signal counting, no platform-action injection. |
| Moderator abuse or compromise | Deny-by-default authorization, step-up, audit, revocation; no content access. |
| Over-moderation reduces product value | Conservative thresholds, per-group configurability, review path, measured coverage. |
| Safety adds latency to webhook path | Deterministic checks before provider I/O; advisory classification bounded and non-blocking. |

## Dependencies

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
- Product Owner and operating-owner approval of thresholds, review scope, and
  escalation policy.

## Deferred work

- Public community moderation and user-to-user content policy.
- Autonomous user sanctions, banning, muting, expelling, or warnings.
- Semantic moderation of all messages, media, or voice content; user profiling;
  reputation scoring; cross-group behavioral tracking.
- A moderation dashboard UI (deferred to the SPEC-021 control-plane roadmap).
- Platform-level reporting and enforcement integrations beyond the assistant's
  own boundary.
- Zalo equivalents of this contract (deferred behind SPEC-014).
- Multi-tenant or billing-backed moderation services.

Status: APPROVED DESIGN
