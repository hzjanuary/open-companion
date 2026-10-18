# Telegram Presence — SPEC-035

This runbook covers the transient native Telegram `typing` signal emitted by
the response-planning worker. Presence is cosmetic and best effort; durable
planning, provider governance, response compilation, and delivery remain the
authoritative path.

## Eligibility

Presence is eligible only for Telegram planning jobs whose trigger is
`addressed`: private direct messages, explicit group mentions/replies, and
supported directly addressed media. Current tenant, Assistant, platform
connection, conversation, planning lease, safety policy, and provider admission
must all permit generation.

Ambient participation, proactive schedules, deterministic commands and
preferences, disabled or foreign authority, safety denial, provider admission
denial, terminal/recovered jobs, and non-Telegram platforms emit no typing
request. Zalo remains frozen.

## Start, refresh, and stop

Governed providers start presence after budget, provider-rate, concurrency,
authority, and durable I/O-start admission, immediately before raw provider
I/O. Legacy mode starts after its final provider-rate gate. The initial call is
synchronous and runs after a fresh exact lease/lifecycle fence.

One execution-owned task refreshes every four seconds. It makes at most five
total calls including the initial request and expires after twenty seconds;
provider work may continue after that bound. Before each refresh, PostgreSQL
must still show the same leased job, owner, claim attempt, unexpired lease,
active authority, and no recovery record. The database scope closes before the
Telegram call.

The planning worker cancels and awaits the task before processing provider
success, denial, error, cancellation, lease loss, or any other exit. Durable
response completion and outbound delivery therefore begin only after presence
has stopped. Worker crash recovery never replays typing; Telegram naturally
expires the last action.

## Telegram and failure semantics

The adapter sends exactly:

```json
{"chat_id":"<canonical chat>","action":"typing"}
```

For topics, it also includes the canonical positive-decimal
`message_thread_id`. Only `typing` is accepted. The adapter reuses its existing
HTTP client and token-safe envelope/error classification.

HTTP 400, 401/403, 429, 5xx, timeout, connection failure, and malformed response
disable presence for that planning execution after the first failure. There is
no presence retry loop, durable retry, recovery item, placeholder message, or
outbound typing action. The provider and response pipeline continue unchanged.
Unexpected programming faults remain visible.

## Privacy and observability

Presence adds no table, migration, message, response plan, outbound action,
memory, semantic-memory, knowledge, summary, or media state. Metrics contain
only closed call outcome/error-category and lifecycle-outcome labels. Do not log
chat/thread/user/conversation/tenant/Assistant/connection/job/provider request
IDs, prompts, responses, or credentials.

Inspect `january_telegram_presence_calls_total` and
`january_telegram_presence_lifecycle_total`. A failure counter with continued
planning success indicates expected cosmetic degradation. Repeated failures
across executions warrant checking Telegram reachability and bot authorization;
do not manually retry chat actions.

## Validation and troubleshooting

Run the isolated no-credential proof:

```bash
JANUARY_DB_HOST_PORT=5450 JANUARY_REDIS_HOST_PORT=6397 \
  ./scripts/validate-telegram-presence.sh
```

It validates exact payload/error classification, controlled heartbeat timing,
task ownership, provider-admission ordering, live PostgreSQL lease/authority
fencing, zero checked-out database connections during fake Telegram calls,
failure independence, offline hard evals, current Alembic head, and a
tracked-plus-untracked clean export.

For `/regenerate`, the same addressed-work controller starts only at the fresh
provider boundary and is stopped/awaited before an edit or send action becomes
deliverable. Regeneration does not create a second presence mechanism; see
[`telegram-regeneration.md`](telegram-regeneration.md).

If typing is absent but replies succeed, check the planning trigger and the
closed presence failure metric before changing provider or delivery policy. If
typing persists unexpectedly, stop the planning worker and inspect lease state;
never create a durable cleanup action. V1 does not stream output, edit
placeholders, emit reactions/custom actions, or provide user-configurable
timing.
