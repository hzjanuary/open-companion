# SPEC-029 — Proactive Scheduling and Durable Social Participation

Status: **APPROVED PRODUCT SPEC** under the Product Owner authority granted by
the SPEC-029 end-to-end goal. The repository implementation candidate is under
release review after repository-safe validation; Docker-backed proof remains
pending and this status is not production approval.

## Purpose

Let a person ask Lumi to remind them later and separately opt into an occasional
companion check-in, while keeping every proactive action bounded, explainable,
private, cancellable and recoverable. SPEC-029 does not create an unrestricted
autonomous agent.

## Problem statement

The current Telegram companion responds only to incoming events. It has durable
jobs and delivery but no authoritative user timezone, recurrence, occurrence
identity, downtime semantics or proactive consent. Adding only in-memory timers
would lose work on restart; replaying every missed time would spam users; treating
a reminder as general permission to message would violate consent.

## Goals

- Private users can create, list and cancel bounded one-time or recurring reminders.
- Private users can separately enable or disable a bounded neutral check-in.
- UTC execution is derived deterministically from an explicit IANA timezone.
- Downtime produces at most one logical catch-up, never a burst.
- PostgreSQL owns schedules/occurrences; leases and existing outbox own recovery.
- Privacy, safety, rate limits, delivery ambiguity and content governance remain true.

## Explicit non-goals

No group schedules; arbitrary cron; workflow engine; webhook/email/calendar
integration; external calendar sync; generated proactive LLM text; delayed model
follow-up; multi-assistant routing; SPEC-030 tenancy; Zalo; TTS; video; web browsing;
autonomous goals/loops; automatic memory inference; or new provider capability.
Editing a schedule is cancel-and-recreate in v1.

## User stories

- As a private user, I set my timezone and create a future reminder in local time.
- As a private user, I create daily or selected-weekday reminders for at most one year.
- As a private user, I see my own upcoming reminders and cancel one by public ID.
- As a private user, I separately opt into or out of neutral companion check-ins.
- As a privacy-conscious user, erasure prevents queued proactive sends and clears text.
- As an operator, I can observe bounded states without seeing schedule content in metrics.

## Terminology

- **Schedule:** the durable user-owned rule and, for reminders, user text.
- **Occurrence:** one stable logical firing time derived from a schedule.
- **Reminder:** explicit user-requested delivery of their stored text.
- **Check-in:** a separately consented, code-owned neutral companion message.
- **Local schedule:** wall-clock rule interpreted in an explicit IANA timezone.
- **Catch-up:** at most one recent missed occurrence considered after downtime.
- **Possible delivery:** Telegram I/O may have happened; never automatically duplicate.
- **Public ID:** bounded opaque schedule reference safe for the owning user's commands.

## Bounded v1 command surface

Only zero-offset Telegram `bot_command` entities in typed text qualify. All
commands below are private-conversation only and creator-scoped:

- `/timezone status` or `/timezone <IANA-name>`;
- `/quiet_hours status`, `/quiet_hours off`, or
  `/quiet_hours HH:MM-HH:MM`;
- `/remind at YYYY-MM-DD HH:MM <text>`;
- `/remind daily HH:MM <text>`;
- `/remind weekly mon,wed HH:MM <text>`;
- `/reminders`;
- `/cancel_reminder <public-id>`;
- `/checkins status`, `/checkins off`,
  `/checkins on daily HH:MM`, or `/checkins on weekly <weekday> HH:MM`.

Malformed, group, unauthorized, over-limit or unavailable requests receive a
fixed deterministic reply and create no partial schedule. Public replies expose
only the owning user's public IDs and local schedule facts, never internal IDs.

## Scheduling model and limits

- Maximum **10 active reminder schedules** per exact private participant and
  conversation; maximum **one active check-in schedule**.
- Reminder text: 1–100 Unicode code points after trim; control characters denied.
- Earliest first occurrence: 60 seconds after command processing.
- Latest one-time occurrence and recurrence end: 365 days after creation.
- Recurrence is only `daily` or `weekly` on 1–7 unique weekdays; no cron.
- Recurring rules run no more often than once per local calendar day.
- List returns at most 10 active reminder rows in next-run/public-ID order.
- Configurable defaults may be stricter, but code hard caps cannot be exceeded.

Each recurring schedule has a fixed `ends_at`. It completes after that horizon.
An edit is an explicit cancellation followed by a new command, giving each rule
and occurrence a stable history.

## Timezone and DST semantics

The user must set an IANA timezone before creating a local schedule or enabling
check-ins. Unknown timezone never falls back to server, connection or inferred
location; `UTC` is valid when explicitly chosen. Names are case-sensitive values
available from the runtime timezone database and stored canonically.

Timezone change affects future recurring reminders and check-ins by preserving
their local wall-clock rule and choosing the next future occurrence in the new
zone. An already-resolved one-time reminder retains its UTC instant. Existing
materialized occurrences never move.

- Normal local times use their exact UTC conversion.
- A nonexistent spring-forward time advances minute-by-minute to the first valid
  local instant after the gap.
- An ambiguous fall-back time uses the earlier occurrence (`fold=0`) exactly once.
- All calculations use the stored zone, never process-local timezone.

## Consent and check-ins

Creating a reminder consents only to that reminder. Check-ins require the
separate `/checkins on ...` command and can be withdrawn with `/checkins off`.
One enabled check-in rule uses a daily or weekly cadence and fires only after at
least **24 hours without inbound activity** in that exact conversation. It may
emit at most one check-in per local calendar day.

Check-in text is a small versioned code-owned neutral template in the existing
English/Vietnamese personality language, e.g. a respectful “How are you doing?”
It is not LLM-generated, does not use private-memory content and cannot modify
its own cadence. This explicitly keeps proactive provider generation outside v1.

## Quiet hours

Quiet hours are exact participant/private-conversation preference. Default is
22:00–08:00 in the configured timezone; users may set another non-empty interval
or turn it off. Quiet hours suppress/defer **check-ins only**. Explicit reminders
are delivered at their requested time because that request is direct consent.

A check-in due during quiet hours keeps the same occurrence identity and is
deferred to the first quiet-hours-end instant. If timezone/quiet-hour settings
change before I/O, current settings win. Deferral never creates a second row.

## Catch-up and overdue behavior

Scheduling evaluates due rules in bounded ordered batches. For a recurrence with
many missed slots, it considers only the latest scheduled slot at or before now,
materializes at most one occurrence, and advances `next_run_at` directly to the
first future slot.

- Reminder catch-up window: 6 hours. A latest missed reminder within the window
  may enqueue once; an older one is recorded skipped/stale.
- Check-in catch-up window: 24 hours, additionally requiring consent, inactivity
  and quiet-hour eligibility. Older check-ins are skipped.
- A one-time reminder more than 6 hours stale completes as skipped.

A daily schedule ten days overdue therefore emits zero or one message, never ten.

## Delivery, idempotency and recovery

Schedule creation is idempotent by the durable command job. Occurrence identity
is unique for `(schedule, local calendar date)`, consistent with the v1 maximum
of one occurrence per schedule per local day. Concurrent schedulers use bounded
row-lock/SKIP LOCKED claims; one logical occurrence creates at most one response
plan and outbound action.

The scheduler commits claim/materialization before work and commits the existing
response-plan/outbox handoff without Telegram I/O. A current UUID lease token,
owner, expiry, schedule version, status, consent and privacy state fence enqueue.
A stale worker cannot overwrite a newer completion.

The existing outbound worker remains the only sender. Confirmed Telegram
rejections use its bounded retry; possible/ambiguous I/O is quarantined and not
automatically repeated. This is durable internal idempotency, not exactly-once
external delivery.

## Failure behavior

| Condition | Deterministic result |
| --- | --- |
| Worker crash before enqueue | Expired claim is recoverable; same occurrence reused |
| Crash after durable enqueue | Existing unique plan/action is reused; no second enqueue |
| Concurrent cancellation before I/O | Fresh fence skips action; no Telegram call |
| Cancellation after possible Telegram I/O | Preserve confirmed/unknown outcome; never claim cancellation of external effect |
| Privacy erasure before I/O | Redact/cancel and skip; stale worker cannot revive it |
| Subject or bot leaves/is restricted | Skip/defer according to current membership; no blind send |
| Delivery rejection | Existing bounded outbound retry/dead-letter semantics |
| Ambiguous delivery | Existing `delivery_unknown` quarantine; no automatic resend |
| Occurrence overdue | Bounded catch-up rule above; no burst |
| Database unavailable | No send; durable state remains authoritative |
| Rate coordination unavailable | Existing delivery fail-closed/retry behavior |
| Provider budget/unavailable | Not applicable: v1 performs no proactive provider I/O |

## Safety and abuse prevention

Reminder/check-in actions are neutral, contain no mentions/stickers/teasing and
pass existing structural response-plan and pre-delivery safety. Current privacy,
protection, conversation/connection/Assistant status, bot membership and delivery
rate limit are rechecked before Telegram I/O. Check-ins are suppressed while the
subject is protected or interaction is reduced/paused.

Active-count, recurrence, horizon, length, catch-up and daily check-in caps prevent
spam/runaway recurrence. Group scheduling is unsupported, so a group member or
admin cannot create group proactive spam. Reminder text is treated as untrusted
user content and never becomes a prompt or instruction in v1.

## Provider governance

SPEC-029 v1 makes no background LLM, embedding or transcription call. Therefore
it consumes no provider budget and cannot bypass SPEC-026. Reminder text is sent
as user-authored stored content with a fixed prefix; check-in text is code-owned.
Any future generated proactive text requires a new Product Owner decision and
must use the full SPEC-026 routing, capability, health, budget, rate, concurrency,
attempt and unknown-usage boundary before I/O.

## Privacy, export, erasure and retention

Reminder text and schedule configuration are private user content. Preference
and occurrence lifecycle fields are restricted metadata. Generated proactive
text does not exist; delivered check-in templates follow ordinary outbound copy
semantics. Metrics/audits contain no content or platform/user identifiers.

- Subject export includes only the subject's exact-scope schedule/preferences,
  bounded recent occurrence status and reminder text.
- Group export contains no private schedule or reminder content. Deployment
  governance may expose content-free aggregate counts only.
- Erasure cancels future schedules, clears text/preferences, invalidates pending
  occurrences and redacts schedule-sourced plan/action content atomically.
- Cancellation stops future occurrences but retains content until ordinary
  schedule retention applies.
- Completed/cancelled schedule content and occurrence details are redacted after
  **30 days** in bounded batches. Minimal content-free tombstones may remain for
  uniqueness/recovery. Active schedules are retained until completion,
  cancellation or erasure.
- Telegram-delivered copies and backup purge timing remain external as documented
  by SPEC-025; no broader deletion claim is made.

## Memory boundary

Schedules, reminder text, check-in events and delivered proactive messages never
automatically create explicit memory, personal context or semantic vectors.
They are not fed to a provider in v1. A later incoming user action may use the
existing explicit memory commands; SPEC-027 recall semantics are unchanged.

## Authorization

All user commands resolve the persisted command job through the exact participant,
private conversation, PlatformConnection and Assistant chain. The creator may
list/cancel only their own exact-conversation schedules. No cross-conversation
matching by Telegram user ID, group authority or tenant role is introduced.
No control-plane schedule content API is authorized. Deployment operators receive
only existing telemetry/operational aggregate visibility, not content access.

## Observability

Expose bounded counters/durations/backlog for schedule command outcomes,
occurrence materialization/claim/enqueue/skip/defer/recovery, and worker outcomes.
Allowed labels are closed values such as kind, recurrence, operation, outcome and
reason. Prohibited labels include reminder/check-in text, usernames, internal or
external IDs, conversation/user/Telegram IDs, timezone names and secrets. Durable
lifecycle records are the detailed authority; metrics are not delivery truth.

## Functional requirements

- **FR-01:** Private users can set/read an explicit validated IANA timezone.
- **FR-02:** Private users can set/read/disable check-in quiet hours.
- **FR-03:** Create one-time, daily and bounded selected-weekday reminders.
- **FR-04:** Enforce active-count, text, lead-time, horizon and recurrence caps.
- **FR-05:** List at most ten own exact-scope active reminders with public IDs.
- **FR-06:** Cancel an own reminder idempotently; foreign/unknown references fail closed.
- **FR-07:** Enable/status/disable one separately consented check-in rule.
- **FR-08:** Apply deterministic timezone, DST and timezone-update semantics.
- **FR-09:** Materialize due work in bounded deterministic batches with stable identity.
- **FR-10:** Apply one-occurrence catch-up and direct next-run advancement.
- **FR-11:** Defer check-ins through quiet hours without duplicating occurrence identity.
- **FR-12:** Recheck inactivity, consent, privacy, status and membership before enqueue/send.
- **FR-13:** Reuse response-plan/outbox/delivery; preserve ambiguous-delivery quarantine.
- **FR-14:** Fence leases, cancellation and stale completion with actual concurrency proof.
- **FR-15:** Integrate exact-scope subject export, erasure and bounded retention.
- **FR-16:** Preserve explicit-only memory and existing safety/rate controls.
- **FR-17:** Emit only closed, low-cardinality, content-free observability.
- **FR-18:** Run in one independently deployable scheduler worker with graceful shutdown.
- **FR-19:** Perform no proactive provider I/O in v1; generated text remains out of scope.

## Non-functional requirements

- **NFR-01:** PostgreSQL is authoritative; Redis is never durable schedule storage.
- **NFR-02:** No DB transaction/session/lock spans Telegram or other external I/O.
- **NFR-03:** No exactly-once external-delivery claim; ambiguity is explicit.
- **NFR-04:** All scans, claims, retries, catch-up and retention are bounded.
- **NFR-05:** Fail closed across privacy, authorization, membership and delivery gates.
- **NFR-06:** UTC/timezone logic is deterministic and independent of host timezone.
- **NFR-07:** One additive migration after 0019; single head and guarded downgrade.
- **NFR-08:** Tests use deterministic clocks/fakes and actual concurrent database races.
- **NFR-09:** Existing text/media/commands/memory/provider behavior remains compatible.

## Acceptance criteria

Each FR/NFR has direct unit or integration proof mapped in the Design Handoff.
Required proof includes DST gap/fold; timezone change; ten-day overdue daily rule;
duplicate creation; actual concurrent schedule materialization repeated enough to
exercise locks/uniqueness; crash before/after enqueue; A-expiry/B-completion/A-late
fencing; cancellation/privacy immediately before I/O; export/erasure/retention;
no automatic memory/provider I/O; bounded labels; staging worker topology; migration
0019→0020→0019→0020 and base/head lifecycle; exact guarded downgrade refusal.

General, dedicated and affected validators must pass. Docker-only proof may be
reported pending only for the recorded agent socket restriction. No repository-owned
Critical or High defect may remain for an approved candidate.

## Migration expectation

Create exactly one additive `0020_proactive_scheduling` revision after
`0019_telegram_media`. It may extend response-plan source identity and outbound
origin only as required. Once schedule/occurrence state exists, downgrade must
refuse with an exact SPEC-029 reason rather than discard user content or fences.
Do not modify committed migrations; preserve the VARCHAR(64) bootstrap.

## Risks and external prerequisites

Risks: DST mistakes, duplicate catch-up, cancellation/privacy races, outbound
spam, content retained too long and docs stronger than proof. Mitigate with pure
time functions, unique constraints, UUID fencing, fresh send-time checks, bounded
batches and negative tests.

External operating-owner items: production timezone database maintenance,
retention acceptance, telemetry/alert thresholds, backup purge/reapply policy,
deployment rollout and user-facing copy review. No legal/compliance or production
acceptance is self-approved. No provider credential or pricing decision is needed.

## Future work

Generated contextual check-ins, delayed model follow-up, group/admin schedules,
schedule edits, generic cron, calendar/email/webhook integration, external
automation, multi-assistant/tenant expansion and proactive media require later
Product Owner authority. SPEC-030 — not started.
