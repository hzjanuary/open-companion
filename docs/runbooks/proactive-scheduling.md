# Proactive Scheduling Operations

SPEC-029 adds private-conversation reminders and separately consented check-ins.
PostgreSQL is authoritative; `proactive_scheduler_worker` only materializes and
enqueues bounded work. The existing outbound worker remains the sole Telegram
sender. V1 makes no provider, embedding, transcription, or memory call.

## Enablement

Apply migrations through current head (`0021_multi_assistant_tenancy` includes
the prior `0020_proactive_scheduling` schema), then configure both the feature
and worker explicitly:

```bash
JANUARY_PROACTIVE_SCHEDULING_ENABLED=true
JANUARY_SCHEDULER_WORKER_ENABLED=true
JANUARY_OUTBOUND_DELIVERY_ENABLED=true
```

The scheduler worker refuses invalid feature/worker combinations. Review the
bounded batch, poll, lease, reminder-count, lead-time, horizon, text-length, and
history-retention settings in `.env.example`; repository hard caps cannot be
raised through configuration.

Start the no-network scheduler separately:

```bash
uv run python -m app.runtime.proactive_scheduler_worker
uv run python -m app.runtime.proactive_scheduler_worker --once
```

Stopping the process finishes only its current bounded iteration. An unexpired
lease cannot be stolen; an expired lease is reclaimed with a new token and
attempt fence. No database transaction spans Telegram I/O.

## User contract

In a private chat, set an explicit IANA timezone before creating a schedule:

```text
/timezone Asia/Ho_Chi_Minh
/quiet_hours 22:00-08:00
/remind at 2026-09-12 09:30 Call Mum
/remind daily 09:00 Take medicine
/remind weekly mon,wed 18:00 Go for a walk
/reminders
/cancel_reminder ABCDEF234567
/checkins on daily 10:00
/checkins status
/checkins off
```

All commands fail closed outside an exact private participant/conversation.
Reminder consent does not enable check-ins. Quiet hours apply only to check-ins;
check-ins additionally require 24 hours without inbound activity. Reminder text
and check-in events never become explicit memory or personal context.

## Catch-up and delivery

Each due rule materializes only its latest logical occurrence. Reminders older
than six hours and check-ins older than 24 hours are skipped, preventing a burst
after downtime. One-time reminders always retain their original resolved UTC
instant. DST gaps advance to the first valid local minute; folds use the earlier
instant once.

The worker atomically creates a schedule-sourced response plan and ordinary
outbound action. Immediately before external I/O, delivery rechecks schedule
version, privacy revision, membership, Assistant/connection/conversation state,
pause state, and—only for check-ins—quiet hours and recent activity. A confirmed
Telegram rejection uses existing bounded retry. Possible I/O remains
`delivery_unknown` and is never automatically repeated.

Assistant and connection authority cannot be rebound. Disabling the tenant,
Assistant, or connection suppresses claimed schedule work at the fresh
pre-enqueue/pre-delivery boundary; it is never retargeted to another Assistant.

## Privacy and retention

Subject export includes only the exact participant/conversation preferences,
schedules, reminder content, and at most 100 recent occurrence states. Group
export excludes private schedules. Erasure cancels schedules, clears preferences,
the local recurrence rule and reminder values, invalidates pre-I/O work, and
redacts related plan and action content. Bounded content-free lifecycle timestamps
may remain as tombstones. Erasure cannot recall an already delivered or possibly
delivered Telegram copy.

Terminal schedule configuration/content and occurrence timestamps are reduced
to content-free tombstones after `JANUARY_SCHEDULER_HISTORY_RETENTION_DAYS`
(default 30) in deterministic shared retention batches. Active schedules are not
retention-redacted.

## Validation and recovery

Repository-safe proof:

```bash
./scripts/validate-proactive-scheduling.sh --repository-only
```

Exit 2 means its focused repository proof passed but the PostgreSQL/Redis and
migration/runtime phases remain pending. A Docker-capable operator runs the full
validator, which uses the isolated `january-spec029-validation` Compose project
and alternate ports 5442/6389 by default.

The full validator proves `0019 -> 0020 -> 0019 -> 0020`, the populated-state
downgrade refusal, empty-state downgrade, base/head lifecycle, database
concurrency, and outbox integration. Do not retry ambiguous delivery or alter
schedule rows manually. For recovery, inspect content-free status, lease expiry,
attempt count, and existing outbound recovery state; allow normal lease recovery.
