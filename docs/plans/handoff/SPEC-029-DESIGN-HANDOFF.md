# SPEC-029 Implementation Design Handoff

Status: **APPROVED DESIGN** under the Product Owner-authorized SPEC-029 goal.
The design has an uncommitted, repository-safe validated implementation
candidate; live Docker-backed release evidence remains pending.

## 1. Executive summary

Add a private-only durable scheduler to the modular monolith. Telegram commands
create exact-participant schedules. PostgreSQL materializes at most one recent
occurrence per due schedule, a scheduler worker leases it, and the worker creates
the existing response-plan/outbound action atomically. The existing sender remains
the sole Telegram I/O path and rechecks cancellation, privacy, membership, quiet
hours and inactivity immediately before marking external I/O started.

V1 reminders contain bounded user text. Separately consented check-ins use a
versioned neutral code-owned template. No provider, embedding or transcription
call occurs; generated proactive content remains future Product Owner work.

## 2. Baseline and audit

- Baseline/HEAD/origin/main: `private-source-checkpoint-omitted`.
- Committed Alembic head: `0019_telegram_media`; next revision is
  `0020_proactive_scheduling`.
- No existing user timezone, reminder or durable schedule abstraction exists.
- Reused surfaces: Telegram entity parser; durable command jobs; exact scope;
  SKIP LOCKED claims; response-plan compiler; outbound ambiguity; privacy,
  retention and export; runtime lifecycle; closed telemetry.
- Docker checked once and unavailable through the mapped socket. Exact evidence
  is in the active plan; no retry or host mutation is allowed in this environment.

## 3. Scope

One-time, daily and selected-weekday user reminders; timezone and quiet-hour
preference; one separately enabled daily/weekly check-in; list/cancel/status;
bounded catch-up; durable recovery; privacy/governance/telemetry/deployment proof.

## 4. Out of scope

Groups, schedule edits, generic cron/workflows, provider-generated proactive text,
follow-up inference, calendars/email/webhooks, Zalo, media generation, automatic
memory, multi-assistant tenancy, SPEC-030, and control-plane content APIs.

## 5. Domain model

Create `domain/scheduling.py` with closed values:

- `ScheduleKind`: reminder, check_in;
- `RecurrenceKind`: once, daily, weekly;
- `ScheduleStatus`: active, completed, cancelled, erased;
- `OccurrenceStatus`: pending, leased, enqueued, delivered, skipped,
  permanently_failed, delivery_unknown, history_redacted;
- `ScheduleReason`: none, stale, quiet_hours, recent_activity, cancelled,
  privacy, membership, paused, expired, delivery_rejected, delivery_unknown;
- validated recurrence/time/preference/mutation and detached claim values.

Schedule public IDs are deterministic bounded encodings of internal UUID entropy,
never authorization credentials, identity keys, logs or metric labels.

## 6. Command and consent surface

Extend `application/commands.py` with `SCHEDULING` and the exact Product Spec
grammar. Parsing remains pure, bounded and provider-free. The infrastructure
entity parser remains unchanged: captions, prose, edits and other-bot commands
cannot create scheduling work.

`telegram_command_worker.py` routes scheduling operations to a scheduling service
only after canonical state load. Every operation denies non-private conversations.
Mutations write a content-free receipt keyed uniquely by command job before the
normal deterministic command response is completed. A crash between mutation and
acknowledgement replays the receipt, not the effect.

The user who owns the exact participant/conversation may inspect and cancel only
their rows. A reminder command is consent for that schedule only. The check-in
schedule itself is the separate opt-in; `off` cancels it. Tenant/control-plane
roles and Telegram group roles grant no schedule-content authority.

## 7. Timezone and recurrence calculations

Create pure `application/scheduling.py` functions using `zoneinfo.ZoneInfo` only:

1. validate a canonical available IANA name;
2. resolve a local date/time by round-tripping both folds;
3. choose fold=0 when both folds are valid and different;
4. for a gap, scan at most 180 minutes to the first round-tripping local minute;
5. derive next/previous allowed local date using arithmetic and at most seven
   weekday steps;
6. return latest due plus first future instant without enumerating every missed
   occurrence.

Weekday bit mask uses Monday bit0 through Sunday bit6; daily uses all days; once
stores its resolved UTC instant. Timezone changes recalculate only active recurring
rows under lock, preserve local rule, choose a future instant, increment schedule
version and complete schedules whose horizon has passed. One-time UTC stays fixed.

## 8. Persistence and migration 0020

Create exactly one migration after 0019 and matching ORM models.

### `participant_schedule_preferences`

- id; participant_id + conversation_id exact composite FK;
- canonical timezone_name (nullable until set);
- quiet_hours_enabled; quiet_start_minute; quiet_end_minute;
- positive revision and timestamps.
- unique participant_id; checks for minute ranges and non-empty enabled interval.

### `proactive_schedules`

- id/public_id; conversation_id + creator_participant_id composite FK;
- source_command_job_id unique; kind/status/recurrence/timezone_name;
- local_time_minute; weekday_mask; starts_on; one_time_at; next_run_at; ends_at;
- reminder_text; positive version; cancelled/completed/redacted timestamps;
- timestamps and deterministic due indexes.
- shape checks: reminder requires text; check-in forbids text; once versus recurring
  columns; active requires next run and a materialized one-time schedule completes;
  bounded text, mask, local time and terminal timestamp shapes.
- partial unique active check-in per participant/conversation.

### `proactive_schedule_command_receipts`

- command_job_id unique; exact participant/conversation; operation, outcome and
  optional schedule_id; content-free timestamps.
- closed operation/outcome checks. It stores no reminder text or timezone.

### `proactive_schedule_occurrences`

- id; schedule_id; scheduled_for/local_date; status/available_at;
- owner, UUID lease token, expiry, positive attempt count;
- schedule_version and conversation privacy revision fences;
- closed outcome/reason; completion/redaction timestamps.
- unique `(schedule_id, local_date)` and due/lease indexes; state-shape checks.

### Existing-table changes

- Add nullable unique `schedule_occurrence_id` FK to `response_plans`; replace
  `response_plan_exactly_one_source` with exactly one of planning, command or
  occurrence.
- Extend `ParticipationTrigger`/outbound origin check with `scheduled`.
- No provider registry, price, budget or usage schema change.

Downgrade checks all four new tables and schedule-sourced response plans/actions.
If any SPEC-029 durable state exists, raise exactly
`SPEC-029 schedule state blocks downgrade`. Empty-state downgrade restores source
constraint/origin check and drops new objects in dependency order.

## 9. Repository and transaction boundaries

Create `infrastructure/database/scheduling.py`:

- preference get/update with receipt replay;
- reminder/check-in create, list, cancel and check-in status;
- `materialize_due(now, limit)`: short schedule-row claim transaction;
- `claim(owner, now, limit, lease)`: pending/expired lease claim with SKIP LOCKED;
- `enqueue_claim(...)`: exact owner/token/attempt/expiry/version/privacy fence,
  current policy checks and atomic response plan/outbound compile;
- skip/defer/fail methods with identical fencing;
- send-time preflight helpers used inside outbound external-start transaction.

No method performs Telegram, Redis or provider I/O. Command mutation and receipt
are one transaction. Command response completion may follow separately; receipt
replay guarantees one effect and stable result. Occurrence completion and plan/
action creation are one transaction.

Lock order is command job/receipt → preference or schedule → occurrence → plan/
action. Worker calls never retain ORM objects beyond the method boundary.

## 10. Due materialization and catch-up

`materialize_due` orders active `next_run_at <= now` by next_run, created_at, id,
locks at most configured batch rows with SKIP LOCKED and for each:

- computes only the latest due local slot and first future slot;
- inserts/reuses one occurrence unique by schedule/local date;
- marks stale one-time/reminder/check-in using 6h/24h windows;
- advances recurrence directly to the first future slot or completes at horizon.

The method never loops across every missed day. A ten-day overdue daily schedule
creates one latest occurrence row at most and advances beyond now.

## 11. Lease, fencing and cancellation

Claims generate a fresh UUID token and increment attempt. Active unexpired leases
cannot be stolen. Completion requires exact owner, token, attempt, unexpired lease,
schedule version and current conversation privacy revision.

Canonical race proof: A claims; A expires; B reclaims with new token; B completes;
A's late completion returns false and cannot alter occurrence/plan/action.

Cancel locks schedule and current actions. It always stops future occurrences.
Pending or leased-before-external-start actions are atomically skipped and their
occurrence marked cancelled. Once `external_started_at` exists, cancellation
records that future work is cancelled but preserves delivery result/ambiguity.

## 12. Scheduler worker

Create `runtime/proactive_scheduler_worker.py` with `--once`, RuntimeLifecycle,
bounded poll/materialize/claim loops and generic worker metrics. It performs no
network I/O. For each claim its repository transaction loads current scope,
applies inactivity/quiet/privacy/protection/status checks, constructs a neutral
deterministic candidate and atomically creates the existing plan/outbox work.
Exceptions record failed worker result and leave recoverable lease state;
graceful stop finishes the bounded current iteration.

Reminder text renders as a fixed localized prefix plus exact stored text. Check-in
selects a versioned code-owned neutral English/Vietnamese template from the current
personality language. Neither includes mentions, stickers, reply target or teasing.

## 13. Outbound delivery integration

The existing outbound worker remains the only Telegram sender. Enhance the
outbound repository's external-start transaction for schedule-sourced actions:

- resolve occurrence→schedule→creator→conversation→connection→Assistant;
- require occurrence enqueued and schedule active/completed, not cancelled/erased;
- require current participant privacy/membership and conversation privacy revision;
- require active conversation/connection/Assistant and usable bot membership;
- for check-ins, require consent, inactivity and outside current quiet hours.

Return a closed started/deferred/skipped result. Deferred check-ins atomically
return the action to pending at current quiet-hours end without marking external
I/O. Blocked actions become skipped. Started atomically sets the existing
delivery attempt `external_started_at`; cancellation/erasure after this point is
recorded as possible I/O, not falsely guaranteed.

Existing delivery rate limiting, safety decision, retry/dead-letter/quarantine and
adapter call order remain. Outbound finalize updates occurrence terminal state in
the same transaction when delivered/permanently failed/unknown/skipped.

## 14. Safety and abuse controls

The schedule worker creates structurally neutral actions only. The existing
pre-delivery safety decision and delivery limiter still execute. Fresh proactive
preflight additionally denies paused response mode, protected/deleted/non-member
subject and unusable bot membership. Check-in inactivity and daily uniqueness stop
recursive loops. Active/horizon/text/recurrence caps stop schedule floods.

Reminder content remains untrusted stored/delivered text; it never becomes prompt,
command, mention entity, model output or memory. No claim of comprehensive semantic
moderation is introduced beyond existing SPEC-024 guarantees.

## 15. Provider and memory boundaries

There is no provider call or new workload. Unit/integration tests assert zero
generation, embedding and transcription calls. Provider budget denial is therefore
not a runtime state for v1. Future generated check-ins require new product authority
and full SPEC-026 integration.

There is no call to memory creation, personal context, semantic indexing or Qdrant.
Outbound scheduled messages remain ordinary outgoing history subject to retention;
they do not automatically become memory.

## 16. Privacy, export, erasure and retention

Extend `GovernanceExportBuilder.build_subject_export` with an exact-participant
schedule/preference projection: public ID, kind, status, recurrence, timezone,
local rule, next/end timestamps, reminder text when not redacted, and bounded
recent occurrence states. Group/deployment content exports exclude it; deployment
inventory/counts may be content-free.

Subject erasure under the existing Assistant/connection scope locks matching
participants and schedules, cancels/erases them, clears reminder text/preferences,
marks pre-I/O occurrences skipped, and redacts schedule-sourced plan/action text.
It advances existing privacy authority and is idempotent. Late completion fails.

Retention extends the existing worker with a configured 30-day threshold and the
shared batch size. It selects bounded deterministic terminal schedule/occurrence
IDs, clears text/configuration details and marks content/history redacted. Active
schedules are untouched; repeats are empty. Tombstones retain only minimum closed
identity/state needed for uniqueness and recovery.

Update data inventory, retention/runbook and backup descriptions. No claim covers
already delivered Telegram copies or backup purge beyond existing policy.

## 17. Authorization/control plane

No new HTTP control-plane endpoint. Deployment/tenant roles cannot access reminder
content. Operational visibility is aggregate telemetry and database/runbook status
under existing infrastructure authority. Telegram group authorization is irrelevant
because every scheduling command fails closed outside a private conversation.

## 18. Configuration and deployment

Add bounded settings: feature/worker enable; batch/poll/lease; active cap10;
text cap100; lead60s; horizon365d; reminder catch-up6h; check-in inactivity/catch-up
24h; retention30d; default quiet22:00–08:00. Worker enable requires feature enable;
lease exceeds one bounded iteration and values respect hard product caps.

Add a staging worker using existing image/app environment, migration dependency,
graceful stop and `restart: unless-stopped`. No volume, timer daemon or Redis
authority. Extend deployment validation so omission/config mismatch fails.

## 19. Telemetry

Add closed `january_schedule_commands_total`,
`january_schedule_occurrences_total`, `january_schedule_delivery_total` and a
capped `january_schedule_backlog` gauge. The gauge exposes only reminder/check-in
and pending/leased, inspects at most `batch_size + 1` rows per combination, and
therefore signals overflow without an unbounded scan. Extend generic worker
metrics with runtime `scheduler`, operation `schedule_batch`, and actual
completed/failed/no_op outcomes and duration.

No text, timezone, public/internal IDs, usernames, conversation/user/Telegram IDs,
credentials or arbitrary exceptions in labels/logs/audits.

## 20. Tests and validator

Unit tests:

- exact command grammar and length/control rejection;
- IANA validation; normal UTC conversion; DST gap/fold; timezone update;
- daily/weekday advancement, horizon and ten-day catch-up;
- quiet hours including overnight interval; fixed templates;
- settings, telemetry label closure and prior command/outbound behavior.

PostgreSQL integration:

- migration constraints/indexes/FKs/single head;
- duplicate command/create receipts; active limit/list/cancel exact scope;
- materialization replay and crash before/after enqueue;
- actual concurrent materialization/claim repeated (not sequential);
- A-expiry/B-complete/A-late fencing;
- cancellation before start and after possible I/O;
- privacy erase, cross-conversation denial, retention, subject/group export;
- outbox link, confirmed/failed/unknown occurrence results;
- no provider/memory/index side effects.

Create executable `scripts/validate-proactive-scheduling.sh` using canonical uv,
fail-fast shell, clean environment, isolated Compose project and configurable
alternate ports. Repository-only mode passes units then exits 2 with explicit
Docker pending. Full mode proves 0019→0020→0019→0020, base→head→base→head, exact
guard refusal, PG concurrency, worker/outbox fake runtime and scoped cleanup.
Wire Quality CI and update head pins/affected validators.

## 21. CI compatibility

Validator must be tracked executable LF with `#!/usr/bin/env bash`, resolve uv via
`scripts/lib/resolve-uv.sh`, use no ignored local binary or credentials, and be
shallow-checkout safe. CI calls it in the existing Docker-capable quality job.
No `continue-on-error`, outcome-masking `|| true`, generic expected failure or
unscoped compose teardown.

## 22. Migration lifecycle and rollback

Offline SQL/head inspection is repository-safe evidence only. Canonical live proof:
empty 0019→0020→0019→0020 and base→head→base→head; then seed durable state and prove
only exact SPEC-029 guard refusal while head remains 0020. Disable scheduler before
binary rollback; after activation keep schema unless authorized state cleanup is
complete. Never discard schedules to force downgrade.

## 23. Risks

- DST/timezone database variance: canonical ZoneInfo and deterministic transition tests.
- Duplicate downtime sends: latest-only catch-up plus unique local-date occurrence.
- Cancellation/privacy race: atomic external-start fence and explicit possible I/O.
- Content exposure: private scope, allowlisted export, physical text redaction.
- Spam: active/cadence/horizon/inactivity/daily/rate caps and no groups.
- Documentation overclaim: separate unit/offline/collected/live evidence.

## 24. Expected files

New scheduling domain/application/repository/worker, migration0020, scheduling unit
and integration tests, dedicated validator, ADR and scheduling runbook. Modify
commands, command worker, models, outbound delivery, privacy, retention, governance
export/inventory, telemetry, config, staging/CI/head pins, README/architecture/product/
Telegram/privacy/observability/deployment/command docs. No provider adapter changes.

## 25. FR/NFR traceability

| Requirement | Implementation | Direct proof |
| --- | --- | --- |
| FR-01/02 | preferences + commands + ZoneInfo | private/status/update/replay/invalid-zone/quiet tests |
| FR-03/04 | parser/service/schedule checks | once/daily/weekly and every hard bound |
| FR-05/06 | scoped list/cancel repository | own/foreign/unknown/replay/concurrent cancel |
| FR-07 | one active check-in + consent commands | on/status/off and reminder-consent separation |
| FR-08 | pure recurrence resolver | UTC, gap, fold, zone-change vectors |
| FR-09/10 | materialize_due + uniqueness | repeat/concurrent and ten-day latest-only proof |
| FR-11/12 | occurrence/send-time preflight | overnight deferral, activity, privacy, membership races |
| FR-13 | response-plan source/outbox | one action; confirmed/retry/unknown semantics |
| FR-14 | UUID lease/version/revision checks | A/B/A race and cancellation around external start |
| FR-15 | export/privacy/retention | exact subject, group exclusion, erase and multibatch |
| FR-16 | neutral action/existing outbound | safety/rate regression; zero memory rows |
| FR-17 | closed telemetry catalog | accepted labels and prohibited-label failures |
| FR-18 | scheduler runtime/staging | once, graceful stop, restart/config validation |
| FR-19 | no governed provider path | injected provider mocks remain uncalled; no usage rows |
| NFR-01/02 | SQL repository + outbox split | no Redis authority/session during fake Telegram I/O |
| NFR-03 | existing delivery attempts | timeout/transport delivery_unknown and no auto replay |
| NFR-04 | caps/batches/direct advancement | batch and >batch/overdue/retry proofs |
| NFR-05 | canonical joins and fresh gates | cross-scope/privacy/membership negatives |
| NFR-06 | ZoneInfo pure functions | host-TZ-independent test matrix |
| NFR-07 | migration0020 | single head/lifecycles/exact guard |
| NFR-08 | deterministic clock + PG gather | repeated actual concurrent race |
| NFR-09 | existing validators | full release regression matrix |

## 26. Implementation phases and acceptance checklist

1. Domain/time/command parser and unit tests.
2. Migration/models/repository with concurrency/privacy tests.
3. Worker/outbox fresh fence and runtime tests.
4. Export/erasure/retention/telemetry/deployment/docs/ADR.
5. Dedicated/general/affected validation and migration proof.
6. Skeptical integrity audit, fixes, completed plan and final handoff.

- [x] Every FR/NFR row has current code and executable or explicitly Docker-pending evidence.
- [x] Ten-day downtime and actual repeated concurrent race are encoded as PostgreSQL proof.
- [x] Cancellation/privacy fences cover before and after possible I/O.
- [x] No provider/memory bypass or high-cardinality telemetry.
- [x] Migration cycles and exact guard are encoded and explicitly Docker-pending.
- [x] CI/script integrity passes; no skip/xfail/failure masking.
- [x] No repository Critical/High; final handoff records exact status.
- [x] No commit/push, historical migration rewrite or SPEC-030.
